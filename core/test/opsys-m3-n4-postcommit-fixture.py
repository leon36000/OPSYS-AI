"""Local-only fixture for Core M3 N4 proposal -> owner-device M9 decision over real Python HTTP (fictif: true).

Business data comes only from the canonical M3 N4 helper (`departments/m03-estimation/tests/
envoi_n4_process_fixture.py`): real M2 readiness, real M3 estimation source, immutable draft quote, M10
session link and its independent read-only witness/oracle. The served application is the unmodified
`application_http_departements`; this fixture supplies only a deterministic approval clock, counts entries
of the original M9 decision handler and, when asked, withholds the body of its first native decision
response after an independent commit read. It never fabricates a handler response or committed state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from opsys import stockage

REPO = Path(__file__).resolve().parents[2]
M9 = "m09-strategic-intelligence"
M9_DECIDE = "m9_decider_demande_approbation"
NON_OWNER = "admin-fictif-non-proprietaire"
ROUTES = {
    "/mcp/m03-estimation": "m3",
    "/mcp/contexte/m03-estimation": "context-m3",
    "/mcp/" + M9: "m9",
}
PREPARED = "m3-n4-prepared.json"
HANDLER_TRACE = "m3-n4-m9-handler.jsonl"
DISPATCH_TRACE = "m3-n4-dispatches.jsonl"
RESPONSE_LOST = "m3-n4-m9-response-lost.json"
ORACLE_T0 = "m3-n4-oracle-t0.json"
GATE_REFUSED = "m3-n4-m9-loss-gate-refused.json"
NEGATIVES = "m3-n4-oracle-negatives"


def _helper():
    """The canonical M3 N4 helper module (a script/helper, never a test module) and its M2 readiness fixture."""
    for path in (REPO / "tests" / "fixtures", REPO / "departments" / "m03-estimation" / "tests"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import envoi_n4_process_fixture

    return envoi_n4_process_fixture


def _home() -> Path:
    return Path(os.environ["OPSYS_HOME"]).resolve()


def _arguments_digest(arguments: dict) -> str:
    return hashlib.sha256(json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _append_trace(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"fictif": True, **row}) + "\n")


def _read_trace(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _prepared(home: Path) -> dict:
    return json.loads((home / PREPARED).read_text(encoding="utf-8"))


def _prepare_quote(label: str) -> dict:
    """One canonical sourced draft and its linked M3 agent session, through the existing helper APIs only."""
    m3 = _helper()
    home = _home()
    lead_id = {"A": m3.LEAD_A, "B": m3.LEAD_B}[label]
    devis_id, source_hash = m3._creer_devis_source(lead_id)
    quote = {
        "lead_id": lead_id,
        "devis_id": devis_id,
        "source_hash": source_hash,
        "session_key": m3._lier_session(lead_id),
        "arguments": {"devis_id": devis_id, "contexte_revue": dict(m3.CONTEXTE_REVUE)},
        "devis_avant": m3._resume_devis(m3._etat_devis(devis_id)),
    }
    prepared = _prepared(home)
    if label in prepared["quotes"]:
        raise RuntimeError(f"fictive quote {label} already prepared")
    prepared["quotes"][label] = quote
    staged = home / (PREPARED + ".tmp")
    staged.write_text(json.dumps(prepared), encoding="utf-8")
    staged.replace(home / PREPARED)
    return quote


def prepare() -> None:
    """Owner admin+nathan_owner, an active non-owner admin, and canonical quote A."""
    m3 = _helper()
    from opsys import identite

    home = _home()
    stockage.migrer()
    m3._creer_proprietaire()
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, NON_OWNER, "Admin non propriétaire (fictif)", "un-autre-mot-de-passe-assez-long", ["admin"]
        )
    with (home / PREPARED).open("x", encoding="utf-8") as stream:
        json.dump({"fictif": True, "owner": m3.PROPRIETAIRE, "non_owner": NON_OWNER, "quotes": {}}, stream)
    quote = _prepare_quote("A")
    print(json.dumps({"fictif": True, "owner": m3.PROPRIETAIRE, "non_owner": NON_OWNER, "quote": quote}))


def prepare_b() -> None:
    """A fresh canonical quote B, created only after the original A decision was lost and replayed."""
    print(json.dumps({"fictif": True, "quote": _prepare_quote("B")}))


def _count_original_m9_decision(trace: Path, generation: int) -> None:
    """Wrap the real M9 decision handler: record each entry, call the original, record its outcome."""
    import dataclasses
    import functools

    import m9_strategic_intelligence.outils as m9_outils

    trace.touch(mode=0o600, exist_ok=True)
    factory = m9_outils.outils

    def counted(original):
        @functools.wraps(original)
        def handler(**arguments):
            digest = _arguments_digest(arguments)
            _append_trace(trace, {"generation": generation, "event": "entered", "arguments_sha256": digest})
            try:
                result = original(**arguments)
            except BaseException as exc:
                _append_trace(trace, {"generation": generation, "event": "raised", "arguments_sha256": digest,
                                      "error": type(exc).__name__})
                raise
            verdict = result.get("verdict") if isinstance(result, dict) else None
            # Completion of the original function; the enclosing transaction commits after this returns.
            _append_trace(trace, {
                "generation": generation, "event": "completed", "arguments_sha256": digest,
                "accepte": result.get("accepte") if isinstance(result, dict) else None,
                "verdict": verdict.get("code") if isinstance(verdict, dict) else None,
            })
            return result
        return handler

    @functools.wraps(factory)
    def observed_factory(*args, **kwargs):
        tools = tuple(factory(*args, **kwargs))
        if sum(tool.nom == M9_DECIDE for tool in tools) != 1:
            raise RuntimeError("fictive handler counter requires the one real M9 decision handler")
        return tuple(dataclasses.replace(tool, fonction=counted(tool.fonction))
                     if tool.nom == M9_DECIDE else tool for tool in tools)

    m9_outils.outils = observed_factory


def _native_messages(start: dict, body: bytes) -> list:
    headers = dict(start["headers"])
    content_type = headers.get(b"content-type", b"").split(b";", 1)[0]
    text = body.decode("utf-8")
    if content_type == b"application/json":
        return [json.loads(text)]
    if content_type == b"text/event-stream":
        messages = []
        for block in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
            data = [line[5:].removeprefix(" ") for line in block.splitlines() if line.startswith("data:")]
            if data:
                messages.append(json.loads("\n".join(data)))
        return messages
    raise RuntimeError("fictive response-loss gate requires actual JSON or SSE")


def _active_roles(cnx, person: str) -> list[str]:
    return sorted(role for (role,) in cnx.execute(
        "SELECT r.role FROM roles r JOIN personnes p ON p.identifiant=r.identifiant "
        "WHERE p.identifiant=? AND p.actif=1", (person,)))


def _committed_decision(home: Path, generation: int, request: dict, start: dict, body: bytes) -> dict:
    """Read the real decision result and independently witness its commit before losing its transport."""
    m3 = _helper()
    from opsys.stockage import codec

    responses = [message for message in _native_messages(start, body) if isinstance(message, dict)
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
    arguments = request["params"]["arguments"]
    demande_id = arguments["demande_id"]
    decided = (native.get("resultat") or {}).get("resultat") or {}
    if (native.get("ok") is not True or native.get("rejoue") is not False
            or (native.get("resultat") or {}).get("accepte") is not True
            or decided.get("statut") != "executee" or decided.get("demande_id") != demande_id
            or decided.get("decide_par") != m3.PROPRIETAIRE):
        raise RuntimeError("fictive response-loss gate requires the actual owner decision execution")
    digest = _arguments_digest(arguments)
    handler = [(row["event"], row["arguments_sha256"]) for row in _read_trace(home / HANDLER_TRACE)
               if row["generation"] == generation]
    if handler != [("entered", digest), ("completed", digest)]:
        raise RuntimeError("fictive response-loss gate requires one completed original handler entry")
    # Fresh `mode=ro` SQLite connection, distinct from the handler's SQLAlchemy transaction/ContextVar.
    database = home / "opsys.db"
    etat = m3.temoin_lecture_seule(database)
    rows = [row for row in etat["approbations"] if row["id"] == demande_id]
    if len(rows) != 1:
        raise RuntimeError("fictive response-loss gate cannot read the decided request")
    pending_arguments = json.loads(rows[0]["arguments"])
    [quote] = [q for q in _prepared(home)["quotes"].values() if q["devis_id"] == pending_arguments.get("devis_id")]
    oracle = m3.oracle_avant_perte(etat, {
        "demande": {"demande_id": demande_id}, "devis_id": quote["devis_id"], "lead_id": quote["lead_id"],
        "arguments": pending_arguments, "source_hash": quote["source_hash"],
    })
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as cnx:
        roles = _active_roles(cnx, m3.PROPRIETAIRE)
    approval = oracle["approbation"]
    if (pending_arguments != quote["arguments"] or approval["decide_par"] != m3.PROPRIETAIRE
            or approval["decide_role"] != "nathan_owner" or decided.get("decide_le") != oracle["t0"]
            or not {"admin", "nathan_owner"} <= set(roles)):
        raise RuntimeError("fictive response-loss gate cannot prove the independent native commit")
    # The canonical storage codec keeps Decimal amounts/tuples exact, so later comparisons are byte-faithful.
    frozen = codec.encoder(oracle)
    with (home / ORACLE_T0).open("x", encoding="utf-8") as stream:
        stream.write(frozen)
    return {
        "fictif": True, "generation": generation, "rpc_id": request["id"], "demande_id": demande_id,
        "devis_id": quote["devis_id"], "t0": oracle["t0"], "native_result": native,
        "handler_events_before_loss": ["entered", "completed"], "owner_roles": roles,
        "independent_committed_read_before_headers": True, "response_body_forwarded_bytes": 0,
        "native_response_bytes_buffered": len(body),
        "oracle_sha256": hashlib.sha256(frozen.encode()).hexdigest(),
    }


def _dispatch_row(label: str, request: dict) -> dict:
    """Correlation only: never headers, tokens, private tickets or business arguments."""
    from opsys import liaison_cibles

    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    tool = params.get("name") if request.get("method") == "tools/call" else None
    row = {"route": label, "http": "POST", "method": request.get("method"), "rpc_id": request.get("id"),
           "tool": tool}
    if tool is None:
        return row
    ticket = meta.get("opsys/cibleTicket")
    row["ticket_hash"] = liaison_cibles.empreinte_ticket(ticket) if isinstance(ticket, str) else None
    row["frame"] = {key: meta.get("opsys/" + key) for key in (
        "personne", "role", "appareil", "idempotencyKey", "horodatageAppareil")}
    if label == "context-m3":
        row["issue"] = {key: arguments.get(key) for key in ("agent_id", "cle_session", "affaire_id", "outil")}
    if tool == M9_DECIDE:
        row["arguments_sha256"] = _arguments_digest(arguments)
    return row


def serve(port: int, generation: int, lose_decision: bool) -> None:
    """Serve the real departments app; optionally lose only the first M9 decision body after its commit."""
    import uvicorn

    from opsys import approbations, etat
    from opsys.departements import charger_departements
    from opsys.serveur_mcp import application_http_departements

    # Only the approval clock is controlled. JWT, device validity, idempotency TTL and the independent
    # SQL witness keep their native implementations. A redecision after restart receives T1 and must
    # fail the frozen T0 oracle; a legitimate fresh B decision receives T1 without a wall-clock sleep.
    decision_times = {1: "2026-10-17T12:10:00+00:00", 2: "2026-10-17T12:20:00+00:00"}
    if generation not in decision_times:
        raise ValueError("fictive approval clock requires server generation 1 or 2")

    def approval_clock() -> str:
        return decision_times[generation]

    approbations._maintenant = approval_clock
    home = _home()
    _count_original_m9_decision(home / HANDLER_TRACE, generation)
    dispatches = home / DISPATCH_TRACE
    dispatches.touch(mode=0o600, exist_ok=True)
    stockage.migrer()
    application = application_http_departements(
        charger_departements(), etat.session, os.environ["OPSYS_MCP_JETON"], "127.0.0.1",
        jeton_contexte=os.environ["OPSYS_CONTEXT_MCP_JETON"],
    )
    loss_available = lose_decision

    async def observed(scope, receive, send):
        nonlocal loss_available
        body = bytearray()
        selected_request = None
        response_start = None
        response_body = bytearray()
        label = ROUTES.get(scope["path"].rstrip("/")) if scope["type"] == "http" else None
        if label is not None and scope["method"] != "POST":
            _append_trace(dispatches, {"generation": generation, "route": label, "http": scope["method"]})

        async def receive_observed():
            nonlocal selected_request, loss_available
            message = await receive()
            if label is not None and scope["method"] == "POST" and message["type"] == "http.request":
                body.extend(message.get("body", b""))
                if len(body) > 64 * 1024:
                    raise RuntimeError("bounded fictive request exceeded fixture limit")
                if not message.get("more_body", False):
                    request = json.loads(body)
                    request = request if isinstance(request, dict) else {}
                    row = _dispatch_row(label, request)
                    selected = False
                    if label == "m9" and row["tool"] == M9_DECIDE and loss_available:
                        if request.get("id") is None:
                            raise RuntimeError("fictive response-loss gate requires the actual RPC id")
                        selected_request = request
                        selected = True
                        # A single owned request consumes the gate, even if its instrumentation fails.
                        loss_available = False
                    _append_trace(dispatches, {"generation": generation, **row, "loss_selected": selected})
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
                    raise RuntimeError("bounded fictive M9 response exceeded fixture limit")
                if not message.get("more_body", False):
                    if response_start is None:
                        raise RuntimeError("fictive response-loss gate has no original headers")
                    try:
                        proof = _committed_decision(
                            home, generation, selected_request, response_start, bytes(response_body))
                    except Exception as exc:
                        # The gate refuses to lose an unproven response; the reason is kept for the test.
                        with (home / GATE_REFUSED).open("x", encoding="utf-8") as stream:
                            stream.write(json.dumps({"fictif": True, "error": type(exc).__name__,
                                                     "reason": str(exc)}) + "\n")
                        raise
                    # Sending the real headers before the exception makes Uvicorn close TCP,
                    # rather than substitute an HTTP500. No tool-result body crosses this seam.
                    await send(response_start)
                    with (home / RESPONSE_LOST).open("x", encoding="utf-8") as stream:
                        stream.write(json.dumps({**proof, "original_headers_forwarded": True}) + "\n")
                    raise RuntimeError("FICTIVE_M9_DECISION_RESPONSE_LOST_AFTER_NATIVE_COMMIT")
            else:
                raise RuntimeError("unexpected fictive ASGI response message")

        await application(scope, receive_observed, send_observed)

    uvicorn.run(observed, host="127.0.0.1", port=port, log_level="info")


def _database_argument(home: Path, database: Path | None) -> Path:
    path = (database or home / "opsys.db").resolve()
    if path != home / "opsys.db" and not path.is_relative_to(home / NEGATIVES):
        raise RuntimeError("inspector reads only this fixture's database or its disposable snapshots")
    return path


def _oracle(home: Path) -> dict | None:
    from opsys.stockage import codec

    path = home / ORACLE_T0
    return codec.decoder(path.read_text(encoding="utf-8")) if path.exists() else None


def inspect(database: Path | None, delivered: bool) -> None:
    """Complete committed M3/M9/M2 state through a new read-only SQLite connection, against frozen T0."""
    m3 = _helper()
    from opsys.stockage import codec

    home = _home()
    path = _database_argument(home, database)
    etat = m3.temoin_lecture_seule(path)
    prepared = _prepared(home)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as cnx:
        people = {person: _active_roles(cnx, person) for person in (prepared["owner"], prepared["non_owner"])}
        mutations = [{"appareil": appareil, "cle": cle, "outil": outil, "statut": statut, "recu_le": recu_le,
                      "reponse": codec.decoder(reponse)}
                     for appareil, cle, outil, statut, recu_le, reponse in cnx.execute(
                         "SELECT appareil, cle_idempotence, outil, statut, recu_le, reponse "
                         "FROM mutations_appliquees ORDER BY recu_le, appareil, cle_idempotence")]
    quotes = {}
    for label, quote in prepared["quotes"].items():
        devis_id = quote["devis_id"]
        lines = [m for m in m3.maillons(etat, m3.DEP, "devis") if m.get("devis_id") == devis_id]
        outbox = [r for r in etat["evenements_sortants"]
                  if r["type_evenement"] == m3.TYPE_ENVOYE and m3.charge(r).get("devis_id") == devis_id]
        quotes[label] = {
            "statuses": [m.get("statut") for m in lines],
            "lines": lines,
            "approvals": [r for r in etat["approbations"] if r["outil"] == m3.NOM
                          and json.loads(r["arguments"]).get("devis_id") == devis_id],
            "outbox": outbox,
            "charges": [m3.charge(r) for r in outbox],
            "m2_facts": [m for m in m3.maillons(etat, m3.M2, "devis_envoyes_recus") if m.get("devis_id") == devis_id],
            "received": [{"consommateur": r["consommateur"], "statut": r["statut"], "tentatives": r["tentatives"]}
                         for r in etat["evenements_recus"] if r["evenement_id"] == f"m3-devis-envoye-{devis_id}"],
            "tickets": [{k: r[k] for k in ("ticket_hash", "statut", "demande_id", "cle_session", "affaire_id",
                                           "outil", "empreinte_arguments")}
                        for r in etat["liaisons_tickets"] if r["affaire_id"] == quote["lead_id"]],
        }
    oracle = _oracle(home)
    frozen = None
    if oracle is not None:
        frozen = {key: oracle[key] for key in (
            "t0", "demande_id", "devis_id", "lead_id", "arguments", "source_hash", "approbation",
            "lignes_devis_a", "outbox_a", "ticket_a", "evenement_a", "client_id")}
        prefix = oracle["prefixe"]
        frozen["approvals_equal_t0"] = etat["approbations"] == prefix["approbations"]
        frozen["outbox_equal_t0"] = etat["evenements_sortants"] == prefix["evenements_sortants"]
        frozen["journal_t0_max"] = max((row["id"] for row in prefix["journal"]), default=0)
        frozen["anomalies"] = m3.controler_cible_a(etat, oracle, livre=delivered)
    print(json.dumps({
        "fictif": True,
        "people": people,
        "quotes": quotes,
        "approvals_total": len(etat["approbations"]),
        "events_total": len(etat["evenements_sortants"]),
        "journal": [{k: row[k] for k in ("id", "par", "action", "cible")} for row in etat["journal"]],
        "mutations": mutations,
        "oracle": frozen,
        "handler": _read_trace(home / HANDLER_TRACE),
        "dispatches": _read_trace(home / DISPATCH_TRACE),
    }, default=str))


def dispatch_m2() -> None:
    """The real event dispatcher, twice, to the real durable M2 consumer only."""
    m3 = _helper()
    from m2_revenue_crm import clients
    from m2_revenue_crm import outils as outils_m2

    from opsys import evenements
    from opsys.departements import charger_departements

    departements = charger_departements()
    outils_m2.utiliser_stockage_durable()
    first = evenements.repartir({m3.M2: departements[m3.M2]})
    second = evenements.repartir({m3.M2: departements[m3.M2]})
    with stockage.transaction():
        registre = outils_m2._obtenir_registre()
        owners = {label: clients.client_de_lead(registre, quote["lead_id"])
                  for label, quote in _prepared(_home())["quotes"].items()}
    print(json.dumps({"fictif": True, "first": first, "second": second, "clients": owners}, default=str))


def _alter_source(copy: Path, oracle: dict) -> None:
    from opsys.stockage import codec

    with closing(sqlite3.connect(str(copy), isolation_level=None)) as cnx:
        cnx.execute("BEGIN")
        for rang, texte in cnx.execute(
                "SELECT rang, maillon FROM registres_maillons WHERE departement=? AND registre='devis' ORDER BY rang",
                ("m03-estimation",)).fetchall():
            maillon = codec.decoder(texte)
            if maillon.get("devis_id") == oracle["devis_id"] and "estimation_source_hash" in maillon:
                cnx.execute("UPDATE registres_maillons SET maillon=? WHERE departement=? AND registre='devis' "
                            "AND rang=?", (codec.encoder({**maillon, "estimation_source_hash": "0" * 64}),
                                           "m03-estimation", rang))
        cnx.execute("COMMIT")


def _duplicate_outbox(copy: Path, oracle: dict) -> None:
    with closing(sqlite3.connect(str(copy), isolation_level=None)) as cnx:
        cnx.row_factory = sqlite3.Row
        cnx.execute("BEGIN")
        row = dict(cnx.execute("SELECT * FROM evenements_sortants WHERE evenement_id=?",
                               (oracle["evenement_a"],)).fetchone())
        row["evenement_id"] = "fictif-doublon-" + hashlib.sha256(oracle["evenement_a"].encode()).hexdigest()[:16]
        columns = ", ".join(row)
        cnx.execute(f"INSERT INTO evenements_sortants ({columns}) VALUES ({', '.join('?' for _ in row)})",
                    tuple(row.values()))
        cnx.execute("COMMIT")


def snapshot_negatives() -> None:
    """Disposable copies only: an intact control and T0/duplicate/lead/source alterations of target A."""
    m3 = _helper()
    home = _home()
    oracle = _oracle(home)
    if oracle is None:
        raise RuntimeError("negative snapshots require the T0 oracle frozen before the loss")
    directory = home / NEGATIVES
    directory.mkdir(mode=0o700)
    paths = {}
    for name in ("intact", "date_recalculee", "doublon_transition", "doublon_fait_m2", "doublon_outbox",
                 "lead_recalcule", "source_recalculee"):
        copy = m3.copie_jetable(home / "opsys.db", directory / f"{name}.db")
        if name == "source_recalculee":
            _alter_source(copy, oracle)
        elif name == "doublon_outbox":
            _duplicate_outbox(copy, oracle)
        elif name != "intact":
            m3.muter_copie(copy, oracle, name)
        paths[name] = str(copy)
    print(json.dumps({"fictif": True, "snapshots": paths}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=(
        "prepare", "prepare-b", "serve", "inspect", "dispatch-m2", "snapshot-negatives",
    ))
    parser.add_argument("--port", type=int)
    parser.add_argument("--generation", type=int)
    parser.add_argument("--lose-decision", action="store_true")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--delivered", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "prepare-b":
        prepare_b()
    elif args.command == "serve":
        if args.port is None or args.generation is None:
            raise RuntimeError("serve requires the owned port and server generation")
        serve(args.port, args.generation, args.lose_decision)
    elif args.command == "inspect":
        inspect(args.database, args.delivered)
    elif args.command == "dispatch-m2":
        dispatch_m2()
    else:
        snapshot_negatives()


if __name__ == "__main__":
    main()
