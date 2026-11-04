"""Régression D2 : mêmes faits M7, mêmes références quelle que soit la seed Python."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from m7_marketing import performance_campagnes

import opsys

_CODE = r'''
import json
from datetime import date
from m7_marketing.performance_campagnes import construire_performance
faits = [{"type": "m2.client_associe", "charge": {
    "lead_id": f"lead-fictif-{i}", "client_id": f"client-fictif-{i}",
    "horodatage_association": "2026-09-10T12:00:00Z",
    "source": None, "campagne": None, "utm": None,
}} for i in range(8)]
r = construire_performance(faits, date(2026, 9, 1), date(2026, 9, 30))
print(json.dumps(r["campagnes"][0]["source_refs"], sort_keys=True))
'''


def _rendre(seed: str) -> str:
    # Dérive les racines Python depuis les modules réellement chargés; aucun chemin machine n'est figé.
    racines = {
        str(Path(performance_campagnes.__file__).resolve().parents[1]),
        str(Path(opsys.__file__).resolve().parents[1]),
    }
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": os.pathsep.join(sorted(racines))}
    return subprocess.check_output([sys.executable, "-c", _CODE], env=env, text=True).strip()


def test_ordre_refs_attribution_absente_stable_entre_processus():
    assert _rendre("1") == _rendre("2")
