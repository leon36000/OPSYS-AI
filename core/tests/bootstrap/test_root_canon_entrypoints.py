"""Contract for the single active Core canon and its root adapters."""
from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_CANON = "docs/core/CANON-INDEX.md"
_ACTIVE_AUTHORITIES = (
    "docs/core/CORE-CANON-v2.md",
    "docs/core/CORE-NON-GOALS-v2.md",
    "docs/core/MODULE-ORDER-AND-DEFERRED-SURFACES.md",
    "docs/core/CI-REQUIRED-CHECKS.md",
    ".opsys/core-control/2.3.0/TASK-REGISTRY.jsonl",
    ".opsys/core-control/2.3.0/DEPENDENCY-GRAPH.json",
    ".opsys/core-control/2.3.0/REPOSITORY-CONTRACT.md",
    ".opsys/core-control/2.3.0/GITHUB-OPERATING-MODEL.md",
)


def _read(relative_path: str) -> str:
    return (_REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_active_canon_indexes_existing_core_authorities() -> None:
    canon = _read(_CANON)

    assert "CANON_STATUS: ACTIVE" in canon
    assert "Core v2.3.0" in canon
    assert "CORE_RC_VERIFIED" in canon
    for relative_path in _ACTIVE_AUTHORITIES:
        assert relative_path in canon
        assert (_REPO_ROOT / relative_path).is_file(), relative_path


def test_root_portals_delegate_to_the_single_canon() -> None:
    for relative_path in ("README.md", "START_HERE.md", "PROMPT_BOOTSTRAP_CLAUDE_CODE.md"):
        assert _CANON in _read(relative_path), relative_path
    assert "core/CANON-INDEX.md" in _read("docs/index.md")

    assert "Source de vérité : le plan maître" not in _read("README.md")
    for relative_path in ("START_HERE.md", "PROMPT_BOOTSTRAP_CLAUDE_CODE.md"):
        first_lines = "\n".join(_read(relative_path).splitlines()[:8])
        assert "SUPERSEDED" in first_lines, relative_path


def test_agents_and_claude_are_short_derived_adapters() -> None:
    agents = _read("AGENTS.md")
    claude = _read("CLAUDE.md")

    assert _CANON in agents
    assert _CANON in claude
    assert "@AGENTS.md" in claude
    for stale_authority in ("GRS_Plan_Squelette", "LiteLLM", "crew-", "Phase 0"):
        assert stale_authority not in agents
        assert stale_authority not in claude
