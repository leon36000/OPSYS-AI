"""Outils M2 de démonstration, pour `tests/test_openclaw_roles.py` (T1.4-c2, T1.4-j)."""

from __future__ import annotations

from opsys.outils import Outil

_VIDE = {"type": "object", "properties": {}, "additionalProperties": False}

OUTILS = (
    Outil("m2_lire_leads", "Liste les leads.", _VIDE, lambda: {},
          roles_appareil=frozenset({"seller", "admin"})),
    # Aucune déclaration : appelable par aucun appareil, admin compris (fermé par défaut).
    Outil("m2_exporter_tous_les_leads", "Exporte tous les leads.", _VIDE, lambda: {}),
)
