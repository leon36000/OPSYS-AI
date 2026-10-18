"""Fictitious M9 dossier fixture; real storage, identities, manifests and MCP app.
No product policy is overridden. Not a real M5/M8 producer or full M9 report proof.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import select

from opsys import identite, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, META, REGISTRES

FICTIF = True
M9 = "m09-strategic-intelligence"
TOOL = "m9_preparer_dossier_direction"
SEEDS = [
    {
        "module_source": "M5-fictif",
        "horodatage": "2026-10-18T03:00:00-04:00",
        "valeurs": {"chantier_fictif": "équipe A fictive"},
    },
    {
        "module_source": "M5-fictif",
        "horodatage": "2026-10-18T07:00:00Z",
        "valeurs": {"chantier_fictif": "équipe B fictive"},
    },
    {
        "module_source": "M8-fictif",
        "horodatage": "2026-10-18T07:01:00Z",
        "valeurs": {"materiau_fictif": "gouttière fictive reçue"},
    },
]


def inspect():
    with stockage.transaction() as cnx:
        tables = {
            n: sorted(
                json.dumps(dict(r), sort_keys=True, ensure_ascii=False, default=str)
                for r in cnx.execute(select(t)).mappings()
            )
            for n, t in META.tables.items()
        }
        chain = list(stockage.maillons(M9, "snapshots"))
    business = {t.name: tables[t.name] for t in (REGISTRES, APPROBATIONS, EVENEMENTS_SORTANTS, EVENEMENTS_RECUS)}
    print(json.dumps({"fictif": True, "tables": tables, "business": business, "chain": chain}, ensure_ascii=False))


def prepare(config):
    from m9_strategic_intelligence import outils

    from opsys import openclaw

    stockage.migrer()
    with stockage.transaction() as cnx:
        for who, roles in [("admin-dossier-fictif", ["admin"]), ("employee-dossier-fictif", ["employee"])]:
            identite.creer_personne(cnx, who, who, "mot-de-passe-dossier-fictif", roles)
    ingest = next(o for o in outils.outils() if o.nom == "m9_etat_consolide")
    for seed in SEEDS:
        result = executer_atomique(ingest, {"snapshot": seed})
        assert result["ok"] is True, result
    deps = charger_departements()
    roles = {"roles": openclaw.roles_outils(deps), "serveurs": openclaw.serveurs_outils(deps)}
    assert TOOL in roles["roles"]["admin"] and TOOL not in roles["roles"]["employee"]
    assert roles["serveurs"][TOOL] == "opsys_m9"
    openclaw._ecrire_json(Path(config) / "opsys/roles.json", roles)
    inspect()


class Observer:
    def __init__(self, app, log):
        self.app, self.log = app, log

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        captured = bytearray()

        async def receiving():
            message = await receive()
            if message["type"] == "http.request":
                captured.extend(message.get("body", b""))
                if not message.get("more_body", False) and captured:
                    request = json.loads(captured)
                    if request.get("method") == "tools/call":
                        p = request.get("params", {})
                        row = {
                            "fictif": True,
                            "path": scope["path"],
                            "method": request["method"],
                            "name": p.get("name"),
                            "meta": p.get("_meta", {}),
                        }
                        with self.log.open("a", encoding="utf-8") as f:
                            f.write(json.dumps(row, sort_keys=True) + "\n")
            return message

        await self.app(scope, receiving, send)


def serve(port):
    import uvicorn

    from opsys import etat
    from opsys.serveur_mcp import application_http_departements

    stockage.migrer()
    app = application_http_departements(
        charger_departements(),
        etat.session,
        os.environ["OPSYS_MCP_JETON"],
        "127.0.0.1",
        jeton_contexte=os.environ["OPSYS_CONTEXT_MCP_JETON"],
    )
    uvicorn.run(
        Observer(app, Path(os.environ["OPSYS_HOME"]) / "dispatches.jsonl"),
        host="127.0.0.1",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "inspect", "serve", "digest"])
    p.add_argument("--payload")
    p.add_argument("--config")
    p.add_argument("--port", type=int)
    a = p.parse_args()
    if a.action == "prepare":
        prepare(a.config)
    elif a.action == "inspect":
        inspect()
    elif a.action == "digest":
        payload = json.loads(a.payload)
        payload.pop("dossier_id")
        print(
            hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
            ).hexdigest()
        )
    else:
        serve(a.port)
