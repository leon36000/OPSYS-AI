"""Run the real Core/HTTP affair qualification with closed process environments.

Evidence directories are unique and never overwritten, including failed executions.
"""

from __future__ import annotations

import argparse
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
    }
    command = [
        sys.executable,
        "-m",
        "pytest",
        CASE,
        "-p",
        "core_verticale_memoire_plugin",
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
        try:
            code = child.wait(timeout=300)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
            raise
    print((destination / "pytest.log").read_text(encoding="utf-8"))
    if code:
        raise SystemExit(code)
    verify_evidence(destination)


def verify_evidence(destination: Path) -> None:
    """Reject empty, skipped, missing, truncated or mixed-affair qualifications."""
    cases = ET.parse(destination / "junit.xml").findall(".//testcase")
    assert len(cases) == 1 and cases[0].get("name") == CASE.split("::")[1]
    assert not cases[0].findall("skipped") and not cases[0].findall("error") and not cases[0].findall("failure")
    profile = json.loads((destination / "profil.json").read_text(encoding="utf-8"))
    memory = json.loads((destination / "memoire.json").read_text(encoding="utf-8"))
    assert profile["fictif"] is memory["fictif"] is True
    assert len(profile["phases"]) == 13 and len(memory["phases"]) == 9
    assert profile["wct_id"] == memory["wct_id"] and profile["devis_id"] == memory["devis_id"]
    for label, proof in (("profil", profile), ("memoire", memory)):
        phases = [phase["phase"] for phase in proof["phases"]]
        assert len(set(phases)) == len(phases)
        print(json.dumps({"qualification": label, "phases": phases, "limites": proof["limites"]}, ensure_ascii=False))
    print("Core→HTTP réel : 1 affaire SQLite fictive, 13 phases profil + 9 phases mémoire, zéro skip.")


if __name__ == "__main__":
    main()
