"""Four native PostgreSQL17 counter-tests for the durable M2/M3 readiness fence.

Opt-in runner only. No local PostgreSQL or production proof is implied by collection.
Only SQL timing is interposed; business functions, rows and query results are native.
All identities, leads and entries are FICTITIOUS.
"""
from __future__ import annotations

import copy
import importlib.util
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from m2_revenue_crm import outils as m2
from m2_revenue_crm import readiness, statuts
from m2_revenue_crm import registre as registre_m2
from memoire.doubles import postgres_ephemere
from sqlalchemy import event, text

from opsys import stockage
from opsys.stockage.maillons import EcritureConcurrente, _verrouiller_m2_principal

pytestmark = pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL17 réel réservé au job frontiere-postgresql explicite",
)
RACINE = (
    Path(__file__).resolve().parents[2]
    if Path(__file__).resolve().parent.name == "e2e"
    else Path(os.environ["OPSYS_READINESS_TEST_SOURCE"])
)


def _helpers():
    """Reuse the exact native setup already covered by the durable boundary tests."""
    name = "readiness_durable_native_fixture_helpers"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, RACINE / "tests/test_estimation_readiness_m2_durable.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


@pytest.fixture
def base_pg_readiness(monkeypatch, tmp_path):
    # Same explicit native PG17 context manager as test_bus_publication_concurrente.
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "instance-readiness-fictive"))
        monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")
        stockage.migrer()
        try:
            yield
        finally:
            stockage.liberer()


@pytest.fixture
def scenario_pg_readiness(base_pg_readiness, monkeypatch):
    helper = _helpers()
    # pytest's decorator preserves the original fixture function in __wrapped__.
    # Passing the real factory keeps every nested operation in its native ContextVar.
    builder = helper.preparation_m2_m3.__wrapped__
    prep = builder(stockage.transaction, monkeypatch)
    marker_a = helper._accepted(prep["device"]("m2_evaluer_readiness", {
        "lead_id": prep["contracts"]["A"]["lead_id"], "horodatage": helper.H3,
    }, "marker-pg-A", reading=True))["resultat"]
    marker_b = helper._accepted(prep["device"]("m2_evaluer_readiness", {
        "lead_id": prep["contracts"]["B"]["lead_id"], "horodatage": helper.H3,
    }, "marker-pg-B", reading=True))["resultat"]
    with stockage.transaction():
        reg = m2._obtenir_registre()
        assert readiness.verifier_marqueur(marker_a, reg) is True
        assert readiness.verifier_marqueur(marker_b, reg) is True
    state = helper._current(stockage.transaction, prep["contracts"], marker_a, marker_b)
    assert state["admin_active"] and state["owner_active"]
    assert state["A"]["owner"] == state["B"]["owner"] == helper.OWNER
    assert state["A"]["ready"] is True and state["B"]["ready"] is True
    return {**prep, "helper": helper, "markers": {"A": marker_a, "B": marker_b}}


def _timeouts(cnx):
    assert cnx.get_isolation_level() == "READ COMMITTED"
    cnx.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
    cnx.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
    return cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()


def _arguments(prep, label, marker=None):
    return {
        "contrat": copy.deepcopy(prep["contracts"][label]),
        "marqueur": copy.deepcopy(prep["markers"][label] if marker is None else marker),
        "photos": [{"photo_id": "photo-pg-fictive", "resolution_largeur": 3000,
                    "resolution_hauteur": 2000, "eclairage": 7, "angle": "face",
                    "reference_echelle": {"type": "porte", "dimensions_connues": True}}],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": {"version": "2026.1-fictif", "unite": "pi2", "postes": {
            "ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}}},
        "quantite": 1200, "plancher_rentable": 9000, "graine": 42,
    }


def _estimate(prep, arguments):
    return prep["cap3"].appeler_profil_runtime(
        "m3_estimer_projet", arguments, None, None, profile_id=prep["helper"].PROFILE,
        profile_revision=prep["profile"]["revision"], server="opsys_m3",
    )


def _lose_a(prep, key):
    return prep["device"]("m2_transitionner_statut", {
        "lead_id": prep["contracts"]["A"]["lead_id"], "statut_cible": "perdu",
        "horodatage": prep["helper"].H4, "motif": "Clôture FICTIVE après qualification",
    }, key)


def _fresh_b(prep):
    marker = prep["helper"]._accepted(prep["device"]("m2_evaluer_readiness", {
        "lead_id": prep["contracts"]["B"]["lead_id"], "horodatage": prep["helper"].H4,
    }, "marker-pg-B-after-change", reading=True))["resultat"]
    with stockage.transaction():
        assert readiness.verifier_marqueur(marker, m2._obtenir_registre()) is True
    state = prep["helper"]._current(
        stockage.transaction, prep["contracts"], prep["markers"]["A"], marker,
    )
    assert state["admin_active"] and state["owner_active"]
    assert state["A"]["owner"] == state["B"]["owner"] == prep["helper"].OWNER
    assert state["A"]["status"] == "perdu" and state["A"]["verified"] is False
    assert state["B"]["ready"] is True and state["B"]["verified"] is True
    before = prep["helper"]._effects(stockage.transaction)
    prep["helper"]._accepted(_estimate(prep, _arguments(prep, "B", marker)))
    after = prep["helper"]._effects(stockage.transaction)
    assert after["m3_count"] == before["m3_count"] + 1
    assert after["events_sha256"] == before["events_sha256"]


def _worker(name, function, observations):
    def run():
        try:
            function()
        except BaseException as exc:
            observations.setdefault("errors", {})[name] = {"type": type(exc).__name__, "detail": str(exc)}
        finally:
            observations.setdefault("done", {})[name] = True
    return threading.Thread(target=run, name="readiness-pg-" + name + "-fictif")


@contextmanager
def _owned_workers(workers, release_events):
    try:
        yield
    finally:
        for flag in release_events:
            flag.set()
        for worker in workers:
            if worker.ident is not None:
                worker.join(15)
        assert not any(worker.is_alive() for worker in workers), "owned native worker not stopped"


def _wait_for_block(waiter, holder):
    """A third PG connection witnesses a real database lock wait, never a fake rowcount."""
    assert waiter != holder
    with stockage.moteur().connect() as observer:
        pid = _timeouts(observer)
        assert pid not in {waiter, holder}
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            blocking = observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter}).scalar_one()
            if holder in blocking:
                return
            time.sleep(0.02)
        pytest.fail("no actual PostgreSQL blocking relationship observed")


def _assert_closed(observations, *names):
    assert not observations.get("errors"), observations.get("errors")
    assert all(observations.get("done", {}).get(name) for name in names), observations


def test_m3_share_fence_blocks_native_m2_writer_until_estimate_commit(scenario_pg_readiness):
    prep = scenario_pg_readiness
    helper = prep["helper"]
    held = threading.Event()
    b_started = threading.Event()
    release_a = threading.Event()
    observations = {}

    def estimate_a():
        with stockage.transaction() as cnx:
            observations["pid_a"] = _timeouts(cnx)
            observations["a_response"] = _estimate(prep, _arguments(prep, "A"))
            helper._accepted(observations["a_response"])
            observations["effects_a_uncommitted"] = helper._effects(stockage.transaction)
            held.set()
            assert release_a.wait(15), "controlled M3 release not received"

    def lose_a():
        with stockage.transaction() as cnx:
            observations["pid_b"] = _timeouts(cnx)
            b_started.set()
            observations["b_response"] = _lose_a(prep, "pg-share-lose-A")
            helper._accepted(observations["b_response"])

    a = _worker("share-estimate", estimate_a, observations)
    b = _worker("exclusive-writer", lose_a, observations)
    with _owned_workers((a, b), (release_a,)):
        a.start()
        assert held.wait(5), observations
        b.start()
        assert b_started.wait(5), observations
        _wait_for_block(observations["pid_b"], observations["pid_a"])
        assert "b_response" not in observations
        release_a.set()
        a.join(12)
        b.join(12)
    _assert_closed(observations, "share-estimate", "exclusive-writer")
    effects = helper._effects(stockage.transaction)
    assert effects["m3_count"] == 1
    assert effects["m3_sha256"] == observations["effects_a_uncommitted"]["m3_sha256"]
    with stockage.transaction():
        reg = m2._obtenir_registre()
        assert statuts.statut_courant(reg, prep["contracts"]["A"]["lead_id"]) == "perdu"
        assert readiness.verifier_marqueur(prep["markers"]["A"], reg) is False
    refused = _estimate(prep, _arguments(prep, "A"))
    assert helper._refused({"response": refused})
    after = helper._effects(stockage.transaction)
    assert after["m3_sha256"] == effects["m3_sha256"]
    assert after["events_sha256"] == effects["events_sha256"]
    _fresh_b(prep)


def test_native_m2_exclusive_commit_is_seen_by_waiting_profile_estimate(scenario_pg_readiness):
    prep = scenario_pg_readiness
    helper = prep["helper"]
    held = threading.Event()
    a_started = threading.Event()
    release_b = threading.Event()
    observations = {}

    def lose_a():
        with stockage.transaction() as cnx:
            observations["pid_b"] = _timeouts(cnx)
            observations["b_response"] = _lose_a(prep, "pg-exclusive-lose-A")
            helper._accepted(observations["b_response"])
            observations["effects_b"] = helper._effects(stockage.transaction)
            held.set()
            assert release_b.wait(15), "controlled M2 release not received"

    def estimate_a():
        with stockage.transaction() as cnx:
            observations["pid_a"] = _timeouts(cnx)
            a_started.set()
            observations["a_response"] = _estimate(prep, _arguments(prep, "A"))

    b = _worker("exclusive-first", lose_a, observations)
    a = _worker("share-second", estimate_a, observations)
    with _owned_workers((b, a), (release_b,)):
        b.start()
        assert held.wait(5), observations
        a.start()
        assert a_started.wait(5), observations
        _wait_for_block(observations["pid_a"], observations["pid_b"])
        assert "a_response" not in observations
        release_b.set()
        b.join(12)
        a.join(12)
    _assert_closed(observations, "exclusive-first", "share-second")
    assert helper._refused({"response": observations["a_response"]})
    after = helper._effects(stockage.transaction)
    assert after["m3_count"] == 0
    assert after["m3_sha256"] == observations["effects_b"]["m3_sha256"]
    assert after["events_sha256"] == observations["effects_b"]["events_sha256"]
    with stockage.transaction():
        assert readiness.verifier_marqueur(prep["markers"]["A"], m2._obtenir_registre()) is False
    _fresh_b(prep)


def test_two_native_m2_preparations_reject_stale_predecessor_after_real_wait(scenario_pg_readiness):
    prep = scenario_pg_readiness
    helper = prep["helper"]
    a_prepared = threading.Event()
    b_prepared = threading.Event()
    allow_a = threading.Event()
    allow_b = threading.Event()
    a_appended = threading.Event()
    release_a = threading.Event()
    observations = {}
    engine = stockage.moteur()
    with stockage.transaction():
        initial = m2._obtenir_registre().lire()
        initial_head = m2._obtenir_registre().tete()

    def append(label):
        try:
            with stockage.transaction() as cnx:
                observations["pid_" + label] = _timeouts(cnx)
                reg = registre_m2.Registre(stockage.maillons("m02-revenue-crm", "principal"))
                observations["head_" + label] = reg.tete()
                entry = {"type_entree": "interaction", "lead_id": prep["contracts"]["A"]["lead_id"],
                         "auteur": helper.ADMIN, "resume": "Concurrent " + label + " FICTIF",
                         "horodatage": helper.H4}
                observations["ligne_" + label] = reg.ajouter(entry)
                if label == "a":
                    a_appended.set()
                    assert release_a.wait(15), "controlled first writer release not received"
                else:
                    observations["b_unexpected_success"] = True
        except EcritureConcurrente as exc:
            if label != "b":
                raise
            observations["b_refused"] = str(exc)

    a = _worker("producer-a", lambda: append("a"), observations)
    b = _worker("producer-b", lambda: append("b"), observations)

    def before_lock(cnx, cursor, statement, parameters, context, executemany):
        current = threading.current_thread()
        if current not in (a, b) or "pg_advisory_xact_lock(" not in statement.lower():
            return
        label = "a" if current is a else "b"
        if observations.get("interposed_" + label):
            return
        observations["interposed_" + label] = True
        # Registre.ajouter already built the entry and its predecessor before append asks for this lock.
        (a_prepared if label == "a" else b_prepared).set()
        assert (allow_a if label == "a" else allow_b).wait(15), "prepared writer not released"

    event.listen(engine, "before_cursor_execute", before_lock)
    try:
        with _owned_workers((a, b), (allow_a, allow_b, release_a)):
            a.start()
            assert a_prepared.wait(5), observations
            b.start()
            assert b_prepared.wait(5), observations
            assert observations["head_a"] == observations["head_b"] == initial_head
            allow_a.set()
            assert a_appended.wait(5), observations
            allow_b.set()
            _wait_for_block(observations["pid_b"], observations["pid_a"])
            assert "b_refused" not in observations and "b_unexpected_success" not in observations
            release_a.set()
            a.join(12)
            b.join(12)
    finally:
        event.remove(engine, "before_cursor_execute", before_lock)
    _assert_closed(observations, "producer-a", "producer-b")
    assert observations.get("b_refused") and "b_unexpected_success" not in observations
    with stockage.transaction():
        reg = m2._obtenir_registre()
        assert reg.valider_chaine() is True
        rows = reg.lire()
        assert len(rows) == len(initial) + 1
        assert rows[-1]["ligne_id"] == observations["ligne_a"]
        assert rows[-1]["precedent_ligne_id"] == initial_head
        assert not any(row.get("resume") == "Concurrent b FICTIF" for row in rows)


def test_savepoint_rollback_releases_new_transaction_advisory_lock_with_outer_open(base_pg_readiness):
    acquired = threading.Event()
    b_started = threading.Event()
    rollback_savepoint = threading.Event()
    rolled_back = threading.Event()
    b_acquired = threading.Event()
    finish_a = threading.Event()
    finish_b = threading.Event()
    observations = {}

    def holder():
        with stockage.transaction() as cnx:
            observations["pid_a"] = _timeouts(cnx)
            nested = cnx.begin_nested()
            try:
                _verrouiller_m2_principal(cnx, partage=True)
                acquired.set()
                assert rollback_savepoint.wait(15), "savepoint rollback not authorized"
                nested.rollback()
                observations["a_root_still_open"] = cnx.in_transaction()
                rolled_back.set()
                assert finish_a.wait(15), "outer transaction not released"
            finally:
                if nested.is_active:
                    nested.rollback()

    def waiter():
        with stockage.transaction() as cnx:
            observations["pid_b"] = _timeouts(cnx)
            b_started.set()
            _verrouiller_m2_principal(cnx)
            b_acquired.set()
            assert finish_b.wait(15), "second lock holder not released"

    a = _worker("savepoint-holder", holder, observations)
    b = _worker("savepoint-waiter", waiter, observations)
    with _owned_workers((a, b), (rollback_savepoint, finish_a, finish_b)):
        a.start()
        assert acquired.wait(5), observations
        b.start()
        assert b_started.wait(5), observations
        _wait_for_block(observations["pid_b"], observations["pid_a"])
        assert not b_acquired.is_set()
        rollback_savepoint.set()
        assert rolled_back.wait(5) and b_acquired.wait(5), observations
        assert observations["a_root_still_open"] is True
        assert not observations.get("done", {}).get("savepoint-holder")
        with stockage.moteur().connect() as observer:
            observer_pid = _timeouts(observer)
            assert observer_pid not in {observations["pid_a"], observations["pid_b"]}
            a_locks = observer.execute(text(
                "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND pid=:pid AND granted"
            ), {"pid": observations["pid_a"]}).scalar_one()
            b_locks = observer.execute(text(
                "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND pid=:pid AND granted"
            ), {"pid": observations["pid_b"]}).scalar_one()
            assert a_locks == 0 and b_locks >= 1
        finish_b.set()
        finish_a.set()
        a.join(12)
        b.join(12)
    _assert_closed(observations, "savepoint-holder", "savepoint-waiter")


@pytest.mark.parametrize("niveau", ["REPEATABLE READ", "SERIALIZABLE"])
def test_refuse_snapshot_pg_non_courant_sur_connexion_reelle(scenario_pg_readiness, niveau):
    """Même prêt et propriétaire valide, un snapshot non qualifié ne permet aucun effet."""
    prep = scenario_pg_readiness
    helper = prep["helper"]
    before = helper._effects(stockage.transaction)
    with stockage.transaction() as cnx:
        # niveau est exclusivement issu des deux constantes de paramétrage ci-dessus.
        cnx.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL " + niveau)
        assert cnx.get_isolation_level() == niveau
        assert cnx.connection.dbapi_connection.autocommit is False
        assert readiness.verifier_marqueur(prep["markers"]["A"], m2._obtenir_registre()) is True
        response = _estimate(prep, _arguments(prep, "A"))
        assert helper._refused({"response": response}), response
        assert "READ COMMITTED" in str(response), response
    after = helper._effects(stockage.transaction)
    assert after["m3_sha256"] == before["m3_sha256"]
    assert after["events_sha256"] == before["events_sha256"]
    # La même préparation reste utilisable dans une transaction canonique courante.
    helper._accepted(_estimate(prep, _arguments(prep, "B")))
    assert helper._effects(stockage.transaction)["m3_count"] == before["m3_count"] + 1


def test_refuse_autocommit_pg_reel_avant_estimation_durable(scenario_pg_readiness):
    """Le niveau SHOW peut rester READ COMMITTED quand DBAPI autocommit est actif."""
    prep = scenario_pg_readiness
    helper = prep["helper"]
    before = helper._effects(stockage.transaction)
    engine = stockage.moteur()
    engine.update_execution_options(isolation_level="AUTOCOMMIT")
    try:
        with stockage.transaction() as cnx:
            assert cnx.get_isolation_level() == "READ COMMITTED"
            assert cnx.connection.dbapi_connection.autocommit is True
        # Entrée durable directe, sans savepoint préalable qui masquerait cette garde.
        with pytest.raises(ValueError, match="READ COMMITTED sans autocommit"):
            helper.m3.estimer_projet(**_arguments(prep, "A"))
    finally:
        # Option confinée à la fixture : le moteur entier est libéré au teardown.
        engine.update_execution_options(isolation_level="READ COMMITTED")
    after = helper._effects(stockage.transaction)
    assert after["m3_sha256"] == before["m3_sha256"]
    assert after["events_sha256"] == before["events_sha256"]
    helper._accepted(_estimate(prep, _arguments(prep, "B")))
    assert helper._effects(stockage.transaction)["m3_count"] == before["m3_count"] + 1
