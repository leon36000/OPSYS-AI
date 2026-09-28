"""Outils M4 de démonstration, pour `tests/test_openclaw_roles.py` (T1.4-c2). Porte un outil T3
(`m4_payer_sous_traitant`) pour vérifier que T3 (= N5) reste exclu d'`employee`/`admin` même s'il
apparaît dans un département de terrain — défense en profondeur, `opsys.openclaw.roles_outils`."""

from __future__ import annotations

from opsys.outils import Autonomie, Outil

_VIDE = {"type": "object", "properties": {}, "additionalProperties": False}

OUTILS = (
    Outil("m4_pointer_entree", "Pointe une entrée terrain.", _VIDE, lambda: {}, Autonomie.T1),
    Outil("m4_payer_sous_traitant", "Paie un sous-traitant.", _VIDE, lambda: {}, Autonomie.T3),
)
