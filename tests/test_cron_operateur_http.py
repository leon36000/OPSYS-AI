"""Transport opérateur HTTP privé, données fictives, sans Core ni scheduler exécuté."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from base64 import urlsafe_b64encode
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, delete, insert, inspect, select, update
from starlette.testclient import TestClient

from opsys import agents, agents_cron_autorite, stockage
from opsys import agents_declencheurs as intentions
from opsys.departements import charger_departements
from opsys.serveur_mcp import application_http_departements
from opsys.stockage.schema import AGENTS_DECLENCHEURS_INTENTIONS as INTENTIONS
from opsys.stockage.schema import AGENTS_DECLENCHEURS_REMISES as REMISES
from opsys.stockage.schema import JOURNAL, ROLES_PERSONNES

JETON_PUBLIC = "jeton-public-fictif-long-abcdefghijklmnopqrstuvwxyz"
JETON_CONTEXTE = "jeton-contexte-fictif-long-abcdefghijklmnopqrstuvwxyz"
JETON_OPERATEUR = "jeton-operateur-fictif-long-abcdefghijklmnopqrstuvwxyz"
CAPACITE = "15" * 32
HASH_CAPACITE = hashlib.sha256(bytes.fromhex(CAPACITE)).hexdigest()


@pytest.fixture
def transport_cron(session, nathan, opsys_home, monkeypatch):
    monkeypatch.delenv(stockage.ENV_URL, raising=False)
    monkeypatch.setenv("OPENCLAW_CONFIG_DIR", str(opsys_home / "core"))
    monkeypatch.setenv("OPSYS_CRON_OPERATEUR_JETON", JETON_OPERATEUR)
    deps = charger_departements()
    with session() as cnx:
        agents.creer(cnx, deps, {
            "id": "cron-fictif", "departement": "m03-estimation",
            "responsabilite": "Lire des devis fictifs et proposer une calibration sans envoi",
            "palier_modele": "standard", "outils": ["m3_lire_devis", "m3_proposer_calibration_temps"],
            "budget_jour": 1000, "budget_mois": 10000, "limite_tours": 8,
            "limite_reessais": 2, "limite_concurrence": 1,
            "declencheurs": [{"type": "cron", "expression": "0 7 * * 1-5"}],
        }, par=nathan, mutation_id="creation-http-cron-fictif")
        agents.definir_actif(cnx, "cron-fictif", deps, True, par=nathan,
                             mutation_id="activation-http-cron-fictif", revision_attendue=1)
    policy = {"version": 1, "departements": {"m03-estimation": "global"},
              "agents": {"opsys-agent-cron-fictif": {"departement": "m03-estimation", "mode": "global"}},
              "procedures_globales": ["procedures"]}
    fichier = opsys_home / "core" / "opsys" / "memoire-autorites.json"
    fichier.parent.mkdir(parents=True)
    fichier.write_text(json.dumps(policy))
    demande = intentions.demander(deps, "cron-fictif", par=nathan, revision_attendue=2,
                                  fuseau="America/Toronto", mutation_id="mandat-http-cron-fictif")
    intention_id = demande["intentions"][0]
    declaration = intentions.projeter(deps, intention_id, par=nathan)["native"]["params"]
    app = application_http_departements(deps, session, JETON_PUBLIC, jeton_contexte=JETON_CONTEXTE)
    with TestClient(app) as client:
        yield client, intention_id, declaration, session


def _headers(jeton=JETON_OPERATEUR):
    return {"Authorization": f"Bearer {jeton}", "Content-Type": "application/json"}


def _preparer(client, intention_id, declaration):
    return client.post("/cron-operateur/v1/cron-fictif/preparer", headers=_headers(), json={
        "intention_id": intention_id,
        "empreinte_capacite": HASH_CAPACITE,
        "declaration": declaration,
        "epoch_attendue": 0,
        "revision_native_attendue": None,
        "lease_secondes": 30,
    })


def test_rpc_operateur_prepare_ack_sur_sqlite_et_rejeu(transport_cron):
    client, intention_id, declaration, session = transport_cron
    preparation = _preparer(client, intention_id, declaration)
    assert preparation.status_code == 200
    assert preparation.headers["cache-control"] == "no-store"
    plan = preparation.json()["resultat"]
    assert plan["native"]["params"] == declaration and plan["execute"] is False
    ack_body = {"intention_id": intention_id, "capabilite": CAPACITE, "epoch": plan["epoch"],
                "lease_epoch": plan["lease_epoch"], "job_id": "job-fictif-http-1",
                "config_revision": 1, "declaration": declaration}
    accuse = client.post("/cron-operateur/v1/cron-fictif/accuser", headers=_headers(), json=ack_body)
    assert accuse.status_code == 200
    assert accuse.json()["resultat"]["etat"] == "remise"
    assert CAPACITE not in accuse.text and HASH_CAPACITE not in accuse.text
    with session() as cnx:
        avant = cnx.execute(select(JOURNAL)).all()
        ligne = cnx.execute(select(REMISES)).mappings().one()
    rejoue = client.post("/cron-operateur/v1/cron-fictif/accuser", headers=_headers(), json=ack_body)
    assert rejoue.status_code == 200 and rejoue.json() == accuse.json()
    with session() as cnx:
        assert cnx.execute(select(JOURNAL)).all() == avant
        assert dict(cnx.execute(select(REMISES)).mappings().one()) == dict(ligne)


def test_rpc_revision_sha256_preimage_et_cible_distinctes_rejeu_exact(transport_cron):
    client, intention_id, declaration, session = transport_cron
    # Empreintes fictives au format Core : ce cas vérifie le transport opaque,
    # pas le calcul d'une définition Core ni l'exécution de son CAS natif.
    revision_avant, revision_cible = [
        "sha256:" + urlsafe_b64encode(hashlib.sha256(texte).digest()).decode().rstrip("=")
        for texte in (b"definition-desactivee-fictive", b"definition-activee-fictive")
    ]
    preparation = client.post("/cron-operateur/v1/cron-fictif/preparer", headers=_headers(), json={
        "intention_id": intention_id, "empreinte_capacite": HASH_CAPACITE,
        "declaration": declaration, "epoch_attendue": 0,
        "revision_native_attendue": revision_avant, "lease_secondes": 30,
    })
    assert preparation.status_code == 200
    plan = preparation.json()["resultat"]
    assert plan["revision_native_attendue"] == revision_avant and plan["execute"] is False
    corps = {"intention_id": intention_id, "capabilite": CAPACITE, "epoch": plan["epoch"],
             "lease_epoch": plan["lease_epoch"], "job_id": "job-sha-fictif",
             "config_revision": revision_cible, "declaration": declaration}
    route = "/cron-operateur/v1/cron-fictif/accuser"
    accuse = client.post(route, headers=_headers(), json=corps)
    assert accuse.status_code == 200
    assert accuse.json()["resultat"]["config_revision"] == revision_cible
    assert CAPACITE not in accuse.text and HASH_CAPACITE not in accuse.text
    with session() as cnx:
        avant = dict(cnx.execute(select(REMISES)).mappings().one())
        journal_avant = cnx.execute(select(JOURNAL)).all()
    assert client.post(route, headers=_headers(), json=corps).json() == accuse.json()
    perime = client.post(route, headers=_headers(), json={**corps, "config_revision": revision_avant})
    assert perime.status_code == 409 and perime.headers["cache-control"] == "no-store"
    with session() as cnx:
        assert dict(cnx.execute(select(REMISES)).mappings().one()) == avant
        assert cnx.execute(select(JOURNAL)).all() == journal_avant


def test_jetons_operateur_et_runtime_sont_des_audiences_distinctes(transport_cron):
    client, intention_id, declaration, session = transport_cron
    route_operateur = "/cron-operateur/v1/cron-fictif/preparer"
    corps = {"intention_id": intention_id, "empreinte_capacite": HASH_CAPACITE,
             "declaration": declaration, "epoch_attendue": 0,
             "revision_native_attendue": None, "lease_secondes": 30}
    refuse = client.post(route_operateur, headers=_headers(JETON_CONTEXTE), json=corps)
    assert refuse.status_code == 401 and refuse.headers["cache-control"] == "no-store"
    refuse_public = client.post(route_operateur, headers=_headers(JETON_PUBLIC), json=corps)
    assert refuse_public.status_code == 401
    refuse_runtime = client.post("/mcp/runtime/cron-fictif", headers=_headers(JETON_OPERATEUR), json={})
    assert refuse_runtime.status_code == 401
    refuse_mcp = client.post("/mcp", headers=_headers(JETON_OPERATEUR), json={})
    assert refuse_mcp.status_code == 401
    with session() as cnx:
        assert cnx.execute(select(REMISES)).all() == []
    assert _preparer(client, intention_id, declaration).status_code == 200


@pytest.mark.parametrize("audience", [JETON_PUBLIC, JETON_CONTEXTE])
def test_credential_operateur_refuse_collision_avec_audience_effective(
    transport_cron, monkeypatch, audience,
):
    _, _, _, session = transport_cron
    monkeypatch.setenv("OPSYS_CRON_OPERATEUR_JETON", audience)
    with pytest.raises(ValueError, match="distinct"):
        application_http_departements(
            charger_departements(), session, JETON_PUBLIC, jeton_contexte=JETON_CONTEXTE,
        )


def test_factory_vers_deuxieme_sqlite_est_refusee_sans_ecriture(monkeypatch, tmp_path):
    canonique = tmp_path / "canonique.db"
    etrangere = tmp_path / "etrangere.db"
    moteur_canonique = create_engine(f"sqlite:///{canonique}")
    moteur_etranger = create_engine(f"sqlite:///{etrangere}")
    for moteur in (moteur_canonique, moteur_etranger):
        with moteur.begin() as cnx:
            cnx.exec_driver_sql("CREATE TABLE sentinelle (id INTEGER PRIMARY KEY)")
    avant = inspect(moteur_etranger).get_table_names()
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{canonique}")
    monkeypatch.setenv("OPSYS_CRON_OPERATEUR_JETON", JETON_OPERATEUR)

    @contextmanager
    def factory_etrangere():
        with moteur_etranger.connect() as cnx:
            yield cnx

    with pytest.raises(ValueError, match="canal cron opérateur indisponible"):
        application_http_departements({}, factory_etrangere, JETON_PUBLIC)
    assert inspect(moteur_etranger).get_table_names() == avant
    moteur_canonique.dispose()
    moteur_etranger.dispose()


def test_base_canonique_changee_apres_montage_refuse_avant_ecriture(transport_cron, monkeypatch, tmp_path):
    client, intention_id, declaration, _ = transport_cron
    autre = tmp_path / "base-apres-montage.db"
    moteur_autre = create_engine(f"sqlite:///{autre}")
    with moteur_autre.begin() as cnx:
        cnx.exec_driver_sql("CREATE TABLE sentinelle (id INTEGER PRIMARY KEY)")
    avant = inspect(moteur_autre).get_table_names()
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{autre}")
    response = _preparer(client, intention_id, declaration)
    assert response.status_code == 503 and response.json()["erreur"] == "base_canonique_modifiee"
    assert inspect(moteur_autre).get_table_names() == avant
    moteur_autre.dispose()


def test_route_absente_sans_credential_operateur(transport_cron, monkeypatch):
    _, intention_id, _, session = transport_cron
    monkeypatch.delenv("OPSYS_CRON_OPERATEUR_JETON")
    app = application_http_departements(charger_departements(), session, JETON_PUBLIC,
                                        jeton_contexte=JETON_CONTEXTE)
    with TestClient(app) as client:
        response = client.post("/cron-operateur/v1/cron-fictif/preparer", headers=_headers(JETON_PUBLIC),
                               content=b"not-json")
        lire = client.post("/cron-operateur/v1/cron-fictif/lire", headers=_headers(JETON_PUBLIC), json={})
        projeter = client.post("/cron-operateur/v1/cron-fictif/projeter", headers=_headers(JETON_PUBLIC), json={
            "intention_id": intention_id,
        })
    assert response.status_code == lire.status_code == projeter.status_code == 404


def test_corps_trop_gros_et_entier_booleen_refuses_sans_grant(transport_cron):
    client, intention_id, declaration, session = transport_cron
    with session() as cnx:
        avant = cnx.execute(select(REMISES)).all()
    trop_gros = client.post("/cron-operateur/v1/cron-fictif/preparer", headers=_headers(),
                            content=b" " * (20 * 1024 + 1))
    assert trop_gros.status_code == 400
    assert trop_gros.headers["cache-control"] == "no-store"
    booleen = client.post("/cron-operateur/v1/cron-fictif/preparer", headers=_headers(), json={
        "intention_id": intention_id, "empreinte_capacite": HASH_CAPACITE,
        "declaration": declaration, "epoch_attendue": True,
        "revision_native_attendue": None, "lease_secondes": 30,
    })
    assert booleen.status_code == 409
    with session() as cnx:
        assert cnx.execute(select(REMISES)).all() == avant


@pytest.mark.parametrize("longueur", ["9" * 4301, "0" * 4301], ids=["nonzero_excessive", "zero_excessive"])
def test_longueur_http_invalide_refusee_sans_grant(transport_cron, longueur):
    client, _, _, session = transport_cron
    response = client.post("/cron-operateur/v1/cron-fictif/preparer",
                           headers={**_headers(), "Content-Length": longueur}, content=b"{}")
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    with session() as cnx:
        assert cnx.execute(select(REMISES)).all() == []


@pytest.mark.parametrize("entete", ["Authorization", "Content-Type", "Content-Length"])
def test_entetes_http_dupliques_refuses_sans_grant(transport_cron, entete):
    client, intention_id, declaration, session = transport_cron
    corps = json.dumps({"intention_id": intention_id, "empreinte_capacite": HASH_CAPACITE,
                        "declaration": declaration, "epoch_attendue": 0,
                        "revision_native_attendue": None, "lease_secondes": 30}).encode()
    headers = list(_headers().items()) + [("Content-Length", str(len(corps)))]
    valeur = dict(headers)[entete]
    headers.append((entete, valeur))
    response = client.post("/cron-operateur/v1/cron-fictif/preparer", headers=headers, content=corps)
    assert response.status_code == (401 if entete == "Authorization" else 400)
    assert response.headers["cache-control"] == "no-store"
    with session() as cnx:
        assert cnx.execute(select(REMISES)).all() == []


@pytest.mark.parametrize("corps", [
    b'{"intention_id":"a","intention_id":"b"}',
    b'{"intention_id":"a","empreinte_capacite":"x","declaration":{},'
    b'"epoch_attendue":0,"revision_native_attendue":null,"lease_secondes":30,"par":"nathan"}',
])
def test_requete_dupliquee_ou_identite_forgée_refusee_sans_ecriture(transport_cron, corps):
    client, intention_id, declaration, session = transport_cron
    with session() as cnx:
        avant = cnx.execute(select(REMISES)).all()
    response = client.post("/cron-operateur/v1/cron-fictif/preparer", headers=_headers(), content=corps)
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    with session() as cnx:
        assert cnx.execute(select(REMISES)).all() == avant


def test_mandant_revoque_entre_prepare_et_ack_ne_peut_acquitter(transport_cron):
    client, intention_id, declaration, session = transport_cron
    plan = _preparer(client, intention_id, declaration).json()["resultat"]
    with session() as cnx:
        cnx.execute(delete(ROLES_PERSONNES).where(ROLES_PERSONNES.c.identifiant == "nathan"))
        avant = cnx.execute(select(REMISES)).all()
    response = client.post("/cron-operateur/v1/cron-fictif/accuser", headers=_headers(), json={
        "intention_id": intention_id, "capabilite": CAPACITE, "epoch": plan["epoch"],
        "lease_epoch": plan["lease_epoch"], "job_id": "job-fictif-http-1",
        "config_revision": 1, "declaration": declaration,
    })
    assert response.status_code == 409 and CAPACITE not in response.text
    with session() as cnx:
        assert cnx.execute(select(REMISES)).all() == avant


def _remettre(client, intention_id, declaration):
    plan = _preparer(client, intention_id, declaration).json()["resultat"]
    body = {"intention_id": intention_id, "capabilite": CAPACITE, "epoch": plan["epoch"],
            "lease_epoch": plan["lease_epoch"], "job_id": "job-valider-http",
            "config_revision": 1, "declaration": declaration}
    assert client.post("/cron-operateur/v1/cron-fictif/accuser", headers=_headers(), json=body).status_code == 200
    return body


def test_rpc_valider_prive_refuse_auth_cap_revision_et_retrait_sans_publication(transport_cron):
    client, intention_id, declaration, session = transport_cron
    ack = _remettre(client, intention_id, declaration)
    validation = {cle: valeur for cle, valeur in ack.items() if cle != "lease_epoch"}
    route = "/cron-operateur/v1/cron-fictif/valider"
    avant_auth = client.post(route, headers=_headers(JETON_PUBLIC), json=validation)
    assert avant_auth.status_code == 401 and CAPACITE not in avant_auth.text
    with session() as cnx:
        avant_validation = dict(cnx.execute(select(REMISES)).mappings().one())
        journal_validation = cnx.execute(select(JOURNAL)).all()
    valide = client.post(route, headers=_headers(), json=validation)
    assert valide.status_code == 200 and valide.headers["cache-control"] == "no-store"
    assert valide.json() == {
        "ok": True, "resultat": {"valide": True},
    }
    with session() as cnx:
        avant = dict(cnx.execute(select(REMISES)).mappings().one())
        journal_avant = cnx.execute(select(JOURNAL)).all()
        assert avant == avant_validation and journal_avant == journal_validation
    for invalide in ({**validation, "capabilite": "00" * 32},
                     {**validation, "config_revision": 2}):
        refuse = client.post(route, headers=_headers(), json=invalide)
        assert refuse.status_code == 409 and CAPACITE not in refuse.text
    role_forge = client.post(route, headers=_headers(), json={**validation, "role": "admin"})
    assert role_forge.status_code == 400
    with session() as cnx:
        assert dict(cnx.execute(select(REMISES)).mappings().one()) == avant
        assert cnx.execute(select(JOURNAL)).all() == journal_avant
    agents_cron_autorite.ProprietaireCron(charger_departements(), "cron-fictif").revoquer(
        intention_id, capabilite=CAPACITE, epoch=ack["epoch"],
    )
    with session() as cnx:
        apres_retrait = dict(cnx.execute(select(REMISES)).mappings().one())
        journal_retrait = cnx.execute(select(JOURNAL)).all()
    refuse_retrait = client.post(route, headers=_headers(), json=validation)
    assert refuse_retrait.status_code == 409 and CAPACITE not in refuse_retrait.text
    with session() as cnx:
        assert dict(cnx.execute(select(REMISES)).mappings().one()) == apres_retrait
        assert cnx.execute(select(JOURNAL)).all() == journal_retrait
    assert apres_retrait != avant and journal_retrait != journal_avant


def test_rpc_lire_projeter_bornes_filtre_et_aucune_ecriture(transport_cron):
    client, intention_id, declaration, session = transport_cron
    with session() as cnx:
        source = dict(cnx.execute(select(INTENTIONS).where(INTENTIONS.c.id == intention_id)).mappings().one())
        deps = charger_departements()
        agents.creer(cnx, deps, {
            "id": "autre-cron-fictif", "departement": "m03-estimation",
            "responsabilite": "Lire des devis fictifs pour vérifier le cloisonnement de lecture",
            "palier_modele": "standard", "outils": ["m3_lire_devis"],
            "budget_jour": 1000, "budget_mois": 10000, "limite_tours": 8,
            "limite_reessais": 2, "limite_concurrence": 1,
            "declencheurs": [{"type": "cron", "expression": "5 9 * * 1-5"}],
        }, par="nathan", mutation_id="creation-autre-cron-fictif")
        supplement = []
        for offset in range(15):
            row = dict(source)
            row["fuseau"] = f"test-zone-{offset}"
            ident = intentions._hash({
                "instance": row["instance_id"], "profil": row["agent_id"],
                "revision": row["profile_revision"], "cron": row["trigger_hash"],
                "fuseau": row["fuseau"],
            })
            row["id"] = ident
            row["declaration_key"] = "opsys-profile:" + ident
            row["cree_le"] = f"2026-10-03T00:00:{offset:02d}+00:00"
            row["modifie_le"] = row["cree_le"]
            supplement.append(row)
        hors_instance = dict(source)
        hors_instance["instance_id"] = "00000000-0000-0000-0000-000000000001"
        hors_instance["fuseau"] = "Etc/GMT+9"
        hors_instance["id"] = intentions._hash({
            "instance": hors_instance["instance_id"], "profil": hors_instance["agent_id"],
            "revision": hors_instance["profile_revision"], "cron": hors_instance["trigger_hash"],
            "fuseau": hors_instance["fuseau"],
        })
        hors_instance["declaration_key"] = "opsys-profile:" + hors_instance["id"]
        supplement.append(hors_instance)
        autre_profil = dict(source)
        autre_profil["agent_id"] = "autre-cron-fictif"
        autre_profil["profile_revision"] = 1
        autre_profil["trigger_hash"] = intentions._hash({
            "type": "cron", "expression": "5 9 * * 1-5",
        })
        autre_profil["fuseau"] = "America/Montreal"
        autre_profil["id"] = intentions._hash({
            "instance": autre_profil["instance_id"], "profil": autre_profil["agent_id"],
            "revision": autre_profil["profile_revision"], "cron": autre_profil["trigger_hash"],
            "fuseau": autre_profil["fuseau"],
        })
        autre_profil["declaration_key"] = "opsys-profile:" + autre_profil["id"]
        supplement.append(autre_profil)
        retiree = dict(source)
        retiree["fuseau"] = "Etc/GMT+8"
        retiree["id"] = intentions._hash({
            "instance": retiree["instance_id"], "profil": retiree["agent_id"],
            "revision": retiree["profile_revision"], "cron": retiree["trigger_hash"],
            "fuseau": retiree["fuseau"],
        })
        retiree["declaration_key"] = "opsys-profile:" + retiree["id"]
        retiree["statut"] = "retiree"
        supplement.append(retiree)
        cnx.execute(insert(INTENTIONS), supplement)
        avant_remises = cnx.execute(select(REMISES)).all()
        avant_journal = cnx.execute(select(JOURNAL)).all()

    route_lire = "/cron-operateur/v1/cron-fictif/lire"
    lecture = client.post(route_lire, headers=_headers(), json={})
    assert lecture.status_code == 200 and lecture.headers["cache-control"] == "no-store"
    resultat = lecture.json()["resultat"]
    assert (resultat["total"], resultat["retournes"], resultat["omis"]) == (16, 16, 0)
    assert len(resultat["items"]) == 16
    assert len(lecture.content) < 20 * 1024
    assert CAPACITE not in lecture.text and HASH_CAPACITE not in lecture.text
    assert all(set(item) == {"intention_id", "etat", "revision_profil", "fuseau"} for item in resultat["items"])
    assert all(item["intention_id"] != hors_instance["id"] for item in resultat["items"])
    assert all(item["intention_id"] != autre_profil["id"] for item in resultat["items"])
    assert all(item["intention_id"] != retiree["id"] for item in resultat["items"])

    route_projet = "/cron-operateur/v1/cron-fictif/projeter"
    projection = client.post(route_projet, headers=_headers(), json={"intention_id": intention_id})
    assert projection.status_code == 200 and projection.headers["cache-control"] == "no-store"
    plan = projection.json()["resultat"]
    assert plan["native"] == {"method": "cron.add", "params": declaration}
    assert plan["execute"] is False and "argv" not in plan
    assert CAPACITE not in projection.text and HASH_CAPACITE not in projection.text

    with session() as cnx:
        assert cnx.execute(select(REMISES)).all() == avant_remises
        assert cnx.execute(select(JOURNAL)).all() == avant_journal


def test_rpc_lire_refuse_dix_sept_intentions_sans_reponse_partielle(transport_cron):
    client, intention_id, _, session = transport_cron
    with session() as cnx:
        source = dict(cnx.execute(select(INTENTIONS).where(INTENTIONS.c.id == intention_id)).mappings().one())
        rows = []
        for offset in range(16):
            row = dict(source, fuseau=f"zone-fictive-{offset}", statut="a_retirer")
            ident = intentions._hash({
                "instance": row["instance_id"], "profil": row["agent_id"],
                "revision": row["profile_revision"], "cron": row["trigger_hash"], "fuseau": row["fuseau"],
            })
            rows.append(dict(row, id=ident, declaration_key="opsys-profile:" + ident))
        cnx.execute(insert(INTENTIONS), rows)
        avant_intentions = cnx.execute(select(INTENTIONS)).all()
        avant_remises = cnx.execute(select(REMISES)).all()
        avant_journal = cnx.execute(select(JOURNAL)).all()
    response = client.post("/cron-operateur/v1/cron-fictif/lire", headers=_headers(), json={})
    assert response.status_code == 409 and response.headers["cache-control"] == "no-store"
    assert "resultat" not in response.json() and "items" not in response.text
    assert CAPACITE not in response.text and HASH_CAPACITE not in response.text
    with session() as cnx:
        assert cnx.execute(select(INTENTIONS)).all() == avant_intentions
        assert cnx.execute(select(REMISES)).all() == avant_remises
        assert cnx.execute(select(JOURNAL)).all() == avant_journal


@pytest.mark.parametrize("route,corps", [
    ("lire", b'{"role":"admin"}'),
    ("lire", b'{"par":"nathan"}'),
    ("projeter", b'{"intention_id":"x","intention_id":"y"}'),
    ("projeter", b'{"intention_id":"x","role":"admin"}'),
])
def test_rpc_lire_projeter_rejettent_role_body_et_doublon_sans_ecriture(
    transport_cron, route, corps,
):
    client, _, _, session = transport_cron
    with session() as cnx:
        avant = cnx.execute(select(JOURNAL)).all()
        remises = cnx.execute(select(REMISES)).all()
    response = client.post(
        f"/cron-operateur/v1/cron-fictif/{route}", headers=_headers(), content=corps,
    )
    assert response.status_code == 400 and response.headers["cache-control"] == "no-store"
    with session() as cnx:
        assert cnx.execute(select(JOURNAL)).all() == avant
        assert cnx.execute(select(REMISES)).all() == remises


@pytest.mark.parametrize("route,corps", [
    ("lire?par=nathan", b"{}"),
    ("projeter?role=admin", b'{"intention_id":"x"}'),
])
def test_rpc_lire_projeter_refusent_query(transport_cron, route, corps):
    client, _, _, session = transport_cron
    with session() as cnx:
        avant = cnx.execute(select(JOURNAL)).all()
    response = client.post(f"/cron-operateur/v1/cron-fictif/{route}", headers=_headers(), content=corps)
    assert response.status_code == 400 and response.headers["cache-control"] == "no-store"
    with session() as cnx:
        assert cnx.execute(select(JOURNAL)).all() == avant


def test_rpc_lire_projeter_exigent_audience_operateur_et_profil_exact(transport_cron):
    client, intention_id, _, session = transport_cron
    with session() as cnx:
        journal_avant = cnx.execute(select(JOURNAL)).all()
        remises_avant = cnx.execute(select(REMISES)).all()
    for audience in (None, JETON_PUBLIC, JETON_CONTEXTE):
        headers = {"Content-Type": "application/json"}
        if audience is not None:
            headers["Authorization"] = f"Bearer {audience}"
        lecture = client.post("/cron-operateur/v1/cron-fictif/lire", headers=headers, json={})
        projection = client.post("/cron-operateur/v1/cron-fictif/projeter", headers=headers, json={
            "intention_id": intention_id,
        })
        assert lecture.status_code == projection.status_code == 401
    croise = client.post("/cron-operateur/v1/autre-profil/projeter", headers=_headers(), json={
        "intention_id": intention_id,
    })
    assert croise.status_code == 409
    with session() as cnx:
        assert cnx.execute(select(REMISES)).all() == remises_avant
        assert cnx.execute(select(JOURNAL)).all() == journal_avant


def test_rpc_lire_reste_metadata_apres_retrait_role_projection_refuse(transport_cron, session):
    client, intention_id, _, _ = transport_cron
    with session() as cnx:
        cnx.execute(delete(ROLES_PERSONNES).where(ROLES_PERSONNES.c.identifiant == "nathan"))
        journal_avant = cnx.execute(select(JOURNAL)).all()
        remises_avant = cnx.execute(select(REMISES)).all()
    lecture = client.post("/cron-operateur/v1/cron-fictif/lire", headers=_headers(), json={})
    assert lecture.status_code == 200
    assert any(item["intention_id"] == intention_id for item in lecture.json()["resultat"]["items"])
    projection = client.post("/cron-operateur/v1/cron-fictif/projeter", headers=_headers(), json={
        "intention_id": intention_id,
    })
    assert projection.status_code == 409
    with session() as cnx:
        assert cnx.execute(select(JOURNAL)).all() == journal_avant
        assert cnx.execute(select(REMISES)).all() == remises_avant


def test_rpc_lire_reste_metadata_profil_inactif_projection_refuse(transport_cron, session):
    client, intention_id, _, _ = transport_cron
    with session() as cnx:
        agents.definir_actif(
            cnx, "cron-fictif", charger_departements(), False, par="nathan",
            mutation_id="desactivation-http-cron-fictif", revision_attendue=2,
        )
        journal_avant = cnx.execute(select(JOURNAL)).all()
        remises_avant = cnx.execute(select(REMISES)).all()
    lecture = client.post("/cron-operateur/v1/cron-fictif/lire", headers=_headers(), json={})
    assert lecture.status_code == 200
    assert any(item["intention_id"] == intention_id for item in lecture.json()["resultat"]["items"])
    projection = client.post("/cron-operateur/v1/cron-fictif/projeter", headers=_headers(), json={
        "intention_id": intention_id,
    })
    assert projection.status_code == 409
    with session() as cnx:
        assert cnx.execute(select(JOURNAL)).all() == journal_avant
        assert cnx.execute(select(REMISES)).all() == remises_avant


def test_rpc_lire_reconciliation_retrait_sans_projection_native(transport_cron, session):
    client, intention_id, _, _ = transport_cron
    with session() as cnx:
        cnx.execute(update(INTENTIONS).where(INTENTIONS.c.id == intention_id).values(statut="a_retirer"))
        journal_avant = cnx.execute(select(JOURNAL)).all()
        remises_avant = cnx.execute(select(REMISES)).all()
    projection = client.post("/cron-operateur/v1/cron-fictif/projeter", headers=_headers(), json={
        "intention_id": intention_id,
    })
    assert projection.status_code == 200
    assert projection.json()["resultat"]["reconciliation"] == "rechercher_id_natif_puis_retirer"
    assert projection.json()["resultat"]["native"] is None
    with session() as cnx:
        assert cnx.execute(select(JOURNAL)).all() == journal_avant
        assert cnx.execute(select(REMISES)).all() == remises_avant


def test_rpc_valider_reverifie_demandeur_actif_apres_ack_sans_ecriture(transport_cron):
    client, intention_id, declaration, session = transport_cron
    ack = _remettre(client, intention_id, declaration)
    validation = {cle: valeur for cle, valeur in ack.items() if cle != "lease_epoch"}
    with session() as cnx:
        cnx.execute(delete(ROLES_PERSONNES).where(ROLES_PERSONNES.c.identifiant == "nathan"))
        avant = dict(cnx.execute(select(REMISES)).mappings().one())
        journal_avant = cnx.execute(select(JOURNAL)).all()
    response = client.post("/cron-operateur/v1/cron-fictif/valider", headers=_headers(), json=validation)
    assert response.status_code == 409 and CAPACITE not in response.text
    with session() as cnx:
        assert dict(cnx.execute(select(REMISES)).mappings().one()) == avant
        assert cnx.execute(select(JOURNAL)).all() == journal_avant


def test_rpc_renouveler_refuse_auth_cap_lease_et_role_inconnu_sans_ecriture(transport_cron):
    client, intention_id, declaration, session = transport_cron
    plan = _preparer(client, intention_id, declaration).json()["resultat"]
    route = "/cron-operateur/v1/cron-fictif/renouveler"
    body = {"intention_id": intention_id, "capabilite": CAPACITE, "epoch": plan["epoch"],
            "lease_epoch": plan["lease_epoch"], "declaration": declaration, "lease_secondes": 30}
    with session() as cnx:
        avant = dict(cnx.execute(select(REMISES)).mappings().one())
        journal_avant = cnx.execute(select(JOURNAL)).all()
    requetes = [(_headers(JETON_PUBLIC), body, 401),
                (_headers(), {**body, "capabilite": "00" * 32}, 409),
                (_headers(), {**body, "lease_epoch": body["lease_epoch"] + 1}, 409),
                (_headers(), {**body, "lease_secondes": True}, 409),
                (_headers(), {**body, "role": "admin"}, 400)]
    for headers, contenu, statut in requetes:
        refuse = client.post(route, headers=headers, json=contenu)
        assert refuse.status_code == statut and CAPACITE not in refuse.text
    with session() as cnx:
        assert dict(cnx.execute(select(REMISES)).mappings().one()) == avant
        assert cnx.execute(select(JOURNAL)).all() == journal_avant


def test_rpc_renouveler_lease_expiree_et_rejeu_exact_sans_second_audit(
    transport_cron, monkeypatch,
):
    client, intention_id, declaration, session = transport_cron
    plan = _preparer(client, intention_id, declaration).json()["resultat"]
    route = "/cron-operateur/v1/cron-fictif/renouveler"
    body = {"intention_id": intention_id, "capabilite": CAPACITE, "epoch": plan["epoch"],
            "lease_epoch": plan["lease_epoch"], "declaration": declaration, "lease_secondes": 30}
    instant = agents_cron_autorite._maintenant()
    monkeypatch.setattr(agents_cron_autorite, "_maintenant",
                        lambda: instant + dt.timedelta(seconds=31))
    with session() as cnx:
        avant_expiration = dict(cnx.execute(select(REMISES)).mappings().one())
        journal_avant = cnx.execute(select(JOURNAL)).all()
    refuse = client.post(route, headers=_headers(), json={**body, "lease_secondes": True})
    assert refuse.status_code == 409 and CAPACITE not in refuse.text
    with session() as cnx:
        assert dict(cnx.execute(select(REMISES)).mappings().one()) == avant_expiration
        assert cnx.execute(select(JOURNAL)).all() == journal_avant
    response = client.post(route, headers=_headers(), json=body)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    resultat = response.json()["resultat"]
    assert resultat["lease_epoch"] == plan["lease_epoch"] + 1
    assert CAPACITE not in response.text and HASH_CAPACITE not in response.text
    with session() as cnx:
        ligne = dict(cnx.execute(select(REMISES)).mappings().one())
        journal = cnx.execute(select(JOURNAL)).all()
    rejoue = client.post(route, headers=_headers(), json=body)
    assert rejoue.status_code == 200 and rejoue.json() == response.json()
    with session() as cnx:
        assert dict(cnx.execute(select(REMISES)).mappings().one()) == ligne
        assert cnx.execute(select(JOURNAL)).all() == journal
