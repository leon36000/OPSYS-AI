"""Export/restore one real fictional affair; never replace an existing instance."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from core_verticale_restoration_driver import snapshot
from sqlalchemy.engine import make_url

from opsys import agents, exportation, stockage
from opsys.serveur_mcp import ENV_REPARTITEUR

pytest_plugins = ["core_verticale_memoire_plugin"]
REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests/fixtures"


def wait_backend(child, evidence: Path, manifest: Path, *, timeout: float):
    """Bound a whole owned backend process group and clean its private manifests."""
    try:
        return child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            child.wait(timeout=10)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=10)
        raise
    finally:
        manifest.unlink(missing_ok=True)
        for temporary in evidence.glob("restauration-*-manifest-fictif.json"):
            temporary.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def qualifier_restauration_affaire(qualifier_memoire_affaire, affaire, finance_fictive, request):
    yield
    moteur = request.getfixturevalue("moteur")
    module = request.module
    destination = Path(os.environ["OPSYS_RESTAURATION_QUALIFICATION_PREUVE"])
    evidence = destination.parent
    source_db = Path(make_url(stockage.url_base()).database).resolve()
    assert source_db.is_relative_to(moteur.dossier.resolve()) and source_db.is_file()
    source_home = Path(os.environ["OPSYS_HOME"]).resolve()
    assert source_home.is_relative_to(moteur.dossier.resolve())
    financial = module._evenements("m5.rentabilite_chantier")
    ((_, lead_event),) = module._evenements("m1.lead_qualifie")
    lead_id = lead_event["lead"]["lead_id"]
    wct_id = financial[-1][1]["wct_id"]
    assert financial[-1][1]["marge_reelle_cad"] == "114.00"
    measures = module._mesures(moteur, affaire["admin"], wct_id)
    profiles = []
    for department, tools, suffix in [
        ("m08-analytics", ["m8_lire_mesures_chantier"], "m8"),
        ("m10-memoire", ["m10_affaire_de_la_session", "m10_auditer_non_oubli"], "m10"),
    ]:
        profile_id = f"qualification-restauration-{suffix}"
        specification = {
            "id": profile_id,
            "departement": department,
            "responsabilite": "Lecture de l'affaire fictive après restauration.",
            "palier_modele": "standard",
            "outils": tools,
            "budget_jour": 200000,
            "budget_mois": 200000,
            "limite_tours": 4,
            "limite_reessais": 1,
            "limite_concurrence": 1,
            "declencheurs": [{"type": "manuel"}],
        }
        with stockage.transaction() as cnx:
            agents.creer(
                cnx,
                moteur.departements,
                specification,
                par="nathan",
                mutation_id=f"restauration-{suffix}-fictif-create",
            )
            profile = agents.definir_actif(
                cnx,
                profile_id,
                moteur.departements,
                True,
                par="nathan",
                mutation_id=f"restauration-{suffix}-fictif-active",
                revision_attendue=1,
            )
        assert profile["revision"] == 2
        profiles.append(profile_id)
    checkpoint = snapshot()
    moteur.arreter()
    try:
        archive = exportation.exporter(source_home, evidence / "affaire-fictive.tar.gz", par="qualification-fictive")
        after_export = snapshot()
        assert {name: digest for name, digest in after_export["hashes"].items() if name != "journal"} == {
            name: digest for name, digest in checkpoint["hashes"].items() if name != "journal"
        }
        assert after_export["journal"][:-1] == checkpoint["journal"]
        audit = after_export["journal"][-1]
        assert audit["action"] == "instance.export" and audit["par"] == "qualification-fictive"
        assert json.loads(audit["details"])["sha256"] == archive.sha256
        corrupt = evidence / "affaire-fictive-alteree.tar.gz"
        content = bytearray(archive.archive.read_bytes())
        content[0] ^= 1
        with corrupt.open("xb") as stream:
            stream.write(content)
        corrupt.chmod(0o600)
        finance = evidence / "m5-manifeste-fictif-hors-export.yaml"
        analytics = evidence / "m8-manifeste-fictif-hors-export.yaml"
        for original, copy in [(module.m5_outils._MANIFESTE, finance), (module.m8_outils._MANIFESTE, analytics)]:
            with copy.open("xb") as stream:
                stream.write(Path(original).read_bytes())
        manifest = evidence / "restauration-entree-fictive.json"
        input_value = {
            "fictif": True,
            "parent_pid": os.getpid(),
            "repo": str(REPO),
            "evidence": str(evidence),
            "archive": str(archive.archive),
            "archive_sha256": archive.sha256,
            "corrupt_archive": str(corrupt),
            "revision": archive.revision,
            "checkpoint": checkpoint,
            "finance_manifest": str(finance),
            "analytics_manifest": str(analytics),
            "m8_profile": profiles[0],
            "m10_profile": profiles[1],
            "public_bearer": module.JETON_MCP,
            "private_bearer": module.JETON_CONTEXTE_FICTIF,
            "affaire_id": lead_id,
            "wct_id": wct_id,
            "devis_id": financial[-1][1]["devis_id"],
            "maintenant": module.iso(moteur.horloge.maintenant),
            "mesures": measures,
            "financial_event_ids": [event_id for event_id, _ in financial],
        }
        dev_proof = json.loads(Path(os.environ["OPSYS_DEV_QUALIFICATION_PREUVE"]).read_text())
        assert dev_proof["wct_id"] == wct_id and dev_proof["devis_id"] == input_value["devis_id"]
        input_value["dev_context_expected"] = dev_proof["dev_context"]
        input_value["dev_prompt_id"] = dev_proof["dev_prompt_plan_ids"][0]
        with manifest.open("x") as stream:
            json.dump(input_value, stream, default=str)
        manifest.chmod(0o600)
        home = evidence / "instance-restauree-fictive"
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(evidence),
            "LANG": "C.UTF-8",
            "TZ": "UTC",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPO / "tests/fixtures"),
                    str(REPO / "src"),
                    *[str(p) for p in sorted((REPO / "departments").glob("*/src"))],
                ]
            ),
            "OPSYS_HOME": str(home),
            "OPSYS_BASE_URL": f"sqlite:///{home / 'opsys.db'}",
            ENV_REPARTITEUR: "0",
        }
        stdout_path = evidence / "backend-restaure-stdout.log"
        stderr_path = evidence / "backend-restaure-stderr.log"
        try:
            with stdout_path.open("x") as stdout, stderr_path.open("x") as stderr:
                child = subprocess.Popen(
                    [sys.executable, str(FIXTURES / "core_verticale_restoration_driver.py"), str(manifest)],
                    cwd=REPO,
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                code = wait_backend(child, evidence, manifest, timeout=180)
        finally:
            manifest.unlink(missing_ok=True)
            for temporary in evidence.glob("restauration-*-manifest-fictif.json"):
                temporary.unlink(missing_ok=True)
        assert code == 0, stderr_path.read_text()[-6000:]
        proof = json.loads(destination.read_text())
        assert proof["backend_pid"] != proof["parent_pid"] == os.getpid()
        assert len(proof["phases"]) == 8
        assert snapshot() == after_export
        assert module._evenements("m5.rentabilite_chantier") == financial
        proof["source_unchanged_after_export"] = True
        proof["source_checkpoint"] = checkpoint
        proof["source_after_export"] = after_export
        proof["configuration_fictive_hors_export"] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [finance, analytics]
        }
        # Keep the child's immutable receipt, write the enriched parent receipt separately.
        with (evidence / "restauration-parent.json").open("x") as stream:
            json.dump(proof, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    finally:
        moteur.demarrer()
