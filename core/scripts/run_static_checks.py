"""Matrice qualité statique et typage (C02-004).

Rendre l'environnement, les dépendances et les checks bloquants
reproductibles avant le Core. Une gate required dont l'outil est absent ou
dont l'exécution échoue ne devient JAMAIS un « pass » silencieux — et une
baseline de dette connue est TOUJOURS enregistrée dans le résultat, jamais
masquée, sans jamais devenir un permis d'empirer silencieusement (seules
les erreurs AU-DELÀ de la baseline bloquent une gate required).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class QualityGate:
    name: str
    argv: list[str]
    required: bool
    scope: list[str]


@dataclass(frozen=True)
class GateOutcome:
    name: str
    executed: bool
    error_count: int
    baseline_count: int
    new_error_count: int
    blocked: bool
    detail: str


def evaluer_gate(
    gate: QualityGate,
    baseline: dict[str, int],
    *,
    timeout: int = 300,
) -> GateOutcome:
    baseline_count = baseline.get(gate.name, 0)

    if not gate.argv or shutil.which(gate.argv[0]) is None:
        return GateOutcome(
            name=gate.name,
            executed=False,
            error_count=0,
            baseline_count=baseline_count,
            new_error_count=0,
            blocked=gate.required,
            detail=f"{gate.name}: outil introuvable ({gate.argv[0] if gate.argv else None!r}) — jamais un pass silencieux",
        )

    try:
        cp = subprocess.run(
            gate.argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GateOutcome(
            name=gate.name,
            executed=False,
            error_count=0,
            baseline_count=baseline_count,
            new_error_count=0,
            blocked=gate.required,
            detail=f"{gate.name}: exécution échouée ({exc}) — jamais un pass silencieux",
        )

    sortie = cp.stdout + cp.stderr
    error_count = len(re.findall(r": error:", sortie))
    new_error_count = max(0, error_count - baseline_count)
    blocked = gate.required and new_error_count > 0

    return GateOutcome(
        name=gate.name,
        executed=True,
        error_count=error_count,
        baseline_count=baseline_count,
        new_error_count=new_error_count,
        blocked=blocked,
        detail=f"{gate.name}: {error_count} erreur(s) ({baseline_count} en baseline, {new_error_count} nouvelle(s))",
    )


def evaluer_matrice(
    gates: list[QualityGate],
    baseline: dict[str, int],
    *,
    timeout: int = 300,
) -> tuple[bool, list[GateOutcome]]:
    resultats = [evaluer_gate(g, baseline, timeout=timeout) for g in gates]
    ok = not any(r.blocked for r in resultats)
    return ok, resultats
