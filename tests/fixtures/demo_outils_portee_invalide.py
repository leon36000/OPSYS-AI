"""Outils d'un département M9 fictif dont les portées d'appareil sont invalides
(`tests/test_openclaw_roles.py`, T1.4-j) : `opsys verifier` et `openclaw.generer` doivent les refuser,
et `openclaw.roles_outils` ne doit jamais en tirer une portée de plus que les rôles d'appareil
connus, ni un outil T3/N5."""

from __future__ import annotations

from opsys.outils import Autonomie, Niveau, Outil

_VIDE = {"type": "object", "properties": {}, "additionalProperties": False}

OUTILS = (
    Outil("m9_valide", "Déclaration valide (témoin).", _VIDE, lambda: {},
          roles_appareil=frozenset({"employee"})),
    Outil("m9_payer_declare", "Paie (T3) et déclare pourtant des rôles.", _VIDE, lambda: {}, Autonomie.T3,
          roles_appareil=frozenset({"employee", "seller", "admin"})),
    Outil("m9_n5_declare", "T1 mais N5 explicite, et déclare admin.", _VIDE, lambda: {}, Autonomie.T1,
          niveau=Niveau.N5, roles_appareil=frozenset({"admin"})),
    Outil("m9_role_inconnu", "Déclare un rôle qui n'existe pas.", _VIDE, lambda: {},
          roles_appareil=frozenset({"employee", "superviseur"})),
    Outil("m9_role_client", "Déclare client, qui n'est jamais un appareil.", _VIDE, lambda: {},
          roles_appareil=frozenset({"client"})),
    Outil("m9_role_proprietaire", "Déclare nathan_owner, jamais porté par un jeton d'appareil.", _VIDE,
          lambda: {}, roles_appareil=frozenset({"nathan_owner"})),
)
