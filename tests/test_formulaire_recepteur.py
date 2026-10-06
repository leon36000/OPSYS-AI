"""Pont interne : requêtes et identité fictives, stockage SQLite réel de test."""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from m1_front_office import outils as outils_m1
from m2_revenue_crm import ingestion as ingestion_m2
from m2_revenue_crm import outils as outils_m2
from sqlalchemy import func, select

from opsys import evenements, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.console.formulaire_recepteur import creer_router
from opsys.departements import Budget, charger_departements, lire_manifeste
from opsys.stockage.schema import EVENEMENTS_SORTANTS

REPO = Path(__file__).resolve().parents[1]
M1 = REPO / "departments/m01-front-office"
FAKE_SITE = "site-fictif-test"
FAKE_SECRET = b"cle-de-test-fictive-qui-ne-sert-qu-aux-tests-012345"
FAKE_EPOCH = 1_791_115_200  # 2026-10-04T12:00:00Z


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    outils_m1.utiliser_stockage_durable()
    outils_m2.utiliser_stockage_durable()
    departement = lire_manifeste(M1)
    capacites = Capacites({departement.id: departement}, stockage.transaction,
                          appelant=departement.id, memoire=False)
    yield capacites
    outils_m2.reinitialiser_registre()
    outils_m1.reinitialiser_registre()
    stockage.liberer()


def _body(**overrides):
    fields = {
        "courriel": "client.fictif@example.test",
        "message": "Mes gouttières fuient à Laval.",
        "nom": "",
        "telephone": "",
    }
    fields.update(overrides)
    return json.dumps(fields, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _signature(body: bytes, *, site=FAKE_SITE, timestamp=FAKE_EPOCH, nonce="nonce-fictif-000001"):
    prefix = f"v1\nPOST\n/interne/m1/formulaire\n{site}\n{timestamp}\n{nonce}\n".encode("ascii")
    mac = hmac.new(FAKE_SECRET, prefix + body, hashlib.sha256).hexdigest()
    return {
        "content-type": "application/json",
        "x-m1-site": site,
        "x-m1-timestamp": str(timestamp),
        "x-m1-nonce": nonce,
        "x-m1-signature": mac,
    }


def _client(invoquer, *, config=True, horloge=lambda: FAKE_EPOCH):
    app = FastAPI()
    app.include_router(creer_router(
        invoquer=invoquer,
        site_id=FAKE_SITE if config else None,
        secret=FAKE_SECRET if config else None,
        horloge=horloge,
    ))
    return TestClient(app)


def _compter():
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m1.lead_qualifie")).scalar_one()


def test_requete_signee_passe_par_capacites_m1_et_publie_le_vrai_lead_m2(runtime):
    client = _client(runtime.appeler)
    body = _body(utm_source="campagne-fictive")
    response = client.post("/interne/m1/formulaire", content=body, headers=_signature(body))
    assert response.status_code == 202
    assert response.json() == {"ok": True, "received": True}
    assert response.headers["cache-control"] == "no-store"
    assert _compter() == 1
    with stockage.transaction():
        charge = evenements.charge_publiee("m1.lead_qualifie", "m1-lead-qualifie-" + _lead_id())
    assert charge["lead"]["source"] == "formulaire"
    assert charge["lead"]["contact"] == {"courriel": "client.fictif@example.test"}
    assert charge["lead"]["utm"]["utm_source"] == "campagne-fictive"
    assert charge["signal_id"] == "formulaire:site-fictif-test:nonce-fictif-000001"
    dep_m2 = charger_departements()["m02-revenue-crm"]
    livre = evenements.repartir({dep_m2.id: dep_m2}, maintenant="2026-10-04T12:01:00+00:00")
    assert livre == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}
    with stockage.transaction():
        crm = outils_m2._obtenir_registre().lire()
    (lead_crm,) = [ligne for ligne in crm if ligne.get("type_entree") == ingestion_m2.TYPE_ENTREE]
    assert lead_crm["contrat"] == charge["lead"]


def _lead_id():
    with stockage.transaction():
        lignes = outils_m1._obtenir_registre().lire()
    return next(ligne["lead"]["lead_id"] for ligne in lignes if ligne["type_entree"] == "lead_emis")


def test_rejeu_exact_est_idempotent_et_ne_republie_pas(runtime):
    client = _client(runtime.appeler)
    body = _body()
    headers = _signature(body)
    premier = client.post("/interne/m1/formulaire", content=body, headers=headers)
    second = client.post("/interne/m1/formulaire", content=body, headers=headers)
    assert premier.status_code == second.status_code == 202
    assert _compter() == 1
    with stockage.transaction():
        lignes = outils_m1._obtenir_registre().lire()
    assert len([ligne for ligne in lignes if ligne["type_entree"] == "signal"]) == 1


def test_meme_nonce_avec_corps_different_est_refuse_sans_second_evenement(runtime):
    client = _client(runtime.appeler)
    premier = _body()
    headers = _signature(premier)
    assert client.post("/interne/m1/formulaire", content=premier, headers=headers).status_code == 202
    autre = _body(message="Mes gouttières fuient à Québec.")
    refuse = client.post("/interne/m1/formulaire", content=autre, headers=_signature(autre))
    assert refuse.status_code == 400
    assert refuse.json() == {"ok": False, "error": "invalid_request"}
    assert _compter() == 1


def test_meme_nonce_avec_timestamp_different_ne_change_pas_silencieusement_le_recu_le(runtime):
    client = _client(runtime.appeler)
    body = _body()
    assert client.post("/interne/m1/formulaire", content=body,
                       headers=_signature(body)).status_code == 202
    autre_timestamp = FAKE_EPOCH - 1
    refuse = client.post("/interne/m1/formulaire", content=body,
                         headers=_signature(body, timestamp=autre_timestamp))
    assert refuse.status_code == 400
    assert refuse.json() == {"ok": False, "error": "invalid_request"}
    assert _compter() == 1


def test_configuration_absente_refuse_503_sans_appeler_m1(runtime):
    called = []
    client = _client(lambda *a, **k: called.append((a, k)), config=False)
    body = _body()
    response = client.post("/interne/m1/formulaire", content=body, headers=_signature(body))
    assert response.status_code == 503 and response.json() == {"ok": False, "error": "unavailable"}
    assert called == []
    assert _compter() == 0


@pytest.mark.parametrize("headers_change", [
    {"x-m1-site": "autre-site-fictif"},
    {"x-m1-timestamp": str(FAKE_EPOCH - 301)},
    {"x-m1-signature": "0" * 64},
])
def test_site_date_ou_signature_invalides_refuses_avant_le_chemin_m1(runtime, headers_change):
    client = _client(runtime.appeler)
    body = _body()
    headers = _signature(body)
    headers.update(headers_change)
    response = client.post("/interne/m1/formulaire", content=body, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"ok": False, "error": "forbidden"}
    assert _compter() == 0


def test_entete_auth_repetee_est_refusee(runtime):
    client = _client(runtime.appeler)
    body = _body()
    headers = list(_signature(body).items()) + [("x-m1-site", FAKE_SITE)]
    response = client.post("/interne/m1/formulaire", content=body, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"ok": False, "error": "forbidden"}
    assert _compter() == 0


def test_date_signee_est_horodatage_canonique_stable(runtime):
    client = _client(runtime.appeler)
    body = _body()
    response = client.post("/interne/m1/formulaire", content=body,
                           headers=_signature(body, timestamp=FAKE_EPOCH - 60))
    assert response.status_code == 202
    with stockage.transaction():
        signal = next(ligne for ligne in outils_m1._obtenir_registre().lire() if ligne["type_entree"] == "signal")
    assert signal["horodatage"] == "2026-10-04T11:59:00+00:00"


def test_flux_sans_content_length_est_lu_puis_livre_au_chemin_m1(runtime):
    client = _client(runtime.appeler)
    body = _body(message="Bonjour.")
    request = client.build_request("POST", "/interne/m1/formulaire", content=body, headers=_signature(body))
    request.headers.pop("content-length", None)
    response = client.send(request)
    assert response.status_code == 202
    assert _compter() == 0  # demande incomplète: réception M1 sans publication
    with stockage.transaction():
        lignes = outils_m1._obtenir_registre().lire()
    assert len([ligne for ligne in lignes if ligne.get("type_entree") == "signal"]) == 1


@pytest.mark.parametrize("raw,content_type", [
    (b'{"courriel":"a@example.test","courriel":"b@example.test","message":"x"}', "application/json"),
    (b'{"courriel":"a@example.test","message":NaN}', "application/json"),
    (b'{', "application/json"),
    (b'{}', "text/plain"),
])
def test_json_ambigu_malforme_ou_mauvais_type_refuse_sans_ecriture(runtime, raw, content_type):
    client = _client(runtime.appeler)
    headers = _signature(raw)
    headers["content-type"] = content_type
    response = client.post("/interne/m1/formulaire", content=raw, headers=headers)
    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "invalid_request"}
    assert _compter() == 0


def test_champs_inconnus_ou_contact_non_supporte_refuses_sans_echo(runtime):
    client = _client(runtime.appeler)
    for body in (_body(nom="Nom fictif"), _body(extra="valeur privée fictive")):
        response = client.post("/interne/m1/formulaire", content=body, headers=_signature(body))
        assert response.status_code == 400
        assert b"fictif" not in response.content and b"client.fictif" not in response.content
    assert _compter() == 0


def test_utm_vide_est_refuse_sans_publication(runtime):
    client = _client(runtime.appeler)
    body = _body(utm_source="")
    response = client.post("/interne/m1/formulaire", content=body, headers=_signature(body))
    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "invalid_request"}
    assert _compter() == 0


def test_corps_trop_volumineux_est_bloque_avant_une_ecriture(runtime):
    client = _client(runtime.appeler)
    body = b" " * 24_001
    response = client.post("/interne/m1/formulaire", content=body, headers=_signature(body))
    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "invalid_request"}
    assert _compter() == 0


@pytest.mark.parametrize("profil", [
    "services: [gouttieres]\n",
    "zone_desservie: [Laval]\n",
    "services: [\n",
])
def test_configuration_metier_incomplete_est_reessayable_sans_lead(runtime, profil):
    taxonomie.fichier_profil().write_text(profil, encoding="utf-8")
    corps = _body()
    reponse = _client(runtime.appeler).post("/interne/m1/formulaire", content=corps, headers=_signature(corps))
    assert reponse.status_code == 503
    assert reponse.json() == {"ok": False, "error": "unavailable"}
    assert _compter() == 0


@pytest.mark.parametrize("corps", [
    br'{"courriel":"client.fictif@example.test","message":"\ud800"}',
    b'{"courriel":"client.fictif@example.test","message":' + b'[' * 9000 + b'0' + b']' * 9000 + b'}',
])
def test_json_signe_invalide_refuse_400_plutot_que_reprise_indefinie(runtime, corps):
    reponse = _client(runtime.appeler).post("/interne/m1/formulaire", content=corps, headers=_signature(corps))
    assert reponse.status_code == 400
    assert reponse.json() == {"ok": False, "error": "invalid_request"}
    assert _compter() == 0


def test_content_length_demasure_est_refuse_avant_conversion_entier(runtime):
    client = _client(runtime.appeler)
    body = b"{}"
    headers = dict(_signature(body))
    headers["content-length"] = "9" * 5000
    response = client.post("/interne/m1/formulaire", content=body, headers=headers)
    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "invalid_request"}
    assert _compter() == 0


def test_budget_m1_epuise_retourne_503_sans_faire_disparaitre_la_demande(runtime):
    nom = "m1_recevoir_message_canal"
    departement, outil = runtime.index[nom]
    runtime.index[nom] = (replace(departement, budget=Budget(tokens_jour=0, tokens_mois=0)), outil)
    client = _client(runtime.appeler)
    body = _body()
    response = client.post("/interne/m1/formulaire", content=body, headers=_signature(body))
    assert response.status_code == 503
    assert response.json() == {"ok": False, "error": "unavailable"}
    assert _compter() == 0
