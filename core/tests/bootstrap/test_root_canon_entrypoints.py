"""Contrat des points d'entrée documentaires actifs du dépôt OPSYS-AI.

Ces tests empêchent les fichiers racine historiques de redevenir une autorité
concurrente du programme Core v2.3.0.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(relative: str) -> str:
    return (_REPO_ROOT / relative).read_text(encoding="utf-8")


def test_readme_points_to_active_core_canon() -> None:
    readme = _read("README.md")
    assert "Core v2.3.0" in readme
    assert "docs/core/CANON-INDEX.md" in readme
    assert "M7 → M1 → M2 → M4 → M3 → M6 → M8 → M10 → M5 → M9" in readme
    assert "Source de vérité : le plan maître" not in readme


def test_canon_index_links_every_active_local_authority() -> None:
    index = _read("docs/core/CANON-INDEX.md")
    for path in (
        "docs/core/CORE-CANON-v2.md",
        "docs/core/CORE-NON-GOALS-v2.md",
        "docs/core/MODULE-ORDER-AND-DEFERRED-SURFACES.md",
        ".opsys/core-control/2.3.0/TASK-REGISTRY.jsonl",
        ".opsys/core-control/2.3.0/DEPENDENCY-GRAPH.json",
        ".opsys/core-control/2.3.0/REPOSITORY-CONTRACT.md",
    ):
        assert path in index
        assert (_REPO_ROOT / path).exists(), path


def test_documentation_index_points_to_core_canon() -> None:
    documentation_index = _read("docs/index.md")
    assert "core/CANON-INDEX.md" in documentation_index
    assert "Porte d'entrée historique" in documentation_index


def test_historical_bootstraps_are_explicitly_superseded() -> None:
    for path in ("START_HERE.md", "PROMPT_BOOTSTRAP_CLAUDE_CODE.md"):
        first_lines = "\n".join(_read(path).splitlines()[:8])
        assert "SUPERSEDED" in first_lines, path
        assert "docs/core/CANON-INDEX.md" in first_lines, path
