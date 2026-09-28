"""Outils M6 de démonstration, pour `tests/test_openclaw_roles.py` (T1.4-c2)."""

from __future__ import annotations

from opsys.outils import Autonomie, Outil

OUTILS = (
    Outil("m6_soumettre_materiaux", "Soumet les matériaux utilisés.",
          {"type": "object", "properties": {}, "additionalProperties": False}, lambda: {}, Autonomie.T1),
)
