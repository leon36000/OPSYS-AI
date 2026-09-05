"""#568 / ADR-0005 : le validateur GitHub control pack (.opsys/tools/github-control) est un fragment
orphelin — module `common.py` et données jamais versionnés. Plutôt que fabriquer une source de vérité
ou casser deux gates fail-closed sur l'existence du répertoire, il est DÉCLARÉ non exécutable et ce
test scelle l'état : (A) la déclaration existe, (B) les 4 scripts échouent bien comme déclaré — le
jour où quelqu'un livre le pack, (B) rougit et force la mise à jour de la déclaration — (C) la
requalification n'a retiré aucune racine au périmètre qualité scellé."""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FRAGMENT = _REPO_ROOT / ".opsys" / "tools" / "github-control"
_DECLARATION = _FRAGMENT / "README.md"
_SCRIPTS = (
    "validate_github_control_pack.py",
    "github_issue_sync.py",
    "github_project_sync.py",
    "github_task_status.py",
)


def test_le_fragment_est_declare_non_executable() -> None:
    assert _DECLARATION.is_file(), "fragment sans declaration de non-executabilite"
    texte = _DECLARATION.read_text(encoding="utf-8")
    assert "NON-EXECUTABLE" in texte
    assert "fac74ea" in texte
    assert "common.py" in texte


@pytest.mark.parametrize("nom", _SCRIPTS)
def test_les_quatre_scripts_sont_reellement_inexecutables(nom: str) -> None:
    resultat = subprocess.run(
        [sys.executable, str(_FRAGMENT / nom)], capture_output=True, text=True, timeout=30, cwd=_REPO_ROOT
    )
    assert resultat.returncode != 0
    assert "No module named 'common'" in resultat.stderr


def test_la_requalification_ne_reduit_pas_le_perimetre_qualite() -> None:
    assert _FRAGMENT.is_dir()
    with (_REPO_ROOT / "core" / "quality-scopes.toml").open("rb") as flux:
        assert ".opsys/tools/github-control" in tomllib.load(flux)["python_roots"]
