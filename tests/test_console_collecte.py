"""Console « Collecte » : la vue qui dit POURQUOI une mesure de M8 est vide, dans la VRAIE console (chantier C2).

Même monde que `test_etat_collecte_m8.py` (vrai planificateur à horloge injectée, vrais outils, vrai bus, M8 réel) et
vraie application FastAPI. Prouvé : accès (session, rôle `admin` relu en base ; propriétaire seul et employé refusés)
; la page d'une installation neuve nomme chaque constat inactif et ce qu'il faut activer ; elle change quand un admin
active (ombre, actif, bus livré) ; lecture seule (aucun formulaire, aucune écriture, aucune méthode d'écriture) ;
aucune valeur de mesure ni donnée personnelle ; rien en ligne (CSP) ; l'API rend le même état. Limites dites : SQLite
seulement."""

from __future__ import annotations

import html as html_module
import json

import planif_m8_monde as pm
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opsys import identite, stockage
from opsys.console import application, collecte_ui, wallboards_ui
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage.schema import META

FICTIF = True
MDP = "mot-de-passe-fictif-12345"
CASH = "m5.constat.cash-libre"
VALEURS_SEMEES = ("1200.00", "27861.98", "689.85", "600.00")


@pytest.fixture
def monde(tmp_path, monkeypatch, declarer_services):
    m = pm.monter(tmp_path, monkeypatch, declarer_services)
    pm.semer_tout(m, pm.lire_yaml(pm.RACINE / "departments/m01-front-office/fixtures/plaintes/plaintes.v1.yaml"))
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "proprio.fictif", "Propriétaire seul (fictif)", MDP, ["nathan_owner"])
    yield m
    pm.demonter()


@pytest.fixture
def navigateur(monde, monkeypatch):
    monkeypatch.setattr(collecte_ui, "_maintenant", lambda: monde.maintenant())
    monkeypatch.setattr(wallboards_ui, "_maintenant", lambda: monde.maintenant())
    app = application.creer_application(Configuration("secret-collecte-fictif-" + "x" * 40, cookie_securise=False,
                                                      prefixe="/opsys"), charger_departements(), stockage.transaction)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        yield client


def _connecter(client, personne="nathan"):
    reponse = client.post("/connexion", data={"identifiant": personne, "mot_de_passe": MDP}, follow_redirects=False)
    assert reponse.status_code == 303, reponse.text


def _texte(reponse) -> str:
    return html_module.unescape(reponse.text)


def _instantane():
    with stockage.transaction() as cnx:
        return {nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
                for nom, table in META.tables.items()}


# ======================================================================================================== accès
def test_sans_session_la_page_redirige_et_l_api_refuse(navigateur):
    assert navigateur.get("/collecte", follow_redirects=False).status_code == 303
    assert navigateur.get("/api/collecte").status_code == 401


@pytest.mark.parametrize("personne", ["marc.fictif", "vendeur.un", "proprio.fictif"],
                         ids=["employe", "vendeur", "proprietaire_sans_admin"])
def test_seul_l_admin_relu_en_base_voit_la_collecte(navigateur, personne):
    _connecter(navigateur, personne)

    assert navigateur.get("/collecte").status_code == 403
    assert navigateur.get("/api/collecte").status_code == 403


def test_la_garde_admin_de_la_page_precede_l_appel_de_l_outil(navigateur, monkeypatch):
    """Défense en profondeur : même si l'outil refusait aussi, la page relit le rôle en base AVANT de l'appeler."""
    appels = []

    def espion(*args, **kwargs):
        appels.append(args[3] if len(args) > 3 else None)
        raise AssertionError("l'outil ne doit pas être appelé pour un non-admin")

    monkeypatch.setattr(collecte_ui.metier, "executer", espion)
    _connecter(navigateur, "proprio.fictif")  # nathan_owner SANS le rôle admin

    assert navigateur.get("/collecte").status_code == 403
    assert navigateur.get("/api/collecte").status_code == 403
    assert appels == []


def test_la_page_est_en_lecture_seule_aucun_formulaire_de_collecte_aucune_methode_d_ecriture(navigateur):
    _connecter(navigateur)
    html = navigateur.get("/collecte").text

    assert "<form" not in html.split("<main>", 1)[1], "seul le formulaire de déconnexion de l'en-tête existe"
    for methode in (navigateur.post, navigateur.put, navigateur.delete, navigateur.patch):
        assert methode("/collecte").status_code in (403, 405), methode
        assert methode("/api/collecte").status_code in (403, 405), methode


def test_lire_la_collecte_n_ecrit_rien(navigateur, monde):
    monde.activer("actif")
    monde.tour(1)
    monde.propager()
    _connecter(navigateur)
    avant = _instantane()
    navigateur.get("/collecte")
    navigateur.get("/api/collecte")
    apres = _instantane()
    # la seule différence admise est la session de console de la connexion elle-même, déjà posée avant `avant`
    assert apres == avant


# ================================================================================================ la page, par étape
def test_une_installation_neuve_nomme_chaque_constat_inactif_et_ce_qu_il_faut_activer(navigateur, monde):
    monde.propager()
    _connecter(navigateur)

    reponse = navigateur.get("/collecte")
    html = _texte(reponse)

    assert reponse.status_code == 200 and reponse.headers["cache-control"] == "no-store"
    assert '<html lang="fr">' in reponse.text and 'aria-current="page">Collecte' in reponse.text
    assert "script-src 'self'" in reponse.headers["content-security-policy"]
    assert "<script>" not in reponse.text and " style=" not in reponse.text and " onclick=" not in reponse.text
    assert "Constat inactif" in html and "Sans constat planifié" in html
    assert f"Activer le constat « {CASH} » en ombre" in html
    assert "Gestes d'activation restants" in html and "activer en ombre" in html
    assert html.count("<caption>") == 3 and 'scope="col"' in html
    assert "lecture seule" in html and "n'active et ne corrige rien" in html
    assert "Toutes les mesures sont calculées" not in html
    for interdit in VALEURS_SEMEES + ("Jeanne", "@", "client-fictif"):
        assert interdit not in html, interdit


def test_la_page_suit_l_etat_en_ombre_puis_actif_puis_livre(navigateur, monde):
    _connecter(navigateur)
    monde.activer("ombre")
    monde.tour(1)
    monde.propager()
    en_ombre = _texte(navigateur.get("/collecte"))
    assert "Constat en ombre" in en_ombre and "ne publie rien" in en_ombre
    assert "Constat inactif" not in en_ombre and "En ombre" in en_ombre

    monde.activer("actif")
    monde.tour(1)
    non_livre = _texte(navigateur.get("/collecte"))
    assert "Jamais reçue" in non_livre and "aucun fait n'a été reçu" in non_livre

    monde.propager()
    livre = _texte(navigateur.get("/collecte"))
    assert "Jamais reçue" not in livre and "Constat en ombre" not in livre
    assert "Le département source dit « non calculable »" in livre  # le cash libre de ce monde : rien à constater
    assert "Tous les constats planifiés sont activés et ont passé avec succès." in livre


def test_la_panne_d_un_constat_est_visible_avec_son_code(navigateur, monde, monkeypatch):
    from m6_material_control import outils as m6_outils

    _connecter(navigateur)
    monde.activer("actif")
    monde.tour(1)
    monde.propager()

    def casse(horodatage):
        raise RuntimeError("panne simulée de M6")

    monkeypatch.setattr(m6_outils, "constater_disponibilite", casse)
    monde.tour(43200)
    monde.tour(43200)
    monde.propager()

    html = _texte(navigateur.get("/collecte"))

    assert "Constat en erreur" in html and "REJ-PLAN-DEFAUT-EXECUTEUR" in html
    assert "m6.constat.disponibilite" in html


def test_le_coupe_circuit_s_affiche_en_alerte(navigateur, monde, monkeypatch):
    from opsys.connecteurs_planification import etat

    _connecter(navigateur)
    monkeypatch.setenv(etat.ENV_PLANIFICATEUR, "0")

    reponse = navigateur.get("/collecte")

    assert 'role="alert"' in reponse.text and "Planificateur coupé" in reponse.text


# ======================================================================================================= l'API
def test_l_api_rend_le_meme_etat_que_la_page_sans_valeur_de_mesure(navigateur, monde):
    monde.activer("actif")
    monde.tour(1)
    monde.propager()
    _connecter(navigateur)

    reponse = navigateur.get("/api/collecte")
    api = reponse.json()

    assert reponse.status_code == 200 and reponse.headers["cache-control"] == "no-store" and api["ok"] is True
    assert set(api) == {"ok", "maintenant", "resume", "mesures", "etapes"}
    page = _texte(navigateur.get("/collecte"))
    for mesure in api["mesures"]:
        assert mesure["nom"] in page and mesure["etat_collecte"] != "a_jour"
    assert api["resume"]["constats"] and {c["executeur"] for c in api["resume"]["constats"]} >= {CASH}
    texte = json.dumps(api, ensure_ascii=False)
    for interdit in VALEURS_SEMEES + ("Jeanne", "@", "client-fictif", '"valeur"'):
        assert interdit not in texte, interdit


def test_une_page_et_une_api_inconnues_ou_hostiles_ne_repondent_pas(navigateur):
    _connecter(navigateur)

    for chemin in ("/collecte/x", "/collecte/..%2f..%2fetc", "/api/collecte/x"):
        assert navigateur.get(chemin).status_code == 404, chemin


# ========================================================================================== le wallboard « collecte »
def test_le_wallboard_collecte_est_servi_par_la_console_et_se_remplit_quand_les_constats_passent(navigateur, monde):
    _connecter(navigateur)
    liste = navigateur.get("/wallboards")
    assert liste.status_code == 200 and "/opsys/wallboards/collecte" in liste.text

    monde.propager()
    neuve = navigateur.get("/api/wallboards/collecte").json()
    assert len(neuve["tuiles"]) == 9 and {t["fraicheur"] for t in neuve["tuiles"]} <= {"manquant", "inconnu", "perime"}
    assert neuve["banniere"]["niveau"] != "ok"

    monde.activer("actif")
    monde.tour(1)
    monde.propager()
    remplie = {t["id"]: t for t in navigateur.get("/api/wallboards/collecte").json()["tuiles"]}
    assert remplie["factures-emises"]["fraicheur"] == "a_jour" and remplie["factures-emises"]["valeur"] == "2"
    assert remplie["leads-ouverts"]["valeur"] == "4" and remplie["plaintes"]["valeur"] == "2"
    # le cash libre de ce monde est « non calculable » (aucun mouvement, aucune déclaration) : la tuile le dit
    assert remplie["cash-libre"]["valeur"] in (None, "") or remplie["cash-libre"]["statut"] != "calculee"
    page = navigateur.get("/wallboards/collecte")
    assert page.status_code == 200 and "Collecte" in html_module.unescape(page.text)
