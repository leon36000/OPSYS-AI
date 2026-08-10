"""Runner de tests hermétique (C02-003).

Rendre l'environnement, les dépendances et les checks bloquants
reproductibles avant le Core. Ce runner n'utilise JAMAIS un interpréteur
ambiant/système qui pourrait différer de celui qui orchestre réellement
(sys.executable), et il ne masque JAMAIS un échec réel (code retour
altéré, timeout avalé, avertissement de thread ignoré) derrière un succès
apparent.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def resolve_test_interpreter() -> Path:
    executable = sys.executable
    if not executable:
        raise RuntimeError(
            "sys.executable vide : impossible de garantir l'hermétisme "
            "(jamais de repli implicite sur /usr/bin/python3 ou tout "
            "autre chemin système en dur)"
        )
    return Path(executable).resolve()


def run_test_slice(args: list[str], *, timeout: int = 1800) -> int:
    interpreter = resolve_test_interpreter()
    argv = [
        str(interpreter),
        "-m",
        "pytest",
        "-W",
        "error::pytest.PytestUnhandledThreadExceptionWarning",
        *args,
    ]
    try:
        cp = subprocess.run(argv, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124
    return cp.returncode
