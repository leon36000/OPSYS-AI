"""Run the real Core/HTTP affair qualification with closed process environments.

Evidence directories are unique and never overwritten, including failed executions.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = (
    "tests/e2e/test_verticale_affaire_durable.py::"
    "test_affaire_unique_reprise_rejoint_facture_mesures_strategie_et_memoire[42.0-True-114.00-sqlite]"
)


def owned_process_groups(pid: int) -> set[int]:
    """Find Linux descendants before terminating a fixture tree with nested sessions."""
    rows = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            data = path.read_text(encoding="utf-8")
            fields = data[data.rindex(")") + 2 :].split()
            rows[int(path.parent.name)] = (int(fields[1]), int(fields[2]))
        except (OSError, ValueError, IndexError):
            continue
    descendants = {pid}
    while True:
        more = {child for child, (parent, _) in rows.items() if parent in descendants}
        if more <= descendants:
            break
        descendants |= more
    return {pid} | {rows[child][1] for child in descendants if child in rows}


def wait_qualification(child, destination: Path, *, timeout: float) -> int:
    """Cancel all owned groups, including the separately-sessioned restore backend."""
    try:
        return child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Freeze the outer group before discovery so it cannot spawn a new session
        # between the process-tree snapshot and cancellation. Existing descendants
        # inherit the backend's captured group.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGSTOP)
        groups = owned_process_groups(child.pid)
        for group in groups:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(group, signal.SIGTERM)
            with contextlib.suppress(ProcessLookupError):
                os.killpg(group, signal.SIGCONT)
        with contextlib.suppress(subprocess.TimeoutExpired):
            child.wait(timeout=10)
        for group in groups:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(group, signal.SIGKILL)
        child.wait(timeout=10)
        for pattern in ("restauration-entree-fictive.json", "restauration-*-manifest-fictif.json"):
            for manifest in destination.glob(pattern):
                manifest.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preuve-dir", required=True, type=Path)
    destination = parser.parse_args().preuve_dir.resolve()
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = {
        "PATH": os.environ["PATH"],
        "LANG": "C.UTF-8",
        "TZ": "UTC",
        "HOME": str(destination),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(ROOT / "tests/fixtures"),
        "OPSYS_PROFIL_QUALIFICATION_PREUVE": str(destination / "profil.json"),
        "OPSYS_MEMOIRE_QUALIFICATION_PREUVE": str(destination / "memoire.json"),
        "OPSYS_DEV_QUALIFICATION_PREUVE": str(destination / "dev.json"),
        "OPSYS_RESTAURATION_QUALIFICATION_PREUVE": str(destination / "restauration.json"),
    }
    command = [
        sys.executable,
        "-m",
        "pytest",
        CASE,
        "-p",
        "core_verticale_developpement_plugin",
        "-q",
        f"--junitxml={destination / 'junit.xml'}",
    ]
    with (destination / "pytest.log").open("x", encoding="utf-8") as log:
        child = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        code = wait_qualification(child, destination, timeout=300)
    print((destination / "pytest.log").read_text(encoding="utf-8"))
    if code:
        raise SystemExit(code)
    verify_evidence(destination)


def verify_evidence(destination: Path) -> None:
    """Reject empty, skipped, missing, truncated or mixed-affair qualifications."""
    cases = ET.parse(destination / "junit.xml").findall(".//testcase")
    assert len(cases) == 1 and cases[0].get("name") == CASE.split("::")[1]
    assert not cases[0].findall("skipped") and not cases[0].findall("error") and not cases[0].findall("failure")
    expected = {"profil": 13, "memoire": 9, "dev": 10, "restauration-parent": 8}
    proofs = {name: json.loads((destination / f"{name}.json").read_text(encoding="utf-8")) for name in expected}
    profile = proofs["profil"]
    restored = proofs["restauration-parent"]
    assert restored["backend_pid"] != restored["parent_pid"]
    assert restored["source_unchanged_after_export"] is True
    for label, proof in proofs.items():
        assert proof["fictif"] is True
        assert proof["wct_id"] == profile["wct_id"] and proof["devis_id"] == profile["devis_id"]
        phases = [phase["phase"] for phase in proof["phases"]]
        assert len(phases) == expected[label] and len(set(phases)) == len(phases)
        print(json.dumps({"qualification": label, "phases": phases, "limites": proof["limites"]}, ensure_ascii=False))
    print("Core→HTTP réel : 1 affaire SQLite fictive, 40 phases profil/mémoire/isolation/restauration, zéro skip.")


if __name__ == "__main__":
    main()
