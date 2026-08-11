"""Noyau constitutionnel du Core OPSYS-AI (C03-001).

CoreKernel.boot() ne devient JAMAIS ACTIVE sans que TOUS les plans requis
soient explicitement enregistrés — aucun bridage silencieux (canon). Le
statut par défaut d'un CoreKernel fraîchement construit (avant tout boot)
est UNKNOWN, jamais ACTIVE — CANON §12 : « No error, timeout or missing
tool becomes success. »
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .planes import CorePlane


class CoreStatus(Enum):
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    BLOCKED_MISSING_PREREQUISITE = "BLOCKED_MISSING_PREREQUISITE"
    BLOCKED_QUALITY_THRESHOLD = "BLOCKED_QUALITY_THRESHOLD"
    BLOCKED_POLICY = "BLOCKED_POLICY"
    UNKNOWN = "UNKNOWN"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class CoreConfig:
    required_planes: frozenset[CorePlane] = frozenset()
    registered_planes: frozenset[CorePlane] = frozenset()


@dataclass(frozen=True)
class CoreKernel:
    status: CoreStatus = CoreStatus.UNKNOWN

    @staticmethod
    def boot(config: CoreConfig) -> CoreStatus:
        manquantes = config.required_planes - config.registered_planes
        if manquantes:
            return CoreStatus.BLOCKED_MISSING_PREREQUISITE
        return CoreStatus.ACTIVE
