"""Outils M6 de démonstration, pour `tests/test_openclaw_roles.py` (T1.4-c2, T1.4-j)."""

from __future__ import annotations

from opsys.outils import Autonomie, Outil

_VIDE = {"type": "object", "properties": {}, "additionalProperties": False}

OUTILS = (
    Outil("m6_soumettre_materiaux", "Soumet les matériaux utilisés.", _VIDE, lambda: {}, Autonomie.T1,
          roles_appareil=frozenset({"employee", "admin"})),
    Outil("m6_approuver_bon_commande", "Approuve un bon de commande.", _VIDE, lambda: {}, Autonomie.T1,
          roles_appareil=frozenset({"admin"})),
)
