"""Console « Plateforme » : parcours HTTP fictifs (fournisseurs, politique, test simulé, coffre de secrets)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from opsys import identite
from opsys.console import application, plateforme_ui
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.fournisseurs import sondes
from opsys.secrets_coffre import cle_maitresse, coffre

FICTIF = True
_MDP = "mot-de-passe-plateforme-fictif-2026"
VALEUR = "valeur-fictive-console-cle-api-0123456789-QWERTY"


@pytest.fixture
def client(session, tmp_path, monkeypatch):
    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    cle_maitresse.generer_fichier(dossier / "coffre.cle")
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(dossier / "coffre.cle"))
    appels = []

    def sonde(fournisseur, secret, delai_s):
        appels.append((fournisseur.identifiant, secret is not None))
        return sondes.ResultatSonde("succes", "HTTP 200 (simulé)", 12)

    monkeypatch.setattr(plateforme_ui, "SONDE_HTTP", sonde)
    monkeypatch.setattr(sondes, "_ouvrir_reel", lambda *a, **k: pytest.fail("appel réseau réel interdit"))
    with session() as cnx:
        identite.creer_personne(cnx, "owner_fictif", "Owner fictif", _MDP, ["nathan_owner"])
        identite.creer_personne(cnx, "vendeur_fictif", "Vendeur fictif", _MDP, ["seller"])
    app = application.creer_application(Configuration("secret-session-plateforme-fictif-" + "x" * 32),
                                        charger_departements(), session)
    with TestClient(app, base_url="https://testserver/opsys") as c:
        c.appels = appels
        yield c


def _connexion(client, user="owner_fictif"):
    r = client.post("/connexion", data={"identifiant": user, "mot_de_passe": _MDP}, follow_redirects=False)
    assert r.status_code == 303


def _csrf(client):
    return client.get("/api/session").json()["csrf"]


def _post(client, chemin, **champs):
    return client.post(chemin, data={"csrf": _csrf(client), **champs}, follow_redirects=False)


def _profil(client, **champs):
    base = {"usage_commercial": "oui", "revenu_annuel_usd": "1500000", "territoire_CA": "oui", "revision_attendue": "0"}
    r = _post(client, "/plateforme/fournisseurs/profil", **{**base, **champs})
    assert r.status_code == 303 and "ok=profil" in r.headers["location"]


def test_pages_protegees_session_role_no_store(client):
    for chemin in ("/plateforme/fournisseurs", "/plateforme/secrets"):
        assert client.get(chemin, follow_redirects=False).status_code == 303  # vers /connexion
    for chemin in ("/api/plateforme/fournisseurs", "/api/plateforme/secrets"):
        assert client.get(chemin).status_code == 401
    _connexion(client, "vendeur_fictif")
    for chemin in ("/plateforme/fournisseurs", "/plateforme/secrets", "/api/plateforme/secrets"):
        r = client.get(chemin, follow_redirects=False)
        assert r.status_code == 403 and "coffre" not in r.text.lower()
    client.post("/deconnexion", data={"csrf": _csrf(client)})
    _connexion(client)
    r = client.get("/plateforme/fournisseurs")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert '<a href="/opsys/plateforme/fournisseurs" aria-current="page">Plateforme</a>' in r.text
    assert "image.flux2-klein-4b.local" in r.text and "PROFIL_CLIENT_ABSENT" in r.text


def test_csrf_obligatoire_sur_chaque_ecriture(client):
    _connexion(client)
    for chemin in ("/plateforme/fournisseurs/profil", "/plateforme/fournisseurs/activer",
                   "/plateforme/secrets/definir", "/plateforme/secrets/revoquer"):
        r = client.post(chemin, data={"csrf": "faux", "identifiant": "ocr.paddleocr.local", "nom": "x.y.z",
                                      "valeur": VALEUR}, follow_redirects=False)
        assert r.status_code == 403
        assert VALEUR not in r.text
    assert client.get("/api/plateforme/secrets").json()["secrets"] == []


def test_role_relu_en_base_a_chaque_requete(client, session):
    _connexion(client)
    assert client.get("/plateforme/secrets").status_code == 200
    with session() as cnx:
        identite.ajouter_role(cnx, "owner_fictif", "employee")
        identite.retirer_role(cnx, "owner_fictif", "nathan_owner")
    csrf = _csrf(client)
    for reponse in (client.get("/plateforme/secrets", follow_redirects=False),
                    client.post("/plateforme/secrets/definir", data={"csrf": csrf, "nom": "google.ads",
                                                                     "service": "google", "valeur": VALEUR},
                                follow_redirects=False)):
        assert reponse.status_code == 403  # le cookie signé ne maintient pas un rôle retiré
    assert VALEUR not in reponse.text
    with session() as cnx:
        assert coffre.lister(cnx) == []


def test_activation_refusee_avec_code_puis_conforme(client):
    _connexion(client)
    _profil(client)
    _post(client, "/plateforme/fournisseurs/configurer", identifiant="tts.xtts-v2", revision_attendue="0")
    r = _post(client, "/plateforme/fournisseurs/activer", identifiant="tts.xtts-v2")
    assert "erreur=REFUS_POLITIQUE" in r.headers["location"]
    assert "LICENCE_NON_COMMERCIALE" in r.headers["location"]
    page = client.get(r.headers["location"].removeprefix("/opsys"))
    assert "Action refusée (REFUS_POLITIQUE)" in page.text and "Rien d&#x27;autre n&#x27;a été activé" in page.text
    _post(client, "/plateforme/fournisseurs/configurer", identifiant="tts.chatterbox-multilingual.local",
          revision_attendue="0")
    r = _post(client, "/plateforme/fournisseurs/activer", identifiant="tts.chatterbox-multilingual.local")
    assert "ok=active" in r.headers["location"]
    api = client.get("/api/plateforme/fournisseurs").json()
    actifs = {f["identifiant"] for f in api["fournisseurs"] if f["actif"]}
    assert actifs == {"tts.chatterbox-multilingual.local"}  # aucun repli vers un autre TTS
    r = _post(client, "/plateforme/fournisseurs/selectionner", capacite="tts", departement="m01-front-office",
              identifiant="tts.chatterbox-multilingual.local")
    assert "ok=selection" in r.headers["location"]
    assert client.get("/api/plateforme/fournisseurs").json()["selections"][0]["portee"] == "m01-front-office"


def test_secret_saisi_une_fois_jamais_reaffiche_et_test_connexion(client):
    _connexion(client)
    _profil(client)
    r = _post(client, "/plateforme/secrets/definir", nom="mistral.ocr", service="fournisseur_modele", valeur=VALEUR)
    assert r.status_code == 303 and VALEUR not in r.headers["location"]
    for chemin in ("/plateforme/secrets", "/api/plateforme/secrets", "/plateforme/fournisseurs",
                   "/api/plateforme/fournisseurs", r.headers["location"].removeprefix("/opsys")):
        reponse = client.get(chemin)
        assert reponse.status_code == 200
        assert VALEUR not in reponse.text and VALEUR[:12] not in reponse.text
    page = client.get("/plateforme/secrets").text
    assert re.search(r'<input type="password" name="valeur"[^>]*autocomplete="new-password"', page)
    assert 'value="' + VALEUR not in page
    export = client.get("/api/plateforme/secrets/mistral.ocr/valeur")
    assert export.status_code == 403 and export.json()["code"] == "COFFRE_EXPORT_INTERDIT"
    _post(client, "/plateforme/fournisseurs/configurer", identifiant="ocr.mistral-ocr-3.api", revision_attendue="0",
          point_acces="https://api.ocr.fictive.example/v1", reference_secret="coffre:mistral.ocr",
          efvp_ref="efvp-fictive-1", contrat_ref="contrat-fictif-1")
    r = _post(client, "/plateforme/fournisseurs/tester", identifiant="ocr.mistral-ocr-3.api")
    assert "ok=teste" in r.headers["location"]
    assert client.appels == [("ocr.mistral-ocr-3.api", True)]  # secret résolu côté serveur pour la sonde simulée
    vue = next(f for f in client.get("/api/plateforme/fournisseurs").json()["fournisseurs"]
               if f["identifiant"] == "ocr.mistral-ocr-3.api")
    assert vue["dernier_test"]["statut"] == "succes" and vue["reference_secret"] == "coffre:mistral.ocr"
    journal = client.get("/plateforme/secrets").text
    assert "resolution" in journal and "export" in journal and VALEUR not in journal


def test_rotation_revocation_et_doublon(client):
    _connexion(client)
    assert "ok=secret_defini" in _post(client, "/plateforme/secrets/definir", nom="meta.ads", service="meta",
                                       valeur=VALEUR).headers["location"]
    r = _post(client, "/plateforme/secrets/definir", nom="meta.ads", service="meta", valeur=VALEUR + "2")
    assert "erreur=COFFRE_SECRET_EXISTE" in r.headers["location"]
    assert "ok=secret_tourne" in _post(client, "/plateforme/secrets/rotation", nom="meta.ads",
                                       valeur=VALEUR + "-v2").headers["location"]
    assert "CONFIRMATION_REQUISE" in _post(client, "/plateforme/secrets/revoquer", nom="meta.ads").headers["location"]
    assert "ok=secret_revoque" in _post(client, "/plateforme/secrets/revoquer", nom="meta.ads",
                                        confirme="oui").headers["location"]
    [meta] = client.get("/api/plateforme/secrets").json()["secrets"]
    assert meta["etat"] == "revoque" and meta["version"] is None and meta["valeur"] == "non affichable"
