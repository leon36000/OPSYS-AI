#!/usr/bin/env python3
"""CLI d'évaluation d'un gate de phase sémantique (tools/proof/gate_engine.py)."""
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from gate_engine import evaluate_gate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Évalue un gate de phase sémantique.")
    parser.add_argument("--phase-file", required=True, type=Path)
    parser.add_argument("--state-file", required=True, type=Path)
    parser.add_argument("--worktree", required=True, type=Path)
    args = parser.parse_args(argv)

    phase = json.loads(args.phase_file.read_text(encoding="utf-8"))
    state = json.loads(args.state_file.read_text(encoding="utf-8"))
    result = evaluate_gate(phase, state, args.worktree)

    print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.satisfied else 1


if __name__ == "__main__":
    raise SystemExit(main())
