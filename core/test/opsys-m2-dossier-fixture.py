"""Fictitious Core/M2 DEVICE dossier fixture; no real client or Native identity producer.

Business setup uses public ingestion and canonical approvals. All subsequent
qualification, notes, reassignment and reads go through the acquired Core leases
and the real HTTP server. Observers delegate to original production handlers.
Inspection is a separate stdlib-only SQLite mode=ro connection, never a projector.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
M2 = "m02-revenue-crm"
ADMIN = "nathan"
SELLER_A = "vendeur-a-core-m2-fictif"
SELLER_B = "vendeur-b-core-m2-fictif"
T0 = "2026-10-17T12:00:00+00:00"
LOOKUP = "m2_trouver_client_de_lead"
VIEW = "m2_obtenir_client_360"
LIST = "m2_lister_leads"
REASSIGN = "m2_reassigner_lead"
HANDLERS = "m2-dossier-handlers.jsonl"
DISPATCHES = "m2-dossier-dispatches.jsonl"
ORIGINS = "m2-dossier-origins.json"
LEADS = (
    {"lead_id": "LEAD-CORE-M2-TRANSFERT-FICTIF", "label": "TRANSFERT-FICTIF-821",
     "courriel": "transfert-821@exemple-fictif.test", "ville": "Repentigny"},
    {"lead_id": "LEAD-CORE-M2-TEMOIN-FICTIF", "label": "TEMOIN-FICTIF-739",
     "courriel": "temoin-739@exemple-fictif.test", "ville": "Laval"},
)


def _home() -> Path:
    return Path(os.environ["OPSYS_HOME"]).resolve()


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _append(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"fictif": True, **row}) + "\n")


def _trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []


def prepare() -> None:
    from opsys import approbations, identite, stockage
    from opsys.capacites import Capacites, outils_executables
    from opsys.departements import lire_manifeste

    stockage.migrer()
    with stockage.transaction() as cnx:
        for person, roles in (
            (ADMIN, ["admin", "nathan_owner"]), (SELLER_A, ["seller"]), (SELLER_B, ["seller"]),
        ):
            identite.creer_personne(cnx, person, person + " (fictif)", "mot-de-passe-fictif-assez-long", roles)
    deps = {M2: lire_manifeste(REPO / "departments" / M2)}
    capabilities = Capacites(deps, stockage.transaction)
    executable = outils_executables(deps, stockage.transaction)
    prepared = []
    for lead in LEADS:
        arguments = {
            "contrat": {
                "lead_id": lead["lead_id"], "conversation_id": "conv-" + lead["lead_id"],
                "contact": {"nom": lead["label"], "courriel": lead["courriel"]},
                "type_travaux": "renovation_totale", "ville": lead["ville"],
                "urgence_declaree": True, "canal": "telephone",
            },
            "horodatage": T0,
        }
        proposal = capabilities.appeler("m2_ingerer_lead", arguments)
        if proposal.get("statut") != "en_attente_approbation":
            raise RuntimeError("public M2 ingestion must request a canonical approval")
        with stockage.transaction() as cnx:
            decision = approbations.decider(cnx, proposal["demande_id"], True, ADMIN, executable, deps)
        if decision.get("statut") != "executee" or decision["reponse"]["resultat"].get("accepte") is not True:
            raise RuntimeError("canonical M2 ingestion approval failed")
        prepared.append({**lead, "client_id": decision["reponse"]["resultat"]["client_id"],
                         "demande_id": proposal["demande_id"]})
    print(json.dumps({"fictif": True, "leads": prepared}))


def inspect() -> None:
    """One independent SELECT-only transaction; compare every user table for T0 purity."""
    with closing(sqlite3.connect((_home() / "opsys.db").as_uri() + "?mode=ro", uri=True)) as cnx:
        cnx.row_factory = sqlite3.Row
        cnx.execute("PRAGMA query_only=ON")
        cnx.execute("BEGIN")
        names = [r[0] for r in cnx.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        tables = {}
        for name in names:
            rows = [dict(r) for r in cnx.execute('SELECT * FROM "' + name.replace('"', '""') + '"')]
            tables[name] = sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))
        people = {person: {
            "active": cnx.execute("SELECT actif FROM personnes WHERE identifiant=?", (person,)).fetchone()[0],
            "roles": [r[0] for r in cnx.execute(
                "SELECT role FROM roles WHERE identifiant=? ORDER BY role", (person,)
            )],
        } for person in (ADMIN, SELLER_A, SELLER_B)}
    registers = tables["registres_maillons"]
    principal = sorted((r for r in registers if r["departement"] == M2 and r["registre"] == "principal"),
                       key=lambda row: row["rang"])
    # Only this canonical mutation's ledger, event, claim, approval trace and audit may change.
    protected = {name: _digest(rows) for name, rows in tables.items()
                 if name not in {"registres_maillons", "evenements_sortants", "mutations_appliquees",
                                 "approbations", "journal"}}
    protected["registers_except_m2_principal"] = _digest([
        r for r in registers if not (r["departement"] == M2 and r["registre"] == "principal")
    ])
    origins = _home() / ORIGINS
    print(json.dumps({
        "fictif": True, "tables": {name: _digest(rows) for name, rows in tables.items()},
        "protected": protected, "people": people, "principal_rows": principal,
        "pieces": [json.loads(r["maillon"]) for r in principal],
        "events": tables["evenements_sortants"], "claims": tables["mutations_appliquees"],
        "approvals": tables["approbations"], "handlers": _trace(_home() / HANDLERS),
        "dispatches": _trace(_home() / DISPATCHES),
        "origins": json.loads(origins.read_text()) if origins.exists() else {},
    }))


def _observe_original_handlers() -> None:
    import dataclasses
    import functools

    import m2_revenue_crm.outils as tools

    original_factory = tools.outils
    watched = {LOOKUP, VIEW, LIST, REASSIGN}

    def counted(original, name):
        @functools.wraps(original)
        def handler(**arguments):
            row = {"tool": name, "arguments_sha256": _digest(arguments)}
            _append(_home() / HANDLERS, {**row, "event": "entered"})
            result = original(**arguments)
            _append(_home() / HANDLERS, {**row, "event": "completed"})
            return result
        return handler

    @functools.wraps(original_factory)
    def observed_factory(*args, **kwargs):
        originals = tuple(original_factory(*args, **kwargs))
        if any(sum(tool.nom == name for tool in originals) != 1 for name in watched):
            raise RuntimeError("each watched public M2 original handler must occur exactly once")
        return tuple(dataclasses.replace(tool, fonction=counted(tool.fonction, tool.nom))
                     if tool.nom in watched else tool for tool in originals)

    tools.outils = observed_factory


def _origins() -> dict:
    import importlib

    modules = {"opsys.capacites": "src/opsys/capacites.py", "opsys.serveur_mcp": "src/opsys/serveur_mcp.py"}
    for name in ("outils", "acces", "assignation", "clients", "liste_leads", "segments"):
        modules["m2_revenue_crm." + name] = f"departments/{M2}/src/m2_revenue_crm/{name}.py"
    result = {}
    for name, relative in modules.items():
        actual = Path(importlib.import_module(name).__file__).resolve()
        if actual != (REPO / relative).resolve():
            raise RuntimeError("M2 dossier fixture loaded another checkout: " + name)
        result[name] = {"path": str(actual), "sha256": hashlib.sha256(actual.read_bytes()).hexdigest()}
    return result


def serve(port: int) -> None:
    import uvicorn

    from opsys import etat, stockage
    from opsys.departements import charger_departements
    from opsys.serveur_mcp import application_http_departements

    _observe_original_handlers()
    (_home() / ORIGINS).write_text(json.dumps(_origins()))
    stockage.migrer()
    application = application_http_departements(
        charger_departements(), etat.session, os.environ["OPSYS_MCP_JETON"], "127.0.0.1",
        jeton_contexte=os.environ["OPSYS_CONTEXT_MCP_JETON"],
    )

    async def observed(scope, receive, send):
        body = bytearray()

        async def receive_observed():
            message = await receive()
            if (scope["type"] == "http" and scope["method"] == "POST"
                    and scope["path"].rstrip("/") == "/mcp/" + M2 and message["type"] == "http.request"):
                body.extend(message.get("body", b""))
                if len(body) > 64 * 1024:
                    raise RuntimeError("bounded fictive M2 request exceeded fixture limit")
                if not message.get("more_body", False):
                    request = json.loads(body)
                    params = request.get("params") if isinstance(request.get("params"), dict) else {}
                    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
                    _append(_home() / DISPATCHES, {
                        "method": request.get("method"), "tool": params.get("name"),
                        "arguments": params.get("arguments", {}), "meta": meta,
                    })
            return message

        await application(scope, receive_observed, send)

    uvicorn.run(observed, host="127.0.0.1", port=port, log_level="info")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "inspect", "serve"))
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "inspect":
        inspect()
    else:
        if args.port is None:
            raise RuntimeError("serve requires an owned loopback port")
        serve(args.port)


if __name__ == "__main__":
    main()
