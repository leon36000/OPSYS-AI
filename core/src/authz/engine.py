from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Set, Optional

from authz.model import Relation, ObjectType, ObjectRef, TenantScope, ObjectListing


class AuthzEngine(ABC):
    @abstractmethod
    def add_tuple(self, user: str, relation: Relation, obj: ObjectRef, scope: TenantScope) -> None:
        ...

    @abstractmethod
    def remove_tuple(self, user: str, relation: Relation, obj: ObjectRef, scope: TenantScope) -> None:
        ...

    @abstractmethod
    def check(self, user: Optional[str], permission: str, obj: ObjectRef, scope: TenantScope) -> bool:
        ...

    @abstractmethod
    def list_objects(self, user: str, permission: str, scope: TenantScope) -> ObjectListing:
        ...


# Hiérarchie explicite : owner -> editor -> viewer
# Admin ne fait pas partie de la hiérarchie d’implication, mais est traité comme
# une relation suffisante pour les permissions (sauf voir_couts où seules owner/admin comptent).
RELATION_IMPLIES: dict[Relation, set[Relation]] = {
    Relation.OWNER:  {Relation.OWNER, Relation.EDITOR, Relation.VIEWER},
    Relation.EDITOR: {Relation.EDITOR, Relation.VIEWER},
    Relation.VIEWER: {Relation.VIEWER},
    Relation.ADMIN:  {Relation.ADMIN},
}

# Permissions → ensemble de relations de base autorisées.
# La résolution effective tient compte de RELATION_IMPLIES.
_PERMISSION_RELATIONS: dict[str, set[Relation]] = {
    "lire":        {Relation.VIEWER, Relation.EDITOR, Relation.OWNER, Relation.ADMIN},
    "ecrire":      {Relation.EDITOR, Relation.OWNER, Relation.ADMIN},
    "administrer": {Relation.OWNER, Relation.ADMIN},
    "voir_couts":  {Relation.OWNER, Relation.ADMIN},   # D-010 : employé ne voit jamais les coûts
}


class LocalAuthzEngine(AuthzEngine):
    """Moteur local en mémoire, deny-by-default, fail-closed."""

    def __init__(self) -> None:
        self._tuples: set[tuple[str, str, str, str, str]] = set()
        # tuple : (user, relation.value, object_type.value, object_id, tenant_id)

    # ------------------------------------------------------------------
    # Gestion des tuples
    # ------------------------------------------------------------------
    def add_tuple(self, user: str, relation: Relation, obj: ObjectRef, scope: TenantScope) -> None:
        if user is None or user == "":
            raise ValueError("user must be a non-empty string")
        rel_str = relation.value
        self._tuples.add((user, rel_str, obj.object_type.value, obj.object_id, scope.tenant_id))

    def remove_tuple(self, user: str, relation: Relation, obj: ObjectRef, scope: TenantScope) -> None:
        if user is None or user == "":
            return
        rel_str = relation.value
        self._tuples.discard((user, rel_str, obj.object_type.value, obj.object_id, scope.tenant_id))

    # ------------------------------------------------------------------
    # Décision
    # ------------------------------------------------------------------
    def check(self, user: Optional[str], permission: str, obj: ObjectRef, scope: TenantScope) -> bool:
        # deny-by-default : entrées invalides → False sans exception
        if not user or not isinstance(user, str) or user.strip() == "":
            return False
        if not permission:
            return False
        if obj is None:
            return False

        allowed_relations = _PERMISSION_RELATIONS.get(permission)
        if not allowed_relations:
            return False

        # Lister les relations que l’utilisateur possède sur cet objet dans ce tenant
        user_relations: set[Relation] = set()
        for (u, rel_str, ot, oid, tid) in self._tuples:
            if u == user and ot == obj.object_type.value and oid == obj.object_id and tid == scope.tenant_id:
                try:
                    rel = Relation(rel_str)
                except ValueError:
                    continue  # relation invalide stockée (ne devrait pas arriver)
                user_relations.add(rel)

        # Transitif via RELATION_IMPLIES
        effective_relations: set[Relation] = set()
        for rel in user_relations:
            effective_relations |= RELATION_IMPLIES.get(rel, {rel})

        # Intersection avec les relations autorisées
        return not effective_relations.isdisjoint(allowed_relations)

    # ------------------------------------------------------------------
    # Listing (borné)
    # ------------------------------------------------------------------
    def list_objects(self, user: str, permission: str, scope: TenantScope) -> ObjectListing:
        if not user or not isinstance(user, str) or user.strip() == "":
            return ObjectListing(objects=[], max_results=0)
        if not permission:
            return ObjectListing(objects=[], max_results=0)

        allowed_relations = _PERMISSION_RELATIONS.get(permission)
        if not allowed_relations:
            return ObjectListing(objects=[], max_results=0)

        objects_set: set[tuple[ObjectType, str]] = set()
        for (u, rel_str, ot, oid, tid) in self._tuples:
            if u == user and tid == scope.tenant_id:
                try:
                    rel = Relation(rel_str)
                except ValueError:
                    continue
                effective_relations = RELATION_IMPLIES.get(rel, {rel})
                if not effective_relations.isdisjoint(allowed_relations):
                    obj_type = ObjectType(ot)
                    objects_set.add((obj_type, oid))

        objects = [ObjectRef(object_type=ot, object_id=oid) for (ot, oid) in sorted(objects_set, key=lambda x: (x[0].value, x[1]))]
        return ObjectListing(objects=objects, max_results=len(objects))
