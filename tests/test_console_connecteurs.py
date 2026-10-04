"""Pré requis des connecteurs : parcours HTTP avec personnes et données fictives."""

from __future__ import annotations

import dataclasses
import json
import urllib.request

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opsys import identite
from opsys.console import application, connecteurs_ui
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS, JOURNAL, REGISTRES

_PASSWORD = "mot-de-passe-connecteurs-fictif-2026"


@pytest.fixture
def client_connecteurs(session):
    with session() as cnx:
        identite.creer_personne(cnx, "owner_fictif", "Owner fictif", _PASSWORD, ["nathan_owner"])
    app = application.creer_application(
        Configuration("secret-session-connecteurs-fictif-" + "x" * 32),
        charger_departements(), session,
    )
    with TestClient(app, base_url="https://testserver/opsys") as client:
        yield client


def _connexion(client, user="owner_fictif"):
    response = client.post(
        "/connexion", data={"identifiant": user, "mot_de_passe": _PASSWORD}, follow_redirects=False
    )
    assert response.status_code == 303


def test_page_connecteurs_accessible_depuis_navigation(client_connecteurs):
    _connexion(client_connecteurs)
    response = client_connecteurs.get("/connecteurs")
    assert response.status_code == 200
    assert '<a href="/opsys/connecteurs" aria-current="page">Connecteurs</a>' in response.text
    assert "OPSYS_M1_STT_URL" in response.text
    assert "Audio2Face" in response.text


def test_api_connecteurs_decrit_les_prerequis_sans_probe(client_connecteurs):
    _connexion(client_connecteurs)
    response = client_connecteurs.get("/api/connecteurs")
    assert response.status_code == 200
    payload = response.json()["resultat"]
    assert payload["verification_distante"] == "non_executee"
    assert {row["id"] for row in payload["connecteurs"]} == {
        "sms-m1", "stt-m1", "memoire-entreprise", "embeddings-memoire",
    }


@pytest.mark.parametrize("chemin", ["/connecteurs", "/api/connecteurs"])
def test_connexion_exigee(client_connecteurs, chemin):
    response = client_connecteurs.get(chemin, follow_redirects=False)
    assert response.status_code == (303 if chemin == "/connecteurs" else 401)
    assert "OPSYS_SMS_JETON" not in response.text


@pytest.mark.parametrize("role", ["employee", "seller", "client", "system_agent"])
def test_roles_metier_ne_voient_pas_la_configuration(client_connecteurs, session, role):
    with session() as cnx:
        identite.creer_personne(cnx, "role_fictif", "Rôle fictif", _PASSWORD, [role])
    _connexion(client_connecteurs, "role_fictif")
    for chemin in ("/connecteurs", "/api/connecteurs"):
        response = client_connecteurs.get(chemin, follow_redirects=False)
        assert response.status_code == 403
        assert "OPSYS_M1_STT_URL" not in response.text


def test_administrateur_actif_accede(client_connecteurs, session):
    with session() as cnx:
        identite.creer_personne(cnx, "admin_fictif", "Admin fictif", _PASSWORD, ["admin"])
    _connexion(client_connecteurs, "admin_fictif")
    assert client_connecteurs.get("/connecteurs").status_code == 200
    assert client_connecteurs.get("/api/connecteurs").status_code == 200


@pytest.mark.parametrize("chemin", ["/connecteurs", "/api/connecteurs"])
@pytest.mark.parametrize("retrait", ["role", "desactivation"])
def test_retrait_pendant_lecture_refuse_la_reponse(client_connecteurs, session, monkeypatch, chemin, retrait):
    _connexion(client_connecteurs)
    original = connecteurs_ui.etat_connecteurs

    def lire_et_retirer(environ, deps):
        resultat = original(environ, deps)
        with session() as cnx:
            if retrait == "role":
                identite.retirer_role(cnx, "owner_fictif", "nathan_owner")
            else:
                identite.activer(cnx, "owner_fictif", False)
        return resultat

    monkeypatch.setattr(connecteurs_ui, "etat_connecteurs", lire_et_retirer)
    response = client_connecteurs.get(chemin, follow_redirects=False)
    assert response.status_code == (403 if retrait == "role" else 401)
    assert "OPSYS_M1_STT_URL" not in response.text


def test_presence_ne_valide_pas_endpoint_ni_authentification(client_connecteurs, monkeypatch):
    monkeypatch.setenv("OPSYS_M1_STT_URL", "url-invalide-fictive")
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "modele-fictif")
    _connexion(client_connecteurs)
    response = client_connecteurs.get("/api/connecteurs")
    ligne = next(x for x in response.json()["resultat"]["connecteurs"] if x["id"] == "stt-m1")
    assert ligne["statut"] == "presence_declaree"
    assert ligne["validation_locale"] == "non_executee"
    assert ligne["authentification_distante"] == "non_verifiee"
    assert "url-invalide-fictive" not in response.text


def test_secrets_et_endpoints_jamais_retournes(client_connecteurs, monkeypatch):
    sentinelles = {
        "OPSYS_M1_STT_CLE": "secret-fictif-stt-<script>secret</script>",
        "OPSYS_SMS_JETON": "secret-fictif-sms-321",
        "OPSYS_EMBEDDINGS_CLE": "secret-fictif-embed-654",
        "OPSYS_EMBEDDINGS_URL": "https://hote-prive-fictif.invalid/?token=secret-fictif-query",
        "SECRET_INCONNU_FICTIF": "secret-fictif-sans-rapport",
    }
    for nom, valeur in sentinelles.items():
        monkeypatch.setenv(nom, valeur)
    _connexion(client_connecteurs)
    for chemin in ("/connecteurs", "/api/connecteurs"):
        response = client_connecteurs.get(chemin)
        assert response.status_code == 200
        assert all(value not in response.text for value in sentinelles.values())
        assert "hote-prive-fictif" not in response.text
        assert "SECRET_INCONNU_FICTIF" not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["pragma"] == "no-cache"
        assert response.headers["x-content-type-options"] == "nosniff"


def test_presence_vide_et_sources_absentes_restent_explicitement_limitees():
    deps = charger_departements()
    resultat = connecteurs_ui.etat_connecteurs({"OPSYS_M1_STT_URL": "   "}, deps)
    stt = next(x for x in resultat["connecteurs"] if x["id"] == "stt-m1")
    assert stt["statut"] == "configuration_incomplete"
    assert stt["variables_manquantes"] == ["OPSYS_M1_STT_URL", "OPSYS_M1_STT_MODELE"]
    resultat_absent = connecteurs_ui.etat_connecteurs({}, {})
    assert all(x["statut"] == "source_indisponible" for x in resultat_absent["connecteurs"])
    deps["m01-front-office"] = dataclasses.replace(deps["m01-front-office"], canaux=())
    sans_sms = connecteurs_ui.etat_connecteurs({}, deps)
    assert next(x for x in sans_sms["connecteurs"] if x["id"] == "sms-m1")["statut"] == "source_indisponible"


def test_catalogue_stateless_et_lectures_sans_mutation_ni_reseau(client_connecteurs, session, monkeypatch):
    _connexion(client_connecteurs)

    def pas_de_reseau(*args, **kwargs):
        raise AssertionError("Ce catalogue ne doit effectuer aucun appel réseau")

    monkeypatch.setattr(urllib.request, "urlopen", pas_de_reseau)

    def snapshot():
        with session() as cnx:
            return {
                table.name: [dict(x) for x in cnx.execute(select(table)).mappings()]
                for table in (REGISTRES, APPROBATIONS, EVENEMENTS_SORTANTS, JOURNAL)
            }

    avant = snapshot()
    for chemin in ("/connecteurs", "/api/connecteurs"):
        assert client_connecteurs.get(chemin).status_code == 200
        assert client_connecteurs.post(chemin, json={"api_key": "secret-fictif"}).status_code == 405
    assert snapshot() == avant
    premier = connecteurs_ui.etat_connecteurs({}, charger_departements())
    premier["connecteurs"][0]["requis"].append("VARIABLE_INJECTEE_FICTIVE")
    suivant = connecteurs_ui.etat_connecteurs({}, charger_departements())
    assert "VARIABLE_INJECTEE_FICTIVE" not in json.dumps(suivant)
