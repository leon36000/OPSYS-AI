"""Fictitious Core/M5 AP integration fixture; no external supplier or payment.

The real department application, approval decision and AP append remain unmodified.
Only fixture configuration, the module-local approval clock, handler observation and
an ASGI response-body loss seam are supplied here. Every committed witness opens a
separate SQLite connection in mode=ro, or an independent PostgreSQL17 read-only
transaction. Negative SQL mutations target backups only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from opsys import stockage
from opsys.outils import vers_json
from opsys.stockage import codec

REPO = Path(__file__).resolve().parents[2]
M5 = "m05-financecore"
M5_CORRECT = "m5_corriger_facture_fournisseur"
M9 = "m09-strategic-intelligence"
M9_DECIDE = "m9_decider_demande_approbation"
OWNER = "owner-ap-fictif"
NON_OWNER = "admin-ap-fictif-non-owner"
T0 = "2026-10-17T12:10:00+00:00"
T1 = "2026-10-17T12:20:00+00:00"
ROUTES = {"/mcp/" + M5: "m5", "/mcp/" + M9: "m9"}
PREPARED = "m5-ap-prepared.json"
HANDLER_TRACE = "m5-ap-handlers.jsonl"
DISPATCH_TRACE = "m5-ap-dispatches.jsonl"
RESPONSE_LOST = "m5-ap-m9-response-lost.json"
ORACLE_T0 = "m5-ap-oracle-t0.json"
GATE_REFUSED = "m5-ap-loss-gate-refused.json"
NEGATIVES = "m5-ap-oracle-negatives"


def _home() -> Path:
    return Path(os.environ["OPSYS_HOME"]).resolve()


def _arguments_digest(arguments: dict) -> str:
    return hashlib.sha256(json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _append_trace(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"fictif": True, **row}) + "\n")


def _read_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []


def _prepared(home: Path) -> dict:
    return json.loads((home / PREPARED).read_text())


def _configure() -> None:
    from m5_financecore import outils

    path = _home() / "m5-fixture-configuration.yaml"
    content = "configuration:\n  categories_depense_sans_po: [carburant]\n"
    if path.exists():
        if path.read_text() != content:
            raise RuntimeError("fictive category configuration changed")
    else:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
    outils._MANIFESTE = path
    if not outils._stockage_durable_actif:
        raise RuntimeError("M5 durable storage must be the production default")


def _prepare_invoice(label: str) -> dict:
    from opsys import approbations
    from opsys.capacites import Capacites, outils_executables
    from opsys.departements import lire_manifeste

    home = _home()
    prepared = _prepared(home)
    if label not in ("A", "B") or label in prepared["invoices"]:
        raise RuntimeError("fictive invoice must be prepared once")
    dep = lire_manifeste(REPO / "departments" / M5)
    proposal = Capacites({M5: dep}, stockage.transaction).appeler(
        "m5_saisir_facture_sans_po",
        {
            "fournisseur_id": "fournisseur-ap-fictif-" + label,
            "categorie": "carburant",
            "numero_facture": "FACTURE-AP-FICTIVE-" + label,
            "date_facture": "2026-10-01",
            "montant_avant_taxes": "100.00",
            "total_facture": None,
            "horodatage": "2026-10-01T12:00:00-04:00",
        },
    )
    if proposal.get("statut") != "en_attente_approbation":
        raise RuntimeError("genuine N3 seed did not propose an approval")
    with stockage.transaction() as cnx:
        decision = approbations.decider(
            cnx, proposal["demande_id"], True, OWNER, outils_executables({M5: dep}, stockage.transaction), {M5: dep}
        )
    if decision.get("statut") != "executee" or not decision["reponse"]["resultat"]["accepte"]:
        raise RuntimeError("genuine owner N3 seed did not execute")
    invoice = decision["reponse"]["resultat"]["resultat"]["facture"]
    revision = invoice.get("corrections", 0)
    if invoice.get("statut") != "SAISIE" or type(revision) is not int or revision != 0:
        raise RuntimeError("genuine seed is not an uncorrected invoice")
    item = {
        "id": invoice["facture_fournisseur_id"],
        "seed_demande_id": proposal["demande_id"],
        "arguments": {
            "facture_fournisseur_id": invoice["facture_fournisseur_id"],
            "revision_attendue": revision,
            "motif": "Correction papier fictive " + label,
            "numero_facture": None,
            "date_facture": None,
            "montant_avant_taxes": "310.00" if label == "A" else "320.00",
            "total_facture": None,
            "horodatage": "2026-10-17T11:40:00+00:00" if label == "A" else "2026-10-17T11:45:00+00:00",
        },
    }
    prepared["invoices"][label] = item
    (home / PREPARED).write_text(json.dumps(prepared))
    return item


def prepare() -> None:
    from opsys import identite

    home = _home()
    _configure()
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, OWNER, "Owner AP fictif", "mot-de-passe-fictif-assez-long", ["admin", "nathan_owner"]
        )
        identite.creer_personne(cnx, NON_OWNER, "Admin AP fictif", "autre-mot-de-passe-fictif-long", ["admin"])
    with (home / PREPARED).open("x", encoding="utf-8") as stream:
        json.dump({"fictif": True, "invoices": {}}, stream)
    print(json.dumps({"fictif": True, "invoice": _prepare_invoice("A")}))


def _active_roles(cnx, person: str) -> list[str]:
    return sorted(
        role
        for (role,) in cnx.execute(
            "SELECT r.role FROM roles r JOIN personnes p ON p.identifiant=r.identifiant "
            "WHERE p.identifiant=? AND p.actif=1",
            (person,),
        )
    )


def _snapshot_postgres() -> dict:
    import psycopg
    from psycopg.rows import dict_row

    # Direct driver connection, independent of the application's SQLAlchemy engine/transactions.
    url = os.environ["OPSYS_BASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as cnx:
        cnx.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        try:
            version = int(cnx.execute("SHOW server_version_num").fetchone()["server_version_num"])
            read_only = cnx.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"]
            if not 170000 <= version < 180000 or read_only != "on":
                raise RuntimeError("independent witness requires real PostgreSQL17 read-only transaction")
            tables = {
                name: list(cnx.execute(query).fetchall())
                for name, query in {
                    "ap": (
                        "SELECT * FROM registres_maillons WHERE departement='m05-financecore' "
                        "AND registre='comptes_a_payer' ORDER BY rang"
                    ),
                    "movements": (
                        "SELECT * FROM registres_maillons WHERE departement='m05-financecore' "
                        "AND registre='principal' ORDER BY rang"
                    ),
                    "approvals": "SELECT * FROM approbations ORDER BY id",
                    "claims": "SELECT * FROM mutations_appliquees ORDER BY appareil,cle_idempotence",
                }.items()
            }
            tables["people"] = {
                person: sorted(row["role"] for row in cnx.execute(
                    "SELECT r.role FROM roles r JOIN personnes p ON p.identifiant=r.identifiant "
                    "WHERE p.identifiant=%s AND p.actif=true", (person,)
                ))
                for person in (OWNER, NON_OWNER)
            }
            # schema.py stores arguments/resultat/maillon as Text; retain those exact encoded values.
            # Only cree_le is a native timestamptz here; vers_json preserves its ISO representation.
            tables["witness"] = {"server_version_num": version, "transaction_read_only": read_only}
            return tables
        finally:
            cnx.execute("ROLLBACK")


def _snapshot(database: Path) -> dict:
    if os.environ.get("OPSYS_TEST_M5_AP_PG17_URL_FILE"):
        if database != _home() / "opsys.db":
            raise RuntimeError("PostgreSQL witness cannot inspect SQLite backup oracles")
        return _snapshot_postgres()
    # This connection is independent of the application's transaction and is SELECT-only.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as cnx:
        cnx.row_factory = sqlite3.Row
        cnx.execute("BEGIN")
        tables = {
            name: [dict(row) for row in cnx.execute(query)]
            for name, query in {
                "ap": (
                    "SELECT * FROM registres_maillons WHERE departement='m05-financecore' "
                    "AND registre='comptes_a_payer' ORDER BY rang"
                ),
                "movements": (
                    "SELECT * FROM registres_maillons WHERE departement='m05-financecore' "
                    "AND registre='principal' ORDER BY rang"
                ),
                "approvals": "SELECT * FROM approbations ORDER BY id",
                "claims": "SELECT * FROM mutations_appliquees ORDER BY appareil,cle_idempotence",
            }.items()
        }
        tables["people"] = {p: _active_roles(cnx, p) for p in (OWNER, NON_OWNER)}
    return tables


def _invoice_state(snapshot: dict, item: dict) -> dict:
    rows = [r for r in snapshot["ap"] if codec.decoder(r["maillon"]).get("facture_fournisseur_id") == item["id"]]
    pieces = [codec.decoder(r["maillon"]) for r in rows]
    corrections = [p for p in pieces if p.get("type_entree") == "correction_facture_fournisseur"]
    return {
        "rows": rows,
        "pieces": pieces,
        "corrections": len(corrections),
        "approvals": [
            r
            for r in snapshot["approvals"]
            if r["outil"] == M5_CORRECT and json.loads(r["arguments"]).get("facture_fournisseur_id") == item["id"]
        ],
    }


def _original_handlers(home: Path, generation: int) -> None:
    import dataclasses
    import functools

    import m5_financecore.outils as m5_tools
    import m9_strategic_intelligence.outils as m9_tools

    def instrument(module, name):
        factory = module.outils

        def counted(original):
            @functools.wraps(original)
            def handler(**arguments):
                digest = _arguments_digest(arguments)
                common = {"generation": generation, "tool": name, "arguments_sha256": digest}
                _append_trace(home / HANDLER_TRACE, {**common, "event": "entered"})
                try:
                    result = original(**arguments)
                except BaseException as exc:
                    _append_trace(home / HANDLER_TRACE, {**common, "event": "raised", "error": type(exc).__name__})
                    raise
                _append_trace(home / HANDLER_TRACE, {**common, "event": "completed"})
                return result

            return handler

        @functools.wraps(factory)
        def observed_factory(*args, **kwargs):
            tools = tuple(factory(*args, **kwargs))
            if sum(tool.nom == name for tool in tools) != 1:
                raise RuntimeError("fixture requires one original handler for " + name)
            return tuple(
                dataclasses.replace(tool, fonction=counted(tool.fonction)) if tool.nom == name else tool
                for tool in tools
            )

        module.outils = observed_factory

    instrument(m5_tools, M5_CORRECT)
    instrument(m9_tools, M9_DECIDE)


def _origins() -> dict:
    import m5_financecore.outils
    import m9_strategic_intelligence.outils

    import opsys.capacites

    origins = {}
    for module, expected in (
        (opsys.capacites, REPO / "src/opsys/capacites.py"),
        (m5_financecore.outils, REPO / "departments/m05-financecore/src/m5_financecore/outils.py"),
        (
            m9_strategic_intelligence.outils,
            REPO / "departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils.py",
        ),
    ):
        actual = Path(module.__file__).resolve()
        if actual != expected.resolve():
            raise RuntimeError("served module did not originate in this checkout: " + module.__name__)
        origins[module.__name__] = {"path": str(actual), "sha256": hashlib.sha256(actual.read_bytes()).hexdigest()}
    return origins


def _committed_decision(home: Path, generation: int, request: dict, start: dict, body: bytes) -> dict:
    responses = [
        m for m in _native_messages(start, body) if isinstance(m, dict) and "id" in m and m["id"] == request["id"]
    ]
    if len(responses) != 1 or responses[0].get("jsonrpc") != "2.0":
        raise RuntimeError("loss gate requires one matching genuine RPC result")
    response = responses[0]
    result = response.get("result", {})
    texts = [c["text"] for c in result.get("content", []) if c.get("type") == "text"]
    if start["status"] != 200 or "error" in response or result.get("isError") or len(texts) != 1:
        raise RuntimeError("loss gate requires a native success body")
    native = json.loads(texts[0])
    decided = (native.get("resultat") or {}).get("resultat") or {}
    demande_id = request["params"]["arguments"]["demande_id"]
    if (
        native.get("ok") is not True
        or native.get("rejoue") is not False
        or native.get("resultat", {}).get("accepte") is not True
        or decided.get("demande_id") != demande_id
        or decided.get("statut") != "executee"
        or decided.get("decide_par") != OWNER
        or decided.get("decide_le") != T0
    ):
        raise RuntimeError("loss gate requires a real owner execution at T0")
    prepared = _prepared(home)
    item = prepared["invoices"]["A"]
    snapshot = _snapshot(home / "opsys.db")
    state = _invoice_state(snapshot, item)
    approvals = [r for r in state["approvals"] if r["id"] == demande_id]
    corrections = [p for p in state["pieces"] if p.get("type_entree") == "correction_facture_fournisseur"]
    handlers = [r for r in _read_trace(home / HANDLER_TRACE) if r["generation"] == generation]
    sequence = [(r["tool"], r["event"]) for r in handlers]
    if sequence != [
        (M9_DECIDE, "entered"),
        (M5_CORRECT, "entered"),
        (M5_CORRECT, "completed"),
        (M9_DECIDE, "completed"),
    ]:
        raise RuntimeError("loss gate requires both completed original handlers in causal order")
    meta = request["params"]["_meta"]
    claims = [
        r
        for r in snapshot["claims"]
        if r["cle_idempotence"] == meta["opsys/idempotencyKey"] and r["appareil"] == meta["opsys/appareil"]
    ]
    if len(approvals) != 1 or len(corrections) != 1 or len(claims) != 1 or len(state["rows"]) != 2:
        raise RuntimeError("independent witness requires one correction, decision and claim")
    approval, piece, claim = approvals[0], corrections[0], claims[0]
    if (
        approval["statut"] != "executee"
        or approval["decide_par"] != OWNER
        or approval["decide_role"] != "nathan_owner"
        or approval["decide_le"] != T0
        or approval["niveau"] != "N4"
        or approval["ticket_cible_hash"] is not None
        or json.loads(approval["arguments"]) != item["arguments"]
        or piece["apres"]["montant_avant_taxes"] != Decimal("310.00")
        or piece["apres"]["montant_apres_taxes"] != Decimal("356.42")
        or piece["horodatage"] != item["arguments"]["horodatage"]
        or piece["corrige_par"] != OWNER
        or claim["statut"] != "ok"
        or snapshot["movements"]
        or snapshot["people"][OWNER] != ["admin", "nathan_owner"]
    ):
        raise RuntimeError("independent committed AP facts do not match the genuine decision")
    frozen = {
        "fictif": True,
        "demande_id": demande_id,
        "t0": T0,
        "invoice_id": item["id"],
        "rows": state["rows"],
        "approval": approval,
        "claim": claim,
        "movements": snapshot["movements"],
    }
    encoded = codec.encoder(frozen)
    with (home / ORACLE_T0).open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    return {
        "fictif": True,
        "generation": generation,
        "demande_id": demande_id,
        "native_result": native,
        "t0": T0,
        "ap_horodatage": piece["horodatage"],
        "sql_cree_le": state["rows"][-1]["cree_le"],
        "handler_sequence": sequence,
        "independent_committed_read_before_headers": True,
        "response_body_forwarded_bytes": 0,
        "native_response_bytes_buffered": len(body),
        "oracle_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
    }


def _dispatch_row(label: str, request: dict) -> dict:
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    return {
        "route": label,
        "method": request.get("method"),
        "tool": params.get("name"),
        "rpc_id": request.get("id"),
        "ticket_present": "opsys/cibleTicket" in meta,
        "arguments_sha256": _arguments_digest(args),
        "frame": {
            k: meta.get("opsys/" + k) for k in ("personne", "role", "appareil", "idempotencyKey", "horodatageAppareil")
        },
    }


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
    _configure()
    _original_handlers(home, generation)
    (home / f"origins-{generation}.json").write_text(json.dumps(_origins()))
    dispatches = home / DISPATCH_TRACE
    dispatches.touch(mode=0o600, exist_ok=True)
    stockage.migrer()
    application = application_http_departements(
        charger_departements(),
        etat.session,
        os.environ["OPSYS_MCP_JETON"],
        "127.0.0.1",
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
                            home, generation, selected_request, response_start, bytes(response_body)
                        )
                    except Exception as exc:
                        # The gate refuses to lose an unproven response; the reason is kept for the test.
                        with (home / GATE_REFUSED).open("x", encoding="utf-8") as stream:
                            stream.write(
                                json.dumps({"fictif": True, "error": type(exc).__name__, "reason": str(exc)}) + "\n"
                            )
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
        raise RuntimeError("only owned database or disposable copies may be inspected")
    return path


def _anomalies(snapshot: dict, frozen: dict) -> list[str]:
    anomalies = []
    actual = [
        r for r in snapshot["ap"] if codec.decoder(r["maillon"]).get("facture_fournisseur_id") == frozen["invoice_id"]
    ]
    if actual != frozen["rows"]:
        anomalies.append("AP_ORIGINAL_CHANGED")
    if [r for r in snapshot["approvals"] if r["id"] == frozen["demande_id"]] != [frozen["approval"]]:
        anomalies.append("DECISION_T0_CHANGED")
    claim = frozen["claim"]
    current_claim = [
        r
        for r in snapshot["claims"]
        if r["appareil"] == claim["appareil"] and r["cle_idempotence"] == claim["cle_idempotence"]
    ]
    if current_claim != [claim]:
        anomalies.append("OWNER_CLAIM_CHANGED")
    if snapshot["movements"] != frozen["movements"]:
        anomalies.append("MONEY_MOVEMENT_CHANGED")
    return anomalies


def inspect(database: Path | None) -> None:
    home = _home()
    snapshot = _snapshot(_database_argument(home, database))
    frozen_path = home / ORACLE_T0
    frozen = codec.decoder(frozen_path.read_text()) if frozen_path.exists() else None
    print(
        json.dumps(
            vers_json(
                {
                    "fictif": True,
                    "people": snapshot["people"],
                    "invoices": {
                        label: _invoice_state(snapshot, item) for label, item in _prepared(home)["invoices"].items()
                    },
                    "movements": snapshot["movements"],
                    "claims": snapshot["claims"],
                    "oracle": frozen,
                    "anomalies": _anomalies(snapshot, frozen) if frozen else None,
                    "handler": _read_trace(home / HANDLER_TRACE),
                    "dispatches": _read_trace(home / DISPATCH_TRACE),
                    "origins": {
                        str(g): json.loads((home / f"origins-{g}.json").read_text())
                        for g in (1, 2)
                        if (home / f"origins-{g}.json").exists()
                    },
                }
            )
        )
    )


def read_revision(label: str) -> None:
    """Explicit SELECT-only witness of the current invoice revision, read from the committed AP chain.

    No M5 business read is assumed by this fixture: the revision is the number of committed correction
    pieces, the same count the genuine seed exposes as ``corrections`` at revision 0.
    """
    home = _home()
    item = _prepared(home)["invoices"].get(label)
    if item is None:
        raise RuntimeError("fictive invoice was not prepared: " + label)
    snapshot = _snapshot(home / "opsys.db")
    state = _invoice_state(snapshot, item)
    if not state["pieces"] or state["pieces"][0].get("type_entree") != "facture_fournisseur_saisie":
        raise RuntimeError("revision witness requires the genuine seeded invoice first")
    print(
        json.dumps(
            vers_json(
                {
                    "fictif": True,
                    "witness": (
                        "postgresql17-read-only-ap-chain" if "witness" in snapshot else "sqlite-mode-ro-ap-chain"
                    ),
                    **snapshot.get("witness", {}),
                    "invoice_id": item["id"],
                    "revision": state["corrections"],
                    "rows": len(state["rows"]),
                    "latest": state["pieces"][-1],
                }
            )
        )
    )


def snapshot_negatives() -> None:
    home = _home()
    frozen = codec.decoder((home / ORACLE_T0).read_text())
    directory = home / NEGATIVES
    directory.mkdir(mode=0o700)
    paths = {}
    for name in ("intact", "duplicate_correction", "ap_timestamp", "decision_timestamp", "amount", "claim"):
        target = directory / (name + ".db")
        with (
            closing(sqlite3.connect((home / "opsys.db").as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(target)) as copy,
        ):
            source.backup(copy)
            row = frozen["rows"][-1]
            if name == "duplicate_correction":
                rank = copy.execute(
                    "SELECT MAX(rang)+1 FROM registres_maillons WHERE departement=? AND registre=?",
                    (M5, "comptes_a_payer"),
                ).fetchone()[0]
                copy.execute(
                    "INSERT INTO registres_maillons(departement,registre,rang,maillon,cree_le) VALUES(?,?,?,?,?)",
                    (M5, "comptes_a_payer", rank, row["maillon"], row["cree_le"]),
                )
            elif name in ("ap_timestamp", "amount"):
                piece = codec.decoder(row["maillon"])
                if name == "ap_timestamp":
                    piece["horodatage"] = T1
                else:
                    piece["apres"]["montant_apres_taxes"] = Decimal("356.43")
                copy.execute(
                    "UPDATE registres_maillons SET maillon=? WHERE departement=? AND registre=? AND rang=?",
                    (codec.encoder(piece), M5, "comptes_a_payer", row["rang"]),
                )
            elif name == "decision_timestamp":
                copy.execute("UPDATE approbations SET decide_le=? WHERE id=?", (T1, frozen["demande_id"]))
            elif name == "claim":
                copy.execute(
                    "UPDATE mutations_appliquees SET recu_le=? WHERE appareil=? AND cle_idempotence=?",
                    ("1900-01-01T00:00:00+00:00", frozen["claim"]["appareil"], frozen["claim"]["cle_idempotence"]),
                )
            copy.commit()
        paths[name] = str(target)
    print(json.dumps({"fictif": True, "snapshots": paths}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("prepare", "prepare-b", "serve", "inspect", "snapshot-negatives", "read-revision")
    )
    parser.add_argument("--port", type=int)
    parser.add_argument("--generation", type=int)
    parser.add_argument("--lose-decision", action="store_true")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--label")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "prepare-b":
        _configure()
        print(json.dumps({"fictif": True, "invoice": _prepare_invoice("B")}))
    elif args.command == "serve":
        if args.port is None or args.generation is None:
            raise RuntimeError("serve requires owned port and generation")
        serve(args.port, args.generation, args.lose_decision)
    elif args.command == "inspect":
        inspect(args.database)
    elif args.command == "read-revision":
        if args.label is None:
            raise RuntimeError("read-revision requires an owned invoice label")
        read_revision(args.label)
    else:
        snapshot_negatives()


if __name__ == "__main__":
    main()
