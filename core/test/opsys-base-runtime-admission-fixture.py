"""Fictitious base-agent provisioning for the real Core/Python HTTP budget junction."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
for department in sorted((REPO / "departments").glob("m*-*/src")):
    sys.path.insert(0, str(department))

DEP = "m09-strategic-intelligence"
PROFILE = f"base-{DEP}"


def prepare(port: int) -> None:
    from opsys import agents_base, identite, openclaw, stockage
    from opsys.departements import Budget, charger_departements

    stockage.migrer()
    department = charger_departements()[DEP]
    departments = {DEP: replace(department, budget=Budget(32, 1_000))}
    with stockage.transaction() as connection:
        identite.creer_personne(connection, "base-http-admin-fictif", "Admin QA fictif",
                               "qa-only-base-http-password-2026", ["admin"])
        profiles = agents_base.provisionner(
            connection, departments, par="base-http-admin-fictif", limite_tours=4, limite_reessais=1,
            limite_concurrence=1, budget_entreprise_jour=10_000, budget_entreprise_mois=100_000,
        )
    origin = f"http://127.0.0.1:{port}"
    files = openclaw.generer(
        departments, Path(os.environ["OPSYS_HOME"]) / "core-config",
        {tier: {"provider": "anthropic", "model": "qa-no-provider"}
         for tier in ("rapide", "standard", "fort", "local")},
        url_mcp=f"{origin}/mcp", origine_http_mcp_autorisee=origin,
        environ={"OPSYS_EMBEDDINGS_URL": "http://embeddings-qa.invalid:11434/v1",
                 "OPSYS_EMBEDDINGS_MODELE": "qa-no-embedding-call"},
        cnx_factory=stockage.transaction,
    )
    generated = {"agents": json.loads(files["agents"].read_text()),
                 "mcp": json.loads(files["mcp"].read_text()),
                 "profile": profiles[DEP]}
    (Path(os.environ["OPSYS_HOME"]) / "base-runtime-export.json").write_text(json.dumps(generated))
    stockage.liberer()


def serve(port: int) -> None:
    import hashlib
    import runpy

    import opsys.admission_agents
    import opsys.capacites

    modules = (opsys.admission_agents, opsys.capacites)
    provenance = {}
    for module in modules:
        path = Path(module.__file__).resolve()
        if not path.is_relative_to(REPO / "src"):
            raise RuntimeError("QA server imported outside the candidate source")
        provenance[module.__name__] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (Path(os.environ["OPSYS_BASE_RUNTIME_EVIDENCE"]) / "PYTHON-SERVER-PROVENANCE.json").write_text(
        json.dumps(provenance)
    )
    sys.argv = ["opsys.serveur_mcp", "--http", "--hote", "127.0.0.1", "--port", str(port)]
    runpy.run_module("opsys.serveur_mcp", run_name="__main__")


def deactivate() -> None:
    from opsys import agents, stockage
    from opsys.departements import charger_departements

    with stockage.transaction() as connection:
        agents.definir_actif(connection, PROFILE, charger_departements(), False,
                            par="base-http-admin-fictif", mutation_id="base-http-disable-common-qa",
                            revision_attendue=2)
    stockage.liberer()


def inspect() -> None:
    database = Path(os.environ["OPSYS_HOME"]) / "opsys.db"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT agent_id, execution_id, cycle_id, statut, tokens_plafond, tokens_reels "
            "FROM agents_reservations ORDER BY execution_id"
        ).fetchall()
        usage = connection.execute(
            "SELECT COALESCE(SUM(tokens_entree + tokens_sortie), 0) FROM usage_tokens WHERE modele = ?",
            (f"agent:{PROFILE}",),
        ).fetchone()[0]
        with sqlite3.connect(Path(os.environ["OPSYS_BASE_RUNTIME_EVIDENCE"]) / "final-qa.db") as backup:
            connection.backup(backup)
    print(json.dumps({"reservations": [dict(row) for row in rows], "usage_tokens": usage}))


if __name__ == "__main__":
    if sys.argv[1:] and sys.argv[1] == "prepare" and len(sys.argv) == 3:
        prepare(int(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "serve":
        serve(int(sys.argv[2]))
    elif sys.argv[1:] == ["deactivate"]:
        deactivate()
    elif sys.argv[1:] == ["inspect"]:
        inspect()
    else:
        raise SystemExit("usage: fixture.py prepare PORT | inspect")
