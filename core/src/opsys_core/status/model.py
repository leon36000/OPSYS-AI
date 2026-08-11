"""Modèle de statut de capacité (C03-003).

CapabilityState partage le VOCABULAIRE de CoreStatus (kernel.py, C03-001)
par convention canon (CANON §12 : « every capability exposes explicit
states ») — mais reste un TYPE DISTINCT, pas une réexportation. Décision
tranchée par revue d'architecture AVANT code : les sources ne décident pas
explicitement l'identité de type ; la lecture retenue (la plus sûre selon
l'architecte) évite un couplage status/ -> kernel.py non demandé par le
spec, préservant la coexistence future de deux axes (statut de BOOT du
kernel vs statut de CHAQUE capacité individuelle) qui partagent le
vocabulaire par convention, pas par identité.

CORRECTIF sécurité (revue TRIAD_CONSENSUS de clôture de phase C03,
Qwen3.7-Max, objection MAJEURE confirmée) : `reasons` est un `tuple[str,
...]`, jamais un `list[str]`. `@dataclass(frozen=True)` n'empêche que la
RÉASSIGNATION d'un attribut, pas la mutation du CONTENU d'un attribut
mutable — un `list[str]` restait modifiable via `.append(...)` même sur
une instance « gelée », contournant silencieusement la garantie
d'immuabilité annoncée. `__post_init__` normalise toute séquence reçue
(list, tuple, génératrice) en tuple, pour rester tolérant aux appelants
existants qui construisent encore des listes littérales.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CapabilityState(Enum):
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    BLOCKED_MISSING_PREREQUISITE = "BLOCKED_MISSING_PREREQUISITE"
    BLOCKED_QUALITY_THRESHOLD = "BLOCKED_QUALITY_THRESHOLD"
    BLOCKED_POLICY = "BLOCKED_POLICY"
    UNKNOWN = "UNKNOWN"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class CapabilityStatus:
    capability_id: str
    state: CapabilityState
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # object.__setattr__ : seul moyen licite de normaliser un champ
        # dans __post_init__ d'une dataclass frozen (voir docstring module).
        object.__setattr__(self, "reasons", tuple(self.reasons))
        if self.state != CapabilityState.ACTIVE and not self.reasons:
            raise ValueError(
                f"CapabilityStatus({self.capability_id!r}, {self.state.name}) "
                "sans raison — tout état non ACTIVE exige au moins une raison explicite"
            )
