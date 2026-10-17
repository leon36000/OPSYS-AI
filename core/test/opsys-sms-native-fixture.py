"""Local-only fixture for the Core SMS Gate -> real Native M1 receipt over loopback TLS.

Every value is fictive. stdout is a JSON-lines protocol owned by the Core test; diagnostics go to stderr.
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

ROOT = Path(__file__).resolve().parents[2]
M1_FIXTURES = ROOT / "departments" / "m01-front-office" / "fixtures"
PROFILE_ID = "sms-demo"
COMPTE_ID = "default"
ACCOUNT_SID = "AC" + "1" * 32
ADMIN = "admin.sms.native.fictif"
RUNTIME_PATH = "/mcp/runtime/" + PROFILE_ID
LIRE = "opsys_runtime_lire_reception_sms"
RECEVOIR = "opsys_runtime_recevoir_sms"
TYPE_RECU = "reception_hote_sms_v1"
MAX_BODY_BYTES = 256 * 1024


def _emit(event: dict) -> None:
    sys.stdout.write(json.dumps({"fictif": True, **event}, sort_keys=True) + "\n")
    sys.stdout.flush()


def _home() -> Path:
    from opsys import stockage

    home = stockage.dossier_opsys().resolve()
    # The independent reader must open the exact file served by the Native owner.
    if stockage.url_base() != f"sqlite:///{home / 'opsys.db'}":
        raise RuntimeError("fictive SMS fixture requires its own OPSYS_HOME SQLite file")
    return home


def _read_only(home: Path) -> sqlite3.Connection:
    """A distinct physical connection: it sees outer commits only, never a handler savepoint."""
    return sqlite3.connect((home / "opsys.db").as_uri() + "?mode=ro", uri=True)


def _m1_rows(cnx: sqlite3.Connection) -> list[dict]:
    return [json.loads(maillon) for (maillon,) in cnx.execute(
        "SELECT maillon FROM registres_maillons WHERE departement='m01-front-office' AND registre='principal' "
        "ORDER BY rang",
    )]


def _profile(cnx: sqlite3.Connection) -> dict | None:
    row = cnx.execute(
        "SELECT revision, actif, supprime FROM agents_configurables WHERE id=?", (PROFILE_ID,),
    ).fetchone()
    if row is None:
        return None
    return {"id": PROFILE_ID, "revision": row[0], "actif": bool(row[1]), "supprime": bool(row[2])}


def _events(cnx: sqlite3.Connection) -> list[str]:
    return [kind for (kind,) in cnx.execute(
        "SELECT type_evenement FROM evenements_sortants ORDER BY cree_le, evenement_id",
    )]


def _receipt(row: dict) -> dict:
    keys = ("horodatage", "intention_id", "commande_sha256", "arguments_sha256", "permission", "recu")
    return {key: row[key] for key in keys}


def _sql_value(value):
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    raise TypeError(type(value).__name__)


def prepare() -> None:
    """Actual active profile/trigger, adapted from tests/test_reception_sms_receipt.py `instance`."""
    import yaml

    from opsys import agents, identite, stockage, taxonomie
    from opsys.departements import charger_departements

    _home()
    stockage.migrer()
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    for filename, setters in [
        ("qualification/profil-fictif.v1.yaml", {
            "questions_qualification": taxonomie.enregistrer_questions_qualification,
            "poids_score_lead": taxonomie.enregistrer_poids_score_lead}),
        ("plaintes/plaintes.v1.yaml", {
            "signaux_plainte": taxonomie.enregistrer_signaux_plainte,
            "destinataires_transfert": taxonomie.enregistrer_destinataires_transfert}),
    ]:
        corpus = yaml.safe_load((M1_FIXTURES / filename).read_text(encoding="utf-8"))
        if corpus.get("fictif") is not True:
            raise RuntimeError("M1 corpus must be fictive")
        for key, setter in setters.items():
            setter(corpus[key])
    departments = charger_departements(ROOT / "departments")
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ADMIN, "Admin SMS fictif", "mot-de-passe-sms-native-fictif-1234", ["admin"])
        profile = agents.creer(cnx, departments, {
            "id": PROFILE_ID, "departement": "m01-front-office", "responsabilite": "Accueil SMS fictif",
            "palier_modele": "rapide", "outils": ["m1_recevoir_message_canal"],
            "budget_jour": 1000, "budget_mois": 10000, "limite_tours": 8, "limite_reessais": 1,
            "limite_concurrence": 1, "declencheurs": [
                {"type": "canal", "version": 1, "canal": "sms", "compte_id": COMPTE_ID, "account_sid": ACCOUNT_SID}],
        }, par=ADMIN, mutation_id="creer-sms-native-0001")
        profile = agents.definir_actif(cnx, profile["id"], departments, True, par=ADMIN,
                                       mutation_id="actif-sms-native-0001", revision_attendue=1)
    _emit({"event": "prepared", "profile_id": profile["id"], "revision": profile["revision"],
           "actif": profile["actif"], "compte_id": COMPTE_ID, "account_sid": ACCOUNT_SID})


def disable(revision: int) -> None:
    from opsys import agents, stockage
    from opsys.departements import charger_departements

    _home()
    departments = charger_departements(ROOT / "departments")
    with stockage.transaction() as cnx:
        profile = agents.definir_actif(cnx, PROFILE_ID, departments, False, par=ADMIN,
                                       mutation_id="retirer-sms-native-0001", revision_attendue=revision)
    _emit({"event": "disabled", "profile_id": profile["id"], "revision": profile["revision"],
           "actif": profile["actif"]})


def inspect() -> None:
    """Whole-database census through an independent read-only connection; executes no write."""
    home = _home()
    with closing(_read_only(home)) as cnx:
        cnx.execute("BEGIN")
        tables = {}
        names = [name for (name,) in cnx.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        ).fetchall()]
        for name in names:
            cursor = cnx.execute('SELECT * FROM "' + name.replace('"', '""') + '"')
            columns = [column[0] for column in cursor.description]
            rows = sorted(json.dumps(dict(zip(columns, row, strict=True)), sort_keys=True, default=_sql_value)
                          for row in cursor)
            tables[name] = {"count": len(rows), "sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest()}
        rows = _m1_rows(cnx)
        profile = _profile(cnx)
        events = _events(cnx)
        cnx.rollback()
    _emit({
        "event": "inspected", "tables": tables, "profile": profile, "events": events,
        "receipts": [_receipt(row) for row in rows if row.get("type_entree") == TYPE_RECU],
        "signals": sum(row.get("type_entree") == "signal" for row in rows),
        "leads": sum(row.get("type_entree") == "lead_emis" for row in rows),
    })


def _ephemeral_tls(home: Path) -> str:
    """Per-run fictive CA and loopback leaf; only the CA certificate leaves this process."""
    import datetime as dt
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = dt.datetime.now(dt.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OPSYS SMS native fixture CA fictif")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(hours=2))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                       data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                       crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]))
            .issuer_name(ca_name).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(hours=2))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                           critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    directory = home / "tls-fictif"
    directory.mkdir(mode=0o700)
    for name, data in (
        ("leaf.pem", leaf.public_bytes(serialization.Encoding.PEM)),
        ("leaf.key", leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption())),
    ):
        descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    return ca.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _header(headers, name: bytes) -> bytes | None:
    values = [value for key, value in headers if key.lower() == name]
    return values[0] if len(values) == 1 else None


def _messages(start: dict, body: bytes) -> tuple[str, list]:
    content_type = (_header(start.get("headers", []), b"content-type") or b"").split(b";", 1)[0].strip().decode()
    if not body:
        return content_type, []
    text = body.decode("utf-8")
    if content_type == "application/json":
        return content_type, [json.loads(text)]
    if content_type != "text/event-stream":
        return content_type, []
    messages = []
    # Parsed only once the whole body ended: a fragmented SSE event is never judged partially.
    for block in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        data = [line[5:].removeprefix(" ") for line in block.splitlines() if line.startswith("data:")]
        if data:
            messages.append(json.loads("\n".join(data)))
    return content_type, messages


def _tool_ack(request: dict, messages: list) -> dict | None:
    responses = [m for m in messages if isinstance(m, dict) and "id" in m and m["id"] == request.get("id")]
    if len(responses) != 1:
        return None
    response = responses[0]
    if "error" in response:
        return {"jsonrpc_error": response["error"].get("code")}
    result = response.get("result") or {}
    texts = [item["text"] for item in result.get("content", []) if item.get("type") == "text"]
    if len(texts) != 1:
        return None
    return {"is_error": bool(result.get("isError")), "native": json.loads(texts[0])}


def _committed_receipt(home: Path, request: dict, start: dict, body: bytes) -> dict:
    """Adapted from opsys-target-ticket-fixture.py `_committed_m9_response` for the actual M1 receipt."""
    content_type, messages = _messages(start, body)
    acknowledged = _tool_ack(request, messages)
    if start["status"] != 200 or acknowledged is None or "native" not in acknowledged or acknowledged["is_error"]:
        raise RuntimeError("fictive loss gate requires one successful correlated native RECEIVE result")
    ack = acknowledged["native"]
    if ack.get("ok") is not True or ack.get("operation") != "recevoir" or ack.get("etat") != "recu":
        raise RuntimeError("fictive loss gate requires an actual received ACK")
    arguments = request["params"]["arguments"]
    commande, permission = arguments["commande"], arguments["permission"]
    with closing(_read_only(home)) as cnx:
        cnx.execute("BEGIN")
        rows = _m1_rows(cnx)
        profile = _profile(cnx)
        events = _events(cnx)
        cnx.rollback()
    by_id = {row.get("ligne_id"): row for row in rows}
    receipts = [row for row in rows if row.get("type_entree") == TYPE_RECU
                and row.get("intention_id") == ack["intention_id"]]
    recu = ack["recu"]
    signal = by_id.get(recu["signal_ligne_id"])
    lead = by_id.get(recu["lead_ligne_id"]) if recu["lead_ligne_id"] is not None else None
    if (len(receipts) != 1 or receipts[0]["recu"] != recu or receipts[0]["permission"] != permission
            or receipts[0]["horodatage"] != commande["recu_le"]
            or receipts[0]["commande_sha256"] != ack["commande_sha256"]
            or receipts[0]["arguments_sha256"] != ack["arguments_sha256"]
            or signal is None or signal.get("type_entree") != "signal"
            or signal.get("signal_id") != "sms:" + commande["message_sid"]
            or (recu["lead_ligne_id"] is not None and (lead is None or lead.get("type_entree") != "lead_emis"))
            or profile != {"id": PROFILE_ID, "revision": permission["revision_profil"], "actif": True,
                           "supprime": False}):
        raise RuntimeError("fictive loss gate cannot prove the independent native outer commit")
    return {
        "rpc_id": request["id"], "tool": RECEVOIR, "status": start["status"], "content_type": content_type,
        "ack": ack, "committed_independent_read": True, "committed_receipt": _receipt(receipts[0]),
        "committed_events": events,
    }


def _observed(application, home: Path, *, lose_receive_once: bool):
    """Observe the real private route without replacing its handler, transaction or result bytes."""
    loss = {"armed": lose_receive_once}

    async def observed(scope, receive, send):
        if scope["type"] != "http" or scope["path"].rstrip("/") != RUNTIME_PATH:
            await application(scope, receive, send)
            return
        method = scope["method"]
        session = (_header(scope.get("headers", []), b"mcp-session-id") or b"").decode("ascii") or None
        state = {"request": None, "selected": False, "start": None, "lost": False, "chunks": 0}
        request_body = bytearray()
        response_body = bytearray()

        async def receive_observed():
            message = await receive()
            if method == "POST" and message["type"] == "http.request" and state["request"] is None:
                request_body.extend(message.get("body", b""))
                if len(request_body) > MAX_BODY_BYTES:
                    raise RuntimeError("bounded fictive SMS request exceeded fixture limit")
                if not message.get("more_body", False):
                    try:
                        parsed = json.loads(request_body)
                    except ValueError:
                        parsed = None
                    request = parsed if isinstance(parsed, dict) else {}
                    state["request"] = request
                    params = request.get("params") if isinstance(request.get("params"), dict) else {}
                    name = params.get("name") if request.get("method") == "tools/call" else None
                    if loss["armed"] and name == RECEVOIR:
                        if request.get("id") is None:
                            raise RuntimeError("fictive loss gate requires the actual JSON-RPC id")
                        # One owned request consumes the gate, even if its later proof fails.
                        loss["armed"] = False
                        state["selected"] = True
                    _emit({"event": "request", "method": request.get("method"), "name": name,
                           "id": request.get("id"), "session": session, "selected_for_loss": state["selected"]})
            return message

        async def send_observed(message):
            kind = message["type"]
            if state["selected"]:
                if state["lost"]:
                    raise RuntimeError("fictive RECEIVE response already lost")
                if kind == "http.response.start":
                    if state["start"] is not None:
                        raise RuntimeError("duplicate fictive response start")
                    state["start"] = {**message, "headers": list(message.get("headers", []))}
                    return
                if kind != "http.response.body":
                    raise RuntimeError("unexpected fictive ASGI response message")
                response_body.extend(message.get("body", b""))
                state["chunks"] += 1
                if len(response_body) > MAX_BODY_BYTES:
                    raise RuntimeError("bounded fictive SMS response exceeded fixture limit")
                if message.get("more_body", False):
                    return
                if state["start"] is None:
                    raise RuntimeError("fictive loss gate has no original headers")
                state["lost"] = True
                body = bytes(response_body)
                try:
                    proof = _committed_receipt(home, state["request"], state["start"], body)
                except Exception as error:
                    _emit({"event": "loss_refused", "reason": str(error)[:200], "session": session})
                    raise
                # Real headers only, then an exception: Uvicorn closes TCP instead of sending a body or HTTP 500.
                await send(state["start"])
                _emit({**proof, "event": "response_lost", "session": session, "headers_forwarded": True,
                       "body_bytes_forwarded": 0, "body_bytes_suppressed": len(body),
                       "body_chunks_suppressed": state["chunks"], "body_sha256": hashlib.sha256(body).hexdigest()})
                raise RuntimeError("FICTIVE_SMS_RECEIVE_RESPONSE_LOST_AFTER_NATIVE_COMMIT")
            await send(message)
            if kind == "http.response.start":
                state["start"] = message
                if method != "POST":
                    _emit({"event": "http", "method": method, "status": message["status"], "session": session})
            elif kind == "http.response.body" and method == "POST":
                response_body.extend(message.get("body", b""))
                if len(response_body) > MAX_BODY_BYTES:
                    raise RuntimeError("bounded fictive SMS response exceeded fixture limit")
                if not message.get("more_body", False):
                    request = state["request"] or {}
                    start = state["start"] or {"status": None, "headers": []}
                    content_type, messages = _messages(start, bytes(response_body))
                    replied = (_header(start.get("headers", []), b"mcp-session-id") or b"").decode("ascii")
                    _emit({"event": "response", "method": request.get("method"), "id": request.get("id"),
                           "name": (request.get("params") or {}).get("name")
                           if request.get("method") == "tools/call" else None,
                           "status": start["status"], "content_type": content_type,
                           "session": session or replied or None,
                           "tool": _tool_ack(request, messages) if request.get("method") == "tools/call" else None})

        await application(scope, receive_observed, send_observed)

    return observed


def serve(*, lose_receive_once: bool) -> None:
    import socket

    import uvicorn

    from opsys import etat, stockage
    from opsys.departements import charger_departements
    from opsys.serveur_mcp import application_http_departements

    home = _home()
    stockage.migrer()
    ca_pem = _ephemeral_tls(home)
    application = application_http_departements(
        charger_departements(ROOT / "departments"), etat.session, os.environ["OPSYS_MCP_JETON"], "127.0.0.1",
        jeton_contexte=os.environ["OPSYS_CONTEXT_MCP_JETON"],
    )
    # Bound once to an ephemeral loopback port and kept: no reservation/re-bind race.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    port = sock.getsockname()[1]

    class OwnedServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                _emit({"event": "ready", "port": port, "ca_pem": ca_pem, "lose_receive_once": lose_receive_once})

    config = uvicorn.Config(
        _observed(application, home, lose_receive_once=lose_receive_once), host="127.0.0.1", port=port,
        ssl_certfile=str(home / "tls-fictif" / "leaf.pem"), ssl_keyfile=str(home / "tls-fictif" / "leaf.key"),
        lifespan="on", log_config=None, access_log=False, timeout_graceful_shutdown=2,
    )
    server = OwnedServer(config)
    # Uvicorn owns SIGTERM: graceful shutdown, then the captured signal is re-raised.
    server.run(sockets=[sock])
    if not server.started:
        raise RuntimeError("fictive SMS native server did not start")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "serve", "inspect", "disable"))
    parser.add_argument("--lose-receive-once", action="store_true")
    parser.add_argument("--revision", type=int)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "serve":
        serve(lose_receive_once=args.lose_receive_once)
    elif args.command == "inspect":
        inspect()
    else:
        if args.revision is None:
            raise RuntimeError("disable requires the expected profile revision")
        disable(args.revision)


if __name__ == "__main__":
    main()
