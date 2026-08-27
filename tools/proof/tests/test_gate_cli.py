"""Contrats de confinement de la CLI des gates de preuve."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


CLI = Path(__file__).resolve().parents[1] / "gate_cli.py"


def _ecrire_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _phase() -> dict:
    return {"task_ids": [], "checks": []}


def _state() -> dict:
    return {"tasks": {}}


def _executer(phase_file: Path, state_file: Path, worktree: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--phase-file",
            str(phase_file),
            "--state-file",
            str(state_file),
            "--worktree",
            str(worktree),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_refuse_un_phase_file_hors_du_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    phase_file = _ecrire_json(tmp_path / "phase.json", _phase())
    state_file = _ecrire_json(worktree / "state.json", _state())

    result = _executer(phase_file, state_file, worktree)

    assert result.returncode == 2
    assert "hors du worktree" in result.stderr


def test_refuse_un_state_file_hors_du_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    phase_file = _ecrire_json(worktree / "phase.json", _phase())
    state_file = _ecrire_json(tmp_path / "state.json", _state())

    result = _executer(phase_file, state_file, worktree)

    assert result.returncode == 2
    assert "hors du worktree" in result.stderr


def test_refuse_un_symlink_vers_un_fichier_hors_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    external_state = _ecrire_json(tmp_path / "state-externe.json", _state())
    phase_file = _ecrire_json(worktree / "phase.json", _phase())
    state_file = worktree / "state.json"
    state_file.symlink_to(external_state)

    result = _executer(phase_file, state_file, worktree)

    assert result.returncode == 2
    assert "hors du worktree" in result.stderr


def test_accepte_les_deux_fichiers_dans_le_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    phase_file = _ecrire_json(worktree / "phase.json", _phase())
    state_file = _ecrire_json(worktree / "state.json", _state())

    result = _executer(phase_file, state_file, worktree)

    assert result.returncode == 0
    assert '"satisfied": true' in result.stdout
