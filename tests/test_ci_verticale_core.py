"""The Core/HTTP regression must run after Python changes and reject false-green receipts."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml
from qualifier_verticale_core import CASE, verify_evidence

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


@pytest.fixture
def receipts(tmp_path):
    suite = ET.Element("testsuite")
    ET.SubElement(suite, "testcase", name=CASE.split("::")[1])
    ET.ElementTree(suite).write(tmp_path / "junit.xml")
    for label, count in (("profil", 13), ("memoire", 9)):
        (tmp_path / f"{label}.json").write_text(
            json.dumps(
                {
                    "fictif": True,
                    "wct_id": "chantier-fictif",
                    "devis_id": "devis-fictif",
                    "phases": [{"phase": f"phase-fictive-{i}"} for i in range(count)],
                    "limites": [],
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
