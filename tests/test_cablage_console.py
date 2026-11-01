"""Console « Connecteurs » : connecter un compte (retour OAuth à `state` à usage unique), activer les exécuteurs,
voir ce qui
attend la direction. Mêmes gardes que les pages Plateforme. Vrai socle, fournisseurs = doubles. Données fictives."""

from __future__ import annotations

import logging
import re
import urllib.parse

import cablage_qa as cq
import courriel_qa as qa
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opsys import identite, stockage
from opsys.connecteurs_planification import etat, hote, journal
from opsys.console import application, cablage_ui, journaux_http
from opsys.console.securite import Configuration
from opsys.courriel_connecteurs import comptes
from opsys.departements import charger_departements
from opsys.stockage.schema import COURRIEL_JOURNAL

FICTIF = True
MDP = "mot-de-passe-nathan-1234"
SCOPES = qa.SCOPE_GMAIL_LECTURE + " " + qa.SCOPE_GMAIL_ENVOI


@pytest.fixture
def env(tmp_path, monkeypatch):
    mon = cq.monter(tmp_path, monkeypatch, scope_google=SCOPES)
    monkeypatch.setattr(hote, "construire_service", lambda *a, **k: mon.monde.service)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "vendeur", "Vendeur fictif", "mot-de-passe-vendeur-1234", ["seller"])
        identite.creer_personne(cnx, "gestionnaire", "Gestionnaire fictive", "mot-de-passe-gest-1234", ["admin"])
    app = application.creer_application(Configuration("secret-session-cablage-fictif-" + "x" * 32),
                                        charger_departements(), stockage.transaction)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        yield mon, client
    cq.demonter()


def _connexion(client, user="nathan", mdp=MDP):
    r = client.post("/connexion", data={"identifiant": user, "mot_de_passe": mdp}, follow_redirects=False)
    assert r.status_code == 303


def _csrf(client):
    return client.get("/api/session").json()["csrf"]


def _post(client, chemin, **champs):
    return client.post(chemin, data={"csrf": _csrf(client), **champs}, follow_redirects=False)


def _creer_compte(client, **plus):
    champs = {"compte_id": "gmail-paul", "fournisseur": "gmail", "adresse": "paul.fictif@example.test",
              "usage": "lecture_envoi", "finalite": "Reprise des factures reçues par courriel",
              "retention_jours": "365", "consentement": "oui", **plus}
    r = _post(client, "/plateforme/connecteurs/comptes/creer", **champs)
    assert r.status_code == 303, r.text
    return r


def _lien_fournisseur(html: str) -> dict[str, str]:
    url = re.search(r'<a href="(https://accounts\.google\.com[^"]+)"', html).group(1).replace("&amp;", "&")
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}


def _demarrer(client, mon, compte="gmail-paul"):
    r = _post(client, "/plateforme/connecteurs/comptes/connecter", compte_id=compte)
    assert r.status_code == 200, r.text
    params = _lien_fournisseur(r.text)
    mon.monde.oauth_google.autoriser("code-fictif-console", params["code_challenge"])
    return params


# -- gardes ---------------------------------------------------------------------------------------------------------
def test_pages_protegees_session_role_no_store(env):
    _, client = env
    assert client.get("/plateforme/connecteurs", follow_redirects=False).status_code == 303  # vers /connexion
    assert client.get("/api/plateforme/connecteurs").status_code == 401
    assert client.get("/courriel/oauth/retour?state=x&code=y", follow_redirects=False).status_code == 303
    _connexion(client, "vendeur", "mot-de-passe-vendeur-1234")
    for chemin in ("/plateforme/connecteurs", "/api/plateforme/connecteurs"):
        assert client.get(chemin, follow_redirects=False).status_code == 403
    assert _post(client, "/plateforme/connecteurs/executeurs", executeur="courriel.envoi", mode="actif",
                 motif="essai fictif").status_code == 403
    client.post("/deconnexion", data={"csrf": _csrf(client)})
    _connexion(client)
    r = client.get("/plateforme/connecteurs")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.text.count("Inactif") >= 5 and "Rien n'attend la direction" in r.text


def test_csrf_obligatoire_sur_chaque_ecriture_et_rien_ne_change(env):
    _, client = env
    _connexion(client)
    for chemin in ("comptes/creer", "comptes/connecter", "comptes/imap", "comptes/mbox", "comptes/revoquer",
                   "executeurs"):
        r = client.post(f"/plateforme/connecteurs/{chemin}", data={
            "csrf": "faux", "compte_id": "gmail-paul", "executeur": "courriel.envoi", "mode": "actif",
            "motif": "essai fictif", "mot_de_passe": "MOT-DE-PASSE-FICTIF-123"}, follow_redirects=False)
        assert r.status_code == 403 and "MOT-DE-PASSE-FICTIF" not in r.text
    with stockage.transaction() as cnx:
        assert comptes.lister(cnx) == [] and all(v["mode"] == "inactif" for v in etat.vue(cnx))


def test_role_relu_en_base_a_chaque_requete(env):
    _, client = env
    _connexion(client, "gestionnaire", "mot-de-passe-gest-1234")
    assert client.get("/plateforme/connecteurs").status_code == 200
    with stockage.transaction() as cnx:
        identite.ajouter_role(cnx, "gestionnaire", "employee")
        identite.retirer_role(cnx, "gestionnaire", "admin")
    csrf = _csrf(client)
    assert client.get("/plateforme/connecteurs", follow_redirects=False).status_code == 403
    r = client.post("/plateforme/connecteurs/executeurs", data={"csrf": csrf, "executeur": "courriel.envoi",
                                                                 "mode": "actif", "motif": "essai fictif"},
                    follow_redirects=False)
    assert r.status_code == 403
    with stockage.transaction() as cnx:
        assert etat.ligne(cnx, "courriel.envoi") is None


# -- connecter un compte --------------------------------------------------------------------------------------------
def test_parcours_oauth_complet_state_a_usage_unique_et_aucun_jeton_dans_l_url_ni_le_journal(env, caplog):
    mon, client = env
    caplog.set_level(logging.DEBUG)
    _connexion(client)
    _creer_compte(client)
    params = _demarrer(client, mon)
    assert params["code_challenge_method"] == "S256" and params["response_type"] == "code"
    r = client.get("/courriel/oauth/retour", params={"state": params["state"], "code": "code-fictif-console"},
                   follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/plateforme/connecteurs?ok=connecte")
    assert "code" not in r.headers["location"] and "state" not in r.headers["location"]
    assert r.headers["referrer-policy"] == "no-referrer" and r.headers["cache-control"] == "no-store"
    with stockage.transaction() as cnx:
        assert comptes.lire(cnx, "gmail-paul")["etat"] == "connecte"
        traces = repr(cnx.execute(select(COURRIEL_JOURNAL)).all()) + repr(journal.lire(cnx))
    page = client.get("/plateforme/connecteurs").text + client.get("/api/plateforme/connecteurs").text
    serveur = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))  # journaux d'OPSYS
    for secret in ("code-fictif-console", params["state"], "access_token", "refresh_token"):
        assert secret not in traces and secret not in page and secret not in serveur
    # le state est à usage unique : le rejouer est refusé, même avec un code valide
    mon.monde.oauth_google.autoriser("code-fictif-console-2", params["code_challenge"])
    rejeu = client.get("/courriel/oauth/retour", params={"state": params["state"], "code": "code-fictif-console-2"},
                       follow_redirects=False)
    assert "erreur=REJ-COURRIEL-OAUTH-ETAT-REUTILISE" in rejeu.headers["location"]


def test_state_falsifie_expire_ou_demarre_par_une_autre_session_est_refuse(env):
    mon, client = env
    _connexion(client)
    _creer_compte(client)
    params = _demarrer(client, mon)
    charge, signature = params["state"].split(".")
    faux = charge + "." + signature[:-2] + ("AA" if not signature.endswith("AA") else "BB")
    r = client.get("/courriel/oauth/retour", params={"state": faux, "code": "c"}, follow_redirects=False)
    assert "erreur=REJ-COURRIEL-OAUTH-ETAT-INVALIDE" in r.headers["location"]
    r = client.get("/courriel/oauth/retour", params={"state": "pas-un-state", "code": "c"}, follow_redirects=False)
    assert "erreur=REJ-COURRIEL-OAUTH-ETAT-INVALIDE" in r.headers["location"]
    r = client.get("/courriel/oauth/retour", params={"state": params["state"], "error": "access_denied"},
                   follow_redirects=False)
    assert "erreur=REJ-COURRIEL-OAUTH-ECHANGE-REFUSE" in r.headers["location"]
    # un autre admin ne peut pas terminer l'autorisation que nathan a démarrée
    client.post("/deconnexion", data={"csrf": _csrf(client)})
    _connexion(client, "gestionnaire", "mot-de-passe-gest-1234")
    r = client.get("/courriel/oauth/retour", params={"state": params["state"], "code": "code-fictif-console"},
                   follow_redirects=False)
    assert "erreur=REJ-COURRIEL-OAUTH-ETAT-INVALIDE" in r.headers["location"]
    with stockage.transaction() as cnx:
        assert comptes.lire(cnx, "gmail-paul")["etat"] == "autorisation_en_cours"
    # le state n'est pas brûlé par le refus d'une autre session : l'initiateur peut finir
    client.post("/deconnexion", data={"csrf": _csrf(client)})
    _connexion(client)
    r = client.get("/courriel/oauth/retour", params={"state": params["state"], "code": "code-fictif-console"},
                   follow_redirects=False)
    assert r.headers["location"].endswith("?ok=connecte")


def test_state_expire(env):
    mon, client = env
    _connexion(client)
    _creer_compte(client)
    params = _demarrer(client, mon)
    mon.monde.horloge.t += 601  # l'horloge d'OAuth du double : au-delà de 10 minutes
    r = client.get("/courriel/oauth/retour", params={"state": params["state"], "code": "code-fictif-console"},
                   follow_redirects=False)
    assert "erreur=REJ-COURRIEL-OAUTH-ETAT-EXPIRE" in r.headers["location"]


def test_un_compte_sans_consentement_ne_se_connecte_pas(env):
    mon, client = env
    _connexion(client)
    r = _creer_compte(client, consentement="")
    assert r.headers["location"].endswith("?ok=cree")
    refus = _post(client, "/plateforme/connecteurs/comptes/connecter", compte_id="gmail-paul")
    assert refus.status_code == 303 and "erreur=REJ-COURRIEL-CONSENTEMENT-ABSENT" in refus.headers["location"]


def test_mot_de_passe_imap_saisi_une_fois_jamais_reaffiche_ni_redirige(env):
    mon, client = env
    _connexion(client)
    _creer_compte(client, compte_id="imap-paul", fournisseur="imap", usage="lecture")
    # la configuration de l'hôte IMAP se déclare à la création par le service ; ici on la pose comme l'administration
    with stockage.transaction() as cnx:
        cnx.exec_driver_sql("UPDATE courriel_comptes SET configuration = ? WHERE compte_id = 'imap-paul'",
                            ('{"hote": "imap.example.test", "port": 993, "smtp_hote": "smtp.example.test", '
                             f'"smtp_port": 465, "utilisateur": "{mon.monde.serveur_imap.utilisateur}"}}',))
    secret = mon.monde.serveur_imap.mot_de_passe
    r = _post(client, "/plateforme/connecteurs/comptes/imap", compte_id="imap-paul", mot_de_passe=secret)
    assert r.status_code == 303 and secret not in r.headers["location"] and secret not in r.text
    page = client.get("/plateforme/connecteurs").text + client.get("/api/plateforme/connecteurs").text
    assert secret not in page
    with stockage.transaction() as cnx:
        assert comptes.lire(cnx, "imap-paul")["etat"] == "connecte"


def test_la_revocation_exige_la_confirmation(env):
    mon, client = env
    _connexion(client)
    _creer_compte(client)
    assert "erreur=CONFIRMATION_REQUISE" in _post(client, "/plateforme/connecteurs/comptes/revoquer",
                                                  compte_id="gmail-paul").headers["location"]
    ok = _post(client, "/plateforme/connecteurs/comptes/revoquer", compte_id="gmail-paul", confirme="oui")
    assert ok.headers["location"].endswith("?ok=revoque")
    with stockage.transaction() as cnx:
        assert comptes.lire(cnx, "gmail-paul")["etat"] == "revoque"


def test_le_journal_d_acces_masque_la_requete_du_retour_oauth():
    filtre = journaux_http.MasquerRecherche()

    class Enregistrement:
        args = ("127.0.0.1:1", "GET", "/opsys/courriel/oauth/retour?state=SECRET-STATE&code=SECRET-CODE", "1.1", 303)

    e = Enregistrement()
    assert filtre.filter(e) is True
    assert "SECRET" not in repr(e.args) and e.args[2].endswith("?oauth=[MASQUE]")


# -- exécuteurs -----------------------------------------------------------------------------------------------------
def test_activer_et_desactiver_un_executeur_depuis_la_console(env):
    _, client = env
    _connexion(client)
    r = _post(client, "/plateforme/connecteurs/executeurs", executeur="courriel.synchro", mode="ombre",
              motif="premier essai fictif", intervalle_s="120")
    assert r.status_code == 303 and r.headers["location"].endswith("?ok=mode")
    api = client.get("/api/plateforme/connecteurs").json()
    synchro = next(v for v in api["executeurs"] if v["executeur"] == "courriel.synchro")
    assert synchro["mode"] == "ombre" and synchro["intervalle_s"] == 120 and synchro["modifie_par"] == "nathan"
    assert "Ombre" in client.get("/plateforme/connecteurs").text
    bad = [("courriel.synchro", "turbo", "motif ok"), ("inconnu", "actif", "motif ok"),
           ("courriel.synchro", "actif", "x")]
    for executeur, mode, motif in bad:
        refus = _post(client, "/plateforme/connecteurs/executeurs", executeur=executeur, mode=mode, motif=motif)
        assert "erreur=" in refus.headers["location"]
    assert "erreur=INTERVALLE_INVALIDE" in _post(client, "/plateforme/connecteurs/executeurs",
                                                 executeur="courriel.synchro", mode="actif", motif="motif ok",
                                                 intervalle_s="abc").headers["location"]
    _post(client, "/plateforme/connecteurs/executeurs", executeur="courriel.synchro", mode="inactif",
          motif="arrêt demandé")
    with stockage.transaction() as cnx:
        assert etat.mode_effectif(etat.ligne(cnx, "courriel.synchro")) == "inactif"
        assert [j["mode"] for j in journal.lire(cnx, "courriel.synchro")][:2] == ["inactif", "ombre"]


def test_les_approbations_en_attente_d_envoi_ou_de_publication_sont_visibles(env):
    mon, client = env
    qa.creer_compte(mon.monde, usage="lecture_envoi", configuration={"reception_m1": 1})
    qa.connecter_oauth(mon.monde)
    mon.monde.gmail.ajouter(cq.courriel_client(1))
    mon.activer("courriel.synchro")
    mon.tour()
    mon.monde.gmail.ajouter(cq.courriel_client(2))
    mon.tour()
    signal = next(ligne for ligne in cq.lignes_m1() if ligne["type_entree"] == "reception_courriel_connecteur_v1")
    brouillon = mon.capacites.appeler("m1_preparer_reponse_courriel", {
        "signal_id": signal["signal_id"], "corps": "Bonjour, merci."})["resultat"]["resultat"]["brouillon_id"]
    demande = mon.capacites.appeler("m1_demander_envoi_courriel", {
        "brouillon_id": brouillon, "contexte": "suite à sa demande"})["resultat"]["resultat"]["demande_id"]
    _connexion(client)
    api = client.get("/api/plateforme/connecteurs").json()
    assert [d["id"] for d in api["en_attente"]] == [demande]
    assert api["en_attente"][0]["outil"] == "opsys_courriel_approuver_envoi" and api["en_attente"][0]["niveau"] == "N3"
    texte = client.get("/plateforme/connecteurs").text
    assert demande in texte and "opsys_courriel_approuver_envoi" in texte and "bonjour, merci" not in texte.lower()
    assert api["comptes"][0]["compte_id"] == "gmail-paul" and "secret_nom" not in api["comptes"][0]


def test_la_page_ne_laisse_passer_aucun_secret(env, monkeypatch):
    mon, client = env
    _connexion(client)
    _creer_compte(client)
    # une valeur active du masquage : la page est refusée (500) plutôt que servie
    from opsys.secrets_coffre import masquage

    masquage.installer()
    masquage.enregistrer("valeur-secrete-fictive-0123456789")
    try:
        with stockage.transaction() as cnx:
            cnx.exec_driver_sql("UPDATE courriel_comptes SET adresse = 'valeur-secrete-fictive-0123456789' "
                                "WHERE compte_id = 'gmail-paul'")
        assert client.get("/plateforme/connecteurs").status_code == 500
    finally:
        masquage.oublier("valeur-secrete-fictive-0123456789")
    _ = cablage_ui
