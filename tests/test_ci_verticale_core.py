"""The Core/HTTP regression must run after Python changes and reject false-green receipts."""

import contextlib
import json
import os
import signal
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml
from qualifier_verticale_core import CASE, verify_evidence, wait_qualification

ROOT = Path(__file__).resolve().parents[1]


def test_python_changes_trigger_the_core_http_qualification():
    workflow = yaml.safe_load((ROOT / ".github/workflows/core.yml").read_text())
    triggers = workflow[True]  # PyYAML interprets YAML 1.1's `on` as a boolean.
    for event in ("push", "pull_request"):
        assert {"core/**", "src/**", "departments/**", "tests/**", "conftest.py", "pyproject.toml", "uv.lock"} <= set(
            triggers[event]["paths"]
        )
    steps = workflow["jobs"]["tests-opsys"]["steps"]
    qualification = [step for step in steps if "qualifier_verticale_core.py" in step.get("run", "")]
    assert len(qualification) == 1
    assert qualification[0]["working-directory"] == "${{ github.workspace }}"
    assert ".venv/bin/python" in qualification[0]["run"]
    upload = [step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(upload) == 1 and upload[0]["if"] == "always()"
    assert upload[0]["with"]["overwrite"] is False
    suffixes = {line.rsplit("/", 1)[-1] for line in upload[0]["with"]["path"].splitlines()}
    assert suffixes == {
        "*.log",
        "junit.xml",
        "profil.json",
        "memoire.json",
        "dev.json",
        "restauration.json",
        "restauration-parent.json",
    }


@pytest.fixture
def receipts(tmp_path):
    suite = ET.Element("testsuite")
    ET.SubElement(suite, "testcase", name=CASE.split("::")[1])
    ET.ElementTree(suite).write(tmp_path / "junit.xml")
    for label, count in (("profil", 13), ("memoire", 9), ("dev", 10), ("restauration-parent", 8)):
        (tmp_path / f"{label}.json").write_text(
            json.dumps(
                {
                    "fictif": True,
                    "wct_id": "chantier-fictif",
                    "devis_id": "devis-fictif",
                    "phases": [{"phase": f"phase-fictive-{i}"} for i in range(count)],
                    "limites": [],
                    "parent_pid": 1,
                    "backend_pid": 2,
                    "source_unchanged_after_export": True,
                }
            )
        )
    return tmp_path


def test_complete_receipts_are_accepted(receipts):
    verify_evidence(receipts)


@pytest.mark.parametrize("result", ["skipped", "error", "failure"])
def test_one_skipped_or_failed_case_is_never_green(receipts, result):
    tree = ET.parse(receipts / "junit.xml")
    ET.SubElement(tree.getroot().find("testcase"), result)
    tree.write(receipts / "junit.xml")
    with pytest.raises(AssertionError):
        verify_evidence(receipts)


def test_empty_selection_is_never_green(receipts):
    ET.ElementTree(ET.Element("testsuite")).write(receipts / "junit.xml")
    with pytest.raises(AssertionError):
        verify_evidence(receipts)


def test_missing_plugin_receipt_is_never_green(receipts):
    (receipts / "memoire.json").unlink()
    with pytest.raises(FileNotFoundError):
        verify_evidence(receipts)


@pytest.mark.parametrize("defect", ["truncated", "duplicate", "different_affair"])
def test_incomplete_or_mixed_proofs_are_never_green(receipts, defect):
    path = receipts / "memoire.json"
    data = json.loads(path.read_text())
    if defect == "truncated":
        data["phases"].pop()
    elif defect == "duplicate":
        data["phases"][-1] = data["phases"][0]
    else:
        data["wct_id"] = "autre-chantier-fictif"
    path.write_text(json.dumps(data))
    with pytest.raises(AssertionError):
        verify_evidence(receipts)


@pytest.mark.parametrize("label", ["dev", "restauration-parent"])
def test_new_qualifications_cannot_be_silently_absent(receipts, label):
    (receipts / f"{label}.json").unlink()
    with pytest.raises(FileNotFoundError):
        verify_evidence(receipts)


def test_restored_backend_must_be_a_new_process(receipts):
    path = receipts / "restauration-parent.json"
    data = json.loads(path.read_text())
    data["backend_pid"] = data["parent_pid"]
    path.write_text(json.dumps(data))
    with pytest.raises(AssertionError):
        verify_evidence(receipts)


def test_restore_cannot_mutate_its_source(receipts):
    path = receipts / "restauration-parent.json"
    data = json.loads(path.read_text())
    data["source_unchanged_after_export"] = False
    path.write_text(json.dumps(data))
    with pytest.raises(AssertionError):
        verify_evidence(receipts)


def test_global_deadline_stops_detached_backend_and_cleans_manifests(tmp_path):
    backend = """
import os, subprocess, sys, threading
leaf_code = 'import os,threading;print(os.getpid(),flush=True);threading.Event().wait()'
leaf = subprocess.Popen([sys.executable, '-c', leaf_code], stdout=subprocess.PIPE, text=True)
print(str(os.getpid())+' '+leaf.stdout.readline().strip(), flush=True)
threading.Event().wait()
"""
    outer = """
import subprocess, sys, threading
backend = subprocess.Popen(
    [sys.executable, '-c', sys.argv[1]], stdout=subprocess.PIPE, text=True, start_new_session=True
)
print(backend.stdout.readline().strip(), flush=True)
threading.Event().wait()
"""
    manifests = [tmp_path / "restauration-entree-fictive.json", tmp_path / "restauration-probe-manifest-fictif.json"]
    for path in manifests:
        path.write_text('{"fictif":true}')
    child = subprocess.Popen(
        [sys.executable, "-c", outer, backend],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
    )
    backend_pid = None
    try:
        assert child.stdout is not None
        backend_pid, leaf_pid = map(int, child.stdout.readline().split())
        assert os.getpgid(backend_pid) == backend_pid != child.pid
        assert os.getpgid(leaf_pid) == backend_pid
        with pytest.raises(subprocess.TimeoutExpired):
            wait_qualification(child, tmp_path, timeout=0)
        assert child.poll() is not None
        for pid in (backend_pid, leaf_pid):
            stat = Path(f"/proc/{pid}/stat")
            assert not stat.exists() or stat.read_text().split(") ", 1)[1].split()[0] == "Z"
        assert all(not path.exists() for path in manifests)
    finally:
        for group in (child.pid, backend_pid):
            if group is not None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(group, signal.SIGKILL)
        child.wait(timeout=10)
        if child.stdout is not None:
            child.stdout.close()
