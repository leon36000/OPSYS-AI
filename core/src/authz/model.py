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
