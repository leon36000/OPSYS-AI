"""Outils d'un département M9 fictif dont les portées d'appareil sont déclarées et valides
(`tests/test_openclaw_roles.py`, T1.4-j) : un outil par cas de la table rôle -> outils."""

from __future__ import annotations

from opsys.outils import Autonomie, Outil

_VIDE = {"type": "object", "properties": {}, "additionalProperties": False}

OUTILS = (
    Outil("m9_pointer_terrain", "Pointe sur le terrain.", _VIDE, lambda: {}, Autonomie.T1,
          roles_appareil=frozenset({"employee", "admin"})),
    Outil("m9_lire_client", "Lit la fiche d'un client.", _VIDE, lambda: {},
          roles_appareil=frozenset({"seller", "admin"})),
    Outil("m9_approuver", "Approuve une demande.", _VIDE, lambda: {}, Autonomie.T1,
          roles_appareil=frozenset({"admin"})),
    Outil("m9_interne", "Outil d'agent, sans déclaration d'appareil.", _VIDE, lambda: {}),
    Outil("m9_payer", "Paie un fournisseur.", _VIDE, lambda: {}, Autonomie.T3),
)
