import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from authz.engine import AuthzEngine, LocalAuthzEngine
from authz.model import ObjectListing, ObjectRef, ObjectType, Relation, TenantScope


def run_engine_contract(engine_factory):
    scope_a = TenantScope("A")
    scope_b = TenantScope("B")

    obj_owner = ObjectRef(ObjectType.DASHBOARD, "obj-owner")
    obj_editor = ObjectRef(ObjectType.DASHBOARD, "obj-editor")
    obj_viewer = ObjectRef(ObjectType.DASHBOARD, "obj-viewer")
    obj_admin_a = ObjectRef(ObjectType.DASHBOARD, "obj-admin-a")
    obj_admin_b = ObjectRef(ObjectType.DASHBOARD, "obj-admin-b")

    engine = engine_factory()

    # Deny-by-default : moteur vide -> tout refusé
    assert engine.check("nobody", "lire", obj_owner, scope_a) is False
    assert engine.check("nobody", "ecrire", obj_owner, scope_a) is False
    assert engine.check("nobody", "administrer", obj_owner, scope_a) is False

    # Hiérarchie explicite : chaque transition testée
    engine.add_tuple("owner", Relation.OWNER, obj_owner, scope_a)
    engine.add_tuple("editor", Relation.EDITOR, obj_editor, scope_a)
    engine.add_tuple("viewer", Relation.VIEWER, obj_viewer, scope_a)
    engine.add_tuple("admin-a", Relation.ADMIN, obj_admin_a, scope_a)

    assert engine.check("owner", "lire", obj_owner, scope_a) is True
    assert engine.check("owner", "ecrire", obj_owner, scope_a) is True
    assert engine.check("owner", "administrer", obj_owner, scope_a) is True

    assert engine.check("editor", "lire", obj_editor, scope_a) is True
    assert engine.check("editor", "ecrire", obj_editor, scope_a) is True
    assert engine.check("editor", "administrer", obj_editor, scope_a) is False

    assert engine.check("viewer", "lire", obj_viewer, scope_a) is True
    assert engine.check("viewer", "ecrire", obj_viewer, scope_a) is False
    assert engine.check("viewer", "administrer", obj_viewer, scope_a) is False

    # Admin = accès global MAIS scopé au tenant courant (A1)
    assert engine.check("admin-a", "lire", obj_admin_a, scope_a) is True
    assert engine.check("admin-a", "ecrire", obj_admin_a, scope_a) is True
    assert engine.check("admin-a", "administrer", obj_admin_a, scope_a) is True
    assert engine.check("admin-a", "lire", obj_admin_b, scope_b) is False
    assert engine.check("admin-a", "ecrire", obj_admin_b, scope_b) is False
    assert engine.check("admin-a", "administrer", obj_admin_b, scope_b) is False


class FakeEngine(AuthzEngine):
    _PERMISSION_RELATIONS = {
        "lire": {"viewer", "editor", "owner", "admin"},
        "ecrire": {"editor", "owner", "admin"},
        "administrer": {"owner", "admin"},
    }

    def __init__(self):
        self._tuples = set()

    def add_tuple(self, user, relation, obj, scope):
        rel = relation.value if hasattr(relation, "value") else relation
        self._tuples.add((user, rel, obj.object_id, scope.tenant_id))

    def remove_tuple(self, user, relation, obj, scope):
        rel = relation.value if hasattr(relation, "value") else relation
        self._tuples.discard((user, rel, obj.object_id, scope.tenant_id))

    def check(self, user, permission, obj, scope):
        allowed = self._PERMISSION_RELATIONS.get(permission)
        if not allowed:
            return False
        for rel in allowed:
            if (user, rel, obj.object_id, scope.tenant_id) in self._tuples:
                return True
        return False

    def list_objects(self, user, permission, scope):
        return ObjectListing(objects=[], max_results=0)


def test_contract_local_authz_engine():
    run_engine_contract(LocalAuthzEngine)


def test_contract_fake_engine():
    run_engine_contract(FakeEngine)
