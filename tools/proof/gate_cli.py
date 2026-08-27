#!/usr/bin/env python3
"""CLI d'évaluation d'un gate de phase sémantique (tools/proof/gate_engine.py)."""
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from gate_engine import evaluate_gate


def _fichier_dans_worktree(
    parser: argparse.ArgumentParser,
    fichier: Path,
    worktree: Path,
) -> Path:
    """Résout un fichier existant et refuse toute sortie du worktree réel."""
    try:
        racine = worktree.resolve(strict=True)
    except (OSError, RuntimeError):
        parser.error("--worktree doit désigner un répertoire existant")
    if not racine.is_dir():
        parser.error("--worktree doit désigner un répertoire")

    try:
        resolu = fichier.resolve(strict=True)
    except (OSError, RuntimeError):
        parser.error(f"{fichier} est introuvable ou ne peut pas être résolu")
    if not resolu.is_file():
        parser.error(f"{fichier} doit désigner un fichier")
    try:
        resolu.relative_to(racine)
    except ValueError:
        parser.error(f"{fichier} est hors du worktree")
    return resolu


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Évalue un gate de phase sémantique.")
    parser.add_argument("--phase-file", required=True, type=Path)
    parser.add_argument("--state-file", required=True, type=Path)
    parser.add_argument("--worktree", required=True, type=Path)
    args = parser.parse_args(argv)

    phase_file = _fichier_dans_worktree(parser, args.phase_file, args.worktree)
    state_file = _fichier_dans_worktree(parser, args.state_file, args.worktree)
    worktree = args.worktree.resolve(strict=True)
    phase = json.loads(phase_file.read_text(encoding="utf-8"))
    state = json.loads(state_file.read_text(encoding="utf-8"))
    result = evaluate_gate(phase, state, worktree)

    print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.satisfied else 1


if __name__ == "__main__":
    raise SystemExit(main())
