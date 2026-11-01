"""Garde de structure : le paquet des médias payants et les connecteurs publicitaires n'ont AUCUN chemin d'écriture
chez une
plateforme, ni transport réseau, ni exécution dynamique. Lu par AST : rien n'est exécuté."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from m7_marketing.medias_payants import regles
from m7_marketing.signaux import catalogue, publicite

SRC = Path(__file__).resolve().parents[2] / "src" / "m7_marketing"
PAQUET = sorted((SRC / "medias_payants").glob("*.py"))
FICHIERS = [*PAQUET, SRC / "medias_outils.py", SRC / "signaux" / "publicite.py", SRC / "signaux" / "base.py"]
IMPORTS_INTERDITS = {
    "socket",
    "http",
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "ftplib",
    "smtplib",
    "subprocess",
    "ssl",
    "asyncio",
    "telnetlib",
    "xmlrpc",
    "paramiko",
}
# Un nom de fonction, de méthode ou de classe qui ressemble à une écriture chez une plateforme ou à une exécution.
NOMS_ECRITURE = re.compile(
    r"(mutate|create_?campaign|pause_?campaign|resume_?campaign|set_?budget|update_?budget|update_?campaign|delete|"
    r"remove_?campaign|launch|lancer|executer|exécuter|activer_?campagne|mettre_?en_?pause|creer_?campagne|"
    r"modifier_?budget|ajuster_?budget|financer|payer|publier|publish|push|upload|envoyer)",
    re.IGNORECASE,
)
# Les seuls points d'accès de chaque connecteur : de la LECTURE (liste blanche explicite, par source).
LECTURE = {
    "search_console": {"searchAnalytics.query"},
    "pagespeed": {"runPagespeed"},
    "crux": {"records:queryRecord"},
    "bing_webmaster": {"GetPageStats", "GetQueryStats", "GetRankAndTrafficStats"},
    "umami": {"websites.metrics", "websites.stats"},
    "matomo": {"Referrers.getWebsites", "VisitsSummary.get"},
    "gbp_avis": {"accounts.locations.reviews.list"},
    "gbp_insights": {"locations.getDailyMetricsTimeSeries"},
    "google_ads": {"googleAds:search"},
    "meta_ads": {"act.insights"},
}


def _arbre(chemin: Path) -> ast.AST:
    return ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))


def test_le_paquet_existe_et_la_liste_de_fichiers_n_est_pas_vide():
    assert {p.name for p in PAQUET} >= {"plan.py", "regles.py", "anomalies.py", "rapport.py"}


@pytest.mark.parametrize("chemin", FICHIERS, ids=lambda p: p.name)
def test_aucun_module_reseau_ni_processus_externe(chemin):
    for noeud in ast.walk(_arbre(chemin)):
        if isinstance(noeud, ast.Import):
            noms = [a.name for a in noeud.names]
        elif isinstance(noeud, ast.ImportFrom) and noeud.module and not noeud.level:
            noms = [noeud.module]
        else:
            continue
        for nom in noms:
            assert nom.split(".")[0] not in IMPORTS_INTERDITS, (chemin.name, nom)
            assert nom not in ("urllib.request", "urllib.error"), (chemin.name, nom)


@pytest.mark.parametrize("chemin", FICHIERS, ids=lambda p: p.name)
def test_ni_open_ni_eval_ni_exec_ni_import_dynamique_ni_variable_d_environnement(chemin):
    for noeud in ast.walk(_arbre(chemin)):
        if isinstance(noeud, ast.Name):
            assert noeud.id not in {"open", "eval", "exec", "compile", "__import__"}, (chemin.name, noeud.id)
    texte = chemin.read_text(encoding="utf-8")
    assert "os.environ" not in texte and "getenv" not in texte and "importlib" not in texte, chemin.name


@pytest.mark.parametrize("chemin", FICHIERS, ids=lambda p: p.name)
def test_aucun_nom_de_fonction_ou_de_methode_ne_ressemble_a_une_ecriture_chez_une_plateforme(chemin):
    fautifs = []
    for noeud in ast.walk(_arbre(chemin)):
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and NOMS_ECRITURE.search(
            noeud.name
        ):
            fautifs.append(noeud.name)
    assert fautifs == [], f"{chemin.name} : {fautifs}"


def test_la_regle_de_detection_des_noms_d_ecriture_detecte_bien_les_noms_dangereux():
    for nom in (
        "pause_campaign",
        "mutate_campaign",
        "set_budget",
        "lancer_campagne",
        "executer_regle",
        "publier",
        "update_budget",
        "mettre_en_pause",
        "CampaignMutateService",
        "create_campaign",
    ):
        assert NOMS_ECRITURE.search(nom), nom
    for nom in (
        "composer",
        "soumettre",
        "approuver_lancement",
        "dossier_de_lancement",
        "evaluer",
        "detecter",
        "retirer",
    ):
        assert NOMS_ECRITURE.search(nom) is None, nom


@pytest.mark.parametrize("source", sorted(LECTURE))
def test_chaque_connecteur_n_expose_que_des_points_d_acces_de_lecture_de_la_liste_blanche(source):
    points = set(catalogue.CONNECTEURS[source].POINTS_ACCES)
    assert points == LECTURE[source]
    assert not [
        p
        for p in points
        if re.search(r"mutate|create|update|delete|remove|set|post|publish|upload|pause", p, re.IGNORECASE)
    ]


def test_les_connecteurs_publicitaires_n_ont_aucune_methode_publique_d_ecriture():
    for classe in (publicite.ConnecteurGoogleAds, publicite.ConnecteurMetaAds):
        publiques = [n for n in dir(classe) if not n.startswith("_")]
        assert not [n for n in publiques if NOMS_ECRITURE.search(n)], (classe.__name__, publiques)
        assert set(publiques) >= {"lire_page", "releves_depenses", "fenetre_suivante"}


def test_la_seule_action_d_une_regle_est_une_proposition_de_pause():
    constantes = {n: getattr(regles, n) for n in dir(regles) if n.isupper()}
    assert constantes["ACTION"] == "proposer_pause" and constantes["STATUT_PREPAREE"] == "PREPAREE_NON_EXECUTEE"
    # aucune autre valeur d'action n'est écrite dans le module des règles
    texte = (SRC / "medias_payants" / "regles.py").read_text(encoding="utf-8")
    assert set(re.findall(r'"action":\s*"([a-z_]+)"', texte)) <= {"proposer_pause"}
    assert re.findall(r"\"executee(?:_par_opsys)?\":\s*(True|False)", texte) == ["False"] * texte.count('"executee')
