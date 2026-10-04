"""Adaptateur réel M3 vers le registre de reçus de campagne.

Les racines d'une épreuve incluent le dépôt source et, si présent, le root exact
de la copie temporaire. Le root d'un scénario rouge est donc une entrée de preuve,
pas une information décorative ni un chemin substituable après exécution.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from campagne_m3 import CampagneM3, EmpreinteEntrees, SpecificationExecution


def _hash_environnement(environnement: dict[str, str] | None = None) -> str:
    env = _copie_environnement_sans_pytest(environnement)
    canon = json.dumps(sorted(env.items()), separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _copie_environnement_sans_pytest(
    environnement: dict[str, str] | None = None,
) -> dict[str, str]:
    """Retourne l'environnement exact du sous-processus, sans le contexte pytest parent."""
    copie = dict(os.environ if environnement is None else environnement)
    copie.pop("PYTEST_CURRENT_TEST", None)
    return copie


def fermeture_execution(
    racine_depot: Path,
    *,
    racine_scenario: Path | None = None,
    outil_sabote: Path | None = None,
) -> EmpreinteEntrees:
    from campagne_m3 import racines_fermeture_m3

    racines = racines_fermeture_m3(racine_depot)
    if racine_scenario is not None:
        racines["scenario-root"] = Path(racine_scenario)
    if outil_sabote is not None:
        racines["outil-sabote"] = Path(outil_sabote)
    return EmpreinteEntrees.capturer(racines)


def specification_outil(
    script: Path,
    racine: Path,
    scenario: str,
    arguments: Sequence[str] = (),
    *,
    collecte: Path | None = None,
    environnement: dict[str, str] | None = None,
) -> SpecificationExecution:
    """Normalise uniquement les chemins temporaires aléatoires du script M3."""
    script = Path(script).resolve(strict=True)
    racine = Path(racine).resolve(strict=True)
    commande = (sys.executable, "-B", str(script), str(racine), *arguments)
    tests = "{ENV_MUTATION}/departments/m03-estimation/tests"
    ignore_reprise = f"--ignore={tests}/test_campagne_m3_persistante.py"
    ignore_gardes = f"--ignore={tests}/test_gardes_des_outils.py"
    ignore_preuves = f"--ignore={tests}/test_outils_de_preuve.py"
    options_par_outil = {
        "enumerer_gardes.py": (
            ignore_reprise,
            ignore_gardes,
            ignore_preuves,
            "-q",
            "-p",
            "no:cacheprovider",
            "--color=no",
            "--tb=line",
        ),
        "muter": (
            "-q",
            ignore_reprise,
            ignore_gardes,
            ignore_preuves,
            "-p",
            "no:cacheprovider",
            "--color=no",
            "--junitxml={JUNIT_TEMPORAIRE}",
        ),
    }
    options_pytest = options_par_outil.get(
        script.name,
        options_par_outil["muter"],
    )
    environnement_execution = _copie_environnement_sans_pytest(environnement)
    canon = json.dumps(
        sorted(environnement_execution.items()), separators=(",", ":")
    )
    return SpecificationExecution(
        outil=script.name,
        scenario=scenario,
        commande=commande,
        argv=commande,
        cwd=str(racine),
        python=f"{sys.executable} | {sys.version}",
        environnement_sha256=hashlib.sha256(canon.encode("utf-8")).hexdigest(),
        options_pytest=options_pytest,
        collecte=str(
            collecte or "{ENV_MUTATION}/departments/m03-estimation/tests"
        ),
        environnement_execution=tuple(sorted(environnement_execution.items())),
    )


def executer_preuve(
    campagne: CampagneM3,
    specification: SpecificationExecution,
    racine_depot: Path,
    *,
    racine_scenario: Path | None = None,
    outil_sabote: Path | None = None,
    environnement: dict[str, str] | None = None,
):
    environnement_execution = (
        _copie_environnement_sans_pytest(environnement)
        if environnement is not None
        else (
            dict(specification.environnement_execution)
            if specification.environnement_execution is not None
            else _copie_environnement_sans_pytest()
        )
    )
    return campagne.obtenir_ou_lancer_commande(
        specification,
        lambda: fermeture_execution(
            racine_depot,
            racine_scenario=racine_scenario,
            outil_sabote=outil_sabote,
        ),
        environnement=environnement_execution,
    )
