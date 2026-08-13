from __future__ import annotations

from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "core-ci.yml"
_REQUIRED_JOB_IDS = {
    "types",
    "tests",
    "security",
    "pack-validation",
    "proof-sealed",
}


def _workflow() -> dict[object, object]:
    """Charge le workflow réel afin de prouver son câblage structurel."""
    contenu = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(contenu, dict)
    return contenu


def test_un_job_requis_core_ci_execute_le_gate_no_stub() -> None:
    """Prouve que le gate NO-STUB est relié à un check requis et ne peut disparaître silencieusement."""
    workflow = _workflow()
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)

    invocations: list[tuple[str, str]] = []
    for identifiant, definition in jobs.items():
        if identifiant not in _REQUIRED_JOB_IDS or not isinstance(definition, dict):
            continue
        etapes = definition.get("steps")
        if not isinstance(etapes, list):
            continue
        for etape in etapes:
            if not isinstance(etape, dict):
                continue
            commande = etape.get("run")
            if isinstance(commande, str) and "scripts/quality/no_stub_gate.py" in commande:
                invocations.append((identifiant, commande))

    assert invocations, "Aucun job requis de core-ci.yml n'invoque scripts/quality/no_stub_gate.py"
    assert any(
        commande == "python3 scripts/quality/no_stub_gate.py --repo . --base-ref origin/main"
        for _, commande in invocations
    )
