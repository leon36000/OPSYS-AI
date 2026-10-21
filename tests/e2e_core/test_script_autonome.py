"""Le script de la CI `e2e-core` se charge seul, comme dans le job : sans PYTHONPATH.

Le job lance `python tests/e2e_core/scenario.py` après la construction du core (plus de
10 minutes). Une importation cassée ne se voyait qu'à ce moment-là ; ce test la voit tout de
suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCENARIO = Path(__file__).resolve().parent / "scenario.py"


def test_scenario_se_charge_sans_pythonpath() -> None:
    env = {cle: valeur for cle, valeur in os.environ.items() if cle != "PYTHONPATH"}
    resultat = subprocess.run(
        [sys.executable, str(SCENARIO), "--help"],
        capture_output=True,
        text=True,
        env=env,
        cwd=SCENARIO.parents[2],
        timeout=120,
        check=False,
    )
    assert resultat.returncode == 0, resultat.stderr
    assert "--moteur" in resultat.stdout
