from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List


class Relation(enum.Enum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"
    ADMIN = "admin"


class ObjectType(enum.Enum):
    DASHBOARD = "dashboard"
    MODULE = "module"
    CHANTIER = "chantier"


@dataclass(frozen=True)
class ObjectRef:
    object_type: ObjectType
    object_id: str
    # identifiant tronqué pour les logs/listes (indice court + hash) — ne révèle JAMAIS l'id complet,
    # même pour un id court, tout en restant corrélable (A3/A4 anti-énumération).
    object_id_tronque: str = field(default="", compare=False, repr=False)

    def __post_init__(self):
        # Calcul automatique du champ tronqué s'il n'a pas été fourni explicitement.
        # Schéma : 4 premiers caractères + "…" -> ne révèle pas l'id complet même pour un id court
        # (un id de 8 chars comme "dash-001" devient "dash…", insuffisant pour l'énumération).
        if not self.object_id_tronque:
            object.__setattr__(self, "object_id_tronque", self.object_id[:4] + "…")

    def get_full_object_id(self) -> str:
        """Retourne l'identifiant complet pour les usages autorisés internes."""
        return self.object_id


@dataclass(frozen=True)
class TenantScope:
    tenant_id: str


@dataclass
class ObjectListing:
    objects: List[ObjectRef] = field(default_factory=list)
    max_results: int = 0

    def __iter__(self):
        return iter(self.objects)

    def __len__(self) -> int:
        return len(self.objects)
