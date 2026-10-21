"""Fictitious Core/M6 persisted PO authority fixture; no supplier contact or payment.

Setup uses public M6 capabilities and canonical approvals, never SQL inserts of
business facts. The manual needs carry fictitious M3 references; this fixture does
not prove an M3 producer/consumer. Original handlers, Core leases and real HTTP
remain in the tested path. The independent committed witness uses SQLite mode=ro.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from opsys import stockage
from opsys.outils import vers_json
from opsys.stockage import codec

REPO = Path(__file__).resolve().parents[2]
M6 = "m06-material-control"
M9 = "m09-strategic-intelligence"
CREATE = "m6_creer_po_brouillon"
APPROVE = "m6_approuver_po"
EMAIL = "m6_generer_courriel_po"
SEND = "m6_marquer_po_envoye"
DECIDE = "m9_decider_demande_approbation"
OWNER = "nathan"
NON_OWNER = "marie-po-fictive"
MANAGER = "manager-po-fictif"
SUPPLIER = "gentek-cf027-fictif"
UNPRICED_SUPPLIER = "sans-prix-cf027-fictif"
GUTTER = "gouttiere-cf027-fictive"
SCREW = "vis-cf027-fictive"
T0 = "2026-10-17T12:10:00+00:00"
T1 = "2026-10-17T12:20:00+00:00"
PREPARED = "m6-po-prepared.json"
HANDLER_TRACE = "m6-po-handlers.jsonl"
DISPATCH_TRACE = "m6-po-dispatches.jsonl"
RESPONSE_LOST = "m6-po-m9-response-lost.json"
GATE_REFUSED = "m6-po-loss-gate-refused.json"
ORACLE = "m6-po-committed-oracle.json"
BASELINE = "m6-po-before-decision.json"
ROUTES = {"/mcp/" + M6: "m6", "/mcp/" + M9: "m9"}


def _home() -> Path:
    return Path(os.environ["OPSYS_HOME"]).resolve()


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _append_trace(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"fictif": True, **row}) + "\n")


def _read_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []


def prepare() -> None:
    """Canonical local setup only; no Core/DEVICE credit is claimed for these calls."""
    from opsys import approbations, identite
    from opsys.capacites import Capacites, outils_executables
    from opsys.departements import lire_manifeste

    stockage.migrer()
    with stockage.transaction() as cnx:
        for person, roles in (
            (OWNER, ["admin", "nathan_owner"]), (NON_OWNER, ["admin"]), (MANAGER, ["manager"]),
        ):
            identite.creer_personne(cnx, person, person + " (fictif)", "mot-de-passe-fictif-assez-long", roles)
    dep = lire_manifeste(REPO / "departments" / M6)
    deps = {M6: dep}
    capabilities = Capacites(deps, stockage.transaction)
    executable = outils_executables(deps, stockage.transaction)
    setup_requests = []

    def admit(name, arguments):
        proposal = capabilities.appeler(name, arguments)
        if proposal.get("statut") != "en_attente_approbation":
            raise RuntimeError("real setup capability did not request canonical approval: " + name)
        with stockage.transaction() as cnx:
            decision = approbations.decider(cnx, proposal["demande_id"], True, OWNER, executable, deps)
        if decision.get("statut") != "executee" or decision["reponse"]["resultat"].get("accepte") is not True:
            raise RuntimeError("real setup capability was not accepted: " + name)
        setup_requests.append(proposal["demande_id"])

    for supplier in (SUPPLIER, UNPRICED_SUPPLIER):
        admit("m6_enregistrer_fournisseur", {
            "fournisseur_id": supplier, "nom": supplier + " (fictif)",
            "courriel_commande": "commandes@fournisseur.exemple-fictif.test",
            "horodatage": "2026-10-01T12:00:00+00:00",
        })
    for material, price, document in ((GUTTER, 12.5, "FACT-PRIX-CF027-FICTIVE"), (SCREW, 0.5, None)):
        admit("m6_enregistrer_prix", {
            "materiau_id": material, "fournisseur_id": SUPPLIER, "prix_unitaire": price,
            "devise": "CAD", "date_effet": "2026-10-01", "source_document": document,
        })
    needs = {
        "chantier_id": "CHANTIER-CF027-FICTIF", "devis_id": "DEVIS-M3-CF027-FICTIF",
        "lignes": [{"materiau_id": GUTTER, "quantite_estimee": 10.0, "unite": "pi"},
                   {"materiau_id": SCREW, "quantite_estimee": 4.0, "unite": "boite"}],
    }
    admit("m6_enregistrer_besoins_prevus", needs)
    prepared = {"fictif": True, "M3_references_fixture_only": True, "setup_requests": setup_requests,
                "needs": needs, "supplier": SUPPLIER, "unpriced_supplier": UNPRICED_SUPPLIER}
    with (_home() / PREPARED).open("x", encoding="utf-8") as stream:
        json.dump(prepared, stream)
    print(json.dumps(prepared))


def _snapshot() -> dict:
    """One independent native connection, one consistent transaction, SELECT-only SQL."""
    with closing(sqlite3.connect((_home() / "opsys.db").as_uri() + "?mode=ro", uri=True)) as cnx:
        cnx.row_factory = sqlite3.Row
        cnx.execute("BEGIN")
        names = [r[0] for r in cnx.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        tables = {}
        for name in names:
            rows = [dict(r) for r in cnx.execute('SELECT * FROM "' + name.replace('"', '""') + '"')]
            tables[name] = sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))
        registers = tables["registres_maillons"]
        po_rows = sorted((r for r in registers if r["departement"] == M6 and r["registre"] == "bons_commande"),
                         key=lambda row: row["rang"])
        people = {p: [r[0] for r in cnx.execute(
            "SELECT r.role FROM roles r JOIN personnes p ON p.identifiant=r.identifiant "
            "WHERE p.identifiant=? AND p.actif=1 ORDER BY r.role", (p,)
        )] for p in (OWNER, NON_OWNER, MANAGER)}
    # Only the PO ledger and canonical control-plane tables can change in this lot.
    protected = {name: _digest(rows) for name, rows in tables.items()
                 if name not in {"registres_maillons", "approbations", "mutations_appliquees", "journal"}}
    protected["registers_except_po"] = _digest([
        r for r in registers if not (r["departement"] == M6 and r["registre"] == "bons_commande")
    ])
    return {"protected": protected, "po_rows": po_rows,
            "po_pieces": [codec.decoder(r["maillon"]) for r in po_rows],
            "approvals": tables["approbations"], "claims": tables["mutations_appliquees"],
            "journal": sorted(tables["journal"], key=lambda row: row["id"]), "people": people,
            "sources": {name: [codec.decoder(r["maillon"]) for r in sorted(registers, key=lambda row: row["rang"])
                               if r["departement"] == M6 and r["registre"] == name]
                        for name in ("besoins_prevus", "fournisseurs", "livre_prix", "principal")},
            "tables": {name: _digest(rows) for name, rows in tables.items()}}


def inspect() -> None:
    home = _home()
    oracle_path = home / ORACLE
    print(json.dumps(vers_json({**_snapshot(), "handler": _read_trace(home / HANDLER_TRACE),
        "dispatches": _read_trace(home / DISPATCH_TRACE),
        "oracle": codec.decoder(oracle_path.read_text()) if oracle_path.exists() else None,
        "origins": {str(g): json.loads((home / f"origins-{g}.json").read_text())
                    for g in (1, 2) if (home / f"origins-{g}.json").exists()}})))


def save_baseline() -> None:
    baseline = {**_snapshot(), "handler_prefix": _read_trace(_home() / HANDLER_TRACE)}
    with (_home() / BASELINE).open("x", encoding="utf-8") as stream:
        stream.write(codec.encoder(baseline))
    print(json.dumps({"fictif": True, "baseline_saved": True}))


def _original_handlers(home: Path, generation: int) -> None:
    import dataclasses
    import functools

    import m6_material_control.outils as m6_tools
    import m9_strategic_intelligence.outils as m9_tools

    def counted(original, name):
        @functools.wraps(original)
        def handler(**arguments):
            common = {"generation": generation, "tool": name, "arguments_sha256": _digest(arguments)}
            _append_trace(home / HANDLER_TRACE, {**common, "event": "entered"})
            try:
                result = original(**arguments)
            except BaseException as exc:
                _append_trace(home / HANDLER_TRACE, {**common, "event": "raised", "error": type(exc).__name__})
                raise
            _append_trace(home / HANDLER_TRACE, {**common, "event": "completed"})
            return result
        return handler

    def instrument(module, names):
        factory = module.outils

        @functools.wraps(factory)
        def observed_factory(*args, **kwargs):
            tools = tuple(factory(*args, **kwargs))
            if any(sum(tool.nom == name for tool in tools) != 1 for name in names):
                raise RuntimeError("fixture requires every original PO/decision handler exactly once")
            return tuple(dataclasses.replace(tool, fonction=counted(tool.fonction, tool.nom))
                         if tool.nom in names else tool for tool in tools)
        module.outils = observed_factory

    instrument(m6_tools, {CREATE, APPROVE, EMAIL, SEND})
    instrument(m9_tools, {DECIDE})


def _origins() -> dict:
    import m6_material_control.outils
    import m9_strategic_intelligence.outils

    import opsys.capacites

    origins = {}
    for module, expected in (
        (opsys.capacites, REPO / "src/opsys/capacites.py"),
        (m6_material_control.outils, REPO / "departments" / M6 / "src/m6_material_control/outils.py"),
        (m9_strategic_intelligence.outils, REPO / "departments" / M9 / "src/m9_strategic_intelligence/outils.py"),
    ):
        actual = Path(module.__file__).resolve()
        if actual != expected.resolve():
            raise RuntimeError("served production module is from another checkout")
        origins[module.__name__] = {"path": str(actual), "sha256": hashlib.sha256(actual.read_bytes()).hexdigest()}
    return origins


def _decision_handler_suffix(prefix, trace, generation, decision_hash, send_hash):
    """Preserve all earlier refusals; require exactly this decision's four new events."""
    if type(prefix) is not list:
        raise RuntimeError("loss gate requires a saved handler trace prefix")
    observed_prefix = trace[:len(prefix)]
    new_events = trace[len(prefix):]
    expected = [
        {"fictif": True, "generation": generation, "tool": tool, "event": event, "arguments_sha256": digest}
        for tool, event, digest in (
            (DECIDE, "entered", decision_hash), (SEND, "entered", send_hash),
            (SEND, "completed", send_hash), (DECIDE, "completed", decision_hash),
        )
    ]
    if observed_prefix != prefix or new_events != expected:
        mismatch = next((index for index, row in enumerate(prefix)
                         if index >= len(observed_prefix) or row != observed_prefix[index]), None)
        diagnostic = {
            "prefix_length": len(prefix), "observed_prefix_length": len(observed_prefix),
            "prefix_unchanged": observed_prefix == prefix, "first_prefix_mismatch_index": mismatch,
            "expected_prefix_event": prefix[mismatch] if mismatch is not None else None,
            "observed_prefix_event": observed_prefix[mismatch]
            if mismatch is not None and mismatch < len(observed_prefix) else None,
            "new_events_count": len(new_events), "new_events_first8": new_events[:8], "expected_new_events": expected,
        }
        raise RuntimeError("loss gate requires unchanged handler prefix and exactly four new original events: "
                           + json.dumps(diagnostic, sort_keys=True))
    return [(row["tool"], row["event"]) for row in new_events]


def _committed_decision(home: Path, generation: int, request: dict, start: dict, body: bytes) -> dict:
    messages = [m for m in _native_messages(start, body) if isinstance(m, dict) and m.get("id") == request["id"]]
    if len(messages) != 1 or messages[0].get("jsonrpc") != "2.0":
        raise RuntimeError("loss gate requires one matching genuine RPC response")
    response = messages[0]
    result = response.get("result", {})
    texts = [c["text"] for c in result.get("content", []) if c.get("type") == "text"]
    if start["status"] != 200 or "error" in response or result.get("isError") or len(texts) != 1:
        raise RuntimeError("loss gate requires successful original MCP output")
    native = json.loads(texts[0])
    decision = native.get("resultat", {}).get("resultat", {})
    request_args = request["params"]["arguments"]
    meta = request["params"]["_meta"]
    ident = request_args["demande_id"]
    if (native.get("ok") is not True or native.get("rejoue") is not False
            or native.get("resultat", {}).get("accepte") is not True
            or decision.get("demande_id") != ident or decision.get("outil") != SEND
            or decision.get("statut") != "executee" or decision.get("decide_par") != OWNER
            or decision.get("role") != "nathan_owner" or decision.get("decide_le") != T0
            or decision.get("issue", {}).get("accepte") is not True):
        raise RuntimeError("loss gate requires original owner PO N4 execution at T0")
    snapshot = _snapshot()
    baseline = codec.decoder((home / BASELINE).read_text())
    [approval] = [row for row in snapshot["approvals"] if row["id"] == ident]
    arguments = json.loads(approval["arguments"])
    [before] = [row for row in baseline["approvals"] if row["id"] == ident]
    original_rows = [r for r in baseline["po_rows"] if codec.decoder(r["maillon"])["po_id"] == arguments["po_id"]]
    rows = [r for r in snapshot["po_rows"] if codec.decoder(r["maillon"])["po_id"] == arguments["po_id"]]
    pieces = [codec.decoder(r["maillon"]) for r in rows]
    if (before["statut"] != "en_attente" or approval["statut"] != "executee"
            or approval["niveau"] != "N4" or approval["outil"] != SEND or approval["departement"] != M6
            or approval["ticket_cible_hash"] is not None or approval["decide_par"] != OWNER
            or approval["decide_role"] != "nathan_owner" or approval["decide_le"] != T0
            or len(original_rows) != 3 or rows[:-1] != original_rows
            or pieces[-1] != {"type_entree": "transition_po", "po_id": arguments["po_id"],
                              "statut": "sent_to_supplier", "horodatage": arguments["horodatage"]}
            or json.loads(approval["resultat"])["resultat"].get("accepte") is not True):
        raise RuntimeError("independent PO transition or approval does not match the original decision")
    [claim] = [r for r in snapshot["claims"] if r["appareil"] == meta["opsys/appareil"]
               and r["cle_idempotence"] == meta["opsys/idempotencyKey"]]
    if (claim["statut"] != "ok" or claim["outil"] != DECIDE
            or {**codec.decoder(claim["reponse"]), "rejoue": False} != native
            or claim["empreinte_arguments"] != _digest(request_args)):
        raise RuntimeError("independent original owner claim was not committed")
    if (snapshot["po_rows"][:-1] != baseline["po_rows"]
            or [r for r in snapshot["approvals"] if r["id"] != ident]
            != [r for r in baseline["approvals"] if r["id"] != ident]
            or [r for r in snapshot["claims"] if r != claim] != baseline["claims"]
            or snapshot["journal"][:-1] != baseline["journal"]
            or len(snapshot["journal"]) != len(baseline["journal"]) + 1
            or any(snapshot["journal"][-1][key] != expected for key, expected in (
                ("par", OWNER), ("action", "approbation.approuver"), ("cible", ident)))):
        raise RuntimeError("PO decision exceeded its exact ledger/approval/claim/audit write set")
    sequence = _decision_handler_suffix(
        baseline.get("handler_prefix"), _read_trace(home / HANDLER_TRACE), generation,
        _digest(request_args), _digest(arguments),
    )
    if (snapshot["protected"] != baseline["protected"] or snapshot["people"] != baseline["people"]
            or snapshot["people"][OWNER] != ["admin", "nathan_owner"]
            or snapshot["people"][NON_OWNER] != ["admin"]):
        raise RuntimeError("PO decision changed protected stock/finance/source or invalidated its owner")
    frozen = {"native_result": native, "demande_id": ident, "po_rows": snapshot["po_rows"],
              "approval": approval, "claim": claim, "protected": snapshot["protected"], "people": snapshot["people"]}
    with (home / ORACLE).open("x", encoding="utf-8") as stream:
        stream.write(codec.encoder(frozen))
    return {"fictif": True, "generation": generation, "native_result": native, "demande_id": ident,
            "independent_committed_read_before_headers": True, "response_body_forwarded_bytes": 0,
            "native_response_bytes_buffered": len(body), "handler_sequence": sequence, "t0": T0}


def _dispatch_row(label: str, request: dict) -> dict:
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    return {"route": label, "method": request.get("method"), "tool": params.get("name"),
            "arguments_sha256": _digest(params.get("arguments", {})),
            "ticket_present": "opsys/cibleTicket" in meta,
            "frame": {k: meta.get("opsys/" + k) for k in (
                "personne", "role", "appareil", "idempotencyKey", "horodatageAppareil")}}


def _native_messages(start: dict, body: bytes) -> list:
    content_type = dict(start["headers"]).get(b"content-type", b"").split(b";", 1)[0]
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
    raise RuntimeError("loss gate requires actual JSON or SSE")


def serve(port: int, generation: int, lose_decision: bool) -> None:
    import uvicorn

    from opsys import approbations, etat
    from opsys.departements import charger_departements
    from opsys.serveur_mcp import application_http_departements

    # Only this module-local approval clock is controlled, as in the Core/AP fixture.
    # A re-executed decision after restart would receive T1, not the committed T0.
    # DEVICE reception, JWT, validity and idempotency clocks retain native behavior.
    def approval_clock() -> str:
        return {1: T0, 2: T1}[generation]

    approbations._maintenant = approval_clock
    home = _home()
    _original_handlers(home, generation)
    (home / f"origins-{generation}.json").write_text(json.dumps(_origins()))
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
                    # Arm only after TS persisted a pending final N4 baseline. Earlier N3
                    # preparation decisions and deliberate authority refusals retain their ACKs.
                    if (label == "m9" and row["tool"] == DECIDE and loss_available
                            and (home / BASELINE).exists()):
                        if request.get("id") is None:
                            raise RuntimeError("loss gate requires the actual RPC id")
                        selected_request = request
                        selected = True
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
                    raise RuntimeError("bounded fictive decision response exceeded fixture limit")
                if not message.get("more_body", False):
                    if response_start is None:
                        raise RuntimeError("loss gate has no original headers")
                    try:
                        proof = _committed_decision(
                            home, generation, selected_request, response_start, bytes(response_body)
                        )
                    except Exception as exc:
                        with (home / GATE_REFUSED).open("x", encoding="utf-8") as stream:
                            json.dump({"fictif": True, "error": type(exc).__name__, "reason": str(exc)}, stream)
                        raise
                    # Original headers, zero business body; raising now closes TCP instead of
                    # replacing the genuinely committed tool response with an HTTP500 body.
                    await send(response_start)
                    with (home / RESPONSE_LOST).open("x", encoding="utf-8") as stream:
                        json.dump({**proof, "original_headers_forwarded": True}, stream)
                    raise RuntimeError("FICTIVE_PO_M9_BODY_LOST_AFTER_NATIVE_COMMIT")
            else:
                raise RuntimeError("unexpected fictive ASGI response message")

        await application(scope, receive_observed, send_observed)

    uvicorn.run(observed, host="127.0.0.1", port=port, log_level="info")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "inspect", "baseline", "serve"))
    parser.add_argument("--port", type=int)
    parser.add_argument("--generation", type=int)
    parser.add_argument("--lose-decision", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "inspect":
        inspect()
    elif args.command == "baseline":
        save_baseline()
    else:
        if args.port is None or args.generation not in (1, 2):
            raise RuntimeError("serve requires an owned port and generation 1 or 2")
        serve(args.port, args.generation, args.lose_decision)


if __name__ == "__main__":
    main()
