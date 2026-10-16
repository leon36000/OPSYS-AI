"""Local-only fixture for the Core -> real Python target ticket HTTP test."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from m2_revenue_crm import ingestion
from m2_revenue_crm import registre as registre_m2
from m10_memoire import liaison as liaison_m10
from m10_memoire import registre as registre_m10

from opsys import approbations, identite, stockage
from opsys.departements import charger_departements, tous_les_outils

LEAD_ID = "LEAD-CORE-C02"
SESSION_KEY = "agent:m02-revenue-crm:webchat:direct:core-c02"
M3_SESSION_KEY = "agent:m03-estimation:webchat:direct:core-c02-n4"
M3_QUOTE_ID = "DEV-CORE-C02-N4"
M3_REVOKED_QUOTE_ID = "DEV-CORE-C02-N4-REVOKED"
TIMESTAMP = "2026-09-30T12:00:00+00:00"
M9 = "m09-strategic-intelligence"
M9_SESSION_KEY = "agent:m09-strategic-intelligence:webchat:direct:core-m9-fictif"
M9_RESPONSIBLE = "responsable-core-m9-fictif"
M9_OPEN = "m9_ouvrir_suivi_decision"
M9_TOOLS = (M9_OPEN, "m9_preparer_suivi_decision", "m9_lire_suivi_decision")


def _m9_source(suffix: str) -> dict:
    """Fictive M3/M4 inputs; their actual M8 publication and M10 receipts are mandatory."""
    return {
        "fictif": True,
        "devis": {
            "devis_id": "devis-core-m9-fictif-" + suffix,
            "lead_id": "lead-core-m9-fictif-" + suffix, "chantier_id": None,
            "lignes": [{"reference_ligne": "ligne-fictive", "description": "Gouttières fictives",
                        "quantite": "40", "unite": "pi", "prix_unitaire": "15.00",
                        "prix_ligne": "600.00", "reference_besoin_materiau": None}],
            "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25",
            "duree_estimee_minutes": "60", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
        },
        "wct": {
            "wct_id": "wct-core-m9-fictif-" + suffix,
            "intervention_id": "intervention-core-m9-fictive-" + suffix,
            "lead_id": "lead-core-m9-fictif-" + suffix, "technicien_id": M9_RESPONSIBLE,
            "horodatage_completion": "2026-09-27T15:00:00-04:00",
            "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
            "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None,
            "hash_maillon": "preuve-terrain-core-fictive-" + suffix,
            "consommateurs_cibles": ["M8", "M10"],
            "devis_id": "devis-core-m9-fictif-" + suffix, "statut": "completed_verified",
        },
    }


def _link_m9(suffix: str) -> None:
    with stockage.transaction():
        line, refused = liaison_m10.lier_session_affaire(
            M9_SESSION_KEY, "lead-core-m9-fictif-" + suffix, "nathan-fixture",
            "admin", "appareil", "Liaison Core M9 fictive", TIMESTAMP,
            registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires")),
        )
        if refused is not None or line is None:
            raise RuntimeError(f"canonical M9 affair link refused: {refused!r}")


def prepare_m9(*, postflight_depot: bool = False) -> None:
    import yaml
    from m8_analytics import outils as outils_m8
    from m9_strategic_intelligence.encodage import empreinte

    from opsys import evenements, openclaw

    prepare()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, M9_RESPONSIBLE, "Responsable fictif",
                                "mot-de-passe-responsable-core-fictif", ["employee"])
    manifest = Path(os.environ["OPSYS_HOME"]) / "m8-seuil-core-fictif.yaml"
    manifest.write_text(yaml.safe_dump({"configuration": {
        "seuils_alerte": {"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50}},
    }}), encoding="utf-8")
    manifest.chmod(0o600)
    # Process-local fixture override; no repository manifest or live provider is modified.
    outils_m8._MANIFESTE = manifest
    departments = charger_departements(Path(__file__).resolve().parents[2] / "departments")
    active = {name: departments[name] for name in ("m08-analytics", M9, "m10-memoire")}
    for suffix in ("A", "B"):
        source = _m9_source(suffix)
        assert source["fictif"] is True
        evenements.publier("m3.devis_accepte", "m03-estimation", source["devis"])
        evenements.publier("m4.travaux_termines", "m04-field-ops", source["wct"],
                           evenement_id=source["wct"]["wct_id"])
    for _ in range(3):
        result = evenements.repartir(active, maintenant="2026-09-27T20:00:00+00:00")
        assert result["echecs"] == result["quarantaines"] == 0, result
    arguments = {}
    with stockage.transaction():
        for suffix in ("A", "B"):
            [alert] = [a for a in stockage.maillons(M9, "alertes_m8")
                       if a["preuve"].get("wct_id") == "wct-core-m9-fictif-" + suffix]
            assert alert["type_alerte"] == "MESURE-SEUIL-FRANCHI"
            assert alert["preuve"]["valeur"] == "100.00"
            arguments[suffix] = {
                "evenement_id": alert["evenement_id"], "empreinte_source": empreinte(alert),
                "action": "Revoir les causes de durée du chantier fictif",
                "responsable_id": M9_RESPONSIBLE, "echeance": "2026-10-20T09:00:00-04:00",
            }
    _link_m9("A")
    generated = openclaw._configuration_contexte(
        departments, {M9: [M9_OPEN] if postflight_depot else []}, [M9],
    )
    assert generated is not None
    print(json.dumps({
        "fictif": True, "session_key": M9_SESSION_KEY,
        "affairs": {suffix: "lead-core-m9-fictif-" + suffix for suffix in ("A", "B")},
        "arguments": arguments,
        "generated_context": {
            "agent": generated["agents"][M9],
            "niveaux": {name: generated["niveaux"][name] for name in M9_TOOLS},
            "cibles": {name: generated["cibles"][name] for name in M9_TOOLS
                       if name in generated["cibles"]},
        },
    }))


def _committed_m9_response(home: Path, request: dict, start: dict, body: bytes) -> dict:
    """Read a real result and independently verify its commit before losing its transport."""
    import re
    import sqlite3
    from contextlib import closing

    from opsys import idempotence

    headers = dict(start["headers"])
    content_type = headers.get(b"content-type", b"").split(b";", 1)[0]
    text = body.decode("utf-8")
    if content_type == b"application/json":
        messages = [json.loads(text)]
    elif content_type == b"text/event-stream":
        messages = []
        for block in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
            data = [line[5:].removeprefix(" ") for line in block.splitlines()
                    if line.startswith("data:")]
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
    if native.get("ok") is not True or native.get("statut") != "en_attente_approbation":
        raise RuntimeError("fictive response-loss gate requires an actual pending approval")
    request_id = native["demande_id"]
    arguments = request["params"]["arguments"]
    # This connection is distinct from the handler's SQLAlchemy transaction/ContextVar.
    with closing(sqlite3.connect((home / "opsys.db").as_uri() + "?mode=ro", uri=True)) as cnx:
        cnx.row_factory = sqlite3.Row
        cnx.execute("BEGIN")
        row = cnx.execute(
            "SELECT a.statut AS approval_status, a.departement, a.outil, a.arguments, "
            "a.ticket_cible_hash, t.ticket_hash, t.demande_id, t.statut AS ticket_status, "
            "t.affaire_id, t.cle_session, t.empreinte_arguments "
            "FROM approbations a JOIN liaisons_tickets t ON t.ticket_hash=a.ticket_cible_hash "
            "WHERE a.id=?", (request_id,),
        ).fetchone()
        roles = {r[0] for r in cnx.execute(
            "SELECT r.role FROM roles r JOIN personnes p ON p.identifiant=r.identifiant "
            "WHERE p.identifiant='nathan-fixture' AND p.actif=1",
        )}
        if (row is None or row["approval_status"] != "en_attente"
                or (row["departement"], row["outil"]) != (M9, M9_OPEN)
                or json.loads(row["arguments"]) != arguments
                or row["ticket_status"] != "scelle" or row["demande_id"] != request_id
                or row["cle_session"] != M9_SESSION_KEY or not row["affaire_id"]
                or row["empreinte_arguments"] != idempotence.empreinte_arguments(arguments)
                or re.fullmatch(r"[a-f0-9]{64}", row["ticket_hash"]) is None
                or not {"admin", "nathan_owner"} <= roles):
            raise RuntimeError("fictive response-loss gate cannot prove the independent native commit")
    return {
        "fictif": True, "request_id": request_id, "ticket_hash": row["ticket_hash"],
        "affaire_id": row["affaire_id"], "cle_session": row["cle_session"],
        "empreinte_arguments": row["empreinte_arguments"], "owner_active": True,
        "independent_committed_read_before_headers": True, "response_body_forwarded_bytes": 0,
        "native_response_bytes_buffered": len(body),
    }


def serve_m9_observed(port: int, intent_database: Path, *, lose_response: bool = False) -> None:
    """Observe the real business HTTP boundary without replacing its native handler/result."""
    import sqlite3
    from contextlib import closing

    import uvicorn

    from opsys import etat
    from opsys.serveur_mcp import application_http_departements

    home = Path(os.environ["OPSYS_HOME"]).resolve()
    database = intent_database.resolve()
    if not database.is_relative_to(home / "core-state") or not database.is_file():
        raise RuntimeError("expected this fixture's actual Core transcript SQLite database")
    log_path = home / "m9-business-dispatches.jsonl"
    log_path.touch(mode=0o600, exist_ok=False)
    stockage.migrer()
    application = application_http_departements(
        charger_departements(), etat.session, os.environ["OPSYS_MCP_JETON"], "127.0.0.1",
        jeton_contexte=os.environ["OPSYS_CONTEXT_MCP_JETON"],
    )
    loss_available = lose_response

    async def observed(scope, receive, send):
        nonlocal loss_available
        body = bytearray()
        selected_request = None
        response_start = None
        response_body = bytearray()

        async def receive_observed():
            nonlocal selected_request, loss_available
            message = await receive()
            if (scope["type"] == "http" and scope["method"] == "POST"
                    and scope["path"].rstrip("/") == "/mcp/" + M9
                    and message["type"] == "http.request"):
                body.extend(message.get("body", b""))
                if len(body) > 64 * 1024:
                    raise RuntimeError("bounded fictive M9 request exceeded fixture limit")
                if not message.get("more_body", False):
                    request = json.loads(body)
                    if request.get("method") == "tools/call" and request.get("params", {}).get("name") == M9_OPEN:
                        if loss_available:
                            if request.get("id") is None:
                                raise RuntimeError("fictive response-loss gate requires the actual RPC id")
                            selected_request = request
                            # A single owned request consumes the gate, even if its instrumentation fails.
                            loss_available = False
                        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as cnx:
                            intents = [{"fact_key": key, "state": state} for key, state in cnx.execute(
                                "SELECT fact_key, state FROM opsys_postflight_intents ORDER BY fact_key",
                            )]
                            [outbox_count] = cnx.execute("SELECT COUNT(*) FROM opsys_postflight_outbox").fetchone()
                        # Only synthetic correlation/state is logged, never headers, tickets or arguments.
                        with log_path.open("a", encoding="utf-8") as stream:
                            stream.write(json.dumps({
                                "fictif": True, "intents": intents, "outbox_count": outbox_count,
                            }) + "\n")
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
                    proof = _committed_m9_response(home, selected_request, response_start, bytes(response_body))
                    # Sending the real headers before the exception makes Uvicorn close TCP,
                    # rather than substitute an HTTP500. No tool-result body crosses this seam.
                    await send(response_start)
                    with (home / "m9-response-lost.json").open("x", encoding="utf-8") as stream:
                        stream.write(json.dumps({**proof, "original_headers_forwarded": True}) + "\n")
                    raise RuntimeError("FICTIVE_M9_RESPONSE_LOST_AFTER_NATIVE_COMMIT")
            else:
                raise RuntimeError("unexpected fictive ASGI response message")

        await application(scope, receive_observed, send_observed)

    uvicorn.run(observed, host="127.0.0.1", port=port, log_level="info")


def install_m9_sql_trace(path: Path) -> None:
    """Observe real SQLAlchemy DML/DDL, including no-op writes, without storing SQL or parameters."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    path.touch(mode=0o600, exist_ok=False)

    def observe(connection, cursor, statement, parameters, context, executemany):
        operation = statement.lstrip().split(None, 1)[0].upper()
        for flag, verb in (("isinsert", "INSERT"), ("isupdate", "UPDATE"), ("isdelete", "DELETE")):
            if getattr(context, flag, False):
                operation = verb
                break
        if operation in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}:
            # Errors propagate through the execution event; a failed observer cannot report zero.
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"fictif": True, "operation": operation}) + "\n")

    event.listen(Engine, "before_cursor_execute", observe)


def serve_m9_sql_observed(port: int) -> None:
    import uvicorn

    from opsys import etat
    from opsys.serveur_mcp import application_http_departements

    install_m9_sql_trace(Path(os.environ["OPSYS_HOME"]) / "m9-sql-writes.jsonl")
    stockage.migrer()
    application = application_http_departements(
        charger_departements(), etat.session, os.environ["OPSYS_MCP_JETON"], "127.0.0.1",
        jeton_contexte=os.environ["OPSYS_CONTEXT_MCP_JETON"],
    )
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="info")


def inspect_m9() -> None:
    from sqlalchemy import func, select

    from opsys import etat
    from opsys.stockage.schema import APPROBATIONS, LIAISONS_TICKETS, META

    with stockage.transaction() as cnx:
        owner = identite.personne_active(cnx, "nathan-fixture")
        owner_active = owner is not None and {"admin", "nathan_owner"} <= owner.roles
        link = liaison_m10.liaison_courante(
            M9_SESSION_KEY,
            registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires")),
        )
        demands = [d for d in approbations.lister(cnx) if d["outil"] == M9_OPEN]
        requests = [{"id": d["id"], "status": d["statut"]} for d in demands]
        bindings = []
        for demand in demands:
            seal_hash = cnx.execute(select(APPROBATIONS.c.ticket_cible_hash).where(
                APPROBATIONS.c.id == demand["id"],
            )).scalar_one()
            ticket = cnx.execute(select(
                LIAISONS_TICKETS.c.ticket_hash, LIAISONS_TICKETS.c.demande_id,
                LIAISONS_TICKETS.c.statut, LIAISONS_TICKETS.c.departement,
                LIAISONS_TICKETS.c.outil, LIAISONS_TICKETS.c.affaire_id,
                LIAISONS_TICKETS.c.cle_session, LIAISONS_TICKETS.c.ligne_liaison_id,
                LIAISONS_TICKETS.c.empreinte_arguments,
            ).where(LIAISONS_TICKETS.c.ticket_hash == seal_hash)).mappings().one_or_none()
            bindings.append({
                "demande_id": demand["id"], "ticket_cible_hash": seal_hash,
                "arguments": demand["arguments"], "decide_par": demand["decide_par"],
                "decide_role": demand["decide_role"],
                "ticket": dict(ticket) if ticket is not None else None,
            })
        decisions = [e for e in etat.lire_journal(cnx) if e["action"] == "approbation.approuver"]
        followups = list(stockage.maillons(M9, "suivi_decisions"))
        tickets = int(cnx.execute(select(func.count()).select_from(LIAISONS_TICKETS)).scalar_one())
        snapshot = {name: sorted(json.dumps(dict(row), sort_keys=True, default=str)
                                 for row in cnx.execute(select(table)).mappings())
                    for name, table in META.tables.items()}
    print(json.dumps({
        "owner_active": owner_active, "linked_affair": link["affaire_id"] if link else None,
        "requests": requests, "followups": followups, "tickets": tickets,
        "approval_bindings": bindings, "decision_audits": decisions,
        "tables_digest": hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest(),
    }))


def refuse_m9_approval(request_id: str) -> None:
    from opsys import liaison_cibles

    try:
        approve(request_id)
    except liaison_cibles.CibleRefusee as error:
        with stockage.transaction() as cnx:
            owner = identite.personne_active(cnx, "nathan-fixture")
            assert owner is not None and {"admin", "nathan_owner"} <= owner.roles
        assert any(word in str(error) for word in ("révoquée", "remplacée"))
        print(json.dumps({"refused": True, "reason": str(error), "owner_active": True}))
    else:
        raise RuntimeError("stale M9 approval unexpectedly succeeded")


def prepare() -> None:
    stockage.migrer()
    contrat = {
        "lead_id": LEAD_ID,
        "conversation_id": "CONV-CORE-C02",
        "contact": {"nom": "Client fictif", "telephone": "555-0101", "courriel": "x@example.test"},
        "type_travaux": "renovation_totale",
        "ville": "Québec",
        "urgence_declaree": False,
        "canal": "telephone",
    }
    registre = registre_m2.Registre()
    _, refus = ingestion.ingerer(contrat, registre, TIMESTAMP)
    if refus is not None:
        raise RuntimeError("synthetic M2 lead fixture was refused")
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx,
            "nathan-fixture",
            "Nathan Fixture",
            "synthetic-password-never-used-1234",
            ["admin", "nathan_owner"],
        )
        stockage.maillons("m02-revenue-crm", "principal").extend(registre.lire())
        affaires = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        lien, refus = liaison_m10.lier_session_affaire(
            SESSION_KEY,
            LEAD_ID,
            "nathan-fixture",
            "admin",
            "appareil",
            "liaison de test synthétique",
            TIMESTAMP,
            affaires,
        )
    if refus is not None or lien is None:
        raise RuntimeError(f"synthetic M10 case link fixture was refused: {refus!r}")


def revoke() -> None:
    with stockage.transaction():
        affaires = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        courant = liaison_m10.liaison_courante(SESSION_KEY, affaires)
        if courant is None:
            raise RuntimeError("expected an active synthetic M10 link")
        _, refus = liaison_m10.revoquer_session_affaire(
            SESSION_KEY,
            courant["ligne_id"],
            "nathan-fixture",
            "admin",
            "appareil",
            "révocation de test synthétique",
            "2026-09-30T12:01:00+00:00",
            affaires,
        )
    if refus is not None:
        raise RuntimeError("synthetic M10 link revocation was refused")


def prepare_m3() -> None:
    """Seed one canonical M3 draft and a seller-linked M10 session for the N4 HTTP scenario."""
    prepare()
    from m3_estimation import outils as outils_m3

    from opsys import approbations
    from opsys.outils import executer_atomique

    outil_creation = next(outil for outil in outils_m3.outils() if outil.nom == "m3_creer_devis")
    for devis_id in (M3_QUOTE_ID, M3_REVOKED_QUOTE_ID):
        resultat = executer_atomique(
            outil_creation,
            {
                "devis_id": devis_id,
                "lead_id": LEAD_ID,
                "chantier_id": None,
                "lignes": [
                    {
                        "description": "Travaux synthétiques de test",
                        "quantite": "1",
                        "unite": "forfait",
                        "cout_unitaire": "100.00",
                        "reference_besoin_materiau": None,
                    }
                ],
                "taux_marge": "0.20",
                "horodatage": TIMESTAMP,
            },
        )
        if not resultat.get("ok") or not resultat.get("resultat", {}).get("accepte"):
            raise RuntimeError("synthetic M3 quote fixture was refused")

    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx,
            "seller-fixture",
            "Seller Fixture",
            "synthetic-password-never-used-5678",
            ["seller"],
        )
        affaires = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        lien, refus = liaison_m10.lier_session_affaire(
            M3_SESSION_KEY,
            LEAD_ID,
            "nathan-fixture",
            "admin",
            "appareil",
            "liaison M3 de test synthétique",
            TIMESTAMP,
            affaires,
        )
        approbations.fixer_mode(cnx, "m03-estimation", "autonome", "nathan-fixture")
    if refus is not None or lien is None:
        raise RuntimeError(f"synthetic M3 M10 link fixture was refused: {refus!r}")


def inspect_m3() -> None:
    from m3_estimation import outils as outils_m3
    from sqlalchemy import func, select

    from opsys import approbations
    from opsys.stockage.schema import LIAISONS_TICKETS

    with stockage.transaction() as cnx:
        statuses = {}
        for devis_id in (M3_QUOTE_ID, M3_REVOKED_QUOTE_ID):
            devis, verdict = outils_m3.devis_durable.lire_devis(
                outils_m3.registre_devis_production(), devis_id
            )
            if verdict is not None or devis is None:
                raise RuntimeError("synthetic M3 quote could not be read")
            statuses[devis_id] = devis["statut"]
        demandes = [
            demande
            for demande in approbations.lister(cnx)
            if demande["outil"] == "m3_demander_envoi_devis"
            and demande["arguments"].get("devis_id") in (M3_QUOTE_ID, M3_REVOKED_QUOTE_ID)
        ]
        tickets = int(cnx.execute(select(func.count()).select_from(LIAISONS_TICKETS)).scalar_one())
    print(json.dumps({
        "quote_statuses": statuses,
        "requests": [{"status": d["statut"], "devis_id": d["arguments"]["devis_id"]} for d in demandes],
        "tickets": tickets,
    }))


def revoke_seller_role() -> None:
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "seller-fixture", "seller")


def inspect_state() -> None:
    with stockage.transaction():
        principal = registre_m2.Registre(maillons=stockage.maillons("m02-revenue-crm", "principal"))
        interactions = [
            maillon
            for maillon in principal.lire()
            if maillon.get("type_entree") == "interaction" and maillon.get("lead_id") == LEAD_ID
        ]
        cases = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        linked = liaison_m10.liaison_courante(SESSION_KEY, cases) is not None
    print(json.dumps({"interactions": len(interactions), "linked": linked}))


def approve(demande_id: str) -> None:
    departements = charger_departements()
    outils = {nom: outil for nom, (_, outil) in tous_les_outils(departements.values()).items()}
    with stockage.transaction() as cnx:
        decision = approbations.decider(
            cnx,
            demande_id,
            True,
            "nathan-fixture",
            outils,
            departements,
            "approbation synthétique du test d'intégration",
            role="nathan_owner",
        )
    print(json.dumps({
        "statut": decision.get("statut"),
        "reponse": decision.get("reponse"),
    }))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("prepare", "prepare-m3", "prepare-m9", "serve-m9-observed", "serve-m9-sql-observed",
                 "switch-m9-b", "inspect-m9",
                 "refuse-m9-approval", "revoke", "inspect", "inspect-m3", "revoke-seller-role", "approve"),
    )
    parser.add_argument("--request-id")
    parser.add_argument("--postflight-depot", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--intent-db", type=Path)
    parser.add_argument("--lose-m9-response", action="store_true")
    args = parser.parse_args()
    command = args.command
    if command == "prepare":
        prepare()
    elif command == "prepare-m3":
        prepare_m3()
    elif command == "prepare-m9":
        prepare_m9(postflight_depot=args.postflight_depot)
    elif command == "serve-m9-observed":
        if args.port is None or args.intent_db is None:
            raise RuntimeError("serve-m9-observed requires the owned port and Core database")
        serve_m9_observed(args.port, args.intent_db, lose_response=args.lose_m9_response)
    elif command == "serve-m9-sql-observed":
        if args.port is None:
            raise RuntimeError("serve-m9-sql-observed requires the owned port")
        serve_m9_sql_observed(args.port)
    elif command == "switch-m9-b":
        _link_m9("B")
    elif command == "inspect-m9":
        inspect_m9()
    elif command == "refuse-m9-approval":
        if not args.request_id:
            raise RuntimeError("refuse-m9-approval requires the synthetic request id")
        refuse_m9_approval(args.request_id)
    elif command == "revoke":
        revoke()
    elif command == "inspect":
        inspect_state()
    elif command == "inspect-m3":
        inspect_m3()
    elif command == "revoke-seller-role":
        revoke_seller_role()
    else:
        if not args.request_id:
            raise RuntimeError("approve requires the synthetic request id")
        approve(args.request_id)


if __name__ == "__main__":
    main()
