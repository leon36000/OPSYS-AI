"""Start a loopback-only synthetic MCP issuer/business fixture for cross-language tests."""

from __future__ import annotations

import argparse
import inspect
import json
import os
import signal
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn

from opsys import agent_cfo_grants, agents, contexte, departements, identite, serveur_mcp, stockage

OWNER = "owner.cfo.fixture"
AGENT = "m5-cfo-agent"
PUBLIC_TOKEN = "fixture-public-token-not-a-secret-0001"
PRIVATE_TOKEN = "fixture-runtime-token-not-a-secret-0001"


def _profile_spec() -> dict[str, Any]:
    return {
        "id": AGENT,
        "departement": "m05-financecore",
        "responsabilite": "Préparer un état CFO fictif.",
        "palier_modele": "rapide",
        "outils": sorted(agent_cfo_grants.OUTILS),
        "budget_jour": 10_000,
        "budget_mois": 100_000,
        "limite_tours": 8,
        "limite_reessais": 1,
        "limite_concurrence": 1,
        "declencheurs": [{"type": "manuel"}],
    }


def _provisionner(deps: dict[str, Any]) -> tuple[int, str]:
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, OWNER, "Owner fictif", "fixture-password-not-real-2026", ["nathan_owner"])
        agents.creer(cnx, deps, _profile_spec(), par=OWNER, mutation_id="fixture-create-0001")
        profile = agents.definir_actif(
            cnx, AGENT, deps, True, par=OWNER, mutation_id="fixture-activate-0001", revision_attendue=1
        )
        instance = agent_cfo_grants.instance_id(cnx)
    with (
        contexte.appele_par_appareil(contexte.IdentiteAppelante(OWNER, "nathan_owner", source="console")),
        stockage.transaction() as cnx,
    ):
        agent_cfo_grants.accorder(
            cnx,
            AGENT,
            par=OWNER,
            instance_id=instance,
            revision_attendue=profile["revision"],
            version_attendue=0,
            date_debut_rapport="2026-10-01",
            date_fin_rapport="2026-10-31",
        )
    return profile["revision"], instance


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="m5-cfo-http-fixture-") as root:
        os.environ["OPSYS_HOME"] = str(Path(root) / "opsys")
        os.environ["OPSYS_DEPARTMENTS"] = str(Path(__file__).resolve().parents[2] / "departments")
        os.environ["OPSYS_EVENEMENTS_REPARTITEUR"] = "0"
        stockage.migrer()
        deps = departements.charger_departements()
        revision, _instance = _provisionner(deps)
        business_tool = next(
            tool for tool in deps["m05-financecore"].charger_outils() if tool.nom == "m5_preparer_dossier_decision_cfo"
        )
        app = serveur_mcp.application_http_departements(
            deps, stockage.transaction, PUBLIC_TOKEN, hote="127.0.0.1", jeton_contexte=PRIVATE_TOKEN
        )
        listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listen.bind(("127.0.0.1", 0))
        listen.listen(128)
        port = listen.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listen]}, daemon=True)
        stop = threading.Event()
        previous_handlers = {
            signum: signal.signal(signum, lambda _signum, _frame: stop.set())
            for signum in (signal.SIGINT, signal.SIGTERM)
        }
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            if not server.started:
                raise RuntimeError("fixture MCP loopback ne démarre pas")
            manifest = {
                "baseUrl": f"http://127.0.0.1:{port}",
                "profileId": AGENT,
                "profileRevision": revision,
                "privateIssuerPath": f"/mcp/runtime/{AGENT}",
                "businessPath": "/mcp/m05-financecore",
                "businessHandlerSource": inspect.getfile(business_tool.fonction),
                "privateBearer": PRIVATE_TOKEN,
                "businessBearer": PUBLIC_TOKEN,
                "ownerPerson": OWNER,
                "syntheticOnly": True,
            }
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            args.manifest.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
            args.manifest.chmod(0o600)
            print("READY", flush=True)
            while not stop.wait(0.1) and thread.is_alive():
                pass
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            listen.close()
            stockage.liberer()
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)


if __name__ == "__main__":
    main()
