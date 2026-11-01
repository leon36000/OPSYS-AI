"""Le paquet `veille` (et ses outils) n'a AUCUN accès réseau, système ou dynamique : vérifié sur la source, par
l'arbre syntaxique."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2] / "src" / "m7_marketing"
SOURCES = sorted([*(RACINE / "veille").glob("*.py"), RACINE / "veille_outils.py"])
INTERDITS = {"socket", "ssl", "http", "urllib3", "requests", "httpx", "aiohttp", "smtplib", "ftplib", "telnetlib",
    "subprocess",
             "asyncio", "selectors", "webbrowser", "xmlrpc", "playwright", "selenium", "scrapy", "bs4", "lxml",
                 "ctypes", "pickle",
             "marshal", "importlib", "shelve"}
NOMS_INTERDITS = {"open", "eval", "exec", "compile", "__import__"}


def test_le_balayage_voit_bien_les_modules_de_la_veille():
    noms = {s.name for s in SOURCES}
    assert {"registre.py", "collecte.py", "observations.py", "comparaison.py", "conformite.py", "doubles.py",
        "robots.py",
            "veille_outils.py"} <= noms


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.name)
def test_aucun_import_reseau_systeme_ou_dynamique(source):
    arbre = ast.parse(source.read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        noms = []
        if isinstance(noeud, ast.Import):
            noms = [a.name for a in noeud.names]
        elif isinstance(noeud, ast.ImportFrom) and noeud.module and not noeud.level:
            noms = [noeud.module]
        for nom in noms:
            assert nom.split(".")[0] not in INTERDITS, (source.name, nom)
            assert nom not in {"urllib.request", "urllib.robotparser", "os"}, (source.name, nom)
        if isinstance(noeud, ast.Name):
            assert noeud.id not in NOMS_INTERDITS, (source.name, noeud.id)
        if isinstance(noeud, ast.Attribute) and isinstance(noeud.value, ast.Name) and noeud.value.id == "os":
            raise AssertionError((source.name, noeud.attr))


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.name)
def test_ni_environnement_ni_secret_ni_cookie_dans_le_code(source):
    texte = source.read_text(encoding="utf-8")
    for motif in ("os.environ", "getenv", "Authorization:", "Set-Cookie", "Cookie:", "Bearer "):
        assert motif not in texte, (source.name, motif)


def test_le_seul_transport_par_defaut_est_celui_qui_refuse():
    from m7_marketing.veille import collecte

    implementations = [n for n in dir(collecte) if n.startswith("Transport")]
    assert sorted(implementations) == ["TransportPublic", "TransportPublicNonBranche"]
    source = (RACINE / "veille" / "collecte.py").read_text(encoding="utf-8")
    assert source.count("TransportPublicNonBranche()") == 1
