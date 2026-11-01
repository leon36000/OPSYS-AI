"""Garde transversale de la tranche « signaux » : aucun module des cinq paquets (ni leurs outils) n'importe un
module réseau,
n'ouvre un fichier, n'exécute du texte, ne lit l'environnement ni ne nomme un geste d'écriture chez un fournisseur.

Ce que ce test prouve : par la SOURCE, le code livré ne PEUT pas parler à un réseau (tout passe par des ports :
`Transport`,
`TransportPublic`, `PortMoteurIA`, qui n'ont aucune implémentation réelle). Ce qu'il ne prouve pas : que le futur
transport réel,
quand il existera, respectera ces ports.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1] / "src" / "m7_marketing"
PAQUETS = ("signaux", "medias_payants", "veille", "geo", "mesure")
OUTILS = ("signaux_outils.py", "medias_outils.py", "veille_outils.py", "geo_outils.py", "mesure_outils.py")
INTERDITS = {
    "socket",
    "ssl",
    "http",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "smtplib",
    "ftplib",
    "imaplib",
    "poplib",
    "telnetlib",
    "subprocess",
    "asyncio",
    "selectors",
    "websockets",
    "websocket",
    "playwright",
    "selenium",
    "pyppeteer",
    "mechanize",
    "scrapy",
    "bs4",
    "lxml",
    "urllib.request",
    "xmlrpc",
    "multiprocessing",
    "ctypes",
    "pickle",
    "marshal",
    "shelve",
    "googleapiclient",
    "google",
    "facebook",
    "facebook_business",
    "tweepy",
    "linkedin",
    "openai",
    "anthropic",
    "litellm",
}
NOMS_INTERDITS = {"open", "eval", "exec", "__import__", "compile"}
GESTES_ECRITURE = re.compile(
    r"(mutate|create_campaign|creer_campagne|pause_campaign|mettre_en_pause|set_budget|update_budget|modifier_budget|"
    r"delete_campaign|lancer_campagne|publish_ad|publier_annonce|submit_ad|enable_campaign|activer_campagne|"
    r"envoyer_requete_ecriture|post_to|publier_sur)",
    re.IGNORECASE,
)


def sources():
    for paquet in PAQUETS:
        yield from sorted((RACINE / paquet).glob("*.py"))
    for nom in OUTILS:
        yield RACINE / nom


@pytest.mark.parametrize("fichier", list(sources()), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_aucune_importation_reseau_ni_acces_systeme(fichier):
    arbre = ast.parse(fichier.read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        noms = []
        if isinstance(noeud, ast.Import):
            noms = [a.name for a in noeud.names]
        elif isinstance(noeud, ast.ImportFrom) and noeud.module and not noeud.level:
            noms = [noeud.module]
        for nom in noms:
            assert not (nom in INTERDITS or nom.split(".")[0] in INTERDITS), (fichier.name, nom)
        if isinstance(noeud, ast.Name):
            assert noeud.id not in NOMS_INTERDITS, (fichier.name, noeud.id)
        if isinstance(noeud, ast.Attribute) and isinstance(noeud.value, ast.Name) and noeud.value.id == "os":
            assert noeud.attr not in {"environ", "getenv", "system", "popen", "remove", "unlink"}, (
                fichier.name,
                noeud.attr,
            )
    texte = fichier.read_text(encoding="utf-8")
    assert "os.environ" not in texte and "getenv(" not in texte


@pytest.mark.parametrize("fichier", list(sources()), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_aucun_nom_de_geste_d_ecriture_chez_un_fournisseur(fichier):
    arbre = ast.parse(fichier.read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        nom = None
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nom = noeud.name
        elif isinstance(noeud, ast.Name):
            nom = noeud.id
        elif isinstance(noeud, ast.Attribute):
            nom = noeud.attr
        if nom is not None and not nom.isupper():
            assert not GESTES_ECRITURE.search(nom), (fichier.name, nom)


def test_les_listes_blanches_de_points_d_acces_ne_contiennent_que_de_la_lecture():
    from m7_marketing.signaux import catalogue

    for source, classe in catalogue.CONNECTEURS.items():
        for point in classe.POINTS_ACCES:
            assert not GESTES_ECRITURE.search(point), (source, point)
            assert not re.search(
                r"(add|delete|insert|submit|update|remove|post|put|patch)", point, re.IGNORECASE
            ) or point in {"googleAds:search"}, (source, point)


def test_le_garde_detecte_vraiment_un_import_interdit(tmp_path):
    f = tmp_path / "mauvais.py"
    f.write_text("import socket\nopen('x')\n", encoding="utf-8")
    arbre = ast.parse(f.read_text(encoding="utf-8"))
    trouves = {a.name for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names}
    assert trouves & INTERDITS == {"socket"}
    assert any(isinstance(n, ast.Name) and n.id in NOMS_INTERDITS for n in ast.walk(arbre))
    assert GESTES_ECRITURE.search("googleAds:mutate") and GESTES_ECRITURE.search("pause_campaign")
