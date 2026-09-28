"""Console web OPSYS : authentification par personne, session signée, CSRF, approbations, modes,
paliers, pages HTML (ADR-0009 §5, PLAN T1.3-a)."""

from __future__ import annotations

import dataclasses
import re
import time

import demo_outils
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from opsys import approbations, console, identite, modeles
from opsys.capacites import Capacites
from opsys.console import application, pages, securite
from opsys.console.securite import Configuration

SECRET = "secret-de-signature-de-test-" + "x" * 32
IDENTIFIANT = "nathan"
MOT_DE_PASSE = "mot-de-passe-de-console-test-1234"
PREFIXE = "/opsys"  # préfixe par défaut derrière Caddy
ENV_OK = {"OPSYS_CONSOLE_SECRET": SECRET}
ATTESTATION_TEST = {"nom": "Alex Comptable", "profession": "CPA", "reference_document": "piece-jointe-test.pdf"}


@pytest.fixture
def personne_nathan(session):
    """Personne 'nathan', rôle nathan_owner (ADR-0009 §5) : connexion console + décisions de test."""
    with session() as cnx:
        identite.creer_personne(cnx, IDENTIFIANT, "Nathan St-Louis", MOT_DE_PASSE, ["nathan_owner"])
    return IDENTIFIANT


@pytest.fixture
def client(departements_demo, session):
    demo_outils.JOURNAL.clear()
    app = application.creer_application(Configuration(SECRET), departements_demo, session)
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        yield client


def _connecter(client, identifiant=IDENTIFIANT, mot_de_passe=MOT_DE_PASSE):
    return client.post("/connexion", data={"identifiant": identifiant, "mot_de_passe": mot_de_passe},
                       follow_redirects=False)


@pytest.fixture
def connecte(client, personne_nathan):
    assert _connecter(client).status_code == 303
    return client


def _csrf(client) -> str:
    return client.get("/api/session").json()["csrf"]


@pytest.fixture
def demande(departements_demo, session):
    """Demande en attente créée par le vrai chemin des capacités (T2/N4 en mode supervise)."""
    arguments = {"destinataire": "client", "texte": "<script>alert(1)</script>"}
    reponse = Capacites(departements_demo, session).appeler("m9_envoyer_message", arguments)
    assert reponse["statut"] == "en_attente_approbation"
    return reponse["demande_id"]


@pytest.fixture
def demande_n5(departements_demo, session):
    """Demande N5 (m9_payer, T3) en attente : exerce l'attestation professionnelle (ADR-0009 §5)."""
    reponse = Capacites(departements_demo, session).appeler("m9_payer", {"montant": 250})
    assert reponse["statut"] == "en_attente_approbation"
    return reponse["demande_id"]


# -- configuration et primitives de sécurité ---------------------------------------------------


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({}, "OPSYS_CONSOLE_SECRET"),
        ({"OPSYS_CONSOLE_SECRET": "trop-court"}, "32 caractères"),
        ({**ENV_OK, "OPSYS_CONSOLE_COOKIE_SECURISE": "peut-etre"}, "OPSYS_CONSOLE_COOKIE_SECURISE"),
        ({**ENV_OK, "OPSYS_CONSOLE_PREFIXE": "opsys"}, "OPSYS_CONSOLE_PREFIXE"),
        ({**ENV_OK, "OPSYS_CONSOLE_PREFIXE": "/op sys"}, "OPSYS_CONSOLE_PREFIXE"),
    ],
)
def test_configuration_refusee_sans_secrets_solides(environ, message):
    with pytest.raises(ValueError, match=message):
        Configuration.depuis_environnement(environ)


def test_configuration_depuis_l_environnement_ne_revele_pas_le_secret():
    conf = Configuration.depuis_environnement(ENV_OK)
    assert (conf.cookie_securise, conf.prefixe) == (True, PREFIXE)
    assert SECRET not in repr(conf)
    assert Configuration.depuis_environnement({**ENV_OK, "OPSYS_CONSOLE_COOKIE_SECURISE": "0"}).cookie_securise is False
    assert Configuration.depuis_environnement({**ENV_OK, "OPSYS_CONSOLE_PREFIXE": "/console/"}).prefixe == "/console"
    assert Configuration.depuis_environnement({**ENV_OK, "OPSYS_CONSOLE_PREFIXE": ""}).prefixe == ""


def test_session_signee_aller_retour_falsification_et_expiration():
    ouverte = securite.ouvrir_session("nathan", ["nathan_owner"], duree=60, maintenant=1000)
    assert (ouverte.utilisateur, ouverte.roles, ouverte.expire) == ("nathan", frozenset({"nathan_owner"}), 1060)
    assert len(ouverte.csrf) >= 32
    jeton = securite.signer_session(ouverte, SECRET)
    assert securite.lire_session(jeton, SECRET, maintenant=1059) == ouverte
    assert securite.lire_session(jeton, SECRET, maintenant=1060) is None  # expirée
    assert securite.lire_session(jeton, "un-autre-secret-" + "y" * 32, maintenant=1000) is None
    usurpee = securite.signer_session(dataclasses.replace(ouverte, utilisateur="intrus"), SECRET).split(".")[0]
    assert securite.lire_session(f"{usurpee}.{jeton.split('.')[1]}", SECRET, maintenant=1000) is None
    for invalide in (None, "", "sans-point", "a.b.c", "é.é", jeton + "x"):
        assert securite.lire_session(invalide, SECRET, maintenant=1000) is None


def test_jeton_csrf():
    ouverte = securite.ouvrir_session("nathan", ["nathan_owner"], 60)
    assert securite.csrf_valide(ouverte.csrf, ouverte)
    assert not securite.csrf_valide("", ouverte) and not securite.csrf_valide(None, ouverte)
    assert not securite.csrf_valide("é" + ouverte.csrf[1:], ouverte)


@pytest.mark.parametrize(("nom", "message"), [("   ", "manquant"), ("x" * 81, "trop long"),
                                              ("a\x00b", "invalide")])
def test_identifiant_de_session_valide(nom, message):
    with pytest.raises(ValueError, match=message):
        securite.valider_nom(nom)


# -- authentification ----------------------------------------------------------------------------


def test_pages_et_api_exigent_une_session(client):
    for chemin in ("/departements", "/approbations", "/budgets", "/modeles"):
        reponse = client.get(chemin, follow_redirects=False)
        assert (reponse.status_code, reponse.headers["location"]) == (303, f"{PREFIXE}/connexion")
    for methode, chemin in [("get", "/api/session"), ("get", "/api/departements"), ("get", "/api/approbations"),
                            ("get", "/api/approbations/file"), ("get", "/api/budgets"), ("get", "/api/paliers"),
                            ("post", "/api/departements/m09-demo/mode"), ("post", "/api/approbations/x/decision"),
                            ("put", "/api/paliers/local")]:
        assert client.request(methode, chemin, json={}).status_code == 401
    for chemin in ("/departements/m09-demo/mode", "/approbations/x/decision", "/modeles/local", "/deconnexion"):
        reponse = client.post(chemin, data={"csrf": "x"}, follow_redirects=False)
        assert (reponse.status_code, reponse.headers["location"]) == (303, f"{PREFIXE}/connexion")
    # Seuls la connexion, la sonde de santé et les ressources embarquées sont publics.
    assert client.get("/connexion").status_code == 200
    assert client.get("/sante").json() == {"statut": "ok"}
    assert client.get("/statique/console.css").headers["content-type"].startswith("text/css")
    assert client.get("/statique/console.js").headers["content-type"].startswith("text/javascript")


def test_connexion_refusee_avec_mauvais_mot_de_passe(client, personne_nathan):
    reponse = _connecter(client, mot_de_passe="mauvais-mot-de-passe")
    assert reponse.status_code == 401 and "Identifiant ou mot de passe incorrect" in reponse.text
    assert "set-cookie" not in reponse.headers
    assert client.get("/api/session").status_code == 401


def test_connexion_refusee_pour_identifiant_inconnu_ou_personne_inactive(client, session, personne_nathan):
    inconnu = _connecter(client, identifiant="fantome")
    assert inconnu.status_code == 401 and "Identifiant ou mot de passe incorrect" in inconnu.text
    with session() as cnx:
        identite.activer(cnx, IDENTIFIANT, False)
    inactive = _connecter(client)
    assert inactive.status_code == 401 and "Identifiant ou mot de passe incorrect" in inactive.text


def test_connexion_avec_identifiant_vide_refusee(client, personne_nathan):
    """Un identifiant vide ne peut jamais correspondre à une personne (`opsys.identite` ne crée
    aucun identifiant vide) : même refus générique qu'un identifiant inconnu, rien de plus révélé."""
    reponse = _connecter(client, identifiant="  ")
    assert reponse.status_code == 401 and "Identifiant ou mot de passe incorrect" in reponse.text
    assert "set-cookie" not in reponse.headers


def test_connexion_pose_un_cookie_de_session_protege(client, personne_nathan):
    reponse = _connecter(client)
    assert (reponse.status_code, reponse.headers["location"]) == (303, f"{PREFIXE}/departements")
    cookie = reponse.headers["set-cookie"]
    assert cookie.startswith("opsys_session=")
    for attribut in ("HttpOnly", "Secure", "SameSite=strict", f"Path={PREFIXE};", "Max-Age=28800"):
        assert attribut in cookie
    session_api = client.get("/api/session").json()
    assert session_api["utilisateur"] == IDENTIFIANT and session_api["roles"] == ["nathan_owner"]


def test_cookie_falsifie_ou_expire_refuse(client):
    maintenant = int(time.time())
    expiree = securite.Session(utilisateur="intrus", roles=frozenset(), csrf="c" * 43, expire=maintenant - 1)
    client.cookies.set("opsys_session", securite.signer_session(expiree, SECRET))
    assert client.get("/api/session").status_code == 401
    valide = securite.Session(utilisateur="intrus", roles=frozenset({"admin"}), csrf="c" * 43, expire=maintenant + 60)
    client.cookies.set("opsys_session", securite.signer_session(valide, "un-autre-secret-" + "z" * 32))
    assert client.get("/api/session").status_code == 401
    client.cookies.set("opsys_session", securite.signer_session(valide, SECRET))  # témoin : bien signé
    assert client.get("/api/session").json() == {"utilisateur": "intrus", "roles": ["admin"], "csrf": "c" * 43}


def test_deconnexion(connecte):
    reponse = connecte.post("/deconnexion", data={"csrf": _csrf(connecte)}, follow_redirects=False)
    assert (reponse.status_code, reponse.headers["location"]) == (303, f"{PREFIXE}/connexion")
    assert "Max-Age=0" in reponse.headers["set-cookie"]
    assert connecte.get("/api/session").status_code == 401


def test_corps_trop_volumineux_refuse(client):
    reponse = client.post("/connexion", content=b"a" * (application.LIMITE_CORPS + 1),
                          headers={"content-type": "application/x-www-form-urlencoded"})
    assert reponse.status_code == 413


# -- approbations --------------------------------------------------------------------------------


def test_parcours_approbation_par_l_api(connecte, session, demande):
    [premiere] = connecte.get("/api/approbations").json()["approbations"]
    assert premiere["id"] == demande and premiere["statut"] == "en_attente"
    assert premiere["arguments"] == {"destinataire": "client", "texte": "<script>alert(1)</script>"}
    url = f"/api/approbations/{demande}/decision"

    sans_jeton = connecte.post(url, json={"decision": "approuver"})
    assert sans_jeton.status_code == 403 and demo_outils.JOURNAL == []

    entetes = {"X-CSRF-Token": _csrf(connecte)}
    corps = {"decision": "approuver", "motif": "vu avec le client"}
    reponse = connecte.post(url, json=corps, headers=entetes)
    assert reponse.status_code == 200 and reponse.json()["statut"] == "executee"
    assert demo_outils.JOURNAL == [{"a": "client", "texte": "<script>alert(1)</script>"}]
    with session() as cnx:
        [traitee] = approbations.lister(cnx, "executee")
    # La signature vient de la session, jamais du corps de la requête ; le rôle utilisé est enregistré.
    assert (traitee["decide_par"], traitee["decide_role"], traitee["motif_decision"]) == (
        IDENTIFIANT, "nathan_owner", "vu avec le client")

    deja = connecte.post(url, json={"decision": "refuser"}, headers=entetes)
    assert deja.status_code == 400 and "déjà traitée" in deja.json()["detail"]
    inconnue = connecte.post("/api/approbations/inconnue/decision", json={"decision": "refuser"}, headers=entetes)
    assert inconnue.status_code == 404 and "demande inconnue" in inconnue.json()["detail"]
    assert connecte.post(url, json=["pas", "un", "objet"], headers=entetes).status_code == 400
    assert connecte.get("/api/approbations", params={"statut": "bidon"}).status_code == 400


def test_refus_par_formulaire_html_avec_arguments_exacts_echappes(connecte, session, demande):
    page = connecte.get("/approbations")
    assert page.status_code == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text and "<script>alert(1)" not in page.text
    url = f"/approbations/{demande}/decision"
    assert connecte.post(url, data={"decision": "refuser", "motif": "non"}, follow_redirects=False).status_code == 403

    jeton = _csrf(connecte)
    reponse = connecte.post(url, data={"decision": "refuser", "motif": "non", "csrf": jeton}, follow_redirects=False)
    assert (reponse.status_code, reponse.headers["location"]) == (303, f"{PREFIXE}/approbations?ok=refusee")
    assert "Demande refusée" in connecte.get("/approbations?ok=refusee").text
    with session() as cnx:
        [refusee] = approbations.lister(cnx, "refusee")
    assert (refusee["decide_par"], refusee["decide_role"], refusee["motif_decision"]) == (
        IDENTIFIANT, "nathan_owner", "non")
    assert demo_outils.JOURNAL == []

    deja = connecte.post(url, data={"decision": "approuver", "csrf": jeton}, follow_redirects=False)
    assert deja.status_code == 400 and "déjà traitée" in deja.text


def test_approbation_employe_refusee_proprietaire_acceptee(connecte, session, departements_demo, demande):
    """Un rôle non autorisé pour le niveau N de la demande est un refus nommé, rien exécuté, la
    demande reste en attente (ADR-0009 §5). Ici : politique par défaut, seul nathan_owner décide."""
    with session() as cnx:
        identite.creer_personne(cnx, "employe1", "Un Employé", "mot-de-passe-employe-1234", ["employee"])
    entetes = {"X-CSRF-Token": _csrf(connecte)}
    corps = {"decision": "approuver"}
    # Un employé n'a pas de session ici (la console authentifie par cookie) : on exerce directement
    # le socle, la garde exacte que la console traverse.
    with session() as cnx:
        with pytest.raises(ValueError, match="aucun rôle autorisé"):
            approbations.decider(cnx, demande, True, "employe1", {}, departements_demo)
        [encore] = approbations.lister(cnx, "en_attente")
    assert encore["id"] == demande
    # Le propriétaire, lui, peut : le même chemin HTTP que testé plus haut le confirme déjà
    # (`test_parcours_approbation_par_l_api`) ; ici on vérifie la page ne montre pas d'erreur pour lui.
    reponse = connecte.post(f"/api/approbations/{demande}/decision", json=corps, headers=entetes)
    assert reponse.status_code == 200 and reponse.json()["statut"] == "executee"


def test_decision_n5_exige_l_attestation_par_l_api_et_le_formulaire(connecte, session, demande_n5):
    entetes = {"X-CSRF-Token": _csrf(connecte)}
    sans_attestation = connecte.post(f"/api/approbations/{demande_n5}/decision", json={"decision": "approuver"},
                                     headers=entetes)
    assert sans_attestation.status_code == 400 and "attestation" in sans_attestation.json()["detail"]
    with session() as cnx:
        [encore] = approbations.lister(cnx, "en_attente")
    assert encore["id"] == demande_n5 and demo_outils.JOURNAL == []

    avec_attestation = connecte.post(f"/api/approbations/{demande_n5}/decision",
                                     json={"decision": "approuver", "attestation": ATTESTATION_TEST},
                                     headers=entetes)
    assert avec_attestation.status_code == 200 and avec_attestation.json()["statut"] == "executee"
    with session() as cnx:
        [traitee] = approbations.lister(cnx, "executee")
    assert traitee["attestation"] == ATTESTATION_TEST
    page = connecte.get("/approbations?statut=executee").text
    assert "Attestation du professionnel" in page and ATTESTATION_TEST["nom"] in page


def test_decision_n5_par_formulaire_html_avec_attestation(connecte, demande_n5):
    page = connecte.get("/approbations").text
    assert "attestation_nom" in page and "Niveau N5" in page
    jeton = _csrf(connecte)
    reponse = connecte.post(
        f"/approbations/{demande_n5}/decision",
        data={"decision": "approuver", "csrf": jeton, "attestation_nom": ATTESTATION_TEST["nom"],
             "attestation_profession": ATTESTATION_TEST["profession"],
             "attestation_document": ATTESTATION_TEST["reference_document"]},
        follow_redirects=False,
    )
    assert (reponse.status_code, reponse.headers["location"]) == (303, f"{PREFIXE}/approbations?ok=executee")


def test_file_du_proprietaire_agrege_socle_et_attentes(connecte, demande):
    reponse = connecte.get("/api/approbations/file")
    assert reponse.status_code == 200
    file = reponse.json()["file"]
    assert any(item["id"] == demande and item["type"] == "approbation" for item in file)
    for item in file:
        assert set(item) >= {"type", "id", "resume", "niveau", "depuis", "action_proposee", "departement"}


# -- modes et paliers ----------------------------------------------------------------------------


def test_changement_de_mode_signe(connecte, session):
    jeton = _csrf(connecte)
    entetes = {"X-CSRF-Token": jeton}
    url = "/api/departements/m09-demo/mode"
    reponse = connecte.post(url, json={"mode": "autonome"}, headers=entetes)
    assert reponse.status_code == 200
    assert reponse.json() == {"departement": "m09-demo", "mode": "autonome", "par": IDENTIFIANT}
    assert connecte.post(url, json={"mode": "libre"}, headers=entetes).status_code == 400
    inconnu = connecte.post("/api/departements/m09-inconnu/mode", json={"mode": "ombre"}, headers=entetes)
    assert inconnu.status_code == 404 and "département inconnu" in inconnu.json()["detail"]
    assert connecte.post(url, json={"mode": "ombre"}).status_code == 403

    formulaire = connecte.post("/departements/m09-demo/mode", data={"mode": "ombre", "csrf": jeton},
                               follow_redirects=False)
    assert formulaire.status_code == 303
    assert formulaire.headers["location"].startswith(f"{PREFIXE}/departements?ok=mode")
    with session() as cnx:
        assert approbations.mode_effectif(cnx, "m09-demo", "supervise") == "ombre"
        ligne = cnx.execute(
            text("SELECT modifie_par FROM modes_departements WHERE departement = 'm09-demo'")
        ).mappings().fetchone()
    assert ligne["modifie_par"] == IDENTIFIANT
    invalide = connecte.post("/departements/m09-demo/mode", data={"mode": "libre", "csrf": jeton},
                             follow_redirects=False)
    assert invalide.status_code == 400 and "mode inconnu" in invalide.text
    assert connecte.get("/api/departements").json()["departements"][0]["mode"] == "ombre"


def test_paliers_invalides_400_et_valides_persistes(connecte, opsys_home):
    jeton = _csrf(connecte)
    entetes = {"X-CSRF-Token": jeton}
    sans_base = connecte.put("/api/paliers/local", json={"provider": "custom", "model": "qwen3:8b"}, headers=entetes)
    assert sans_base.status_code == 400 and "exige base_url" in sans_base.json()["detail"]
    assert connecte.put("/api/paliers/geant", json={"provider": "x", "model": "y"}, headers=entetes).status_code == 400
    assert connecte.put("/api/paliers/local", content="pas du json", headers=entetes).status_code == 400
    assert connecte.put("/api/paliers/local", json={"provider": "x", "model": "y"}).status_code == 403
    assert not (opsys_home / "paliers.yaml").exists()

    local = {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"}
    reponse = connecte.put("/api/paliers/local", json=local, headers=entetes)
    assert reponse.status_code == 200 and reponse.json()["par"] == IDENTIFIANT
    assert modeles.charger_paliers() == {"local": local}
    assert connecte.get("/api/paliers").json()["manquants"] == ["rapide", "standard"]

    invalide = connecte.post("/modeles/rapide", data={"provider": "custom", "model": "m", "base_url": "",
                                                      "csrf": jeton}, follow_redirects=False)
    assert invalide.status_code == 400 and "exige base_url" in invalide.text
    assert 'value="m"' in invalide.text  # la saisie est conservée pour être corrigée
    valide = connecte.post("/modeles/rapide", data={"provider": "anthropic", "model": "claude-haiku-4-5-20251001",
                                                    "base_url": "", "csrf": jeton}, follow_redirects=False)
    assert (valide.status_code, valide.headers["location"]) == (303, f"{PREFIXE}/modeles?ok=palier")
    assert set(modeles.charger_paliers()) == {"local", "rapide"}


def test_aide_fournisseur_local_conforme_au_socle():
    with pytest.raises(ValueError, match="exige base_url"):
        modeles.valider_palier("local", {"provider": pages.FOURNISSEUR_COMPATIBLE_OPENAI, "model": "qwen3:8b"})


# -- pages et API de lecture ---------------------------------------------------------------------


def test_pages_en_francais_protegees_et_sans_ressource_externe(connecte, demande):
    for chemin, titre in (("/departements", "Départements"), ("/approbations", "Approbations"),
                          ("/budgets", "Budgets"), ("/modeles", "Modèles")):
        page = connecte.get(chemin)
        assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
        assert '<html lang="fr">' in page.text and f"<h1>{titre}</h1>" in page.text
        assert "default-src 'none'" in page.headers["content-security-policy"]
        assert (page.headers["x-frame-options"], page.headers["cache-control"]) == ("DENY", "no-store")
        liens = re.findall(r'(?:src|href|action)="([^"]*)"', page.text)
        assert liens and all(lien.startswith(f"{PREFIXE}/") for lien in liens)
        assert 'class="pastille">1<' in page.text  # une demande en attente, signalée dans la navigation

    departements = connecte.get("/departements").text
    assert "Démo" in departements and "m9_payer" in departements and "procedure-demo" in departements
    assert "0 7 * * 1-5" in departements and "KPI d&#x27;exemple." in departements
    assert "<meter" in connecte.get("/budgets").text and 'low="80"' in connecte.get("/budgets").text
    modeles_page = connecte.get("/modeles").text
    assert "Ollama" in modeles_page and "compatible OpenAI" in modeles_page
    approbations_page = connecte.get("/approbations").text
    assert "Approuver" in approbations_page and "Refuser" in approbations_page


def test_console_servie_a_la_racine_sans_prefixe(departements_demo, session, personne_nathan):
    app = application.creer_application(Configuration(SECRET, prefixe=""), departements_demo, session)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/departements", follow_redirects=False).headers["location"] == "/connexion"
        reponse = _connecter(client)
        assert reponse.headers["location"] == "/departements" and "Path=/;" in reponse.headers["set-cookie"]
        page = client.get("/departements").text
    liens = re.findall(r'(?:src|href|action)="([^"]*)"', page)
    assert liens and all(lien.startswith("/") and not lien.startswith(PREFIXE) for lien in liens)


def test_api_de_lecture(connecte):
    lecture = connecte.get("/api/departements").json()
    assert lecture["departements"][0]["id"] == "m09-demo"
    assert [m["mode"] for m in lecture["modes"]] == ["ombre", "supervise", "autonome"]
    [budget] = connecte.get("/api/budgets").json()["budgets"]
    assert (budget["departement"], budget["niveau"]) == ("m09-demo", "ok")


# -- point d'entrée ------------------------------------------------------------------------------


def test_point_d_entree_ecoute_sur_8700_et_refuse_sans_configuration(monkeypatch, racine_demo, opsys_home):
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(racine_demo))
    appels = {}
    monkeypatch.setattr(application.uvicorn, "run", lambda app, **options: appels.update(options, app=app))
    for nom in ("OPSYS_CONSOLE_COOKIE_SECURISE", "OPSYS_CONSOLE_PREFIXE"):
        monkeypatch.delenv(nom, raising=False)
    for nom, valeur in ENV_OK.items():
        monkeypatch.setenv(nom, valeur)
    assert console.main([]) == 0
    assert (appels["host"], appels["port"]) == ("0.0.0.0", 8700)
    assert appels["app"].title == "Console OPSYS"

    appels.clear()
    monkeypatch.delenv("OPSYS_CONSOLE_SECRET")
    assert console.main(["--port", "8701"]) == 2  # fail-closed : aucun serveur sans secret de session
    assert appels == {}
