"""Package opsys_core — noyau constitutionnel du Core OPSYS-AI (C03-001).

Aucun effet de bord à l'import (pas de connexion, pas d'I/O, pas de
mutation d'état global) — uniquement des définitions de types.
"""
from __future__ import annotations

from .kernel import CoreConfig, CoreKernel, CoreStatus
from .planes import CorePlane

__all__ = ["CoreConfig", "CoreKernel", "CoreStatus", "CorePlane"]
