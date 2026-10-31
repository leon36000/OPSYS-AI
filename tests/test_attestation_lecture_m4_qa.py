"""Contrat privé d'attestation gateway ; données et secret strictement fictifs."""

import base64
import hashlib
import hmac
import json
import time

import pytest

from opsys import attestation_appareil_gateway as att
from opsys.contexte import IdentiteAppelante

SECRET = "secret-gateway-fictif-01234567890123456789"
OUTIL = "m3_lire_apprentissage_chantier"
IDENTITE = IdentiteAppelante("admin.fictif", "admin", source="appareil")
ARGS = {"wct_id": "f" * 64, "coupure_utc": "2030-06-08T12:00:00-04:00"}


def _signer(*, nonce="a" * 32, generation=None, timestamp=None, args=None, personne="admin.fictif"):
    args = args or ARGS
    corps = json.dumps([args["wct_id"], args["coupure_utc"]], separators=(",", ":")).encode()
    champs = [
        1,
        generation or att.generation(),
        "device-fictif",
        personne,
        "admin",
        OUTIL,
        hashlib.sha256(corps).hexdigest(),
        int(time.time() * 1000) if timestamp is None else timestamp,
        nonce,
    ]
    contenu = base64.urlsafe_b64encode(json.dumps(champs, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(SECRET.encode(), contenu.encode(), hashlib.sha256).hexdigest()
    return {"opsys/attestationAppareil": contenu + "." + signature}


@pytest.fixture(autouse=True)
def _environnement(monkeypatch):
    monkeypatch.setenv(att._ENV, SECRET)
    att._reinitialiser_apres_fork()
    yield
    att._reinitialiser_apres_fork()


def test_absence_faux_corps_et_rejeu_fermes():
    meta = _signer()
    assert att.verifier({}, OUTIL, IDENTITE, ARGS) is None
    assert att.verifier(meta, OUTIL, IDENTITE, {**ARGS, "wct_id": "e" * 64}) is None
    assert att.verifier(meta, "autre_outil", IDENTITE, ARGS) is None
    preuve = att.verifier(meta, OUTIL, IDENTITE, ARGS)
    assert preuve is not None and preuve.wct_id == ARGS["wct_id"]
    assert att.verifier(meta, OUTIL, IDENTITE, ARGS) is None
    assert att.cle_est_valide(preuve)


def test_generation_redemarrage_cle_et_expiration_fermees(monkeypatch):
    meta = _signer()
    ancien = att.generation()
    att._reinitialiser_apres_fork()
    assert att.generation() != ancien
    assert att.verifier(meta, OUTIL, IDENTITE, ARGS) is None
    assert att.verifier(_signer(nonce="b" * 32, timestamp=1), OUTIL, IDENTITE, ARGS) is None
    preuve = att.verifier(_signer(nonce="c" * 32), OUTIL, IDENTITE, ARGS)
    assert preuve is not None
    monkeypatch.setenv(att._ENV, "autre-secret-fictif-01234567890123456789")
    assert not att.cle_est_valide(preuve)


def test_saturation_cache_refuse_sans_evict_une_preuve_active(monkeypatch):
    monkeypatch.setattr(att, "_BORNE", 1)
    assert att.verifier(_signer(nonce="a" * 32), OUTIL, IDENTITE, ARGS) is not None
    assert att.verifier(_signer(nonce="b" * 32), OUTIL, IDENTITE, ARGS) is None
    assert att.verifier(_signer(nonce="a" * 32), OUTIL, IDENTITE, ARGS) is None


def test_prevol_exige_deux_secrets_distincts_et_refuse_mcp_non_atteste(monkeypatch):
    import asyncio

    import httpx

    from opsys.serveur_mcp import _ExigerJeton

    async def application(scope, receive, send):
        raise AssertionError("le prévol ne doit pas atteindre une application métier")

    token = "bearer-mcp-fictif-01234567890123456789"
    app = _ExigerJeton(application, token)
    proof = hmac.new(SECRET.encode(), b"opsys.device.generation.v1", hashlib.sha256).hexdigest()

    async def tester():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            url = att._CHEMIN
            assert (await client.get(url, headers={"Authorization": "Bearer " + token})).status_code == 404
            assert (await client.get(url, headers={"x-opsys-gateway-proof": proof})).status_code == 401
            reponse = await client.get(
                url, headers={"Authorization": "Bearer " + token, "x-opsys-gateway-proof": proof}
            )
            assert reponse.status_code == 200 and reponse.json() == {"generation": att.generation()}
            monkeypatch.setenv(att._ENV, token)
            refuse = await client.get(url, headers={"Authorization": "Bearer " + token, "x-opsys-gateway-proof": proof})
            assert refuse.status_code == 404

    asyncio.run(tester())


def test_meta_direct_ne_peut_pas_fabriquer_une_identite_gateway():
    faux = {"opsys/appareilAuthentifie": "device-fictif", "opsys/personne": "admin.fictif", "opsys/role": "admin"}
    assert att.verifier(faux, OUTIL, IDENTITE, ARGS) is None
    signe = _signer(nonce="d" * 32)
    contenu = signe["opsys/attestationAppareil"].split(".")[0]
    bearer_mcp = "jeton-mcp-fictif-01234567890123456789"
    faux_mac = hmac.new(bearer_mcp.encode(), contenu.encode(), hashlib.sha256).hexdigest()
    assert att.verifier({"opsys/attestationAppareil": contenu + "." + faux_mac}, OUTIL, IDENTITE, ARGS) is None
    assert att.verifier({"opsys/attestationAppareil": contenu + ".é"}, OUTIL, IDENTITE, ARGS) is None
    assert att.verifier(signe, OUTIL, IDENTITE, ARGS) is not None


def test_recul_mural_invalide_generation_et_atteinte_echeance_monotone(monkeypatch):
    temps = {"mur": 1_900_000_000.0, "mono": 1000.0}
    monkeypatch.setattr(att.time, "time", lambda: temps["mur"])
    monkeypatch.setattr(att.time, "monotonic", lambda: temps["mono"])
    att._reinitialiser_apres_fork()
    meta = _signer(nonce="e" * 32)
    ancienne_generation = att.generation()
    preuve = att.verifier(meta, OUTIL, IDENTITE, ARGS)
    assert preuve is not None and att.cle_est_valide(preuve)
    assert att.verifier(meta, OUTIL, IDENTITE, ARGS) is None
    temps["mono"] += 23
    temps["mur"] += 1
    assert not att.cle_est_valide(preuve)
    assert att.generation() != ancienne_generation
    assert att.verifier(meta, OUTIL, IDENTITE, ARGS) is None


def test_derive_lente_cumulee_ne_contourne_pas_ancre_fixe(monkeypatch):
    temps = {"mur": 1_900_000_000.0, "mono": 1000.0}
    monkeypatch.setattr(att.time, "time", lambda: temps["mur"])
    monkeypatch.setattr(att.time, "monotonic", lambda: temps["mono"])
    att._reinitialiser_apres_fork()
    ancienne = att.generation()
    for _ in range(3):
        temps["mur"] += 1
        temps["mono"] += 2
        att.generation()
    assert att.generation() != ancienne


def test_expiration_monotone_de_la_portee_meme_sans_changement_de_generation(monkeypatch):
    temps = {"mur": 1_900_000_000.0, "mono": 1000.0}
    monkeypatch.setattr(att.time, "time", lambda: temps["mur"])
    monkeypatch.setattr(att.time, "monotonic", lambda: temps["mono"])
    att._reinitialiser_apres_fork()
    ancienne = att.generation()
    preuve = att.verifier(_signer(nonce="f" * 32), OUTIL, IDENTITE, ARGS)
    assert preuve is not None and att.cle_est_valide(preuve)
    temps["mur"] += 21
    temps["mono"] += 21
    assert att.generation() == ancienne
    assert not att.cle_est_valide(preuve)
