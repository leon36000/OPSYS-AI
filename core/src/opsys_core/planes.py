"""Planes architecturaux du Core OPSYS-AI (C03-001).

Les 6 planes reliées au Core Kernel, doublement sourcées : le diagramme
d'architecture (sources/continuity/key/69-CORE-ARCHITECTURE-DESIGN-v1.0.0.md
§2, arêtes KERNEL --> EVT/CMF/RAG/TOK/BRICK/OBS) ET les workstreams de
recherche fondatrice correspondants (sources/continuity/key/18-RF01-CORE-
RESEARCH-MAP.md : W1/W3/W4/W5/W7/W9). TRUST (en amont du KERNEL, pas une
arête KERNEL-->) et DATA (arête KERNEL--> mais sans workstream RF01
correspondant) ne sont PAS inclus — non fondés de façon équivalente.
"""
from __future__ import annotations

from enum import Enum


class CorePlane(Enum):
    EVENT_ACTION_FABRIC = "EVENT_ACTION_FABRIC"
    CAPABILITY_MODEL_FABRIC = "CAPABILITY_MODEL_FABRIC"
    RAG_MEMORY_FABRIC = "RAG_MEMORY_FABRIC"
    TOKEN_CONTEXT_CONTROL = "TOKEN_CONTEXT_CONTROL"  # nosec: B105 # nom de plan architectural (Enum), aucun secret, contient "TOKEN" par coïncidence
    FRAMEWORK_BRICK_FABRIC = "FRAMEWORK_BRICK_FABRIC"
    OBSERVABILITY_COST_SLO = "OBSERVABILITY_COST_SLO"
