"""Qualify development/business corpus separation on the same real fictional affair.

This plugin is a regression of the composed fictional affair. Console uses its production ASGI application;
private business context uses the real Core/HTTP transport. No RAG or client ACL claim.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opsys import agents, identite, stockage
from opsys.console import securite
from opsys.console.application import creer_application
from opsys.stockage.schema import META, REGISTRES

pytest_plugins = ["core_verticale_restoration_plugin"]
REPO = Path(__file__).resolve().parents[2]
DEV = "dev.isolation.fictif"
PASSWORD = "mot-de-passe-dev-isolation-fictif-1234"
MARKER = "OPSYS_DEVELOPPEMENT_ISOLATION_FICTIF_20261006"
PROFILE = "qualification-affaire-dev"


@pytest.fixture(autouse=True)
def qualifier_developpement_affaire(qualifier_restauration_affaire, request):
    yield
    moteur = request.getfixturevalue("moteur")
    module = request.module
    financial = module._evenements("m5.rentabilite_chantier")
    ((_, event),) = module._evenements("m1.lead_qualifie")
    lead_id = event["lead"]["lead_id"]
    wct_id = financial[-1][1]["wct_id"]
    assert financial[-1][1]["marge_reelle_cad"] == "114.00"
    destination = Path(os.environ["OPSYS_DEV_QUALIFICATION_PREUVE"])
    proofs = []
    specification = {
        "id": PROFILE,
        "departement": "m10-memoire",
        "responsabilite": "Lecture de l'affaire fictive pour isolation corpus.",
        "palier_modele": "standard",
        "outils": ["m10_affaire_de_la_session", "m10_auditer_non_oubli"],
        "budget_jour": 200000,
        "budget_mois": 200000,
        "limite_tours": 4,
        "limite_reessais": 1,
        "limite_concurrence": 1,
        "declencheurs": [{"type": "manuel"}],
    }
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, DEV, "Admin développement fictif", PASSWORD, ["admin"])
        agents.creer(cnx, moteur.departements, specification, par="nathan", mutation_id="dev-profil-fictif-create")
        profile = agents.definir_actif(
            cnx,
            PROFILE,
            moteur.departements,
            True,
            par="nathan",
            mutation_id="dev-profil-fictif-active",
            revision_attendue=1,
        )
    assert profile["revision"] == 2

    def hashes():
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

    def business_register_hash():
        with stockage.transaction() as cnx:
            query = (
                select(REGISTRES)
                .where(~((REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "developpement")))
                .order_by(*REGISTRES.primary_key.columns)
            )
            rows = [dict(row._mapping) for row in cnx.execute(query)]
        return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()

    def record(phase, operation, *, changed_tables=frozenset()):
        before = module._empreinte(moteur)
        tables_before = hashes()
        business_before = business_register_hash()
        value = operation()
        after = module._empreinte(moteur)
        tables_after = hashes()
        changed = {name for name in tables_before if tables_before[name] != tables_after[name]}
        business_after = business_register_hash()
        assert business_after == business_before, phase
        if changed_tables and hasattr(value, "status_code"):
            assert value.status_code == 200, (phase, value.status_code, value.text)
        assert changed == set(changed_tables), (phase, changed)
        if not changed_tables:
            assert before == after, phase
        proofs.append(
            {
                "fictif": True,
                "phase": phase,
                "all_meta_unchanged": before == after,
                "meta_sha256_before": before["contenu_sha256"],
                "meta_sha256_after": after["contenu_sha256"],
                "changed_tables": sorted(changed),
                "table_sha256_before": tables_before,
                "table_sha256_after": tables_after,
                "business_registers_sha256_before_after": business_before,
            }
        )
        return value

    driver = REPO / "core/test/fixtures/opsys-verticale/core_verticale_memoire_driver.mjs"

    def business_packet(phase):
        manifest = moteur.dossier / f"dev-{phase}-fictif.json"
        manifest.write_text(
            json.dumps(
                {
                    "fictif": True,
                    "phase": phase,
                    "profileId": PROFILE,
                    "workspaceDir": str(moteur.dossier),
                    "serverName": "opsys_context_m5",
                    "url": f"http://127.0.0.1:{moteur.port}/mcp/contexte/m05-financecore",
                    "bearer": module.JETON_CONTEXTE_FICTIF,
                    "tool": "m10_paquet_contexte_affaire",
                    "args": {"affaire_id": lead_id, "horodatage": module.iso(moteur.horloge.maintenant)},
                    "catalog": False,
                }
            )
        )
        manifest.chmod(0o600)
        env = {
            "PATH": os.environ["PATH"],
            "LANG": "C.UTF-8",
            "TZ": "UTC",
            "HOME": str(moteur.dossier),
            "OPENCLAW_STATE_DIR": str(moteur.dossier / "core-dev-etat-fictif"),
            "OPENCLAW_CONFIG_PATH": str(moteur.dossier / "config-dev-inexistant-fictif.json"),
            "OPSYS_QUALIFICATION_REPO": str(REPO),
        }
        out = destination.parent / f"dev-{phase}-stdout.log"
        err = destination.parent / f"dev-{phase}-stderr.log"
        try:
            with out.open("x") as stdout, err.open("x") as stderr:
                result = subprocess.run(
                    ["node", "--import", "./scripts/tsx.mjs", str(driver), str(manifest)],
                    cwd=REPO / "core",
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=90,
                )
        finally:
            manifest.unlink(missing_ok=True)
        assert result.returncode == 0, err.read_text()[-3000:]
        lines = [
            row.removeprefix("OPSYS_PROOF_JSON:")
            for row in out.read_text().splitlines()
            if row.startswith("OPSYS_PROOF_JSON:")
        ]
        assert len(lines) == 1
        receipt = json.loads(lines[0])
        assert receipt.get("envelope", {}).get("ok") is True and not receipt.get("isError"), receipt
        packet = receipt["envelope"]["resultat"]
        assert packet["affaire_id"] == lead_id and packet["affaire"]["connue"] is True
        return packet

    first_packet = record("paquet-metier-avant-corpus-dev", lambda: business_packet("avant-corpus"))
    configuration = securite.Configuration("cle-session-dev-isolation-fictive-" + "x" * 32, cookie_securise=False)
    app = creer_application(configuration, moteur.departements, stockage.transaction)
    with TestClient(app, base_url=f"http://testserver{configuration.prefixe}") as client:
        login = client.post("/connexion", data={"identifiant": DEV, "mot_de_passe": PASSWORD}, follow_redirects=False)
        assert login.status_code == 303, login.text
        session = securite.lire_session(client.cookies.get(securite.NOM_COOKIE), configuration.secret)
        assert session is not None and session.utilisateur == DEV
        headers = {"x-csrf-token": session.csrf}
        prompt_id = "prompt-dev-isolation-fictif"
        plan_id = "plan-dev-isolation-fictif"
        prompt = {
            "prompt_id": prompt_id,
            "content": MARKER + " Garder les tests de structure et de source.",
            "version": 1,
            "module": "M10",
            "purpose": "Qualification technique fictive des registres séparés",
        }
        denied = record(
            "ecriture-prompt-refusee-sans-csrf", lambda: client.post("/api/memoire-developpement/prompts", json=prompt)
        )
        assert denied.status_code == 403, denied.text
        response = record(
            "prompt-dev-ecrit-au-registre-dedie",
            lambda: client.post("/api/memoire-developpement/prompts", json=prompt, headers=headers),
            changed_tables={REGISTRES.name},
        )
        assert response.status_code == 200, response.text
        plan = {
            "plan_id": plan_id,
            "version": 1,
            "module": "M10",
            "prompt_id": prompt_id,
            "prompt_version": 1,
            "objective": MARKER + " Vérifier les invariants techniques.",
            "steps": [{"id": "structure-fictive", "description": "Comparer les corpus sans mutation."}],
            "files": [],
        }
        response = record(
            "plan-dev-ecrit-au-registre-dedie",
            lambda: client.post("/api/memoire-developpement/plans", json=plan, headers=headers),
            changed_tables={REGISTRES.name},
        )
        assert response.status_code == 200, response.text

        def preflight(module_id, task):
            return client.post(
                "/api/memoire-developpement/preflight", json={"module": module_id, "task": task, "files": []}
            )

        response = record("preflight-dev-retourne-ses-deux-sources", lambda: preflight("M10", prompt_id))
        assert response.status_code == 200, response.text
        dev_packet = response.json()
        assert dev_packet["status"] == "available"
        selected = {(row["kind"], row["entity_id"]) for row in dev_packet["must_know"]}
        assert selected == {("prompt", prompt_id), ("plan", plan_id)}, dev_packet
        context = {key: dev_packet[key] for key in ("must_know", "evidence", "contradictions", "links")}
        text = json.dumps(context, ensure_ascii=False)
        assert MARKER in text
        assert "marge_reelle_cad" not in text and "cliente-verticale@exemple.test" not in text
        assert lead_id not in text and wct_id not in text and all(event_id not in text for event_id, _ in financial)
        response = record(
            "preflight-dev-ne-recherche-pas-les-faits-finance",
            lambda: preflight("M5", f"marge_reelle_cad {financial[-1][0]}"),
        )
        assert response.status_code == 200
        absent = response.json()
        assert absent["status"] == "unavailable" and not absent["must_know"] and not absent["evidence"], absent
        # `task` echoes the supplied query; only retrieved context is an isolation claim.
        second_packet = record("paquet-metier-ne-lit-pas-prompts-et-plans-dev", lambda: business_packet("apres-corpus"))
        assert second_packet == first_packet
        assert MARKER not in json.dumps(second_packet)
        assert prompt_id not in json.dumps(second_packet) and plan_id not in json.dumps(second_packet)

        with TestClient(app, base_url=f"http://testserver{configuration.prefixe}") as anonymous:
            response = record(
                "bearer-public-ne-remplace-pas-cookie-console",
                lambda: anonymous.post(
                    "/api/memoire-developpement/preflight",
                    json={"module": "M10", "task": prompt_id, "files": []},
                    headers={"Authorization": f"Bearer {module.JETON_MCP}"},
                ),
            )
            assert response.status_code == 401, response.text
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, DEV, "admin")
        response = record("cookie-ancien-refuse-apres-retrait-role", lambda: preflight("M10", prompt_id))
        assert response.status_code == 403, response.text
        with stockage.transaction() as cnx:
            identite.ajouter_role(cnx, DEV, "admin")
            identite.activer(cnx, DEV, False)
        response = record("cookie-ancien-refuse-apres-desactivation", lambda: preflight("M10", prompt_id))
        assert response.status_code == 401, response.text
    assert module._evenements("m5.rentabilite_chantier") == financial
    with stockage.transaction():
        development = list(stockage.maillons("m10-memoire", "developpement"))
    assert len(development) == 2 and all(row["type_entree"] == "memoire_developpement" for row in development)
    persisted = [event for row in development for event in row["paquet"]["events"]]
    assert {(row["event_type"], row["entity_id"]) for row in persisted} == {
        ("prompt", f"prompt:{prompt_id}"),
        ("plan", f"plan:{plan_id}"),
    }
    assert all(row["actor"] == DEV and row["actor_role"] == "admin" for row in persisted)
    assert len(proofs) == 10 and len({row["phase"] for row in proofs}) == 10
    with destination.open("x") as stream:
        json.dump(
            {
                "fictif": True,
                "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
                "affaire_id": lead_id,
                "wct_id": wct_id,
                "devis_id": financial[-1][1]["devis_id"],
                "phases": proofs,
                "dev_prompt_plan_ids": [prompt_id, plan_id],
                "financial_event_ids": [event_id for event_id, _ in financial],
                "dev_records": development,
                "dev_context": context,
                "business_packet_before_after": first_packet,
                "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__), driver]},
                "limites": [
                    "une affaire SQLite et deux entrées développement fictives, aucune collecte réelle",
                    "console ASGI production via TestClient, pas un navigateur ni TCP console",
                    "paquet métier via vrai Core/HTTP et nouvelle lease",
                    "préflight lexical/registre dédié, pas RAG/embedding",
                    "query task echo exclu des claims de contexte récupéré",
                    "pas de clients A/B ni ACL client",
                    "qualification intégrée au job Core tests-opsys",
                ],
            },
            stream,
            ensure_ascii=False,
            indent=2,
        )
        stream.write("\n")
