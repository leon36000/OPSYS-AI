"""M9 — garde statique : tout outil des modules ``outils_*`` exige l'admin authentifié (jamais un agent) ; les outils
historiques de ``outils.py`` conservent leur voie d'origine, dite telle (fictif)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = (
    Path(__file__).resolve().parents[1]
    / "departments"
    / "m09-strategic-intelligence"
    / "src"
    / "m9_strategic_intelligence"
)
MODULES = sorted(p for p in SRC.glob("outils_*.py"))


def _outils_et_fonctions(arbre: ast.AST):
    """(outil, fonction liée) pour chaque appel ``Outil(...)`` ou ``outil(nom, ..., fonction, ...)``."""
    fonctions = {n.name: n for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef)}
    trouves = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        cible = noeud.func.id if isinstance(noeud.func, ast.Name) else None
        if cible == "Outil":
            nom = next((k.value for k in noeud.keywords if k.arg == "nom"), None)
            lie = next((k.value for k in noeud.keywords if k.arg == "fonction"), None)
        elif cible == "outil" and len(noeud.args) >= 5:
            nom, lie = noeud.args[0], noeud.args[4]
        else:
            continue
        if isinstance(nom, ast.Constant) and isinstance(lie, ast.Name) and lie.id in fonctions:
            trouves.append((nom.value, fonctions[lie.id]))
    return trouves


def _appelle(fonction: ast.FunctionDef, nom: str) -> bool:
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == nom for n in ast.walk(fonction)
    )


def test_il_y_a_des_modules_et_des_outils_a_verifier():
    comptes = [len(_outils_et_fonctions(ast.parse(p.read_text(encoding="utf-8")))) for p in MODULES]
    assert len(MODULES) >= 15 and sum(comptes) >= 45, (len(MODULES), sum(comptes))


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.stem)
def test_chaque_outil_des_modules_outils_exige_l_admin_strict(module):
    arbre = ast.parse(module.read_text(encoding="utf-8"))
    sans_garde = [
        nom
        for nom, fonction in _outils_et_fonctions(arbre)
        if not (_appelle(fonction, "exiger_admin_strict") or _appelle(fonction, "_exiger_admin_strict"))
    ]
    assert sans_garde == [], f"outil sans exiger_admin_strict : {sans_garde}"


def test_les_outils_historiques_de_outils_py_gardent_leur_voie_d_origine_et_restent_fermes_aux_autres_profils():
    texte = (SRC / "outils.py").read_text(encoding="utf-8")
    assert "def _exiger_admin_pour_appareil" in texte
    assert "La voie des agents/console sans identité d'appareil conserve ses permissions existantes." in texte
