import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import logging

import pytest

from authz.domain_api import DomainAuthz
from authz.engine import AuthzEngine, LocalAuthzEngine
from authz.model import (
    ObjectListing,
    ObjectRef,
    ObjectType,
    Relation,
    TenantScope,
)


@pytest.fixture
def tenant_a():
    return TenantScope("tenant-a")


@pytest.fixture
def tenant_b():
    return TenantScope("tenant-b")


@pytest.fixture
def obj_a():
    return ObjectRef(ObjectType.DASHBOARD, "dash-001")


@pytest.fixture
def obj_b():
    return ObjectRef(ObjectType.DASHBOARD, "dash-002")


@pytest.fixture
def engine():
    return LocalAuthzEngine()


@pytest.fixture
def domain(engine):
    return DomainAuthz(engine)


def test_deny_by_default_empty_engine(engine, tenant_a, obj_a):
    assert engine.check("anyone", "lire", obj_a, tenant_a) is False
    assert engine.check("anyone", "ecrire", obj_a, tenant_a) is False
    assert engine.check("anyone", "administrer", obj_a, tenant_a) is False
    assert engine.check("anyone", "voir_couts", obj_a, tenant_a) is False


def test_owner_implies_all_permissions(engine, tenant_a, obj_a):
    engine.add_tuple("alice", Relation.OWNER, obj_a, tenant_a)
    assert engine.check("alice", "lire", obj_a, tenant_a) is True
    assert engine.check("alice", "ecrire", obj_a, tenant_a) is True
    assert engine.check("alice", "administrer", obj_a, tenant_a) is True
    assert engine.check("alice", "voir_couts", obj_a, tenant_a) is True


def test_editor_implies_read_and_write_not_admin(engine, tenant_a, obj_a):
    engine.add_tuple("bob", Relation.EDITOR, obj_a, tenant_a)
    assert engine.check("bob", "lire", obj_a, tenant_a) is True
    assert engine.check("bob", "ecrire", obj_a, tenant_a) is True
    assert engine.check("bob", "administrer", obj_a, tenant_a) is False
    assert engine.check("bob", "voir_couts", obj_a, tenant_a) is False


def test_viewer_implies_read_only(engine, tenant_a, obj_a):
    engine.add_tuple("carol", Relation.VIEWER, obj_a, tenant_a)
    assert engine.check("carol", "lire", obj_a, tenant_a) is True
    assert engine.check("carol", "ecrire", obj_a, tenant_a) is False
    assert engine.check("carol", "administrer", obj_a, tenant_a) is False
    assert engine.check("carol", "voir_couts", obj_a, tenant_a) is False


def test_hierarchy_loop_no_divergence(engine, tenant_a, obj_a):
    engine.add_tuple("dave", Relation.OWNER, obj_a, tenant_a)
    engine.add_tuple("dave", Relation.VIEWER, obj_a, tenant_a)
    assert engine.check("dave", "lire", obj_a, tenant_a) is True
    assert engine.check("dave", "ecrire", obj_a, tenant_a) is True
    assert engine.check("dave", "administrer", obj_a, tenant_a) is True


def test_admin_scoped_to_tenant_no_cross_tenant_elevation(
    engine, tenant_a, tenant_b, obj_a, obj_b
):
    engine.add_tuple("admin-a", Relation.ADMIN, obj_a, tenant_a)
    assert engine.check("admin-a", "lire", obj_a, tenant_a) is True
    assert engine.check("admin-a", "ecrire", obj_a, tenant_a) is True
    assert engine.check("admin-a", "administrer", obj_a, tenant_a) is True
    assert engine.check("admin-a", "lire", obj_b, tenant_b) is False
    assert engine.check("admin-a", "ecrire", obj_b, tenant_b) is False
    assert engine.check("admin-a", "administrer", obj_b, tenant_b) is False


def test_employe_ne_voit_pas_les_couts(domain, engine, tenant_a, obj_a):
    engine.add_tuple("viewer", Relation.VIEWER, obj_a, tenant_a)
    engine.add_tuple("editor", Relation.EDITOR, obj_a, tenant_a)
    engine.add_tuple("owner", Relation.OWNER, obj_a, tenant_a)
    engine.add_tuple("admin", Relation.ADMIN, obj_a, tenant_a)

    assert domain.peut_voir_couts("viewer", obj_a, tenant_a) is False
    assert domain.peut_voir_couts("editor", obj_a, tenant_a) is False
    assert domain.peut_voir_couts("owner", obj_a, tenant_a) is True
    assert domain.peut_voir_couts("admin", obj_a, tenant_a) is True


def test_permission_does_not_leak_across_objects(engine, tenant_a, obj_a, obj_b):
    engine.add_tuple("alice", Relation.OWNER, obj_a, tenant_a)
    assert engine.check("alice", "lire", obj_a, tenant_a) is True
    assert engine.check("alice", "lire", obj_b, tenant_a) is False
    assert engine.check("alice", "ecrire", obj_b, tenant_a) is False


def test_revocation_immediate_no_cache(engine, tenant_a, obj_a):
    engine.add_tuple("alice", Relation.OWNER, obj_a, tenant_a)
    assert engine.check("alice", "lire", obj_a, tenant_a) is True
    engine.remove_tuple("alice", Relation.OWNER, obj_a, tenant_a)
    assert engine.check("alice", "lire", obj_a, tenant_a) is False


@pytest.mark.parametrize("user", [None, "", "unknown"])
def test_malformed_or_unknown_user_returns_false(user, engine, tenant_a, obj_a):
    engine.add_tuple("alice", Relation.OWNER, obj_a, tenant_a)
    assert engine.check(user, "lire", obj_a, tenant_a) is False


def test_user_none_and_empty_distinct_from_unknown(engine, tenant_a, obj_a):
    engine.add_tuple("unknown", Relation.OWNER, obj_a, tenant_a)
    assert engine.check(None, "lire", obj_a, tenant_a) is False
    assert engine.check("", "lire", obj_a, tenant_a) is False
    assert engine.check("unknown", "lire", obj_a, tenant_a) is True


def test_unknown_permission_returns_false(engine, tenant_a, obj_a):
    engine.add_tuple("alice", Relation.OWNER, obj_a, tenant_a)
    assert engine.check("alice", "supprimer", obj_a, tenant_a) is False


def test_unknown_object_returns_false(engine, tenant_a):
    obj = ObjectRef(ObjectType.CHANTIER, "does-not-exist")
    engine.add_tuple("alice", Relation.OWNER, obj, tenant_a)
    other = ObjectRef(ObjectType.CHANTIER, "other-chantier")
    assert engine.check("alice", "lire", other, tenant_a) is False


@pytest.mark.parametrize(
    "object_id",
    [
        "x" * 10000,
        "admin\u200b",
        "../../../etc/passwd",
        "🚀\u202eevil",
        "\u0000\u0001",
    ],
)
def test_payload_object_id_returns_false_without_crash(object_id, engine, tenant_a):
    obj = ObjectRef(ObjectType.MODULE, object_id)
    assert engine.check("anyone", "lire", obj, tenant_a) is False


def test_list_objects_returns_object_listing(engine, tenant_a, tenant_b, obj_a, obj_b):
    engine.add_tuple("alice", Relation.VIEWER, obj_a, tenant_a)
    engine.add_tuple("alice", Relation.VIEWER, obj_b, tenant_b)

    listing = engine.list_objects("alice", "lire", tenant_a)

    assert isinstance(listing, ObjectListing)
    assert hasattr(listing, "max_results")
    assert isinstance(listing.max_results, int)

    objects = getattr(listing, "objects", list(listing))
    assert all(isinstance(o, ObjectRef) for o in objects)
    assert obj_a in objects
    assert obj_b not in objects

    # Vérification renforcée : les identifiants sont tronqués dans l'interface publique
    for o in objects:
        assert hasattr(o, 'object_id_tronque')
        assert '…' in o.object_id_tronque
        assert o.object_id_tronque.endswith('…')
        # L'identifiant complet reste accessible via get_full_object_id()
        assert o.get_full_object_id() == o.object_id


class FakeEngine(AuthzEngine):
    def __init__(self):
        self._allowed = set()

    def add_tuple(self, user, relation, obj, scope):
        self._allowed.add((user, obj.object_id, scope.tenant_id))

    def remove_tuple(self, user, relation, obj, scope):
        self._allowed.discard((user, obj.object_id, scope.tenant_id))

    def check(self, user, permission, obj, scope):
        return (user, obj.object_id, scope.tenant_id) in self._allowed

    def list_objects(self, user, permission, scope):
        return ObjectListing(objects=[], max_results=0)


def test_domain_authz_accepts_fake_engine_without_modification():
    fake = FakeEngine()
    domain = DomainAuthz(fake)
    scope = TenantScope("tenant-fake")
    obj = ObjectRef(ObjectType.DASHBOARD, "fake-dash")

    assert domain.peut_lire("alice", obj, scope) is False
    fake.add_tuple("alice", Relation.VIEWER, obj, scope)
    assert domain.peut_lire("alice", obj, scope) is True


def test_logging_contains_decision_and_reason_but_no_sensitive_data(
    caplog, domain, engine, tenant_a, obj_a
):
    caplog.set_level(logging.INFO)
    engine.add_tuple("alice", Relation.OWNER, obj_a, tenant_a)

    domain.peut_lire("alice", obj_a, tenant_a)
    domain.peut_ecrire("bob", obj_a, tenant_a)

    log_text = caplog.text
    assert "decision" in log_text
    assert "reason_code" in log_text
    assert "alice" not in log_text
    assert "bob" not in log_text
    # l'identifiant complet n'apparaît pas dans les logs (seulement la version tronquée)
    assert obj_a.object_id not in log_text
    assert obj_a.object_id_tronque in log_text


@pytest.mark.parametrize("rel,perms", [
    (Relation.OWNER, {"lire": True, "ecrire": True, "administrer": True, "voir_couts": True}),
    (Relation.EDITOR, {"lire": True, "ecrire": True, "administrer": False, "voir_couts": False}),
    (Relation.VIEWER, {"lire": True, "ecrire": False, "administrer": False, "voir_couts": False}),
    (Relation.ADMIN, {"lire": True, "ecrire": True, "administrer": True, "voir_couts": True}),
])
def test_relation_implies_correct_permissions(engine, tenant_a, obj_a, rel, perms):
    """Couverture explicite de chaque transition d'implication, y compris ADMIN → permissions."""
    engine.add_tuple("user", rel, obj_a, tenant_a)
    for perm, expected in perms.items():
        assert engine.check("user", perm, obj_a, tenant_a) == expected, \
            f"failed for {rel.value} {perm}: expected {expected}"
