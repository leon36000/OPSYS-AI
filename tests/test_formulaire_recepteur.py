"""Pont interne : requêtes et identité fictives, stockage SQLite réel de test."""
from __future__ import annotations

import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from m1_front_office import outils as outils_m1
from m2_revenue_crm import ingestion as ingestion_m2
from m2_revenue_crm import outils as outils_m2
from sqlalchemy import func, select

from opsys import contexte, evenements, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.console.formulaire_recepteur import creer_router
from opsys.departements import Budget, charger_departements, lire_manifeste
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

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


def _etat_metier_formulaire():
    """Contenu SQL réel : les UPDATE aussi doivent être détectés, pas seulement les comptes."""
    with stockage.transaction() as cnx:
        return {
            table.name: [dict(ligne._mapping) for ligne in cnx.execute(
                select(table).order_by(*table.primary_key.columns)
            )]
            for table in (REGISTRES, EVENEMENTS_SORTANTS, EVENEMENTS_RECUS)
        }


@pytest.mark.parametrize("message,qualifie", [
    ("Mes gouttières fuient à Laval.", True),
    ("Bonjour.", False),
], ids=["qualifie", "incomplet"])
@pytest.mark.parametrize("utm_initial,utm_rejoue", [
    ({"utm_source": "facebook"}, {"utm_source": "google"}),
    ({}, {"utm_source": "facebook"}),
    ({"utm_source": "facebook"}, {}),
], ids=["utm-change", "utm-ajoute", "utm-retire"])
def test_meme_nonce_avec_utm_divergent_refuse_sans_mutation_metier(
    runtime, message, qualifie, utm_initial, utm_rejoue,
):
    """La provenance d'un signal signé ne change pas lors d'un rejeu du même ID."""
    client = _client(runtime.appeler)
    premier = _body(message=message, **utm_initial)
    assert client.post("/interne/m1/formulaire", content=premier,
                       headers=_signature(premier)).status_code == 202
    assert _compter() == int(qualifie)
    if qualifie:
        dep_m2 = charger_departements()["m02-revenue-crm"]
        livraison = evenements.repartir({dep_m2.id: dep_m2}, maintenant="2026-10-04T12:01:00+00:00")
        assert livraison == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}
    avant = _etat_metier_formulaire()
    autre = _body(message=message, **utm_rejoue)
    refuse = client.post("/interne/m1/formulaire", content=autre, headers=_signature(autre))
    assert refuse.status_code == 400
    assert refuse.json() == {"ok": False, "error": "invalid_request"}
    assert _etat_metier_formulaire() == avant


def test_rejeu_utm_identique_ordre_des_cles_indifferent_apres_reouverture_sqlite(runtime):
    """Même processus, nouvelle connexion et nouvelle app ; aucune restauration revendiquée."""
    utm = {
        "utm_source": "facebook", "utm_medium": "social",
        "utm_campaign": "workflow-fictif-2026", "utm_content": "contenu-fictif-1",
    }
    premier = _body(**utm)
    assert _client(runtime.appeler).post("/interne/m1/formulaire", content=premier,
                                        headers=_signature(premier)).status_code == 202
    dep_m2 = charger_departements()["m02-revenue-crm"]
    livraison = evenements.repartir({dep_m2.id: dep_m2}, maintenant="2026-10-04T12:01:00+00:00")
    assert livraison["traites"] == 1 and livraison["echecs"] == livraison["quarantaines"] == 0
    avant = _etat_metier_formulaire()
    stockage.liberer()
    autre = _body(**dict(reversed(list(utm.items()))))
    assert autre != premier, "des octets différents peuvent porter le même UTM canonique"
    rejoue = _client(runtime.appeler).post("/interne/m1/formulaire", content=autre,
                                         headers=_signature(autre))
    assert rejoue.status_code == 202 and rejoue.json() == {"ok": True, "received": True}
    assert _etat_metier_formulaire() == avant


def test_nouveau_nonce_conserve_utm_de_sa_demande_incomplete(runtime):
    """Un nouvel ID reste une nouvelle réception, même pour le même correspondant."""
    client = _client(runtime.appeler)
    premier = _body(message="Bonjour.", utm_source="facebook")
    second = _body(message="Bonjour.", utm_source="google")
    assert client.post("/interne/m1/formulaire", content=premier,
                       headers=_signature(premier)).status_code == 202
    assert client.post("/interne/m1/formulaire", content=second,
                       headers=_signature(second, nonce="nonce-fictif-000002")).status_code == 202
    with stockage.transaction():
        signaux = [ligne for ligne in outils_m1._obtenir_registre().lire() if ligne["type_entree"] == "signal"]
    assert [ligne["utm"] for ligne in signaux] == [{"utm_source": "facebook"}, {"utm_source": "google"}]
    assert _compter() == 0


@pytest.mark.parametrize("alteration", ["signal_id", "utm", "utm_absent"])
def test_capsule_signee_incoherente_refuse_avant_premier_signal(runtime, alteration):
    """Un raccord interne incorrect ne peut dégrader la portée capturée en appel legacy."""
    def invoquer(nom, arguments):
        capture = contexte.formulaire_signe_courant()
        assert capture.signal_id == f"formulaire:{FAKE_SITE}:nonce-fictif-000001"
        assert capture.utm == (("utm_source", "facebook"),)
        modifies = dict(arguments)
        if alteration == "signal_id":
            modifies["message_id"] = f"{FAKE_SITE}:nonce-fictif-autre"
        elif alteration == "utm":
            arguments["utm"]["utm_source"] = "google"
        else:
            modifies["utm"] = None
        return runtime.appeler(nom, modifies)

    avant = _etat_metier_formulaire()
    body = _body(utm_source="facebook")
    response = _client(invoquer).post("/interne/m1/formulaire", content=body, headers=_signature(body))
    assert response.status_code == 400 and response.json() == {"ok": False, "error": "invalid_request"}
    assert _etat_metier_formulaire() == avant


@pytest.mark.parametrize("utm_initial,utm_rejoue", [
    ({"utm_source": "facebook"}, {"utm_source": "google"}),
    ({}, {"utm_source": "facebook"}),
    ({"utm_source": "facebook"}, {}),
])
def test_plainte_signee_refuse_utm_divergent_sur_signal_sans_lead(runtime, utm_initial, utm_rejoue):
    taxonomie.enregistrer_signaux_plainte({"insatisfaction": ["plainte"]})
    client = _client(runtime.appeler)
    premier = _body(message="Je dépose une plainte.", **utm_initial)
    assert client.post("/interne/m1/formulaire", content=premier, headers=_signature(premier)).status_code == 202
    with stockage.transaction():
        lignes = outils_m1._obtenir_registre().lire()
    assert any(ligne["type_entree"] == "transfert" and ligne["evenement"] == "ouvert" for ligne in lignes)
    assert not any(ligne["type_entree"] == "lead_emis" for ligne in lignes)
    assert _compter() == 0
    avant = _etat_metier_formulaire()
    autre = _body(message="Je dépose une plainte.", **utm_rejoue)
    refuse = client.post("/interne/m1/formulaire", content=autre, headers=_signature(autre))
    assert refuse.status_code == 400 and refuse.json() == {"ok": False, "error": "invalid_request"}
    assert _etat_metier_formulaire() == avant


def test_deux_workers_signes_concurrents_meme_nonce_un_signal_un_refus(runtime):
    barriere = Barrier(2)

    def invoquer(nom, arguments):
        assert contexte.formulaire_signe_courant().utm == tuple(sorted(arguments["utm"].items()))
        barriere.wait(timeout=5)
        return runtime.appeler(nom, arguments)

    def envoyer(source):
        body = _body(utm_source=source)
        with _client(invoquer) as client:
            return source, client.post("/interne/m1/formulaire", content=body, headers=_signature(body))

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(envoyer, "facebook")
        b = pool.submit(envoyer, "google")
        resultats = [a.result(timeout=15), b.result(timeout=15)]
    assert sorted(response.status_code for _, response in resultats) == [202, 400]
    gagnante = next(source for source, response in resultats if response.status_code == 202)
    refuse = next(response for _, response in resultats if response.status_code == 400)
    assert refuse.json() == {"ok": False, "error": "invalid_request"}
    with stockage.transaction():
        signaux = [ligne for ligne in outils_m1._obtenir_registre().lire() if ligne["type_entree"] == "signal"]
    assert len(signaux) == 1 and signaux[0]["utm"] == {"utm_source": gagnante}
    assert _compter() == 1
    with stockage.transaction():
        charge = evenements.charge_publiee("m1.lead_qualifie", "m1-lead-qualifie-" + _lead_id())
    assert charge["lead"]["utm"] == {"utm_source": gagnante}


def test_rejeu_generique_divergent_reste_permissif_apres_reception_signee(runtime):
    body = _body(utm_source="facebook")
    client = _client(runtime.appeler)
    assert client.post("/interne/m1/formulaire", content=body, headers=_signature(body)).status_code == 202
    avant = _etat_metier_formulaire()
    assert contexte.formulaire_signe_courant() is None
    legacy = runtime.appeler("m1_recevoir_message_canal", {
        "canal": "formulaire", "expediteur": "client.fictif@example.test",
        "message_id": f"{FAKE_SITE}:nonce-fictif-000001",
        "recu_le": datetime.fromtimestamp(FAKE_EPOCH, UTC).isoformat(timespec="seconds"),
        "texte": "Mes gouttières fuient à Laval.", "utm": {"utm_source": "google"},
    })
    assert legacy["ok"] is True and legacy["resultat"]["doublon"] is True
    assert legacy["resultat"]["lead"]["utm"] == {"utm_source": "facebook"}
    assert legacy["resultat"]["utm"]["statut"] == "non_porte"
    assert _etat_metier_formulaire() == avant
    autre = _body(utm_source="google")
    assert client.post("/interne/m1/formulaire", content=autre, headers=_signature(autre)).status_code == 400
    assert _etat_metier_formulaire() == avant


def test_nouveau_nonce_avec_utm_distinct_garde_le_lead_de_conversation(runtime):
    taxonomie.enregistrer_fenetre_conversation(30)
    client = _client(runtime.appeler)
    premier = _body(utm_source="facebook")
    autre = _body(utm_source="google")
    assert client.post("/interne/m1/formulaire", content=premier, headers=_signature(premier)).status_code == 202
    assert client.post("/interne/m1/formulaire", content=autre,
                       headers=_signature(autre, nonce="nonce-fictif-000002")).status_code == 202
    with stockage.transaction():
        lignes = outils_m1._obtenir_registre().lire()
    signaux = [ligne for ligne in lignes if ligne["type_entree"] == "signal"]
    leads = [ligne["lead"] for ligne in lignes if ligne["type_entree"] == "lead_emis"]
    assert [ligne["utm"] for ligne in signaux] == [{"utm_source": "facebook"}, {"utm_source": "google"}]
    assert len(leads) == 1 and leads[0]["utm"] == {"utm_source": "facebook"}
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
