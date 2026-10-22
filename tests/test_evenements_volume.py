"""Répartition bornée d'un historique fictif, sous le profil SQLite QA de 999 variables."""
from __future__ import annotations

import datetime as dt
import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import event, insert, select

from opsys import stockage
from opsys.evenements import repartir
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

FICTIF = True
T0 = dt.datetime(2026, 10, 22, 11, tzinfo=dt.UTC)


@pytest.fixture
def bus(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "instance-fictive"))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'bus-fictif.db'}")
    stockage.migrer()
    engine = stockage.moteur()
    with engine.connect() as cnx:
        native = cnx.connection.driver_connection
        native.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
        assert native.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER) == 999
    calls = []

    def departement(ident, types):
        def consommer(charge):
            calls.append((charge["message"], ident))
            stockage.maillons(ident, "livraisons-fictives").append({"fictif": True, **charge})
            return {"fictif": True, "livre": charge["message"]}

        return SimpleNamespace(id=ident, evenements_consomme=types,
                               charger_consommateurs=lambda: dict.fromkeys(types, consommer))

    yield engine, calls, departement
    stockage.liberer()


def _semer(engine, ids, *, type_evenement="opsys.demo_complete", recus=(), cree_le=None):
    """Historique synthétique explicite ; aucune ancienne livraison métier n'est rejouée."""
    with engine.begin() as cnx:
        cnx.execute(insert(EVENEMENTS_SORTANTS), [
            {"evenement_id": ident, "type_evenement": type_evenement, "producteur": "qa-fictif",
             "charge": codec.encoder({"message": ident}), "cree_le": cree_le or T0.isoformat()}
            for ident in ids
        ])
        if recus:
            cnx.execute(insert(EVENEMENTS_RECUS), [
                {"evenement_id": ident, "consommateur": consommateur, "statut": statut,
                 "tentatives": 1, "prochaine_tentative": prochaine, "resultat": None,
                 "derniere_erreur": None}
                for ident, consommateur, statut, prochaine in recus
            ])


def test_historique_clos_depasse_borne_sqlite_sans_bloquer_pending(bus):
    engine, calls, departement = bus
    dep = departement("qa-a", ("opsys.demo_complete",))
    anciens = [f"a-{i:04d}" for i in range(1001)]
    _semer(engine, [*anciens, "z-pending"], recus=[
        (ident, dep.id, "traite" if i % 2 else "quarantaine", None)
        for i, ident in enumerate(anciens)
    ])
    assert repartir({dep.id: dep}, limite=1, maintenant=T0.isoformat()) == {
        "livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0,
    }
    assert calls == [("z-pending", dep.id)]
    assert repartir({dep.id: dep}, limite=1, maintenant=T0.isoformat())["livres"] == 0
    assert calls == [("z-pending", dep.id)]


def test_pages_futures_offsets_et_ordre_des_paires_multiconsommateurs(bus):
    engine, calls, departement = bus
    a = departement("qa-a", ("opsys.demo_complete",))
    b = departement("qa-b", ("opsys.demo_complete",))
    deps = {a.id: a, b.id: b}
    futurs = [f"a-{i:04d}" for i in range(301)]
    # 07:00-05:00 est FUTUR (12:00 UTC), malgré son texte inférieur à T0.
    future = "2026-10-22T07:00:00-05:00"
    _semer(engine, futurs, cree_le=(T0 - dt.timedelta(days=1)).isoformat(),
           recus=[(ident, dep.id, "echec", future) for ident in futurs for dep in (a, b)])
    # 12:00+02:00 est DÛ (10:00 UTC), malgré son texte supérieur à T0.
    _semer(engine, ["z-a", "z-b", "z-c"], recus=[
        ("z-a", a.id, "quarantaine", None), ("z-a", b.id, "echec", "2026-10-22T12:00:00+02:00"),
        ("z-b", b.id, "traite", None),
    ])
    params = []

    def observer(cnx, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            params.append(len(parameters))

    event.listen(engine, "before_cursor_execute", observer)
    try:
        assert repartir(deps, limite=3, maintenant=T0.isoformat())["traites"] == 3
        assert calls == [("z-a", b.id), ("z-b", a.id), ("z-c", a.id)]
        assert repartir(deps, limite=2, maintenant=T0.isoformat())["traites"] == 1
        assert calls[-1] == ("z-c", b.id)
    finally:
        event.remove(engine, "before_cursor_execute", observer)
    assert params and max(params) <= 999
    with engine.connect() as cnx:
        apres = cnx.execute(select(EVENEMENTS_RECUS).where(
            EVENEMENTS_RECUS.c.prochaine_tentative == future
        )).mappings().all()
    assert len(apres) == 2 * len(futurs)
    assert all(r["statut"] == "echec" and r["tentatives"] == 1 for r in apres)


def test_recus_clos_ne_sappliquent_quau_type_et_consommateur_abonne(bus):
    engine, calls, departement = bus
    a = departement("qa-a", ("qa.type-a",))
    b = departement("qa-b", ("qa.type-b",))
    _semer(engine, ["a-clos"], type_evenement="qa.type-a", recus=[
        ("a-clos", a.id, "traite", None),
    ])
    _semer(engine, ["b-pending"], type_evenement="qa.type-b", recus=[
        ("b-pending", a.id, "quarantaine", None),
    ])
    assert repartir({a.id: a, b.id: b}, limite=1, maintenant=T0.isoformat())["traites"] == 1
    assert calls == [("b-pending", b.id)]
    assert repartir({a.id: a, b.id: b}, limite=1, maintenant=T0.isoformat())["livres"] == 0
