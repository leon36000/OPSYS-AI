"""SOCLE partitions: real miniature pytest processes, fictitious GitHub/Git context only."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ci/tester_socle.py"
SHA = "1" * 40


def helper():
    assert SCRIPT.is_file(), "le propriétaire SOCLE déterministe est absent"
    spec = importlib.util.spec_from_file_location("ci_socle_parts_owned", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def miniature(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths=tests\naddopts=-q\n")
    tools = tmp_path / "bin"
    tools.mkdir()
    git = tools / "git"
    git.write_text(f"#!/bin/sh\nprintf '%s\\n' '{SHA}'\n")
    git.chmod(0o700)
    env = {**os.environ, "PATH": str(tools) + os.pathsep + os.defpath,
           "GITHUB_SHA": SHA, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH"):
        env.pop(name, None)
    files = {}
    for part in (0, 1):
        index = 0
        while True:
            name = f"tests/test_fictif_{part}_{index}.py"
            if int(hashlib.sha256(name.encode()).hexdigest(), 16) % 2 == part:
                break
            index += 1
        files[part] = tmp_path / name
        files[part].write_text("import pytest\n@pytest.mark.parametrize('fictif',[1,2])\n"
                               "def test_fictif(fictif):\n    assert fictif in (1,2)\n")

    def run(part=0, *, mode="run", suffix="", parts=2):
        output = tmp_path / f"artifacts{suffix}"
        output.mkdir(exist_ok=True)
        output = output / f"socle-parts-123-2-{part}"
        output.mkdir(exist_ok=True)
        manifest = output / f"socle-part-{part}.json"
        command = [sys.executable, str(SCRIPT), mode, "--part", str(part), "--parts", str(parts),
                   "--manifest", str(manifest)]
        result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
        return result, manifest

    return tmp_path, env, files, run


def test_native_parts_cover_every_occurrence_and_preserve_file_order(miniature):
    root, env, _, run = miniature
    h = helper()
    receipts = []
    for part in (0, 1):
        result, path = run(part)
        assert result.returncode == 0, result.stdout + result.stderr
        receipts.append(json.loads(path.read_text()))
    h.verify(root / "artifacts", h.context(root, env), h.signature(root))
    full = [item["nodeid"] for item in receipts[0]["inventory"]]
    selected = receipts[0]["selected"] + receipts[1]["selected"]
    assert Counter(full) == Counter(selected)
    assert set(receipts[0]["selected"]).isdisjoint(receipts[1]["selected"])
    assert all(Counter(m["selected"]) == Counter(m["completed"]) for m in receipts)
    result = subprocess.run([sys.executable, "-I", "-S", str(SCRIPT), "verify", "--manifest-dir",
                             str(root / "artifacts")], cwd=root, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("defect", ["mixed-sha", "mixed-run", "mixed-attempt", "inventory", "duplicate-part",
                                    "missing-case", "extra-case", "unfinished", "nonzero", "collect-only",
                                    "empty-version", "numeric-version", "traversal"])
def test_gate_refuses_incomplete_or_mixed_runtime_manifests(miniature, defect):
    root, env, _, run = miniature
    h = helper()
    for part in (0, 1):
        assert run(part)[0].returncode == 0
    path = root / "artifacts/socle-parts-123-2-1/socle-part-1.json"
    data = json.loads(path.read_text())
    if defect.startswith("mixed-"):
        field = {"mixed-sha": "sha", "mixed-run": "run_id", "mixed-attempt": "attempt"}[defect]
        data[field] = "2" * 40 if field == "sha" else "999"
    elif defect == "inventory":
        data["inventory"].pop()
    elif defect == "duplicate-part":
        data["part"] = 0
    elif defect == "missing-case":
        data["completed"].pop()
    elif defect == "extra-case":
        data["completed"].append(data["completed"][0])
    elif defect == "unfinished":
        data["ended"] = False
    elif defect == "nonzero":
        data["exit"] = 1
    elif defect.endswith("version"):
        data["pytest_version"] = "" if defect == "empty-version" else 9
    elif defect == "traversal":
        data["inventory"][0]["path"] = "tests/../x.py"
        data["inventory"][0]["nodeid"] = "tests/../x.py::test_fictif"
    else:
        data["mode"] = "collect"
    path.write_text(json.dumps(data))
    identity, source = h.context(root, env), h.signature(root)
    with pytest.raises(h.RefusSocle):
        h.verify(root / "artifacts", identity, source)


@pytest.mark.parametrize("case", ["failure", "early-zero", "interrupt", "collection-error", "empty"])
def test_real_pytest_failure_or_early_exit_never_becomes_global_success(miniature, case):
    root, env, files, run = miniature
    h = helper()
    if case == "failure":
        files[0].write_text("def test_fictif():\n    assert 1 == 2\n")
    elif case == "early-zero":
        files[0].write_text("import pytest\ndef test_fictif():\n    pytest.exit('fictif', returncode=0)\n")
    elif case == "interrupt":
        files[0].write_text("def test_fictif():\n    raise KeyboardInterrupt\n")
    elif case == "collection-error":
        files[0].write_text("raise RuntimeError('erreur de collecte fictive')\n")
    else:
        files[0].unlink()
    first, _ = run(0)
    second, _ = run(1)
    if case == "early-zero":
        assert first.returncode != 0  # wrapper must reject a green pytest exit with an incomplete ledger
    else:
        assert first.returncode != 0
    identity, source = h.context(root, env), h.signature(root)
    with pytest.raises(h.RefusSocle):
        h.verify(root / "artifacts", identity, source)
    assert second.returncode == 0 or case == "collection-error"


def test_collect_is_observable_but_cannot_satisfy_runtime_gate(miniature):
    root, env, _, run = miniature
    h = helper()
    for part in (0, 1):
        result, path = run(part, mode="collect")
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(path.read_text())["mode"] == "collect"
    identity, source = h.context(root, env), h.signature(root)
    with pytest.raises(h.RefusSocle):
        h.verify(root / "artifacts", identity, source)


@pytest.mark.parametrize("parts,part", [(0, 0), (3, 0), (2, -1), (2, 2)])
def test_partition_configuration_is_closed(miniature, parts, part):
    _, _, _, run = miniature
    result, _ = run(part, parts=parts)
    assert result.returncode != 0


def test_ci_keeps_existing_gates_and_full_collection_on_both_runners():
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    socle = ci["jobs"]["socle"]
    assert socle["strategy"] == {"fail-fast": False, "max-parallel": 2, "matrix": {"part": [0, 1]}}
    step = next(s for s in socle["steps"] if s.get("name") == "Tests du socle")
    assert "tester_socle.py run" in step["run"]
    assert "--part" in step["run"] and "--parts 2" in step["run"]
    gates = ci["jobs"]["gates"]
    assert len(gates["needs"]) == 10 and "socle" in gates["needs"]
    assert any(s.get("uses") == "actions/download-artifact@634f93cb2916e3fdff6788551b99b062d0335ce0"
               for s in gates["steps"])
    assert any("tester_socle.py verify" in s.get("run", "") for s in gates["steps"])
    assert any(s.get("run") == "python .github/ci/selection_workflows.py gates" for s in gates["steps"])


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", '{"x":1,"x":2}'])
def test_json_rejects_nonstandard_constants_and_duplicate_keys(tmp_path, constant):
    h = helper()
    path = tmp_path / "fictif.json"
    path.write_text(constant)
    with pytest.raises(h.RefusSocle):
        h._read(path)


def test_last_collection_hook_preserves_duplicate_occurrences(miniature):
    root, env, _, run = miniature
    (root / "conftest.py").write_text(
        "def pytest_collection_modifyitems(items):\n    items.append(items[0])\n")
    h = helper()
    receipts = []
    for part in (0, 1):
        result, path = run(part)
        assert result.returncode == 0, result.stdout + result.stderr
        receipts.append(json.loads(path.read_text()))
    assert len(receipts[0]["inventory"]) == 5
    assert max(Counter(x["nodeid"] for x in receipts[0]["inventory"]).values()) == 2
    assert h.verify(root / "artifacts", h.context(root, env), h.signature(root))["tests"] == 5


@pytest.mark.parametrize("extra", ["artifact", "file", "missing"])
def test_gate_requires_exact_two_artifact_containers(miniature, extra):
    root, env, _, run = miniature
    h = helper()
    for part in (0, 1):
        assert run(part)[0].returncode == 0
    directory = root / "artifacts"
    if extra == "artifact":
        (directory / "socle-parts-123-2-2").mkdir()
    elif extra == "file":
        (directory / "socle-parts-123-2-0" / "extra.json").write_text("{}")
    else:
        (directory / "socle-parts-123-2-0" / "socle-part-0.json").unlink()
    with pytest.raises(h.RefusSocle):
        h.verify(directory, h.context(root, env), h.signature(root))
