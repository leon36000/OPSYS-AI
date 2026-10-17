"""Six oracles PG17 fictifs sur les écritures durables de M3.

Les quatre conflits métier exigent B visible par psycopg AVANT la reprise A.
Le contrôle SQL ne prétend pas prouver la fraîcheur métier. L'adaptateur est
exercé avec deux conflits réels puis son troisième essai, sans stub de requête.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from decimal import Decimal

import psycopg
import pytest
from m3_estimation import devis_durable, outils, registre
from memoire.doubles import postgres_ephemere
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.maillons import EcritureConcurrente, MaillonsDurables

pytestmark = pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
D = "m03-estimation"
T = "2026-09-29T14:00:00-04:00"
MARKER = "oracle_pg_m3_fictif"
WAIT = 12


@pytest.fixture
def base_pg(monkeypatch, tmp_path):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "m3-pg-fictif"))
        monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")
        try:
            stockage.migrer()
            yield url
        finally:
            stockage.liberer()


def _create(devis_id="FICTIF-A", cost="1600.00"):
    return devis_durable.creer_devis(
        devis_id, "FICTIF-LEAD", None,
        [{"description": "FICTIF gouttière alu", "quantite": "1", "unite": "forfait",
          "cout_unitaire": cost, "reference_besoin_materiau": None}],
        "0.25", T, stockage.maillons(D, "devis"),
    )


def _accept(devis_id="FICTIF-A"):
    return devis_durable.marquer_devis_accepte(devis_id, "FICTIF-owner", T, stockage.maillons(D, "devis"))


def _ok(couple):
    value, refusal = couple
    assert refusal is None, refusal
    return value


def _charge(devis_id):
    return {"devis_id": devis_id, "lead_id": "FICTIF-LEAD", "empreinte_marqueur_m2": "a" * 64,
            "niveau_confiance": 0.9, "bareme_version": "FICTIF-v1", "graine_monte_carlo": 7}


def _estimate(devis_id):
    return registre.Registre(stockage.maillons(D, "principal")).ajouter(_charge(devis_id))


def _rows(observer, name):
    return observer.execute(
        "SELECT rang,maillon,cree_le FROM registres_maillons "
        "WHERE departement=%s AND registre=%s ORDER BY rang", (D, name),
    ).fetchall()


def _values(rows):
    return [codec.decoder(row[1]) for row in rows]


def _configure(cnx):
    assert cnx.get_isolation_level() == "READ COMMITTED"
    assert cnx.connection.dbapi_connection.autocommit is False
    cnx.exec_driver_sql("SET LOCAL statement_timeout = '8s'")
    cnx.exec_driver_sql("SET LOCAL lock_timeout = '2s'")
    return cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()


def _interleave(url, monkeypatch, name, operation_a, operations_b, observe_b, *, sql_collision=False,
                success=False):
    """Pause le vrai append A, conserve les exceptions du thread, témoigne chaque commit B.

    L'exception attendue sort de la transaction RACINE A, annulant son marqueur.
    Le timeout est uniquement un échec de coordination et jamais une preuve.
    """
    ready = [threading.Event() for _ in operations_b]
    release = [threading.Event() for _ in operations_b]
    observed = {"append_calls": 0, "ranks": []}
    original = MaillonsDurables.append
    engine = stockage.moteur()

    def pause(rank):
        index = observed["append_calls"]
        observed["append_calls"] += 1
        observed["ranks"].append(rank)
        if index < len(ready):
            ready[index].set()
            assert release[index].wait(WAIT), "barrière non libérée: protocole non concluant"

    def wrapped(self, value, *, rang_attendu=None):
        if (threading.current_thread() is worker
                and (self.departement, self.registre) == (D, name) and not sql_collision):
            assert stockage.connexion_courante() is observed["cnx_a"]
            pause(rang_attendu)
        return original(self, value, rang_attendu=rang_attendu)

    def before_insert(cnx, cursor, statement, parameters, context, executemany):
        if threading.current_thread() is not worker or not context.isinsert:
            return
        params = context.compiled_parameters[0]
        if (params.get("departement"), params.get("registre")) == (D, name):
            assert cnx is observed["cnx_a"]
            pause(params["rang"])

    def write_a():
        try:
            with stockage.transaction() as cnx:
                observed["cnx_a"] = cnx
                observed["pid_a"] = _configure(cnx)
                stockage.maillons(D, MARKER).append({"fictif": True, "acteur": "A"})
                observed["result_a"] = operation_a()
        except BaseException as exc:  # Transport vers le parent, jamais accepté comme succès.
            observed["exception"] = exc
        finally:
            for signal in ready:
                signal.set()

    worker = threading.Thread(target=write_a, name="m3-pg-A-fictif")
    monkeypatch.setattr(MaillonsDurables, "append", wrapped)
    if sql_collision:
        event.listen(engine, "before_cursor_execute", before_insert)
    snapshots = []
    try:
        assert stockage.connexion_courante() is None
        with psycopg.connect(url, autocommit=True) as witness:
            witness.execute("SET statement_timeout = '3s'")
            pid_c = witness.execute("SELECT pg_backend_pid()").fetchone()[0]
            assert witness.execute("SHOW transaction_isolation").fetchone()[0] == "read committed"
            baseline = _rows(witness, name)
            worker.start()
            for index, operation_b in enumerate(operations_b):
                assert ready[index].wait(WAIT), "append natif A non atteint: protocole non concluant"
                if "exception" in observed:
                    raise observed["exception"]
                assert len(observed["ranks"]) == index + 1
                with stockage.transaction() as cnx_b:
                    pid_b = _configure(cnx_b)
                    assert len({pid_c, pid_b, observed["pid_a"]}) == 3
                    operation_b()
                # B a quitté sa transaction; C est native, indépendante et sans transaction OPSYS.
                assert stockage.connexion_courante() is None
                rows = _rows(witness, name)
                assert rows[:len(baseline)] == baseline
                assert len(rows) == len(baseline) + index + 1
                assert _rows(witness, MARKER) == [], "écriture A non commit ne doit pas être visible"
                observe_b(index, _values(rows))  # contenu exact B AVANT libération A
                snapshots.append(rows)
                release[index].set()
                if index + 1 < len(operations_b):
                    assert ready[index + 1].wait(WAIT), "second append A non atteint"
            worker.join(WAIT)
            assert not worker.is_alive(), "worker A non arrêté"
            if success:
                if "exception" in observed:
                    raise observed["exception"]
                assert len(_rows(witness, MARKER)) == 1
                assert _rows(witness, name)[:len(snapshots[-1])] == snapshots[-1]
            else:
                error = observed.get("exception")
                if error is not None and type(error) is not EcritureConcurrente:
                    raise error
                assert type(error) is EcritureConcurrente, observed
                assert "result_a" not in observed
                assert _rows(witness, MARKER) == [], "le rollback racine A doit annuler son marqueur"
                assert _rows(witness, name) == snapshots[-1], "B doit rester exact après rollback A"
            return observed, snapshots[-1]
    finally:
        for signal in release:
            signal.set()
        try:
            if worker.ident is not None:
                worker.join(WAIT)
        finally:
            # Restaurer même si join échoue; l'exception initiale garde son contexte.
            try:
                monkeypatch.setattr(MaillonsDurables, "append", original)
            finally:
                if sql_collision:
                    event.remove(engine, "before_cursor_execute", before_insert)
        assert not worker.is_alive(), "worker possédé A non terminé"


def _one_creation(cost):
    def verify(index, entries):
        assert index == 0
        assert len(entries) == 1
        assert entries[0]["type_entree"] == "devis_cree"
        assert entries[0]["devis_id"] == "FICTIF-A"
        assert entries[0]["cout_total"] == Decimal(cost)
    return verify


def test_creation_identique_refuse_snapshot_puis_rejoue_sans_append(base_pg, monkeypatch):
    _, after_b = _interleave(base_pg, monkeypatch, "devis", lambda: _ok(_create()),
                             [lambda: _ok(_create())], _one_creation("1600.00"))
    with stockage.transaction():
        assert _ok(_create())["prix_total"] == Decimal("2000.00")
    with psycopg.connect(base_pg, autocommit=True) as witness:
        assert _rows(witness, "devis") == after_b


def test_creation_differente_preserve_b_et_reprise_refus_nommee(base_pg, monkeypatch):
    _, after_b = _interleave(base_pg, monkeypatch, "devis", lambda: _ok(_create()),
                             [lambda: _ok(_create(cost="9999.00"))], _one_creation("9999.00"))
    with stockage.transaction():
        value, refusal = _create()
        assert value is None and refusal["code"] == "REJ-DEVIS-ID-DEJA-UTILISE"
    with psycopg.connect(base_pg, autocommit=True) as witness:
        assert _rows(witness, "devis") == after_b


def test_envoi_perime_ne_defait_pas_acceptation_commise(base_pg, monkeypatch):
    with stockage.transaction():
        creation = _ok(_create())

    def send():
        return _ok(devis_durable.marquer_devis_envoye("FICTIF-A", T, stockage.maillons(D, "devis")))

    def verify(index, entries):
        assert index == 0 and [m["statut"] for m in entries] == ["brouillon", "accepte"]
        assert entries[0]["prix_total"] == creation["prix_total"]
        assert entries[1]["approbateur"] == "FICTIF-owner"

    _, after_b = _interleave(base_pg, monkeypatch, "devis", send, [lambda: _ok(_accept())], verify)
    with stockage.transaction():
        value, refusal = devis_durable.marquer_devis_envoye("FICTIF-A", T, stockage.maillons(D, "devis"))
        assert value is None and refusal["code"] == "REJ-DEVIS-TRANSITION-ILLEGALE"
    with psycopg.connect(base_pg, autocommit=True) as witness:
        assert _rows(witness, "devis") == after_b
        assert witness.execute("SELECT count(*) FROM evenements_sortants").fetchone()[0] == 0


def _expected_hash(value):
    # Spécification canonique S008, indépendante des fonctions de hash du produit.
    def normalize(item):
        if isinstance(item, dict):
            return ["__dict__", [[key, normalize(item[key])] for key in sorted(item)]]
        assert item is None or type(item) in (str, int, float, bool)
        return item
    text = json.dumps(normalize(value), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(f"{len(text)}:{text}".encode()).hexdigest()


def _valid_chain(rows, expected_ids):
    values = _values(rows)
    assert [rank for rank, _, _ in rows] == list(range(len(rows)))
    assert [m["rang"] for m in values] == list(range(len(rows)))
    assert [m["charge"]["devis_id"] for m in values] == expected_ids
    for index, maillon in enumerate(values):
        previous = registre.HASH_PREDECESSEUR_INITIAL if index == 0 else values[index - 1]["hash_maillon"]
        assert maillon["hash_precedent"] == previous
        assert maillon["hash_maillon"] == _expected_hash({
            "rang": index, "hash_precedent": previous,
            "charge": maillon["charge"], "cout_reel": maillon["cout_reel"],
        })
    assert registre.Registre(values).valider_chaine() == (True, "")


def test_chaine_estimations_refuse_hash_perime_et_recalcule_reprise(base_pg, monkeypatch):
    with stockage.transaction():
        _ok(_estimate("FICTIF-SEED"))

    def verify(index, entries):
        assert index == 0
        assert [m["charge"]["devis_id"] for m in entries] == ["FICTIF-SEED", "FICTIF-B"]

    _, after_b = _interleave(base_pg, monkeypatch, "principal", lambda: _ok(_estimate("FICTIF-A")),
                             [lambda: _ok(_estimate("FICTIF-B"))], verify)
    _valid_chain(after_b, ["FICTIF-SEED", "FICTIF-B"])
    with stockage.transaction():
        _ok(_estimate("FICTIF-A"))
    with psycopg.connect(base_pg, autocommit=True) as witness:
        rows = _rows(witness, "principal")
        assert rows[:2] == after_b
        _valid_chain(rows, ["FICTIF-SEED", "FICTIF-B", "FICTIF-A"])


def test_collision_sql_meme_rang_est_ecriture_concurrente_specifique(base_pg, monkeypatch):
    def append(actor):
        stockage.maillons(D, "oracle_collision").append({"fictif": True, "acteur": actor})

    def verify(index, entries):
        assert index == 0 and entries == [{"fictif": True, "acteur": "B"}]

    result, after_b = _interleave(base_pg, monkeypatch, "oracle_collision", lambda: append("A"),
                                [lambda: append("B")], verify, sql_collision=True)
    assert isinstance(result["exception"].__cause__, IntegrityError)
    with stockage.transaction():
        append("A")
    with psycopg.connect(base_pg, autocommit=True) as witness:
        rows = _rows(witness, "oracle_collision")
        assert rows[:1] == after_b
        assert _values(rows) == [{"fictif": True, "acteur": "B"}, {"fictif": True, "acteur": "A"}]


def test_adaptateur_trois_essais_reels_autres_devis_et_publication_unique(base_pg, monkeypatch):
    assert outils._ESSAIS_ECRITURE_CONCURRENTE == 3
    with stockage.transaction():
        for name in ["FICTIF-A", "FICTIF-B1", "FICTIF-B2"]:
            _ok(_create(name))

    def verify(index, entries):
        transitions = [m for m in entries if m["type_entree"] == "transition_devis"]
        assert [m["devis_id"] for m in transitions] == ["FICTIF-B1", "FICTIF-B2"][:index + 1]
        assert all(m["statut"] == "accepte" for m in transitions)
        assert len(entries) == 4 + index

    result, after_b = _interleave(
        base_pg, monkeypatch, "devis", lambda: outils.marquer_devis_accepte("FICTIF-A", "FICTIF-owner", T),
        [lambda: _ok(_accept("FICTIF-B1")), lambda: _ok(_accept("FICTIF-B2"))], verify, success=True,
    )
    assert result["append_calls"] == 3 and result["ranks"] == [3, 4, 5]
    assert result["result_a"]["accepte"] is True
    with psycopg.connect(base_pg, autocommit=True) as witness:
        rows = _rows(witness, "devis")
        assert rows[:5] == after_b and len(rows) == 6
        assert _values(rows)[-1]["devis_id"] == "FICTIF-A"
        assert _values(rows)[-1]["statut"] == "accepte"
        events = witness.execute(
            "SELECT evenement_id,type_evenement,producteur,charge FROM evenements_sortants"
        ).fetchall()
        assert len(events) == 1
        assert events[0][:3] == ("m3-devis-accepte-FICTIF-A", "m3.devis_accepte", D)
        assert codec.decoder(events[0][3])["devis_id"] == "FICTIF-A"
    with stockage.transaction():
        replay = outils.marquer_devis_accepte("FICTIF-A", "FICTIF-owner", T)
        assert replay["accepte"] is False
        assert replay["verdict"]["code"] == "REJ-DEVIS-TRANSITION-ILLEGALE"
    with psycopg.connect(base_pg, autocommit=True) as witness:
        assert _rows(witness, "devis") == rows
        assert witness.execute(
            "SELECT evenement_id,type_evenement,producteur,charge FROM evenements_sortants"
        ).fetchall() == events
