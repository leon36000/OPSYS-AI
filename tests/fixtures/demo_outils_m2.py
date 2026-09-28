"""Outils M2 de démonstration, pour `tests/test_openclaw_roles.py` (T1.4-c2)."""

from __future__ import annotations

from opsys.outils import Outil

OUTILS = (
    Outil("m2_lire_leads", "Liste les leads.",
          {"type": "object", "properties": {}, "additionalProperties": False}, lambda: {}),
)
