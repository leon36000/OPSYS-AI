"""Preuve que les scanners reçoivent le périmètre qualité réellement configuré."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "core" / "scripts"))

import run_codeql_scan as codeql  # noqa: E402
import run_security_scan as security  # noqa: E402


def _racines_contractuelles() -> tuple[str, ...]:
    return (
        "core/src",
        "core/scripts",
        "tools/proof",
        "scripts",
        ".opsys/tools/github-control",
    )


def test_les_cinq_racines_contractuelles_existent() -> None:
    assert all((_REPO_ROOT / racine).is_dir() for racine in _racines_contractuelles())


def test_codeql_transmet_toutes_les_racines_dans_l_environnement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captures: list[dict[str, object]] = []

    def _executer(
        codeql_path: str,
        argv: list[str],
        *,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        captures.append({"codeql": codeql_path, "argv": argv, "timeout": timeout, "env": env})
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(codeql, "_executer", _executer)

    ok, _ = codeql.construire_base("codeql", tmp_path / "db")

    assert ok is True
    assert len(captures) == 1
    env = captures[0]["env"]
    assert isinstance(env, dict)
    assert env["LGTM_INDEX_FILTERS"] == "\n".join(
        ["exclude:**/*"]
        + [f"include:{racine}/**" for racine in _racines_contractuelles()]
    )


def test_security_transmet_toutes_les_racines_a_bandit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captures: list[list[str]] = []

    def _executer(argv: list[str]) -> subprocess.CompletedProcess[str]:
        captures.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({"results": []}),
            stderr="",
        )

    monkeypatch.setattr(security, "_executer", _executer)

    ok, _ = security.executer_bandit()

    assert ok is True
    assert len(captures) == 1
    argv = captures[0]
    index = argv.index("-r")
    assert argv[index + 1 : index + 1 + len(_racines_contractuelles())] == [
        str(_REPO_ROOT / racine) for racine in _racines_contractuelles()
    ]


def test_codeql_refuse_une_racine_contractuelle_absente(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    contrat = tmp_path / "quality-scopes.toml"
    contrat.write_text('python_roots = ["core/src", "missing-root"]\n', encoding="utf-8")
    monkeypatch.setattr(codeql, "_QUALITY_SCOPES", contrat)

    with pytest.raises(codeql.OutilCodeQLAbsent, match="racine.*absente"):
        codeql.charger_racines_qualite()


def test_bandit_refuse_une_racine_contractuelle_absente(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    contrat = tmp_path / "quality-scopes.toml"
    contrat.write_text('python_roots = ["core/src", "missing-root"]\n', encoding="utf-8")
    monkeypatch.setattr(security, "_QUALITY_SCOPES", contrat)

    with pytest.raises(security.OutilSecuriteAbsent, match="racine.*absente"):
        security.charger_racines_qualite()
