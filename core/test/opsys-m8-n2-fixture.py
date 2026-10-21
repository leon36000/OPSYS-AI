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


M8_N2_TOOL = "m8_evaluer_qualite_metrique"
M8_ALERT_EVENT = "m8.alerte_proposee"
HANDLER_TRACE = "m8-n2-handler-trace.jsonl"
DISPATCH_TRACE = "m8-n2-dispatches.jsonl"
RESPONSE_LOST = "m8-n2-response-lost.json"
NEGATIVES = "m8-n2-oracle-negatives"


def _arguments_digest(arguments: dict) -> str:
    return hashlib.sha256(json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _append_trace(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"fictif": True, **row}) + "\n")


def _read_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _count_original_m8_handler(trace: Path) -> None:
    """Wrap the real N2 evaluator: record each entry, call the original, record its completion."""
    import dataclasses
    import functools

    import m8_analytics.outils as m8_outils

    trace.touch(mode=0o600, exist_ok=False)
    factory = m8_outils.outils

    def counted(original):
        @functools.wraps(original)
        def handler(**arguments):
            digest = _arguments_digest(arguments)
            _append_trace(trace, {"event": "entered", "arguments_sha256": digest})
            try:
                result = original(**arguments)
            except BaseException as exc:
                _append_trace(trace, {"event": "raised", "arguments_sha256": digest,
                                      "error": type(exc).__name__})
                raise
            # Completion of the original function; its transaction commits after this returns.
            _append_trace(trace, {"event": "completed", "arguments_sha256": digest})
            return result
        return handler

    @functools.wraps(factory)
    def observed_factory(*args, **kwargs):
        tools = tuple(factory(*args, **kwargs))
        if sum(tool.nom == M8_N2_TOOL for tool in tools) != 1:
            raise RuntimeError("fictive handler counter requires the one real M8 N2 evaluator")
        return tuple(dataclasses.replace(tool, fonction=counted(tool.fonction))
                     if tool.nom == M8_N2_TOOL else tool for tool in tools)

    m8_outils.outils = observed_factory


def _alert_identity(arguments: dict, alert_type: str) -> str:
    # Mirrors the native producer identity: metric + alert type + full reference timestamp.
    return f"m8-alerte-{arguments['metric_id']}-{alert_type}-{arguments['horodatage_reference']}"


def _m8_alert_rows(cnx) -> list[dict]:
    from opsys.stockage import codec

    return [{
        "evenement_id": ident, "type_evenement": kind, "producteur": producer,
        "charge": codec.decoder(charge),
        "charge_sha256": hashlib.sha256(charge.encode()).hexdigest(), "cree_le": created,
    } for ident, kind, producer, charge, created in cnx.execute(
        "SELECT evenement_id, type_evenement, producteur, charge, cree_le FROM evenements_sortants "
        "WHERE type_evenement=? ORDER BY cree_le, evenement_id", (M8_ALERT_EVENT,))]


def _committed_m8_response(home: Path, request: dict, start: dict, body: bytes) -> dict:
    """Read the real N2 result and independently verify its commit before losing its transport."""
    import datetime as dt
    import sqlite3
    from contextlib import closing

    headers = dict(start["headers"])
    content_type = headers.get(b"content-type", b"").split(b";", 1)[0]
    text = body.decode("utf-8")
    if content_type == b"application/json":
        messages = [json.loads(text)]
    elif content_type == b"text/event-stream":
        messages = []
        for block in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
            data = [line[5:].removeprefix(" ") for line in block.splitlines() if line.startswith("data:")]
            if data:
                messages.append(json.loads("\n".join(data)))
    else:
        raise RuntimeError("fictive response-loss gate requires actual JSON or SSE")
    responses = [message for message in messages if isinstance(message, dict)
                 and message.get("id") == request["id"] and "id" in message]
    if len(responses) != 1 or responses[0].get("jsonrpc") != "2.0":
        raise RuntimeError("fictive response-loss gate did not observe one matching RPC response")
    response = responses[0]
    result = response.get("result", {})
    if "error" in response or result.get("isError") or start["status"] != 200:
        raise RuntimeError("fictive response-loss gate requires a successful native tool result")
    texts = [item["text"] for item in result.get("content", []) if item.get("type") == "text"]
    if len(texts) != 1:
        raise RuntimeError("fictive response-loss gate requires one native result text")
    native = json.loads(texts[0])
    alerts = [alert["type_alerte"] for alert in native.get("resultat", {}).get("alertes_proposees", [])]
    if native.get("ok") is not True or alerts != ["REJ-QUALITE-DONNEE-PERIMEE"]:
        raise RuntimeError("fictive response-loss gate requires the actual N2 stale-data alert")
    arguments = request["params"]["arguments"]
    handler = _read_trace(home / HANDLER_TRACE)
    digest = _arguments_digest(arguments)
    if [(row["event"], row["arguments_sha256"]) for row in handler] != [("entered", digest), ("completed", digest)]:
        raise RuntimeError("fictive response-loss gate requires one completed original handler entry")
    ident = _alert_identity(arguments, alerts[0])
    # This connection is distinct from the handler's SQLAlchemy transaction/ContextVar.
    with closing(sqlite3.connect((home / "opsys.db").as_uri() + "?mode=ro", uri=True)) as cnx:
        cnx.execute("BEGIN")
        rows = _m8_alert_rows(cnx)
        [approvals] = cnx.execute("SELECT COUNT(*) FROM approbations").fetchone()
    expected = {"evenement_id": ident, "metric_id": arguments["metric_id"], "type_alerte": alerts[0],
                "horodatage_reference": arguments["horodatage_reference"]}
    if (len(rows) != 1 or rows[0]["evenement_id"] != ident or rows[0]["producteur"] != M8
            or any(rows[0]["charge"].get(key) != value for key, value in expected.items())
            or dt.datetime.fromisoformat(rows[0]["cree_le"]).tzinfo is None or approvals != 0):
        raise RuntimeError("fictive response-loss gate cannot prove the independent native commit")
    row = rows[0]
    return {
        "fictif": True, "rpc_id": request["id"], "evenement_id": ident,
        "type_evenement": row["type_evenement"], "producteur": row["producteur"],
        "charge_sha256": row["charge_sha256"], "cree_le": row["cree_le"],
        "handler_events_before_loss": ["entered", "completed"],
        "independent_committed_read_before_headers": True, "response_body_forwarded_bytes": 0,
        "native_response_bytes_buffered": len(body),
    }


def serve_m8_postcommit(port: int) -> None:
    """Serve the real M8 app; lose only the first N2 response body after its independent commit."""
    import uvicorn

    from opsys.serveur_mcp import application_http_departements

    home = Path(os.environ["OPSYS_HOME"]).resolve()
    _count_original_m8_handler(home / HANDLER_TRACE)
    dispatches = home / DISPATCH_TRACE
    dispatches.touch(mode=0o600, exist_ok=False)
    stockage.migrer()
    application = application_http_departements(
        charger_departements(), etat.session, os.environ["OPSYS_MCP_JETON"], "127.0.0.1",
        jeton_contexte=os.environ["OPSYS_CONTEXT_MCP_JETON"],
    )
    loss_available = True

    async def observed(scope, receive, send):
        nonlocal loss_available
        body = bytearray()
        selected_request = None
        response_start = None
        response_body = bytearray()
        route = scope["type"] == "http" and scope["path"].rstrip("/") == "/mcp/" + M8
        if route and scope["method"] != "POST":
            # Standalone SSE/session traffic is recorded apart from business tools/call.
            _append_trace(dispatches, {"http": scope["method"]})

        async def receive_observed():
            nonlocal selected_request, loss_available
            message = await receive()
            if route and scope["method"] == "POST" and message["type"] == "http.request":
                body.extend(message.get("body", b""))
                if len(body) > 64 * 1024:
                    raise RuntimeError("bounded fictive M8 request exceeded fixture limit")
                if not message.get("more_body", False):
                    request = json.loads(body)
                    request = request if isinstance(request, dict) else {}
                    params = request.get("params") if isinstance(request.get("params"), dict) else {}
                    tool = params.get("name") if request.get("method") == "tools/call" else None
                    selected = False
                    if tool == M8_N2_TOOL and loss_available:
                        if request.get("id") is None:
                            raise RuntimeError("fictive response-loss gate requires the actual RPC id")
                        selected_request = request
                        selected = True
                        # A single owned request consumes the gate, even if its instrumentation fails.
                        loss_available = False
                    # Only RPC correlation is logged, never headers, tokens or arguments.
                    _append_trace(dispatches, {"http": "POST", "method": request.get("method"),
                                               "rpc_id": request.get("id"), "tool": tool,
                                               "loss_selected": selected})
            return message

        async def send_observed(message):
            nonlocal response_start
            if selected_request is None:
                await send(message)
                return
            if message["type"] == "http.response.start":
                if response_start is not None:
                    raise RuntimeError("duplicate fictive response start")
                response_start = {**message, "headers": list(message.get("headers", []))}
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))
                if len(response_body) > 64 * 1024:
                    raise RuntimeError("bounded fictive M8 response exceeded fixture limit")
                if not message.get("more_body", False):
                    if response_start is None:
                        raise RuntimeError("fictive response-loss gate has no original headers")
                    proof = _committed_m8_response(home, selected_request, response_start, bytes(response_body))
                    # Sending the real headers before the exception makes Uvicorn close TCP,
                    # rather than substitute an HTTP500. No tool-result body crosses this seam.
                    await send(response_start)
                    with (home / RESPONSE_LOST).open("x", encoding="utf-8") as stream:
                        stream.write(json.dumps({**proof, "original_headers_forwarded": True}) + "\n")
                    raise RuntimeError("FICTIVE_M8_RESPONSE_LOST_AFTER_NATIVE_COMMIT")
            else:
                raise RuntimeError("unexpected fictive ASGI response message")

        await application(scope, receive_observed, send_observed)

    uvicorn.run(observed, host="127.0.0.1", port=port, log_level="info")


def _database_argument(home: Path, database: Path | None) -> Path:
    path = (database or home / "opsys.db").resolve()
    if path != home / "opsys.db" and not path.is_relative_to(home / NEGATIVES):
        raise RuntimeError("inspector reads only this fixture's database or its disposable snapshots")
    return path


def inspect_m8_events(database: Path | None) -> None:
    """Complete committed M8 alert/handler/dispatch state through a new read-only SQLite connection."""
    import sqlite3
    from contextlib import closing

    home = Path(os.environ["OPSYS_HOME"]).resolve()
    path = _database_argument(home, database)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as cnx:
        cnx.execute("BEGIN")
        alerts = _m8_alert_rows(cnx)
        [events] = cnx.execute("SELECT COUNT(*) FROM evenements_sortants").fetchone()
        approvals = [list(row) for row in cnx.execute(
            "SELECT id, departement, outil, statut FROM approbations ORDER BY cree_le")]
    print(json.dumps({
        "fictif": True, "alerts": alerts, "events_total": events, "approvals": approvals,
        "handler": _read_trace(home / HANDLER_TRACE) if (home / HANDLER_TRACE).exists() else [],
        "dispatches": _read_trace(home / DISPATCH_TRACE) if (home / DISPATCH_TRACE).exists() else [],
    }))


def snapshot_negatives(evenement_id: str) -> None:
    """Disposable copies with a duplicate, altered payload and altered date; never the live database."""
    import sqlite3
    from contextlib import closing

    from opsys.stockage import codec

    home = Path(os.environ["OPSYS_HOME"]).resolve()
    directory = home / NEGATIVES
    directory.mkdir(mode=0o700)
    paths = {}
    for name in ("duplicate", "payload", "date"):
        path = directory / f"{name}.db"
        with (closing(sqlite3.connect((home / "opsys.db").as_uri() + "?mode=ro", uri=True)) as source,
              closing(sqlite3.connect(path)) as copy):
            source.backup(copy)
            [(charge, created)] = copy.execute(
                "SELECT charge, cree_le FROM evenements_sortants WHERE evenement_id=? AND type_evenement=?",
                (evenement_id, M8_ALERT_EVENT)).fetchall()
            if name == "duplicate":
                copy.execute("INSERT INTO evenements_sortants (evenement_id, type_evenement, producteur, "
                             "charge, cree_le) VALUES (?, ?, ?, ?, ?)",
                             ("fictif-duplicate-" + hashlib.sha256(evenement_id.encode()).hexdigest()[:16],
                              M8_ALERT_EVENT, M8, charge, created))
            elif name == "payload":
                altered = codec.decoder(charge)
                altered["pourquoi"] = "fictif: altered replay evidence"
                copy.execute("UPDATE evenements_sortants SET charge=? WHERE evenement_id=?",
                             (codec.encoder(altered), evenement_id))
            else:
                copy.execute("UPDATE evenements_sortants SET cree_le=? WHERE evenement_id=?",
                             ("2099-01-01T00:00:00+00:00", evenement_id))
            copy.commit()
        paths[name] = str(path)
    print(json.dumps({"fictif": True, "snapshots": paths}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=(
        "prepare-m8", "serve-m8", "inspect-m8", "verify-sql-trace",
        "serve-m8-postcommit", "inspect-m8-events", "snapshot-negatives",
    ))
    parser.add_argument("--port", type=int)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--evenement-id")
    args = parser.parse_args()
    if args.command == "verify-sql-trace":
        verify_sql_trace()
    elif args.command == "prepare-m8":
        prepare_m8()
    elif args.command == "serve-m8":
        if args.port is None:
            raise RuntimeError("serve-m8 requires the owned port")
        serve_m8(args.port)
    elif args.command == "serve-m8-postcommit":
        if args.port is None:
            raise RuntimeError("serve-m8-postcommit requires the owned port")
        serve_m8_postcommit(args.port)
    elif args.command == "inspect-m8-events":
        inspect_m8_events(args.database)
    elif args.command == "snapshot-negatives":
        if not args.evenement_id:
            raise RuntimeError("snapshot-negatives requires the committed event id")
        snapshot_negatives(args.evenement_id)
    else:
        inspect_m8()


if __name__ == "__main__":
    main()
