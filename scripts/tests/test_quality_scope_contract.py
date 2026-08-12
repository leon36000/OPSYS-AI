"""Contrat unique des périmètres qualité du dépôt."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QUALITY_SCOPES: Final[Path] = _REPO_ROOT / "core" / "quality-scopes.toml"
_PYTHON_ROOTS: Final[list[str]] = [
    "core/src",
    "core/scripts",
    "tools/proof",
    "scripts",
    ".opsys/tools/github-control",
]
_REQUIRED_JOB_IDS: Final[list[str]] = [
    "gates",
    "types",
    "tests",
    "security",
    "pack-validation",
    "proof-sealed",
]
_SCOPE_CONSUMERS: Final[list[Path]] = [
    _REPO_ROOT / "scripts" / "quality" / "no_stub_gate.py",
    _REPO_ROOT / "core" / "scripts" / "run_pack_validation.py",
    _REPO_ROOT / "core" / "scripts" / "run_security_scan.py",
    _REPO_ROOT / "core" / "scripts" / "run_codeql_scan.py",
]


def _arbre_python(chemin: Path) -> ast.Module:
    """Parse un fichier Python afin que le contrat soit vérifié structurellement."""
    return ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))


def _reference_le_fichier_de_scope(arbre: ast.AST) -> bool:
    """Détermine si un arbre référence explicitement le fichier TOML canonique."""
    return any(
        isinstance(noeud, ast.Constant)
        and isinstance(noeud.value, str)
        and "quality-scopes.toml" in noeud.value
        for noeud in ast.walk(arbre)
    )


def _contient_une_copie_de_racines(arbre: ast.AST) -> bool:
    """Détecte une liste littérale qui recopie au moins trois racines canoniques."""
    racines = set(_PYTHON_ROOTS)
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.List):
            continue
        valeurs = {
            element.value
            for element in noeud.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
        if len(valeurs & racines) >= 3:
            return True
    return False


def test_le_fichier_de_scope_unique_existe_et_est_un_toml_valide() -> None:
    """Prouve que le contrat central existe et peut être consommé sans parseur ad hoc."""
    assert _QUALITY_SCOPES.is_file()
    with _QUALITY_SCOPES.open("rb") as fichier:
        contrat: dict[str, object] = tomllib.load(fichier)
    assert isinstance(contrat, dict)


def test_les_racines_python_du_contrat_sont_exactement_celles_attendues() -> None:
    """Prouve que les outils partagent les cinq racines, dans leur ordre scellé."""
    with _QUALITY_SCOPES.open("rb") as fichier:
        contrat: dict[str, object] = tomllib.load(fichier)
    assert contrat["python_roots"] == _PYTHON_ROOTS


def test_les_jobs_requis_du_contrat_sont_exactement_ceux_attendus() -> None:
    """Prouve que la protection des jobs CI repose sur les six identifiants scellés."""
    with _QUALITY_SCOPES.open("rb") as fichier:
        contrat: dict[str, object] = tomllib.load(fichier)
    assert contrat["target_required_job_ids"] == _REQUIRED_JOB_IDS


def test_les_outils_consultent_le_contrat_sans_recopier_les_racines() -> None:
    """Prouve que chaque consommateur lit la source unique et évite toute dérive de copie."""
    for outil in _SCOPE_CONSUMERS:
        assert outil.is_file(), f"outil de qualité absent : {outil}"
        arbre = _arbre_python(outil)
        assert _reference_le_fichier_de_scope(arbre), (
            f"{outil} ne référence pas core/quality-scopes.toml"
        )
        assert not _contient_une_copie_de_racines(arbre), (
            f"{outil} embarque une copie littérale des racines de périmètre"
        )
