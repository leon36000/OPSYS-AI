"""Outils M3 de démonstration, pour `tests/test_openclaw_roles.py` (T1.4-c2, T1.4-j)."""

from __future__ import annotations

from opsys.outils import Outil

OUTILS = (
    Outil("m3_lire_devis", "Lit un devis.",
          {"type": "object", "properties": {}, "additionalProperties": False}, lambda: {},
          roles_appareil=frozenset({"seller", "admin"})),
)
