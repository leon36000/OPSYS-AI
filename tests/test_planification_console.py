"""Console « Connecteurs » : TOUS les tours (état, dernier et prochain passage, mode, expiration, échecs, attente de
transport), activation par l'admin seulement (CSRF, rôle relu), aperçu à blanc et confirmation pour une purge.
Accessibilité et responsive comme les autres pages Plateforme. Vrai socle ; fournisseurs = doubles. Données fictives."""

from __future__ import annotations

import re

import cablage_qa as cq
import pytest
from fastapi.testclient import TestClient

from opsys import identite, stockage
from opsys.connecteurs_planification import etat, hote, inventaire, journal
from opsys.console import application, pages
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage.schema import PLANIFICATEUR_APPROBATIONS

FICTIF = True
MDP = "mot-de-passe-nathan-1234"


@pytest.fixture
def env(tmp_path, monkeypatch):
    mon = cq.monter(tmp_path, monkeypatch)
    monkeypatch.setattr(hote, "construire_service", lambda *a, **k: mon.monde.service)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "vendeur", "Vendeur fictif", "mot-de-passe-vendeur-1234", ["seller"])
    app = application.creer_application(Configuration("secret-session-planif-fictif-" + "x" * 32),
                                        charger_departements(), stockage.transaction)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        yield mon, client
    cq.demonter()


def _connexion(client, user="nathan", mdp=MDP):
    assert client.post("/connexion", data={"identifiant": user, "mot_de_passe": mdp},
                       follow_redirects=False).status_code == 303


def _post(client, chemin, **champs):
    csrf = client.get("/api/session").json()["csrf"]
    return client.post(chemin, data={"csrf": csrf, **champs}, follow_redirects=False)


def test_la_page_montre_tous_les_tours_par_famille_avec_leur_etat(env):
    _, client = env
    _connexion(client)
    r = client.get("/plateforme/connecteurs")
    assert r.status_code == 200
    for nom in etat.noms():
        assert f"<code>{nom}</code>" in r.text, nom
    for titre in ("Connecteurs (courriel", "Départements (calculs", "Constats planifiés pour M8", "Vérifications",
                  "Rétention Loi 25"):
        assert titre in r.text
    assert "En attente de transport" in r.text  # WordPress, réseaux sociaux, signaux… ne sont pas raccordés
    assert "Tours non branchés" in r.text
    for t in inventaire.TOURS:
        if t.decision in ("brancher_quand_transport", "ne_jamais_automatiser", "a_construire"):
            assert t.identifiant in r.text, t.identifiant
    assert r.text.count("Inactif") >= len(etat.noms())


def test_l_api_donne_l_etat_complet_sans_secret(env):
    mon, client = env
    _connexion(client)
    mon.activer("m8.entrepot", "ombre")
    api = client.get("/api/plateforme/connecteurs").json()
    par_nom = {v["executeur"]: v for v in api["executeurs"]}
    assert set(par_nom) == set(etat.noms())
    m8 = par_nom["m8.entrepot"]
    assert m8["mode"] == "ombre" and m8["expire_le"] and m8["prochain_passage"] and m8["famille"] == "departements"
    assert par_nom["m7.signaux"]["en_attente_transport"] is True and par_nom["m7.signaux"]["transport"] == "signaux"
    assert par_nom["m8.entrepot"]["en_attente_transport"] is False
    retention = par_nom["retention.courriel"]
    assert retention["irreversible"] is True and retention["approbation"] is None
    assert {t["identifiant"] for t in api["tours"]} == {t.identifiant for t in inventaire.TOURS}
    assert "secret" not in str(api["executeurs"]).lower().replace("secret_nom", "")


def test_la_page_montre_dernier_passage_echecs_et_plafond(env):
    mon, client = env
    _connexion(client)
    mon.activer("sauvegarde.verification")
    mon.ports.verifier_sauvegarde = lambda: {"trouvee": False}
    mon.tour()
    api = client.get("/api/plateforme/connecteurs").json()
    v = next(x for x in api["executeurs"] if x["executeur"] == "sauvegarde.verification")
    assert v["dernier_statut"] == "erreur" and v["dernier_code"] == "REJ-PLAN-SAUVEGARDE-ABSENTE"
    assert v["echecs_24h"] == 1 and v["dernier_passage"]
    texte = client.get("/plateforme/connecteurs").text
    assert "REJ-PLAN-SAUVEGARDE-ABSENTE" in texte and "Échecs (24 h) : 1" in texte


def test_activation_admin_csrf_et_role_relus_pour_les_nouveaux_tours(env):
    _, client = env
    _connexion(client, "vendeur", "mot-de-passe-vendeur-1234")
    for nom in ("m8.entrepot", "retention.courriel"):
        assert _post(client, "/plateforme/connecteurs/executeurs", executeur=nom, mode="ombre",
                     motif="essai fictif").status_code == 403
    client.post("/deconnexion", data={"csrf": client.get("/api/session").json()["csrf"]})
    _connexion(client)
    r = client.post("/plateforme/connecteurs/executeurs", data={
        "csrf": "faux", "executeur": "retention.courriel", "mode": "ombre", "motif": "essai fictif"},
        follow_redirects=False)
    assert r.status_code == 403
    with stockage.transaction() as cnx:
        assert etat.ligne(cnx, "retention.courriel") is None
    ok = _post(client, "/plateforme/connecteurs/executeurs", executeur="m8.entrepot", mode="ombre",
               motif="premier essai fictif")
    assert ok.headers["location"].endswith("?ok=mode")


def _apercu_champs(html: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in re.finditer(r'<input type="hidden" name="([a-z_]+)" value="([^"]*)">',
    html)}


def test_la_premiere_activation_d_une_purge_montre_l_apercu_puis_exige_la_confirmation(env):
    mon, client = env
    _connexion(client)
    # 1. l'ombre d'abord
    assert _post(client, "/plateforme/connecteurs/executeurs", executeur="retention.cles", mode="ombre",
                 motif="constat à blanc").headers["location"].endswith("?ok=mode")
    # 2. « Actif » ne s'enregistre PAS : la page montre ce qui sera purgé
    r = _post(client, "/plateforme/connecteurs/executeurs", executeur="retention.cles", mode="actif",
              motif="activer la purge")
    assert r.status_code == 200 and "Aperçu à blanc" in r.text and "irréversible" in r.text
    assert r.headers["cache-control"] == "no-store"
    with stockage.transaction() as cnx:
        assert etat.ligne(cnx, "retention.cles")["mode"] == "ombre"  # rien n'a changé
        assert cnx.execute(PLANIFICATEUR_APPROBATIONS.select()).first() is None
    champs = _apercu_champs(r.text)
    assert champs["executeur"] == "retention.cles" and len(champs["apercu_empreinte"]) == 64
    # 3. sans la case de confirmation : refus, rien d'enregistré
    sans = _post(client, "/plateforme/connecteurs/executeurs", **{k: v for k, v in champs.items() if k != "csrf"})
    assert "erreur=CONFIRMATION_IRREVERSIBLE_REQUISE" in sans.headers["location"]
    # 4. avec une empreinte qui n'est pas celle de la liste vue : refus
    faux = _post(client, "/plateforme/connecteurs/executeurs", **{**champs, "apercu_empreinte": "0" * 64},
                 confirme_irreversible="oui")
    assert "erreur=APERCU_CHANGE" in faux.headers["location"]
    # 5. confirmation expresse de CETTE liste
    bon = _post(client, "/plateforme/connecteurs/executeurs", **{k: v for k, v in champs.items() if k != "csrf"},
                confirme_irreversible="oui")
    assert bon.headers["location"].endswith("?ok=irreversible")
    api = client.get("/api/plateforme/connecteurs").json()
    v = next(x for x in api["executeurs"] if x["executeur"] == "retention.cles")
    assert v["mode"] == "actif" and v["approbation"]["approuve_par"] == "nathan"
    with stockage.transaction() as cnx:
        evenements = [j["evenement"] for j in journal.lire(cnx, "retention.cles")]
    assert "approbation_irreversible" in evenements


def test_l_apercu_est_refuse_sans_session_admin_et_sans_csrf(env):
    _, client = env
    r = client.post("/plateforme/connecteurs/executeurs", data={"csrf": "x", "executeur": "retention.cles",
                                                                "mode": "actif", "motif": "essai"},
                    follow_redirects=False)
    assert r.status_code in (303, 401, 403)
    _connexion(client)
    assert client.post("/plateforme/connecteurs/executeurs", data={
        "csrf": "faux", "executeur": "retention.cles", "mode": "actif", "motif": "essai fictif"},
        follow_redirects=False).status_code == 403


def test_accessibilite_et_responsive_de_la_page(env):
    mon, client = env
    _connexion(client)
    html = client.get("/plateforme/connecteurs").text
    assert html.count("<h1") == 1 and 'lang="fr' in html
    assert '<nav aria-label="Plateforme">' in html  # sous-navigation commune, page courante marquée
    assert 'aria-current="page"' in html
    # chaque tableau est dans un conteneur qui défile (WCAG 1.4.10) et porte des en-têtes de colonne
    assert html.count("<table") == html.count('<div class="table-defilante"><table')
    tables = re.findall(r"<table.*?</table>", html, re.S)
    assert tables and all("<th" in t for t in tables)
    assert all('<caption' in t for t in tables if "Tour" in t and "Réglage" in t)
    # chaque champ de formulaire visible est étiqueté
    for etiquette in re.findall(r"<label>.*?</label>", html, re.S):
        assert "<input" in etiquette or "<select" in etiquette
    assert "<label>Mode<select" in html and "<label>Motif<input" in html
    # aucune information portée par la seule couleur : l'état est écrit
    assert "Inactif" in html and "En attente de transport" in html
    # ids uniques (aria-describedby des champs de purge)
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    for dec in re.findall(r'aria-describedby="([^"]+)"', html):
        assert dec in ids
    assert pages.navigation_plateforme("/opsys", "connecteurs") in html
