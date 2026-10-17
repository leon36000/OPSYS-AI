"""Local-only fixture for the Core -> real Python HTTP M8 N0/N2 test (fictif: true)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from opsys import etat, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer_atomique

M8 = "m08-analytics"
METRIC_ID = "m4_duree_reelle_minutes"
# Same fictive definition and snapshot as the official SDK proof (tests/test_serveur_mcp.py).
DEFINITION = {
    "metric_id": METRIC_ID,
    "departement_proprietaire": "m04-field-ops",
    "unite": "min",
    "source": "Module M4 — WCT",
    "fraicheur_attendue_jours": 2,
    "regles_qualite": {"plage_min": None, "plage_max": None},
}
SNAPSHOT = {
    "dictionnaire": {"m04-field-ops": {METRIC_ID: {}}},
    "snapshot": {"module_source": "m04-field-ops", "horodatage": "2026-01-01T00:00:00Z",
                 "valeurs": {METRIC_ID: "42"}},
    "metric_ids": [METRIC_ID],
    "horodatage_reference": "2026-01-01T00:00:00Z", "n_minimal": 1,
}
SQL_TRACE = "m8-n2-sql-writes.jsonl"


def prepare_m8() -> None:
    """Seed through the real atomic M8 tools only; the N2 evaluator is never called here."""
    stockage.migrer()
    capacites = Capacites(charger_departements(), etat.session, filtre={M8}, appelant=M8)
    for name, arguments in (("m8_enregistrer_definition_metrique", {"definition": DEFINITION}),
                            ("m8_rapport_metriques", SNAPSHOT)):
        result = executer_atomique(capacites.index[name][1], arguments)
        if result.get("ok") is not True:
            raise RuntimeError(f"fictive M8 seed refused by {name}")
    print(json.dumps({"fictif": True, "metric_id": METRIC_ID, "definition": DEFINITION}))


def install_sql_trace(path: Path) -> None:
    """Reject DML/DDL and unclassified SQL, including no-op writes, without storing SQL or parameters."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    path.touch(mode=0o600, exist_ok=False)

    def observe(connection, cursor, statement, parameters, context, executemany):
        operation = statement.lstrip().split(None, 1)[0].upper()
        for flag, verb in (("isinsert", "INSERT"), ("isupdate", "UPDATE"), ("isdelete", "DELETE")):
            if getattr(context, flag, False):
                operation = verb
                break
        if operation not in {"SELECT", "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE"}:
            known_writes = {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}
            # Comments, CTEs and PRAGMAs are deliberately not assumed to be read-only.
            operation = operation if operation in known_writes else "UNKNOWN"
            # Errors propagate through the execution event; a failed observer cannot report zero.
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"fictif": True, "operation": operation}) + "\n")

    event.listen(Engine, "before_cursor_execute", observe)



def verify_sql_trace() -> None:
    """Negative controls: ambiguous no-op writes must be visible despite unchanged rows."""
    from tempfile import TemporaryDirectory

    from sqlalchemy import create_engine

    with TemporaryDirectory(prefix="opsys-m8-trace-oracle-") as directory:
        path = Path(directory) / SQL_TRACE
        install_sql_trace(path)
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE fictif (id INTEGER)")
                baseline = path.read_text()
                connection.exec_driver_sql("SELECT * FROM fictif").all()
                if path.read_text() != baseline:
                    raise AssertionError("read-only SELECT was reported as a write")
                connection.exec_driver_sql("/* fictif no-op */ UPDATE fictif SET id = 1 WHERE 0")
                connection.exec_driver_sql(
                    "WITH fictif_cte AS (SELECT 1) UPDATE fictif SET id = 2 WHERE 0"
                )
                rows = connection.exec_driver_sql("SELECT count(*) FROM fictif").scalar_one()
                tail = path.read_text()[len(baseline):].splitlines()
                operations = [json.loads(line)["operation"] for line in tail]
                if operations != ["UNKNOWN", "UNKNOWN"] or rows != 0:
                    raise AssertionError("ambiguous no-op writes escaped the SQL observer")
        finally:
            engine.dispose()
    print(json.dumps({"fictif": True, "readonly_select_observations": 0,
                      "ambiguous_noop_write_observations": operations,
                      "rows_after_noop_writes": rows}))


def serve_m8(port: int) -> None:
    import uvicorn

    from opsys.serveur_mcp import application_http_departements

    install_sql_trace(Path(os.environ["OPSYS_HOME"]) / SQL_TRACE)
    stockage.migrer()
    application = application_http_departements(
        charger_departements(), etat.session, os.environ["OPSYS_MCP_JETON"], "127.0.0.1",
        jeton_contexte=os.environ["OPSYS_CONTEXT_MCP_JETON"],
    )
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="info")


def inspect_m8() -> None:
    """Read the whole committed database through a new read-only SQLite connection."""
    import sqlite3
    from contextlib import closing

    from opsys.stockage import codec
    from opsys.stockage.schema import META

    database = Path(os.environ["OPSYS_HOME"]) / "opsys.db"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as cnx:
        cnx.execute("BEGIN")
        schema = cnx.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name",
        ).fetchall()
        tables = [name for kind, name, _, _ in schema if kind == "table"]
        contents = {}
        for name in tables:
            quoted = '"' + name.replace('"', '""') + '"'
            contents[name] = sorted(json.dumps(list(row), default=repr)
                                    for row in cnx.execute(f"SELECT * FROM {quoted}"))
        [schema_version] = cnx.execute("PRAGMA schema_version").fetchone()
        [user_version] = cnx.execute("PRAGMA user_version").fetchone()
        outbox = [{"type_evenement": kind, "producteur": producer, "charge": codec.decoder(charge)}
                  for kind, producer, charge in cnx.execute(
                      "SELECT type_evenement, producteur, charge FROM evenements_sortants ORDER BY cree_le")]
        approvals = [{"id": ident, "departement": department, "outil": tool, "statut": status}
                     for ident, department, tool, status in cnx.execute(
                         "SELECT id, departement, outil, statut FROM approbations ORDER BY cree_le")]
    dump = {"schema": [list(row) for row in schema], "contents": contents,
            "schema_version": schema_version, "user_version": user_version}
    print(json.dumps({
        "fictif": True,
        "database": {
            "digest": hashlib.sha256(json.dumps(dump, sort_keys=True).encode()).hexdigest(),
            "rows": {name: len(rows) for name, rows in contents.items()},
            "schema_version": schema_version,
            "meta_tables_covered": set(META.tables) <= set(tables),
        },
        "outbox": outbox, "approvals": approvals,
    }))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare-m8", "serve-m8", "inspect-m8", "verify-sql-trace"))
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.command == "verify-sql-trace":
        verify_sql_trace()
    elif args.command == "prepare-m8":
        prepare_m8()
    elif args.command == "serve-m8":
        if args.port is None:
            raise RuntimeError("serve-m8 requires the owned port")
        serve_m8(args.port)
    else:
        inspect_m8()


if __name__ == "__main__":
    main()
