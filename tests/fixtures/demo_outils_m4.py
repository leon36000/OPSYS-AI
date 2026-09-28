"""Outils M4 de démonstration, pour `tests/test_openclaw_roles.py` (T1.4-c2, T1.4-j).

Porte un outil T3 (`m4_payer_sous_traitant`) pour vérifier que T3 (= N5) reste exclu de tous les
rôles même dans un département de terrain, et un outil de lecture sans déclaration
(`m4_lire_outbox_gps`, l'analogue de `m4_lire_outbox`) pour vérifier qu'un outil non déclaré n'est
appelable par aucun appareil — `opsys.openclaw.roles_outils`."""

from __future__ import annotations

from opsys.outils import Autonomie, Outil

_VIDE = {"type": "object", "properties": {}, "additionalProperties": False}

OUTILS = (
    Outil("m4_pointer_entree", "Pointe une entrée terrain.", _VIDE, lambda: {}, Autonomie.T1,
          roles_appareil=frozenset({"employee", "admin"})),
    Outil("m4_lire_outbox_gps", "Lit les positions de tous les techniciens.", _VIDE, lambda: {}),
    Outil("m4_payer_sous_traitant", "Paie un sous-traitant.", _VIDE, lambda: {}, Autonomie.T3),
)
