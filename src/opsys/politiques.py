"""Politiques d'autonomie : quand une action exige une approbation humaine.

Trois modes par département :
- ``ombre``     : le département propose, un humain approuve toute écriture (T1 et plus) ;
- ``supervise`` : les écritures internes passent, toute action externe (T2) est approuvée ;
- ``autonome``  : seules les frontières humaines (T3) sont approuvées.
T3 exige TOUJOURS une approbation : paiements, écritures financières, publication,
engagements externes et suppressions ne sont jamais autonomes.
"""

from __future__ import annotations

from .outils import Autonomie

MODES = ("ombre", "supervise", "autonome")

_SEUIL_APPROBATION = {
    "ombre": Autonomie.T1,
    "supervise": Autonomie.T2,
    "autonome": Autonomie.T3,
}
_RANG = {Autonomie.T0: 0, Autonomie.T1: 1, Autonomie.T2: 2, Autonomie.T3: 3}


def valider_mode(mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"mode de département inconnu {mode!r} (attendu : {', '.join(MODES)})")
    return mode


def approbation_requise(autonomie: Autonomie, mode: str) -> bool:
    """Vrai si l'outil de ce niveau doit passer par la file d'approbation dans ce mode."""
    seuil = _SEUIL_APPROBATION[valider_mode(mode)]
    return _RANG[autonomie] >= _RANG[seuil]
