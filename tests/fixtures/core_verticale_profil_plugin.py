"""Additional qualification on the unchanged published tree, using its real E2E affair.

This plugin extends the test evidence only; it never patches production or the original test.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import func, select

from opsys import admission_agents, agents, stockage
from opsys.stockage.schema import AGENTS_RESERVATIONS, META, USAGE_TOKENS

ROOT = Path(__file__).resolve().parents[2]
DRIVERS = ROOT / "core/test/fixtures/opsys-verticale"
PROFILE = "qualification-affaire-m8"


@pytest.fixture(autouse=True)
def qualifier_raccord_core(_instance_isolee, request, monkeypatch):
    moteur = request.getfixturevalue("moteur")
    assert request.node.name.startswith("test_affaire_unique_reprise_rejoint_facture_mesures_strategie_et_memoire")
    module = request.module
    previous = module._mesures
    reads = []

    def observe(*args, **kwargs):
        result = previous(*args, **kwargs)
        reads.append({"wct_id": args[2], "mesures": result})
        return result

    monkeypatch.setattr(module, "_mesures", observe)
    yield
    assert reads and len({read["wct_id"] for read in reads}) == 1
    wct_id = reads[-1]["wct_id"]
    assert reads[-1]["mesures"]["m8_marge_reelle_cad"]["valeur"] == "114.00"
    specification = {
        "id": PROFILE,
        "departement": "m08-analytics",
        "responsabilite": "Lecture M8 de l'affaire fictive déjà qualifiée.",
        "palier_modele": "standard",
        "outils": ["m8_lire_mesures_chantier"],
        "budget_jour": 200000,
        "budget_mois": 200000,
        "limite_tours": 4,
        "limite_reessais": 1,
        "limite_concurrence": 1,
        "declencheurs": [{"type": "manuel"}],
    }
    with stockage.transaction() as cnx:
        agents.creer(cnx, moteur.departements, specification, par="nathan", mutation_id="profil-affaire-create-fictif")
        profile = agents.definir_actif(
            cnx,
            PROFILE,
            moteur.departements,
            True,
            par="nathan",
            mutation_id="profil-affaire-active-fictif",
            revision_attendue=1,
        )
        admission_agents.configurer_plafonds_entreprise(cnx, 500000, 5000000, par="nathan", revision_attendue=0)
    assert profile["revision"] == 2
    # Runtime endpoints are mounted from active profiles at application startup.
    moteur.arreter()
    moteur.demarrer()
    events = []
    driver = DRIVERS / "core_verticale_profil_driver.mjs"
    repo = ROOT

    def table_hashes():
        with stockage.transaction() as cnx:
            return {
                table.name: hashlib.sha256(
                    json.dumps(
                        [dict(row._mapping) for row in cnx.execute(select(table).order_by(*table.primary_key.columns))],
                        sort_keys=True,
                        default=str,
                    ).encode()
                ).hexdigest()
                for table in META.sorted_tables
            }

    def call(phase, revision, *, provider_mode=None, run_id=None, changed_tables=frozenset()):
        before = module._empreinte(moteur)
        before_tables = table_hashes()
        manifest = moteur.dossier / f"core-{phase}-fictif.json"
        manifest.write_text(
            json.dumps(
                {
                    "fictif": True,
                    "phase": phase,
                    "profileId": PROFILE,
                    "profileRevision": revision,
                    "workspaceDir": str(moteur.dossier),
                    "baseUrl": f"http://127.0.0.1:{moteur.port}",
                    "bearer": module.JETON_MCP,
                    "privateBearer": module.JETON_CONTEXTE_FICTIF,
                    "wctId": wct_id,
                    "providerMode": provider_mode,
                    "runId": run_id,
                }
            )
        )
        manifest.chmod(0o600)
        env = {
            "PATH": os.environ["PATH"],
            "LANG": "C.UTF-8",
            "TZ": "UTC",
            "HOME": str(moteur.dossier),
            "OPENCLAW_STATE_DIR": str(moteur.dossier / "core-etat-fictif"),
            "OPENCLAW_CONFIG_PATH": str(moteur.dossier / "config-inexistant-fictif.json"),
            "OPSYS_QUALIFICATION_REPO": str(repo),
        }
        evidence = Path(os.environ["OPSYS_PROFIL_QUALIFICATION_PREUVE"]).parent
        stdout_path = evidence / f"profil-{phase}-stdout.log"
        stderr_path = evidence / f"profil-{phase}-stderr.log"
        try:
            with stdout_path.open("x", encoding="utf-8") as stdout, stderr_path.open("x", encoding="utf-8") as stderr:
                result = subprocess.run(
                    ["node", "--import", "./scripts/tsx.mjs", str(driver), str(manifest)],
                    cwd=repo / "core",
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=90,
                )
        finally:
            manifest.unlink(missing_ok=True)
        stdout_text = stdout_path.read_text(encoding="utf-8")
        stderr_text = stderr_path.read_text(encoding="utf-8")
        assert result.returncode == 0, stderr_text[-5000:]
        rows = [
            line.removeprefix("OPSYS_PROOF_JSON:")
            for line in stdout_text.splitlines()
            if line.startswith("OPSYS_PROOF_JSON:")
        ]
        assert len(rows) == 1, stdout_text[-3000:]
        proof = json.loads(rows[0])
        after = module._empreinte(moteur)
        after_tables = table_hashes()
        changed = {name for name, digest in before_tables.items() if digest != after_tables[name]}
        assert changed == set(changed_tables), (phase, changed)
        if not changed_tables:
            assert after == before, phase
        proof["meta_sha256_before"] = before["contenu_sha256"]
        proof["meta_sha256_after"] = after["contenu_sha256"]
        proof["table_sha256_before"] = before_tables
        proof["table_sha256_after"] = after_tables
        proof["changed_tables"] = sorted(changed)
        proof["all_meta_unchanged"] = before == after
        events.append(proof)
        return proof

    def accepted(proof):
        assert proof["envelope"]["ok"] is True and not proof["isError"], proof
        content = proof["envelope"]["resultat"]
        assert content["trouve"] is True and content["wct_id"] == wct_id
        actual = {row["metric_id"]: row for row in content["mesures"]}
        assert actual == reads[-1]["mesures"]
        assert actual["m8_marge_reelle_cad"]["valeur"] == "114.00"
        return content

    first = accepted(call("lecture", 2))
    before_restart = module._empreinte(moteur)
    moteur.arreter()
    moteur.demarrer()
    assert module._empreinte(moteur) == before_restart
    assert accepted(call("redemarrage", 2)) == first
    admitted = call(
        "admission-modele-fictif",
        2,
        provider_mode="success",
        run_id="affaire-modele-fictif-ok",
        changed_tables={"agents_reservations", "agents_reservations_historique", "usage_tokens"},
    )
    assert admitted["providerCalls"] == 1 and admitted["tokens"] == 3 and "refusal" not in admitted, admitted
    replay = call("cycle-modele-rejoue", 2, provider_mode="success", run_id="affaire-modele-fictif-ok")
    assert replay["providerCalls"] == 0 and "cycle déjà admis" in replay["refusal"], replay
    with stockage.transaction() as cnx:
        low = agents.modifier(
            cnx,
            PROFILE,
            moteur.departements,
            {**specification, "budget_jour": 3},
            par="nathan",
            mutation_id="profil-affaire-quota-fictif",
            revision_attendue=2,
        )
    assert low["revision"] == 3
    quota = call("budget-modele-epuise", 3, provider_mode="success", run_id="affaire-modele-fictif-quota")
    assert quota["providerCalls"] == 0 and "budget agent insuffisant" in quota["refusal"], quota
    assert accepted(call("lecture-t0-budget-epuise", 3)) == first
    with stockage.transaction() as cnx:
        restored = agents.modifier(
            cnx,
            PROFILE,
            moteur.departements,
            specification,
            par="nathan",
            mutation_id="profil-affaire-budget-restaure-fictif",
            revision_attendue=3,
        )
    assert restored["revision"] == 4
    unknown = call(
        "resultat-fournisseur-inconnu",
        4,
        provider_mode="unknown",
        run_id="affaire-modele-fictif-inconnu",
        changed_tables={"agents_reservations", "agents_reservations_historique"},
    )
    assert unknown["providerCalls"] == 1 and "résultat fournisseur fictif inconnu" in unknown["refusal"], unknown
    with stockage.transaction() as cnx:
        reservations_before = [
            dict(row._mapping)
            for row in cnx.execute(
                select(AGENTS_RESERVATIONS)
                .where(AGENTS_RESERVATIONS.c.agent_id == PROFILE)
                .order_by(AGENTS_RESERVATIONS.c.execution_id)
            )
        ]
        usage_tokens = cnx.scalar(
            select(func.sum(USAGE_TOKENS.c.tokens_entree + USAGE_TOKENS.c.tokens_sortie)).where(
                USAGE_TOKENS.c.modele == f"agent:{PROFILE}"
            )
        )
    assert usage_tokens == 3
    assert [(row["execution_id"], row["statut"], row["tokens_reels"]) for row in reservations_before] == [
        ("affaire-modele-fictif-inconnu", "reservee", None),
        ("affaire-modele-fictif-ok", "conciliee", 3),
    ]
    before_unknown_restart = module._empreinte(moteur)
    moteur.arreter()
    moteur.demarrer()
    assert module._empreinte(moteur) == before_unknown_restart
    unknown_replay = call(
        "resultat-inconnu-rejeu-apres-redemarrage", 4, provider_mode="success", run_id="affaire-modele-fictif-inconnu"
    )
    assert unknown_replay["providerCalls"] == 0 and "cycle déjà admis" in unknown_replay["refusal"], unknown_replay
    blocked = call(
        "nouveau-provider-bloque-par-reservation", 4, provider_mode="success", run_id="affaire-modele-fictif-nouveau"
    )
    assert blocked["providerCalls"] == 0 and "limite de concurrence atteinte" in blocked["refusal"], blocked
    assert accepted(call("lecture-t0-reservation-inconnue", 4)) == first
    with stockage.transaction() as cnx:
        changed = agents.modifier(
            cnx,
            PROFILE,
            moteur.departements,
            {**specification, "outils": ["m8_lister_definitions_metriques"]},
            par="nathan",
            mutation_id="profil-affaire-retrait-outil-fictif",
            revision_attendue=4,
        )
    assert changed["revision"] == 5
    for phase, revision, details in [
        ("revision-perimee", 4, "outil refusé : configuration de profil périmée"),
        ("outil-retire", 5, "outil refusé : capacité absente de la politique courante"),
    ]:
        proof = call(phase, revision)
        assert proof["envelope"]["ok"] is False and proof["envelope"]["erreur"] == "admission_profil_refusee", proof
        assert proof["envelope"]["details"] == details, proof
    with stockage.transaction() as cnx:
        inactive = agents.definir_actif(
            cnx,
            PROFILE,
            moteur.departements,
            False,
            par="nathan",
            mutation_id="profil-affaire-inactif-fictif",
            revision_attendue=5,
        )
        reservations_after = [
            dict(row._mapping)
            for row in cnx.execute(
                select(AGENTS_RESERVATIONS)
                .where(AGENTS_RESERVATIONS.c.agent_id == PROFILE)
                .order_by(AGENTS_RESERVATIONS.c.execution_id)
            )
        ]
    assert reservations_after == reservations_before
    assert inactive["revision"] == 6
    proof = call("profil-inactif", 6)
    assert proof["envelope"]["ok"] is False and proof["envelope"]["erreur"] == "admission_profil_refusee", proof
    assert proof["envelope"]["details"] == "outil refusé : profil inexistant, inactif ou supprimé", proof
    destination = Path(os.environ["OPSYS_PROFIL_QUALIFICATION_PREUVE"])
    with destination.open("x") as stream:
        json.dump(
            {
                "fictif": True,
                "scope": (
                    "Core production→Python HTTP réel→M8 sur même WCT ; admission "
                    "modèle avec fournisseur fictif injecté, aucun appel payé"
                ),
                "profile_id": PROFILE,
                "wct_id": wct_id,
                "devis_id": first["devis_id"],
                "phases": events,
                "reservations_finales": reservations_after,
                "usage_tokens_fictifs": usage_tokens,
                "sources_qualification": {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in [Path(__file__), driver]
                },
                "limites": [
                    "une variante SQLite114CAD",
                    "pas de téléphone",
                    "fournisseur injecté trois tokens et erreur synthétique, pas une panne réseau réelle",
                    "runtime créé à chaque phase ; pas de callback retenu au-delà de révocation",
                    "pas de crash pendant effet métier",
                    "test intégré au job Core tests-opsys ; fournisseur injecté et SQLite seulement",
                ],
            },
            stream,
            ensure_ascii=False,
            indent=2,
        )
        stream.write("\n")
