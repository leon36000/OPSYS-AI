"""Small fixture for the TS↔real-Python-MCP admission integration test."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
for department in sorted((REPO / "departments").glob("m*-*/src")):
    sys.path.insert(0, str(department))


def prepare() -> None:
    from opsys import admission_agents, agents, identite, stockage
    from opsys.departements import charger_departements

    stockage.migrer()
    departements = charger_departements()
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx,
            "runtime-it-admin",
            "Runtime integration test",
            "synthetic-test-only-password-9342",
            ["admin"],
        )
        for profile_id, budget in (
            ("it-runtime-ok", 200_000),
            ("it-runtime-low", 1),
            ("it-runtime-revision", 200_000),
        ):
            specification = {
                "id": profile_id,
                "departement": "m09-strategic-intelligence",
                "responsabilite": "Profil factice de test d'interopérabilité runtime.",
                "palier_modele": "standard",
                "outils": ["m9_etat_consolide"],
                "budget_jour": budget,
                "budget_mois": max(budget, 200_000),
                "limite_tours": 4,
                "limite_reessais": 1,
                "limite_concurrence": 2,
                "declencheurs": [{"type": "manuel"}],
            }
            agents.creer(
                cnx,
                departements,
                specification,
                par="runtime-it-admin",
                mutation_id=f"runtime-it-create-{profile_id}",
            )
            agents.definir_actif(
                cnx,
                profile_id,
                departements,
                True,
                par="runtime-it-admin",
                mutation_id=f"runtime-it-activate-{profile_id}",
                revision_attendue=1,
            )
        admission_agents.configurer_plafonds_entreprise(
            cnx,
            500_000,
            5_000_000,
            par="runtime-it-admin",
            revision_attendue=0,
        )


def revoke_tool() -> None:
    from opsys import agents, stockage
    from opsys.departements import charger_departements

    with stockage.transaction() as cnx:
        current = agents.obtenir(cnx, "it-runtime-revision")
        if current is None:
            raise RuntimeError("synthetic profile missing")
        specification = {
            key: current[key]
            for key in (
                "id",
                "departement",
                "responsabilite",
                "palier_modele",
                "outils",
                "budget_jour",
                "budget_mois",
                "limite_tours",
                "limite_reessais",
                "limite_concurrence",
                "declencheurs",
            )
        }
        specification["outils"] = ["m9_lire_etat_consolide"]
        agents.modifier(
            cnx,
            "it-runtime-revision",
            charger_departements(),
            specification,
            par="runtime-it-admin",
            mutation_id="runtime-it-revoke-tool",
            revision_attendue=current["revision"],
        )


def deactivate_profile() -> None:
    from opsys import agents, stockage
    from opsys.departements import charger_departements

    with stockage.transaction() as cnx:
        current = agents.obtenir(cnx, "it-runtime-revision")
        if current is None:
            raise RuntimeError("synthetic profile missing")
        agents.definir_actif(
            cnx,
            "it-runtime-revision",
            charger_departements(),
            False,
            par="runtime-it-admin",
            mutation_id="runtime-it-deactivate-profile",
            revision_attendue=current["revision"],
        )


def inspect() -> None:
    database = Path(os.environ["OPSYS_HOME"]) / "opsys.db"
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        reservations = connection.execute(
            "SELECT agent_id, execution_id, cycle_id, statut, tokens_plafond, tokens_reels "
            "FROM agents_reservations ORDER BY execution_id"
        ).fetchall()
        usage = connection.execute(
            "SELECT COALESCE(SUM(tokens_entree + tokens_sortie), 0) FROM usage_tokens "
            "WHERE modele = ?",
            ("agent:it-runtime-ok",),
        ).fetchone()[0]
    finally:
        connection.close()
    print(json.dumps({"reservations": [dict(row) for row in reservations], "usage_tokens": usage}))


def prepare_missed_call() -> None:
    from opsys import agents, identite, stockage, taxonomie
    from opsys.departements import charger_departements

    stockage.migrer()
    departments = charger_departements()
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx,
            "missed-it-admin",
            "Admin fictif M1",
            "synthetic-missed-password-2026",
            ["admin"],
        )
        agents.creer(
            cnx,
            departments,
            {
                "id": "it-m1-missed-call",
                "departement": "m01-front-office",
                "responsabilite": "Import hôte fictif M1 via transport natif.",
                "palier_modele": "standard",
                "outils": ["m1_importer_appel_manuellement"],
                "budget_jour": 100,
                "budget_mois": 1_000,
                "limite_tours": 2,
                "limite_reessais": 1,
                "limite_concurrence": 1,
                "declencheurs": [{"type": "manuel"}],
            },
            par="missed-it-admin",
            mutation_id="missed-it-create-001",
        )
        agents.definir_actif(
            cnx,
            "it-m1-missed-call",
            departments,
            True,
            par="missed-it-admin",
            mutation_id="missed-it-activate-001",
            revision_attendue=1,
        )
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])


def revoke_missed_call() -> None:
    from opsys import agents, stockage
    from opsys.departements import charger_departements

    with stockage.transaction() as cnx:
        current = agents.obtenir(cnx, "it-m1-missed-call")
        if current is None:
            raise RuntimeError("synthetic M1 profile missing")
        agents.definir_actif(
            cnx,
            current["id"],
            charger_departements(),
            False,
            par="missed-it-admin",
            mutation_id="missed-it-deactivate-001",
            revision_attendue=current["revision"],
        )


def inspect_missed_call() -> None:
    from opsys import agents, stockage
    from opsys.stockage.schema import (
        AGENTS_CONFIGURABLES,
        CLES_CHIFFREMENT,
        EVENEMENTS_RECUS,
        EVENEMENTS_SORTANTS,
        MUTATIONS_APPLIQUEES,
        REGISTRES,
    )

    # The same six durable owners as test_runtime_import_appel_manque._etat_durable.
    tables = (
        REGISTRES, EVENEMENTS_SORTANTS, EVENEMENTS_RECUS,
        MUTATIONS_APPLIQUEES, CLES_CHIFFREMENT, AGENTS_CONFIGURABLES,
    )
    database = Path(os.environ["OPSYS_HOME"]) / "opsys.db"
    digest = hashlib.sha256()
    counts = {}
    total_rows = 0
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        connection.execute("BEGIN")
        for table in tables:
            name = table.name
            quoted = '"' + name.replace('"', '""') + '"'
            rows = connection.execute(f"SELECT * FROM {quoted}").fetchmany(1_025)
            total_rows += len(rows)
            if len(rows) > 1_024 or total_rows > 4_096:
                raise RuntimeError("synthetic database row bound exceeded")
            counts[name] = len(rows)
            encoded = []
            for row in rows:
                values = [value.hex() if isinstance(value, bytes) else value for value in row]
                text = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
                if len(text.encode()) > 64 * 1_024:
                    raise RuntimeError("synthetic database row byte bound exceeded")
                encoded.append(text)
            # This is an equality oracle, not authentication of historical SQL data.
            digest.update(json.dumps([name, sorted(encoded)], ensure_ascii=False).encode())
    with stockage.transaction() as cnx:
        chain = stockage.maillons("m01-front-office", "principal")
        if len(chain) > 64:
            raise RuntimeError("synthetic M1 chain bound exceeded")
        rows = list(chain)
        profile = agents.obtenir(cnx, "it-m1-missed-call")
        if profile is None:
            raise RuntimeError("synthetic M1 profile missing")
    print(json.dumps({
        "state_sha256": digest.hexdigest(),
        "table_counts": counts,
        "m1_chain_size": len(rows),
        "host_signals": sum(
            row.get("type_entree") == "signal" and row.get("source") == "appel_operateur"
            for row in rows
        ),
        "host_transfers": sum(
            row.get("type_entree") == "transfert" and row.get("source") == "appel_operateur"
            for row in rows
        ),
        "manual_signals": sum(
            row.get("type_entree") == "signal" and row.get("source") == "appel_manuel"
            for row in rows
        ),
        "host_imports": sum(
            row.get("type_entree") == "appel_importe" and row.get("source") == "voice-call:mock"
            for row in rows
        ),
        "profile_revision": profile["revision"],
        "profile_active": profile["actif"],
    }, sort_keys=True))


if __name__ == "__main__":
    actions = {
        "prepare": prepare,
        "revoke-tool": revoke_tool,
        "deactivate-profile": deactivate_profile,
        "inspect": inspect,
        "prepare-missed-call": prepare_missed_call,
        "inspect-missed-call": inspect_missed_call,
        "revoke-missed-call": revoke_missed_call,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        raise SystemExit(f"usage: fixture.py {{{'|'.join(actions)}}}")
    actions[sys.argv[1]]()
