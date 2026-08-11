"""Matrice qualité statique et typage (C02-004).

Rendre l'environnement, les dépendances et les checks bloquants
reproductibles avant le Core. Une gate required dont l'outil est absent ou
dont l'exécution échoue ne devient JAMAIS un « pass » silencieux — et une
baseline de dette connue est TOUJOURS enregistrée dans le résultat, jamais
masquée, sans jamais devenir un permis d'empirer silencieusement (seules
les erreurs AU-DELÀ de la baseline bloquent une gate required).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


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


def valider_configuration(chemin: Path) -> list[str]:
    """Valide un fichier TOML de configuration de gates sans exécuter aucun sous-processus."""
    erreurs: list[str] = []

    if not chemin.is_file():
        return [f"fichier absent: {chemin}"]

    try:
        with chemin.open("rb") as fichier:
            config = tomllib.load(fichier)
    except tomllib.TOMLDecodeError as exc:
        return [f"TOML invalide: {exc}"]

    gates = config.get("gates")
    if gates is None:
        erreurs.append("aucune gate déclarée")
    elif not isinstance(gates, list):
        erreurs.append("gates: doit être une liste")
        gates = []
    elif len(gates) == 0:
        erreurs.append("aucune gate déclarée")

    noms_vus: set[str] = set()

    if isinstance(gates, list):
        for i, gate in enumerate(gates):
            if not isinstance(gate, dict):
                erreurs.append(f"gates[{i}]: entrée non valide")
                continue

            for cle in ("name", "argv", "required", "scope"):
                if cle not in gate:
                    erreurs.append(f"gates[{i}]: clé manquante '{cle}'")

            nom = gate.get("name")
            if nom is not None:
                if nom in noms_vus:
                    erreurs.append(f"dupliqué: la gate '{nom}' est déclarée plusieurs fois")
                else:
                    noms_vus.add(nom)

            argv = gate.get("argv")
            if argv is not None and (not isinstance(argv, list) or len(argv) == 0):
                erreurs.append(
                    f"gates[{i}] ({nom}): argv doit être une liste non vide"
                    if nom is not None
                    else f"gates[{i}]: argv doit être une liste non vide"
                )

            required = gate.get("required")
            if required is not None and not isinstance(required, bool):
                erreurs.append(
                    f"gates[{i}] ({nom}): required doit être un booléen"
                    if nom is not None
                    else f"gates[{i}]: required doit être un booléen"
                )

    baseline = config.get("baseline")
    if baseline is not None:
        if not isinstance(baseline, dict):
            erreurs.append("baseline: doit être un tableau/dict")
        else:
            for cle in baseline:
                if cle not in noms_vus:
                    erreurs.append(f"baseline: clé orpheline '{cle}' ne correspond à aucune gate")

    return erreurs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Matrice qualité statique et typage (C02-004/C02-CHK-02)."
    )
    parser.add_argument(
        "--configuration-only",
        action="store_true",
        help="Valide core/quality-gates.toml sans exécuter aucune gate (aucun subprocess).",
    )
    parser.add_argument(
        "--config",
        default="core/quality-gates.toml",
        help="Chemin du fichier de configuration (défaut: core/quality-gates.toml).",
    )
    args = parser.parse_args()

    if args.configuration_only:
        erreurs = valider_configuration(Path(args.config))
        if erreurs:
            for e in erreurs:
                print(f"ERREUR: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"OK: {args.config} — configuration valide.")
        sys.exit(0)

    print(
        "Ce script n'a pas de mode d'exécution complet en CLI — utiliser "
        "evaluer_matrice() par import, ou --configuration-only pour valider "
        "core/quality-gates.toml sans exécuter aucune gate.",
        file=sys.stderr,
    )
    sys.exit(2)
