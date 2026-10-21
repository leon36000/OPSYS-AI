"""Fictitious Core/M5 AP integration fixture; no external supplier or payment.

The real department application, approval decision and AP append remain unmodified.
Only fixture configuration, the module-local approval clock, handler observation and
an ASGI response-body loss seam are supplied here. Every committed witness opens a
separate SQLite connection in mode=ro, or an independent PostgreSQL17 read-only
transaction. Negative SQL mutations target SQLite backups or disposable PostgreSQL17
database copies only, never the application's primary database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

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
# Disposable PostgreSQL17 copies: one cloned database per negative, owned by this run only.
PG_COPIES = "pg-copies.json"
PG_COPY_SUFFIX = ".pgcopy.json"
PG_COPY_PREFIX = "opsys_m5_neg_"
PG_MAINTENANCE = "template1"
PG_COPY_CHANGES = {
    "intact": [],
    "duplicate_correction": ["ap"],
    "ap_timestamp": ["ap"],
    "decision_timestamp": ["approvals"],
    "amount": ["ap"],
    "claim": ["claims"],
}
SNAPSHOT_TABLES = ("ap", "movements", "approvals", "claims", "people")
_PG_PROVENANCE = (
    "SELECT d.oid::bigint AS database_oid, shobj_description(d.oid, 'pg_database') AS comment, "
    "pg_get_userbyid(d.datdba) = current_user AS owned_by_current_user, d.datistemplate AS is_template, "
    "has_database_privilege('public'::name, d.oid, 'CONNECT') AS public_connect, "
    "has_database_privilege('public'::name, d.oid, 'TEMPORARY') AS public_temporary "
    "FROM pg_database d WHERE d.datname = %s"
)


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


def _write_private(path: Path, content: str) -> None:
    with open(path, "x", encoding="utf-8", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        stream.write(content)


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


def _pg_owned_url(database: str | None = None) -> str:
    """The runner's single private DSN, optionally retargeted to another database of the same owned server."""
    path = Path(os.environ["OPSYS_TEST_M5_AP_PG17_URL_FILE"])
    for status in (path.stat(), path.parent.stat()):
        if status.st_uid != os.getuid() or status.st_mode & 0o077:
            raise RuntimeError("PostgreSQL17 DSN must come from the runner's private owned file")
    configured = os.environ["OPSYS_BASE_URL"]
    if path.read_text().strip() != configured or not configured.startswith("postgresql+psycopg://"):
        raise RuntimeError("application and witness must share the runner's single private DSN")
    url = urlsplit(configured.replace("postgresql+psycopg://", "postgresql://", 1))
    if url.hostname != "127.0.0.1" or url.query or url.fragment:
        raise RuntimeError("PostgreSQL17 witness requires the runner's loopback-published server")
    return (url._replace(path="/" + database) if database is not None else url).geturl()


def _snapshot_postgres(database: str | None = None) -> dict:
    import psycopg
    from psycopg.rows import dict_row

    # Direct driver connection, independent of the application's SQLAlchemy engine/transactions.
    url = _pg_owned_url(database)
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as cnx:
        cnx.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        try:
            version = int(cnx.execute("SHOW server_version_num").fetchone()["server_version_num"])
            read_only = cnx.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"]
            isolation = cnx.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"]
            if not 170000 <= version < 180000 or read_only != "on" or isolation != "repeatable read":
                raise RuntimeError("independent witness requires real PostgreSQL17 read-only transaction")
            identity = cnx.execute(
                "SELECT d.datname, d.oid::bigint AS database_oid, pg_postmaster_start_time() AS postmaster_start "
                "FROM pg_database d WHERE d.datname = current_database()"
            ).fetchone()
            if database is not None and identity["datname"] != database:
                raise RuntimeError("PostgreSQL17 witness connected to an unexpected database")
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
                person: sorted(
                    row["role"]
                    for row in cnx.execute(
                        "SELECT r.role FROM roles r JOIN personnes p ON p.identifiant=r.identifiant "
                        "WHERE p.identifiant=%s AND p.actif=true",
                        (person,),
                    )
                )
                for person in (OWNER, NON_OWNER)
            }
            # schema.py stores arguments/resultat/maillon as Text; retain those exact encoded values.
            # cree_le and postmaster_start are native timestamptz; vers_json preserves their ISO form.
            # The database identity and server start bind every phase to one unrestarted owned server.
            tables["witness"] = {
                "server_version_num": version,
                "transaction_read_only": read_only,
                "transaction_isolation": isolation,
                "database": identity["datname"],
                "database_oid": identity["database_oid"],
                "postmaster_start": identity["postmaster_start"],
            }
            if database is not None:
                tables["witness"]["copy"] = cnx.execute(_PG_PROVENANCE, (database,)).fetchone()
            return tables
        finally:
            cnx.execute("ROLLBACK")


def _copy_provenance(copy: dict) -> dict:
    return {
        "database_oid": copy["database_oid"],
        "comment": copy["comment"],
        "owned_by_current_user": True,
        "is_template": False,
        "public_connect": False,
        "public_temporary": False,
    }


def _require_owned_copy(witness: dict, copy: dict, primary: dict) -> None:
    if (
        witness["database"] != copy["database"]
        or witness["database"] == primary["database"]
        or witness["database_oid"] == primary["database_oid"]
        or copy["source_oid"] != primary["database_oid"]
        or witness["postmaster_start"] != primary["postmaster_start"]
        or witness["server_version_num"] != primary["server_version_num"]
        or witness.get("copy") != _copy_provenance(copy)
    ):
        raise RuntimeError("disposable PostgreSQL copy failed its ownership or provenance barrier")


def _snapshot_pg_copy(path: Path) -> dict:
    """Read-only witness of one disposable copy, only when its manifest and catalog provenance match this run."""
    home = _home()
    name = path.name.removesuffix(PG_COPY_SUFFIX)
    if path.parent != home / NEGATIVES or not path.name.endswith(PG_COPY_SUFFIX) or name not in PG_COPY_CHANGES:
        raise RuntimeError("PostgreSQL witness cannot inspect SQLite backup oracles")
    run = codec.decoder((home / NEGATIVES / PG_COPIES).read_text())
    copy = json.loads(path.read_text())
    if run["copies"].get(name) != copy or copy["database"] != PG_COPY_PREFIX + run["nonce"] + "_" + name:
        raise RuntimeError("disposable PostgreSQL copy is not one of this run's owned copies")
    snapshot = _snapshot_postgres(copy["database"])
    _require_owned_copy(snapshot["witness"], copy, run["primary"])
    return snapshot


def _snapshot(database: Path) -> dict:
    if os.environ.get("OPSYS_TEST_M5_AP_PG17_URL_FILE"):
        if database == _home() / "opsys.db":
            return _snapshot_postgres()
        return _snapshot_pg_copy(database)
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
        # Values actually observed by this barrier's PostgreSQL17 snapshot; absent for SQLite.
        "witness": snapshot.get("witness"),
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
                        stream.write(json.dumps(vers_json({**proof, "original_headers_forwarded": True})) + "\n")
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
                    "witness": snapshot.get("witness"),
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


def _mutate_pg_copy(cnx, name: str, frozen: dict) -> None:
    """The same targeted corruptions as the SQLite backups, written only through a copy's own connection."""
    row = frozen["rows"][-1]
    if name == "intact":
        return
    if name == "duplicate_correction":
        rank = cnx.execute(
            "SELECT MAX(rang)+1 FROM registres_maillons WHERE departement=%s AND registre=%s",
            (M5, "comptes_a_payer"),
        ).fetchone()[0]
        cursor = cnx.execute(
            "INSERT INTO registres_maillons(departement,registre,rang,maillon,cree_le) VALUES(%s,%s,%s,%s,%s)",
            (M5, "comptes_a_payer", rank, row["maillon"], row["cree_le"]),
        )
    elif name in ("ap_timestamp", "amount"):
        piece = codec.decoder(row["maillon"])
        if name == "ap_timestamp":
            piece["horodatage"] = T1
        else:
            piece["apres"]["montant_apres_taxes"] = Decimal("356.43")
        cursor = cnx.execute(
            "UPDATE registres_maillons SET maillon=%s WHERE departement=%s AND registre=%s AND rang=%s",
            (codec.encoder(piece), M5, "comptes_a_payer", row["rang"]),
        )
    elif name == "decision_timestamp":
        cursor = cnx.execute("UPDATE approbations SET decide_le=%s WHERE id=%s", (T1, frozen["demande_id"]))
    elif name == "claim":
        cursor = cnx.execute(
            "UPDATE mutations_appliquees SET recu_le=%s WHERE appareil=%s AND cle_idempotence=%s",
            ("1900-01-01T00:00:00+00:00", frozen["claim"]["appareil"], frozen["claim"]["cle_idempotence"]),
        )
    else:
        raise RuntimeError("unknown disposable PostgreSQL mutation: " + name)
    if cursor.rowcount != 1:
        raise RuntimeError("disposable PostgreSQL mutation did not change exactly one row: " + name)


def _drop_created(databases: list[str], error: BaseException) -> None:
    import psycopg
    from psycopg import sql

    try:
        with psycopg.connect(_pg_owned_url(PG_MAINTENANCE), autocommit=True) as admin:
            for database in databases:
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database)))
    except Exception as cleanup:
        error.add_note("disposable PostgreSQL copy cleanup failed: " + type(cleanup).__name__)


def snapshot_negatives_postgres() -> None:
    """Real SQL mutations, each committed in its own disposable database cloned from the owned primary."""
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row

    home = _home()
    frozen = codec.decoder((home / ORACLE_T0).read_text())
    barrier = json.loads((home / RESPONSE_LOST).read_text())["witness"]
    directory = home / NEGATIVES
    directory.mkdir(mode=0o700)
    if directory.stat().st_mode & 0o077:
        raise RuntimeError("disposable copy manifests require a private directory")
    before = _snapshot_postgres()
    primary = before["witness"]
    if vers_json(primary) != barrier:
        raise RuntimeError("copies must clone the PostgreSQL17 database that witnessed the lost commit")
    nonce = secrets.token_hex(8)
    created: list[str] = []
    copies: dict[str, dict] = {}
    report: dict[str, dict] = {}
    try:
        with psycopg.connect(_pg_owned_url(PG_MAINTENANCE), autocommit=True, row_factory=dict_row) as admin:
            role = admin.execute(
                "SELECT rolsuper OR rolcreatedb AS allowed FROM pg_roles WHERE rolname = current_user"
            ).fetchone()
            databases = sorted(r["datname"] for r in admin.execute("SELECT datname FROM pg_database"))
            if (
                not role
                or role["allowed"] is not True
                or primary["database"] in ("template0", PG_MAINTENANCE)
                or databases != sorted({"template0", PG_MAINTENANCE, primary["database"]})
            ):
                raise RuntimeError("disposable copies require the runner's exclusively owned PostgreSQL17 server")
            for name in PG_COPY_CHANGES:
                target = PG_COPY_PREFIX + nonce + "_" + name
                comment = f"opsys-m5-ap-negative {nonce} {name} source-oid={primary['database_oid']}"
                # Faithful file-level clone; PostgreSQL refuses it while any other session uses the primary.
                admin.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE {} STRATEGY FILE_COPY").format(
                        sql.Identifier(target), sql.Identifier(primary["database"])
                    )
                )
                created.append(target)
                admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(target)))
                admin.execute(
                    sql.SQL("COMMENT ON DATABASE {} IS {}").format(sql.Identifier(target), sql.Literal(comment))
                )
                oid = admin.execute(
                    "SELECT oid::bigint AS oid FROM pg_database WHERE datname = %s", (target,)
                ).fetchone()["oid"]
                copies[name] = {
                    "database": target,
                    "database_oid": oid,
                    "comment": comment,
                    "source_oid": primary["database_oid"],
                }
        for name, copy in copies.items():
            with psycopg.connect(_pg_owned_url(copy["database"]), autocommit=True) as cnx:
                if cnx.execute("SELECT current_database()").fetchone()[0] != copy["database"]:
                    raise RuntimeError("refusing to mutate a database other than its disposable copy")
                with cnx.transaction():
                    _mutate_pg_copy(cnx, name, frozen)
            snapshot = _snapshot_postgres(copy["database"])
            _require_owned_copy(snapshot["witness"], copy, primary)
            changed = [table for table in SNAPSHOT_TABLES if snapshot[table] != before[table]]
            if changed != PG_COPY_CHANGES[name]:
                raise RuntimeError("SQL mutation did not target exactly its intended copy table: " + name)
            provenance = snapshot["witness"]["copy"]
            report[name] = {
                **copy,
                "changed_tables": changed,
                **{k: provenance[k] for k in ("owned_by_current_user", "public_connect", "public_temporary")},
            }
        if _snapshot_postgres() != before:
            raise RuntimeError("primary PostgreSQL17 database changed while mutating disposable copies")
        run = {
            "fictif": True,
            "nonce": nonce,
            "primary": primary,
            "primary_sha256": hashlib.sha256(codec.encoder(before).encode()).hexdigest(),
            "databases_before": databases,
            "copies": copies,
        }
        _write_private(directory / PG_COPIES, codec.encoder(run))
        paths = {}
        for name, copy in copies.items():
            target = directory / (name + PG_COPY_SUFFIX)
            _write_private(target, json.dumps(copy))
            paths[name] = str(target)
    except BaseException as exc:
        _drop_created(created, exc)
        raise
    print(
        json.dumps(
            vers_json(
                {
                    "fictif": True,
                    "snapshots": paths,
                    "postgres": {"primary_unchanged": True, "primary": primary, "copies": report},
                }
            )
        )
    )


def drop_negatives() -> None:
    """Drop exactly this run's disposable copies; prove none remains and the primary is unchanged."""
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row

    home = _home()
    run = codec.decoder((home / NEGATIVES / PG_COPIES).read_text())
    dropped = []
    with psycopg.connect(_pg_owned_url(PG_MAINTENANCE), autocommit=True, row_factory=dict_row) as admin:
        for name in PG_COPY_CHANGES:
            copy = run["copies"][name]
            if admin.execute(_PG_PROVENANCE, (copy["database"],)).fetchone() != _copy_provenance(copy):
                raise RuntimeError("refusing to drop a database without this run's copy provenance")
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(copy["database"])))
            dropped.append(copy["database"])
        remaining = [
            r["datname"]
            for r in admin.execute(
                "SELECT datname FROM pg_database WHERE starts_with(datname, %s) ORDER BY datname", (PG_COPY_PREFIX,)
            )
        ]
        databases = sorted(r["datname"] for r in admin.execute("SELECT datname FROM pg_database"))
    after = _snapshot_postgres()
    unchanged = hashlib.sha256(codec.encoder(after).encode()).hexdigest() == run["primary_sha256"]
    if remaining or databases != run["databases_before"] or not unchanged or after["witness"] != run["primary"]:
        raise RuntimeError("disposable PostgreSQL copies were not cleaned or the primary changed")
    print(
        json.dumps(
            {
                "fictif": True,
                "dropped": dropped,
                "remaining": remaining,
                "databases": databases,
                "primary_unchanged": unchanged,
            }
        )
    )


def snapshot_negatives() -> None:
    if os.environ.get("OPSYS_TEST_M5_AP_PG17_URL_FILE"):
        snapshot_negatives_postgres()
        return
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
        "command",
        choices=("prepare", "prepare-b", "serve", "inspect", "snapshot-negatives", "drop-negatives", "read-revision"),
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
    elif args.command == "drop-negatives":
        if not os.environ.get("OPSYS_TEST_M5_AP_PG17_URL_FILE"):
            raise RuntimeError("drop-negatives only cleans owned PostgreSQL17 copies")
        drop_negatives()
    else:
        snapshot_negatives()


if __name__ == "__main__":
    main()
