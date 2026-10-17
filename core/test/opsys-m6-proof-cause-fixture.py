"""Fictitious CF026 Core/M6 bridge; no physical scene, Native/Gateway or PostgreSQL claim.

The existing E2E helpers create the real M3/WCT/stock/CAS fixture in a separate
setup process. Core proof starts only when TypeScript acquires a production lease
and calls the new real Python HTTP server. The loss seam buffers an original M6
classification response until a distinct SQLite mode=ro connection sees its commit.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import importlib
import io
import json
import os
import sqlite3
import sys
from contextlib import closing, redirect_stdout
from decimal import Decimal
from pathlib import Path

from opsys import stockage
from opsys.outils import vers_json
from opsys.stockage import codec

REPO = Path(__file__).resolve().parents[2]
M6 = "m06-material-control"
DECLARE = "m6_declarer_materiaux_avec_preuves_appareil"
LIST = "m6_lister_variances_classables_wct_appareil"
CLASSIFY = "m6_classer_cause_variance_appareil"
PREPARED = "m6-proof-prepared.json"
HANDLER_TRACE = "m6-proof-handlers.jsonl"
DISPATCH_TRACE = "m6-proof-dispatches.jsonl"
RESPONSE_LOST = "m6-proof-response-lost.json"
GATE_REFUSED = "m6-proof-loss-gate-refused.json"
ORACLE = "m6-proof-committed-oracle.json"
ROUTES = {"/mcp/" + M6: "m6"}


def _home() -> Path:
    return Path(os.environ["OPSYS_HOME"]).resolve()


def _prepared() -> dict:
    return json.loads((_home() / PREPARED).read_text())


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _arguments_digest(arguments: dict) -> str:
    return _digest(arguments)


def _append_trace(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"fictif": True, **row}) + "\n")


def _read_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []


def _setup_modules():
    # Canonical PC1 PYTHONPATH need only contain src + departments. Bind test helpers explicitly.
    for directory in (REPO / "tests/fixtures", REPO / "tests/e2e"):
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
    harness = importlib.import_module("harnais_e2e")
    chantier = importlib.import_module("harnais_e2e_chantier")
    vertical = importlib.import_module("test_verticale_affaire_durable")
    for module, expected in ((harness, REPO / "tests/fixtures/harnais_e2e.py"),
                             (chantier, REPO / "tests/fixtures/harnais_e2e_chantier.py"),
                             (vertical, REPO / "tests/e2e/test_verticale_affaire_durable.py")):
        if Path(module.__file__).resolve() != expected.resolve():
            raise RuntimeError("setup helper is not from this checkout")
    return harness, chantier, vertical


def prepare() -> None:
    """Existing legitimate setup only; no TypeScript/Core runtime credit is claimed here."""
    import m2_revenue_crm.outils as m2_tools
    import m5_financecore.outils as m5_tools
    import pytest

    harness, chantier_helpers, vertical = _setup_modules()
    home = _home()
    engine = None
    generator = None
    closed_setup_threads = []

    class OwnedSetupEngine(harness.Moteur):
        def arreter(self):
            owned = self._fil
            super().arreter()
            if owned is not None:
                if owned.is_alive():
                    raise RuntimeError("owned setup HTTP thread survived its canonical stop/join")
                closed_setup_threads.append(owned.ident)

    with pytest.MonkeyPatch.context() as patch, redirect_stdout(io.StringIO()):
        stockage.migrer()
        m2_tools.utiliser_stockage_durable()
        m5_tools.utiliser_stockage_durable()
        clock = harness.Horloge(chantier_helpers.debut_de_journee(15))
        clock.installer(patch)
        engine = OwnedSetupEngine(home, os.environ[stockage.ENV_URL])
        engine.horloge = clock
        try:
            engine.demarrer()
            engine.creer_personne("nathan", "Nathan propriétaire (fictif)", ["nathan_owner", "admin"], patch)
            engine.creer_personne("etienne", "Étienne employé (fictif)", ["employee"], patch)
            engine.creer_personne("marie", "Marie participante (fictif)", ["admin", "employee"], patch)
            people = {"admin": engine.appairer("nathan", "admin"),
                      "employe": engine.appairer("etienne", "employee")}
            generator = vertical.affaire.__wrapped__(engine, people, patch, home)
            affaire = next(generator)
            participant = engine.appairer("marie", "admin")
            chantier, _, bus_proof = vertical._preparer_affaire(engine, affaire)
            app = chantier_helpers.AppEmploye(engine, affaire["employe"], chantier)
            completion = app.journee_jusqu_a_la_completion()
            wct_id = completion.resultat["wct_id"]
            vertical._drainer(engine)
            if app.statut().resultat["statut"] != "completed_pending_review":
                raise RuntimeError("genuine completed WCT must still await review")
            photo = chantier_helpers.png_minimal(largeur=3)
            photo_sha = hashlib.sha256(photo).hexdigest()
            photo_ref = app.deposer_fichier(photo)
            if photo_ref != "fichier:sha256:" + photo_sha:
                raise RuntimeError("genuine CAS upload reference mismatch")
            data = {"fictif": True, "setup_pid": os.getpid(), "setup_bus_pid": bus_proof["pid"],
                    "wct_id": wct_id, "intervention_id": chantier.intervention_id,
                    "chantier_id": chantier.chantier_id, "devis_id": chantier.devis_id,
                    "material_id": chantier_helpers.MATERIAU_ID,
                    "employee": chantier.technicien, "admin": "marie",
                    "employee_device": affaire["employe"].appareil_id,
                    "admin_device": participant.appareil_id,
                    "owner_device": affaire["admin"].appareil_id,
                    "clock": clock.maintenant.isoformat(), "device_time": app.heure_appareil(),
                    "photo_reference": photo_ref, "photo_sha256": photo_sha, "photo_bytes": len(photo),
                    "M4_initial_status": "completed_pending_review",
                    "declaration": {"wct_id": wct_id, "formulaire": {
                        "wct_id": wct_id, "intervention_id": chantier.intervention_id,
                        "chantier_id": chantier.chantier_id, "lignes_materiaux": [
                            {"type_ligne": "prevu", "materiau_id": chantier_helpers.MATERIAU_ID,
                             "quantite": 55.0, "unite": "pi", "quantite_estimee": 40.0},
                            {"type_ligne": "perte", "materiau_id": chantier_helpers.MATERIAU_ID,
                             "quantite": 1.0, "unite": "pi"}]},
                        "preuves_lignes": [{"position_ligne": 1, "note": "FICTIF : perte, cause à classer.",
                                            "photos": [photo_ref]}]},
                    "helper_pins": {str(Path(m.__file__).resolve()): hashlib.sha256(
                        Path(m.__file__).read_bytes()).hexdigest() for m in (harness, chantier_helpers, vertical)}}
        finally:
            if generator is not None:
                generator.close()
            if engine is not None:
                engine.arreter()
                if engine._fil is None or engine._fil.is_alive():
                    raise RuntimeError("owned setup HTTP server did not stop")
            stockage.liberer()
    data["setup_HTTP_thread_stopped"] = True
    data["setup_HTTP_threads_closed"] = len(closed_setup_threads)
    with (home / PREPARED).open("x", encoding="utf-8") as stream:
        json.dump(data, stream)
    print(json.dumps(data))


def _snapshot() -> dict:
    """Fresh native SQLite connection; no application session/cache and no SQL writes."""
    with closing(sqlite3.connect((_home() / "opsys.db").as_uri() + "?mode=ro", uri=True)) as cnx:
        cnx.row_factory = sqlite3.Row
        cnx.execute("BEGIN")
        names = [r[0] for r in cnx.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        tables = {}
        for name in names:
            rows = [dict(r) for r in cnx.execute('SELECT * FROM "' + name.replace('"', '""') + '"')]
            tables[name] = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))
        registers = tables["registres_maillons"]
        protected = {"registers": [r for r in registers if not (
            r["departement"] == M6 and r["registre"] in {"classements_variance", "refus_classement_variance"})],
            "outgoing": tables["evenements_sortants"], "incoming": tables["evenements_recus"]}
        people = {p: [r[0] for r in cnx.execute(
            "SELECT r.role FROM roles r JOIN personnes p ON p.identifiant=r.identifiant "
            "WHERE p.identifiant=? AND p.actif=1 ORDER BY r.role", (p,))] for p in ("nathan", "etienne", "marie")}
    data = _prepared()
    blocks = sorted((r for r in tables["fichiers_blocs"] if r["empreinte_sha256"] == data["photo_sha256"]),
                    key=lambda r: r["index_bloc"])
    if len(blocks) != 1 or blocks[0]["index_bloc"] != 0:
        raise RuntimeError("independent CAS witness requires the genuine single uploaded block")
    content = base64.b64decode(blocks[0]["contenu_base64"], validate=True)
    if hashlib.sha256(content).hexdigest() != data["photo_sha256"] or len(content) != data["photo_bytes"]:
        raise RuntimeError("independent CAS bytes do not match the uploaded fictitious photo")
    protected["cas_tables"] = {name: _digest(tables[name]) for name in ("fichiers", "fichiers_blocs")}
    return {"registers": registers, "protected": protected,
            "tables": {name: _digest(rows) for name, rows in tables.items()},
            "claims": tables["mutations_appliquees"], "people": people,
            "cas": {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content), "blocks": len(blocks)}}


def _pieces(snapshot: dict, register: str) -> list[dict]:
    rows = [r for r in snapshot["registers"] if r["departement"] == M6 and r["registre"] == register]
    return [codec.decoder(r["maillon"]) for r in sorted(rows, key=lambda row: row["rang"])]


def _stock(snapshot: dict) -> Decimal:
    return sum((Decimal(str(m["quantite"])) for m in _pieces(snapshot, "principal")
                if m.get("materiau_id") == _prepared()["material_id"]), Decimal(0))


def inspect() -> None:
    home = _home()
    snapshot = _snapshot()
    data = _prepared()
    oracle_path = home / ORACLE
    oracle = codec.decoder(oracle_path.read_text()) if oracle_path.exists() else None
    print(json.dumps(vers_json({**snapshot,
        "stock": str(_stock(snapshot)),
        "movements": [m for m in _pieces(snapshot, "principal") if m.get("wct_id") == data["wct_id"]],
        "proofs": _pieces(snapshot, "preuves_pertes_bris"),
        "classifications": _pieces(snapshot, "classements_variance"),
        "refusals": _pieces(snapshot, "refus_classement_variance"),
        "handler": _read_trace(home / HANDLER_TRACE), "dispatches": _read_trace(home / DISPATCH_TRACE),
        "oracle": oracle, "origins": {str(g): json.loads((home / f"origins-{g}.json").read_text())
            for g in (1, 2) if (home / f"origins-{g}.json").exists()}})))


def drain_bus() -> None:
    from opsys import evenements
    from opsys.departements import charger_departements

    data = _prepared()
    now = dt.datetime.fromisoformat(data["clock"])
    deps = charger_departements()
    for _ in range(15):
        now += dt.timedelta(seconds=90)
        result = evenements.repartir(deps, maintenant=now.isoformat())
        if result["echecs"] or result["quarantaines"]:
            raise RuntimeError("fictive business bus failed: " + json.dumps(result))
        if result["livres"] == 0:
            print(json.dumps({"fictif": True, "bus_quiescent": True}))
            return
    raise RuntimeError("fictive business bus did not quiesce")


def withdraw_participant() -> None:
    """Canonical role withdrawal only; no device revocation or Native/Gateway proof."""
    from opsys import identite

    with stockage.transaction() as cnx:
        before = identite.personne_active(cnx, "marie")
        if before is None or "admin" not in before.roles:
            raise RuntimeError("positive admin must be active before revocation")
        identite.retirer_role(cnx, "marie", "admin")
        after = identite.personne_active(cnx, "marie")
        if after is None or set(after.roles) != {"employee"}:
            raise RuntimeError("withdrawal must leave the participant active with her employee role")
        owner = identite.personne_active(cnx, "nathan")
        if owner is None or set(owner.roles) != {"admin", "nathan_owner"}:
            raise RuntimeError("the native owner must remain valid and unchanged")
    print(json.dumps({"fictif": True, "participant_admin_role_removed": True, "owner_unchanged": True}))


def _original_handlers(home: Path, generation: int) -> None:
    import dataclasses
    import functools

    import m6_material_control.outils as tools_module

    factory = tools_module.outils

    def counted(original, name):
        @functools.wraps(original)
        def handler(**arguments):
            common = {"generation": generation, "tool": name, "arguments_sha256": _arguments_digest(arguments)}
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
        if any(sum(t.nom == n for t in tools) != 1 for n in (DECLARE, LIST, CLASSIFY)):
            raise RuntimeError("fixture requires each original M6 handler exactly once")
        return tuple(dataclasses.replace(t, fonction=counted(t.fonction, t.nom))
                     if t.nom in (DECLARE, LIST, CLASSIFY) else t for t in tools)
    tools_module.outils = observed_factory


def _origins() -> dict:
    import m6_material_control.outils

    import opsys.capacites

    return {m.__name__: {"path": str(Path(m.__file__).resolve()),
                        "sha256": hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()}
            for m in (opsys.capacites, m6_material_control.outils)}


def _committed_classification(home: Path, generation: int, request: dict, start: dict, body: bytes) -> dict:
    from m6_material_control import classement_variance_appareil as classification

    messages = [m for m in _native_messages(start, body) if isinstance(m, dict) and m.get("id") == request["id"]]
    if len(messages) != 1 or messages[0].get("jsonrpc") != "2.0":
        raise RuntimeError("loss gate needs exactly one genuine matching RPC response")
    result = messages[0].get("result", {})
    texts = [c["text"] for c in result.get("content", []) if c.get("type") == "text"]
    if start["status"] != 200 or "error" in messages[0] or result.get("isError") or len(texts) != 1:
        raise RuntimeError("loss gate requires a successful original MCP response")
    native = json.loads(texts[0])
    if (native.get("ok") is not True or native.get("rejoue") is not False
            or native.get("resultat", {}).get("accepte") is not True):
        raise RuntimeError("loss gate requires the successful original classification, not a refusal")
    args = request["params"]["arguments"]
    meta = request["params"]["_meta"]
    data = _prepared()
    snapshot = _snapshot()
    classes = _pieces(snapshot, "classements_variance")
    if len(classes) != 1 or _pieces(snapshot, "refus_classement_variance"):
        raise RuntimeError("independent read requires one classification and no classification refusal")
    [piece] = classes
    expected = classification.ack(piece)
    if vers_json(expected) != native["resultat"]:
        raise RuntimeError("independent persisted classification does not produce this genuine native ACK")
    if (piece["auteur"] != {"personne": data["admin"], "role": "admin", "source": "appareil"}
            or any(piece[k] != args[k] for k in ("selection", "cause", "motif", "references_pieces"))
            or piece["reference_precedente"] != args["classement_attendu"]
            or piece["appareil_id"] != meta["opsys/appareil"]
            or snapshot["people"]["nathan"] != ["admin", "nathan_owner"]
            or snapshot["people"][data["admin"]] != ["admin", "employee"]):
        raise RuntimeError("independent classification actor/source/intention mismatch")
    claims = [c for c in snapshot["claims"] if c["appareil"] == meta["opsys/appareil"]
              and c["cle_idempotence"] == meta["opsys/idempotencyKey"]]
    if len(claims) != 1 or claims[0]["statut"] != "ok":
        raise RuntimeError("independent classification claim not committed")
    if {**codec.decoder(claims[0]["reponse"]), "rejoue": False} != native:
        raise RuntimeError("committed claim does not contain the original ACK")
    digest = _arguments_digest(args)
    events = [r for r in _read_trace(home / HANDLER_TRACE)
              if r["generation"] == generation and r["tool"] == CLASSIFY]
    if [(r["event"], r["arguments_sha256"]) for r in events] != [("entered", digest), ("completed", digest)]:
        raise RuntimeError("loss gate needs exactly one completed original classification handler")
    baseline = codec.decoder((home / "before-classification.json").read_text())
    if (snapshot["protected"] != baseline["protected"] or _stock(snapshot) != _stock(baseline)
            or _pieces(snapshot, "preuves_pertes_bris") != _pieces(baseline, "preuves_pertes_bris")):
        raise RuntimeError("classification changed protected stock/cost/M4/events/proofs")
    frozen = {"native_result": native, "piece": piece, "claims": snapshot["claims"],
              "protected": snapshot["protected"], "proofs": _pieces(snapshot, "preuves_pertes_bris")}
    with (home / ORACLE).open("x", encoding="utf-8") as stream:
        stream.write(codec.encoder(frozen))
    return {"fictif": True, "generation": generation, "native_result": native,
            "independent_committed_read_before_headers": True, "response_body_forwarded_bytes": 0,
            "native_response_bytes_buffered": len(body), "handler_events_before_loss": ["entered", "completed"],
            "classification_reference": native["resultat"]["resultat"]["reference"]}


def _dispatch_row(label: str, request: dict) -> dict:
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    return {"route": label, "method": request.get("method"), "tool": params.get("name"),
            "arguments_sha256": _arguments_digest(params.get("arguments", {})),
            "frame": {k: meta.get("opsys/" + k) for k in (
                "personne", "role", "appareil", "idempotencyKey", "horodatageAppareil")}}

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


def serve(port: int, generation: int, lose_classification: bool) -> None:
    """Serve the real M6 app; lose only the selected classification body after independently reading its commit."""
    import pytest
    import uvicorn

    from opsys import etat
    from opsys.departements import charger_departements
    from opsys.serveur_mcp import application_http_departements

    harness, _, _ = _setup_modules()
    data = _prepared()
    clock_patch = pytest.MonkeyPatch()
    harness.Horloge(dt.datetime.fromisoformat(data["clock"])).installer(clock_patch)
    home = _home()
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
    loss_available = lose_classification

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
                    if label == "m6" and row["tool"] == CLASSIFY and loss_available:
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
                    raise RuntimeError("bounded fictive M6 response exceeded fixture limit")
                if not message.get("more_body", False):
                    if response_start is None:
                        raise RuntimeError("fictive response-loss gate has no original headers")
                    try:
                        proof = _committed_classification(
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
                    raise RuntimeError("FICTIVE_M6_CLASSIFICATION_BODY_LOST_AFTER_NATIVE_COMMIT")
            else:
                raise RuntimeError("unexpected fictive ASGI response message")

        await application(scope, receive_observed, send_observed)

    try:
        uvicorn.run(observed, host="127.0.0.1", port=port, log_level="info")
    finally:
        clock_patch.undo()


def save_baseline() -> None:
    path = _home() / "before-classification.json"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(codec.encoder(_snapshot()))
    print(json.dumps({"fictif": True, "baseline_saved": True}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "serve", "inspect", "drain", "baseline", "withdraw-participant"))
    parser.add_argument("--port", type=int)
    parser.add_argument("--generation", type=int)
    parser.add_argument("--lose-classification", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "serve":
        if args.port is None or args.generation not in (1, 2):
            raise RuntimeError("serve requires an owned port and generation 1 or 2")
        serve(args.port, args.generation, args.lose_classification)
    elif args.command == "inspect":
        inspect()
    elif args.command == "drain":
        drain_bus()
    elif args.command == "baseline":
        save_baseline()
    else:
        withdraw_participant()


if __name__ == "__main__":
    main()
