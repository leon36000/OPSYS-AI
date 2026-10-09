"""The Core/HTTP regression must run after Python changes and reject false-green receipts."""

import contextlib
import importlib.util
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


def test_fast_shards_bound_worker_memory_and_keep_failure_telemetry():
    workflow = yaml.safe_load((ROOT / ".github/workflows/core.yml").read_text())
    job = workflow["jobs"]["tests"]
    assert job["strategy"]["matrix"]["morceau"] == [1, 2, 3, 4, 5, 6]
    assert job["strategy"]["fail-fast"] is False
    steps = [step for step in job["steps"] if "pnpm test:fast" in step.get("run", "")]
    assert len(steps) == 1
    step = steps[0]
    # Each worker inherits its own Node heap limit; it is not a shared RSS cap.
    assert step["env"]["NODE_OPTIONS"] == "--max-old-space-size=4096"
    assert step["env"]["OPENCLAW_VITEST_MAX_WORKERS"] == "1"
    assert step["shell"] == "bash"
    command = step["run"]
    assert "set -o pipefail" in command
    assert "--shard=${{ matrix.morceau }}/6" in command
    assert "--logHeapUsage" in command
    for reporter in ("verbose", "github-actions", "./scripts/lib/vitest-resource-reporter.mts"):
        assert f"--reporter={reporter}" in command
    assert 'tee "$RUNNER_TEMP/vitest.log"' in command
    assert "|| true" not in command
    assert "--passWithNoTests" not in command


def assert_dead_process(pid):
    # Linux proc_pid_stat(5), field 3: Z is zombie, X/x are dead. An alive
    # process in R/S/D/T/t/I must still fail, even if its parent already exited.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return
    assert stat.split(") ", 1)[1].split()[0] in ("Z", "X", "x")


def test_python_changes_trigger_the_core_http_qualification():
    workflow = yaml.safe_load((ROOT / ".github/workflows/core.yml").read_text())
    triggers = workflow[True]  # PyYAML interprets YAML 1.1's `on` as a boolean.
    assert set(triggers) == {"workflow_dispatch", "workflow_call"}
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    assert set(ci[True]) == {"push", "pull_request"}
    call = ci["jobs"]["core"]
    assert call["uses"] == "./.github/workflows/core.yml"
    assert call["needs"] == "changements"
    assert call["if"] == "needs.changements.outputs.core == 'true'"
    spec = importlib.util.spec_from_file_location("selection_ci_core", ROOT / ".github/ci/selection_workflows.py")
    assert spec is not None and spec.loader is not None
    selection = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(selection)
    policy = selection.lire_politique(ROOT / ".github/ci/workflows-applicables.json")
    assert policy["workflows"]["core"]["fichier"] == "core.yml"
    for event in ("push", "pull_request"):
        assert {"core/**", "src/**", "departments/**", "tests/**", "conftest.py", "pyproject.toml", "uv.lock"} <= set(
            policy["workflows"]["core"]["evenements"][event]["paths"]
        )
        for chemin in ("core/src/gateway/tools-invoke-http.ts", "src/opsys/outils.py",
                       "departments/m06-material-control/src/m6_material_control/outils.py",
                       "tests/e2e/test_verticale_affaire_durable.py", "conftest.py", "pyproject.toml", "uv.lock"):
            assert selection.selectionner_workflows(policy, [chemin], event, "main")["core"], chemin
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
            assert_dead_process(pid)
        assert all(not path.exists() for path in manifests)
    finally:
        for group in (child.pid, backend_pid):
            if group is not None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(group, signal.SIGKILL)
        child.wait(timeout=10)
        if child.stdout is not None:
            child.stdout.close()


@pytest.mark.parametrize("pidfds", [True, False])
def test_deadline_waits_for_owned_process_exit_before_removing_manifests(tmp_path, monkeypatch, pidfds):
    """Signal delivery can lag the parent exit; cleanup must observe the whole tree."""
    import threading

    backend_code = """
import os, subprocess, sys, threading
leaf_code = 'import os,threading;print(os.getpid(),flush=True);threading.Event().wait()'
leaf = subprocess.Popen([sys.executable, '-c', leaf_code], stdout=subprocess.PIPE, text=True)
print(str(os.getpid())+' '+leaf.stdout.readline().strip(), flush=True)
threading.Event().wait()
"""
    parent_code = """
import subprocess, sys, threading
backend = subprocess.Popen(
    [sys.executable, '-c', sys.argv[1]], stdout=subprocess.PIPE, text=True, start_new_session=True
)
print(backend.stdout.readline().strip(), flush=True)
threading.Event().wait()
"""
    manifest = tmp_path / "restauration-entree-fictive.json"
    manifest.write_text('{"fictif":true}')
    child = subprocess.Popen(
        [sys.executable, "-c", parent_code, backend_code], stdout=subprocess.PIPE, text=True, start_new_session=True
    )
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import threading;threading.Event().wait()"], start_new_session=True
    )
    original_killpg = os.killpg
    original_kill = os.kill
    original_pidfd_send_signal = signal.pidfd_send_signal
    timers = []
    manifests_at_delivery = []
    backend_pid = None

    def deliver_later(callback):
        def deliver():
            manifests_at_delivery.append(manifest.exists())
            with contextlib.suppress(ProcessLookupError):
                callback()

        timer = threading.Timer(0.05, deliver)
        timers.append(timer)
        timer.start()

    def delayed_killpg(group, sig):
        if group != child.pid and sig in (signal.SIGTERM, signal.SIGKILL):
            deliver_later(lambda: original_killpg(group, sig))
        else:
            original_killpg(group, sig)

    def delayed_kill(pid, sig):
        if pid != child.pid and sig in (signal.SIGTERM, signal.SIGKILL):
            deliver_later(lambda: original_kill(pid, sig))
        else:
            original_kill(pid, sig)

    def delayed_pidfd_send_signal(fd, sig, siginfo=None, flags=0):
        info = Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines()
        pid = int(next(line.split()[1] for line in info if line.startswith("Pid:")))
        if pid != child.pid and sig in (signal.SIGTERM, signal.SIGKILL):
            retained_fd = os.dup(fd)

            def send():
                try:
                    original_pidfd_send_signal(retained_fd, sig, siginfo, flags)
                finally:
                    os.close(retained_fd)

            deliver_later(send)
        else:
            original_pidfd_send_signal(fd, sig, siginfo, flags)

    try:
        assert child.stdout is not None
        backend_pid, leaf_pid = map(int, child.stdout.readline().split())
        monkeypatch.setattr(os, "killpg", delayed_killpg)
        monkeypatch.setattr(os, "kill", delayed_kill)
        if not pidfds:
            monkeypatch.delattr(os, "pidfd_open")
        monkeypatch.setattr(signal, "pidfd_send_signal", delayed_pidfd_send_signal)
        with pytest.raises(subprocess.TimeoutExpired):
            wait_qualification(child, tmp_path, timeout=0)
        assert child.poll() is not None
        for pid in (backend_pid, leaf_pid):
            assert_dead_process(pid)
        assert not manifest.exists()
        audits = list(tmp_path.glob("cleanup-*.log"))
        assert len(audits) == 1
        audit = json.loads(audits[0].read_text())
        assert audit["cleanup_complete"] is True and audit["remaining"] == []
        assert {row["pid"] for row in audit["processes"]} == {child.pid, backend_pid, leaf_pid}
        assert all(row["start_time"] > 0 for row in audit["processes"])
        assert audit["signal_strategy"] == ("pidfd" if pidfds else "revalidated_pid")
        assert unrelated.poll() is None
        for timer in timers:
            timer.join(timeout=1)
        assert manifests_at_delivery and all(manifests_at_delivery)
    finally:
        for timer in timers:
            timer.join(timeout=1)
        for group in (child.pid, backend_pid, unrelated.pid):
            if group is not None:
                with contextlib.suppress(ProcessLookupError):
                    original_killpg(group, signal.SIGKILL)
        child.wait(timeout=10)
        unrelated.wait(timeout=10)
        if child.stdout is not None:
            child.stdout.close()


@pytest.mark.parametrize("change", ["pid_reused", "snapshot_disappeared"])
def test_changed_process_identity_is_never_signalled_and_its_fd_is_closed(monkeypatch, change):
    import dataclasses

    import qualifier_verticale_core as qualification

    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import threading;threading.Event().wait()"], start_new_session=True
    )
    opened = []
    original_open = os.pidfd_open

    def record_open(pid):
        fd = original_open(pid)
        opened.append(fd)
        return fd

    try:
        identity = qualification.process_identity(unrelated.pid)
        assert identity is not None
        changed = (
            None
            if change == "snapshot_disappeared"
            else dataclasses.replace(identity, start_time=identity.start_time + 1)
        )
        monkeypatch.setattr(os, "pidfd_open", record_open)
        monkeypatch.setattr(qualification, "process_identity", lambda pid: changed)
        assert qualification.pin_process(identity) is None
        assert unrelated.poll() is None
        assert len(opened) == 1
        with pytest.raises(OSError) as error:
            os.fstat(opened[0])
        assert error.value.errno == 9  # EBADF: the rejected identity released its fd.
    finally:
        unrelated.kill()
        unrelated.wait(timeout=10)


def test_fallback_does_not_signal_a_reused_pid(monkeypatch):
    import dataclasses

    import qualifier_verticale_core as qualification

    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import threading;threading.Event().wait()"], start_new_session=True
    )
    try:
        identity = qualification.process_identity(unrelated.pid)
        assert identity is not None
        stale = dataclasses.replace(identity, start_time=identity.start_time + 1)
        qualification.signal_owned(qualification.PinnedProcess(stale, None), signal.SIGKILL)
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=10)


def test_failed_quiescence_stays_red_keeps_manifests_and_closes_pinned_fds(tmp_path, monkeypatch):
    import qualifier_verticale_core as qualification

    code = """
import os, subprocess, sys, threading
backend = subprocess.Popen(
    [sys.executable, '-c', 'import os,threading;print(os.getpid(),flush=True);threading.Event().wait()'],
    stdout=subprocess.PIPE, text=True, start_new_session=True
)
print(backend.stdout.readline().strip(),flush=True)
threading.Event().wait()
"""
    manifest = tmp_path / "restauration-entree-fictive.json"
    manifest.write_text('{"fictif":true}')
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, start_new_session=True)
    original_signal = qualification.signal_owned
    original_wait = qualification.wait_owned_exit
    original_pin = qualification.pin_process
    pinned_fds = []
    wait_budgets = []
    backend_pid = None

    def pin(identity):
        process = original_pin(identity)
        if process is not None and process.fd is not None:
            pinned_fds.append(process.fd)
        return process

    def withhold_termination(process, sig):
        if process.identity.pid == backend_pid and sig in (signal.SIGTERM, signal.SIGKILL):
            return
        original_signal(process, sig)

    def bounded_probe(processes, timeout):
        wait_budgets.append(timeout)
        return original_wait(processes, timeout=0.01)

    try:
        assert child.stdout is not None
        backend_pid = int(child.stdout.readline().strip())
        monkeypatch.setattr(qualification, "pin_process", pin)
        monkeypatch.setattr(qualification, "signal_owned", withhold_termination)
        monkeypatch.setattr(qualification, "wait_owned_exit", bounded_probe)
        with pytest.raises(RuntimeError, match="did not quiesce within 10 seconds after SIGKILL"):
            wait_qualification(child, tmp_path, timeout=0)
        assert manifest.exists()
        audits = list(tmp_path.glob("cleanup-*.log"))
        assert len(audits) == 1
        audit = json.loads(audits[0].read_text())
        assert audit["cleanup_complete"] is False
        assert "did not quiesce" in audit["error"]
        assert {row["pid"] for row in audit["remaining"]} == {backend_pid}
        assert wait_budgets == [10, 10, 10]
        assert len(pinned_fds) == 2
        for fd in pinned_fds:
            with pytest.raises(OSError) as error:
                os.fstat(fd)
            assert error.value.errno == 9
    finally:
        for group in (child.pid, backend_pid):
            if group is not None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(group, signal.SIGKILL)
        child.wait(timeout=10)
        if child.stdout is not None:
            child.stdout.close()


def test_reused_owner_cannot_claim_an_unrelated_process_tree(monkeypatch):
    import dataclasses

    import qualifier_verticale_core as qualification

    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import threading;threading.Event().wait()"], start_new_session=True
    )
    try:
        identity = qualification.process_identity(unrelated.pid)
        assert identity is not None
        stale = dataclasses.replace(identity, start_time=identity.start_time + 1)
        with pytest.raises(RuntimeError, match="owner identity changed"):
            qualification.owned_processes(stale)
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=10)


@pytest.mark.parametrize("moment", ["before_capture", "before_freeze", "during_discovery", "during_scan"])
def test_owner_exit_keeps_manifests_when_descendant_ownership_is_unknown(tmp_path, monkeypatch, moment):
    """Un parent mort ne prouve jamais la quiescence de descendants devenus orphelins."""
    import select
    import time

    import qualifier_verticale_core as qualification

    flag = tmp_path / "parent-exit"
    manifest = tmp_path / "restauration-entree-fictive.json"
    manifest.write_text('{"fictif":true}')
    backend_code = "import os,threading;print(os.getpid(),flush=True);threading.Event().wait()"
    parent_code = """
import subprocess, sys, threading
from pathlib import Path
backend = subprocess.Popen([sys.executable, '-c', sys.argv[1]], stdout=subprocess.PIPE,
                           text=True, start_new_session=True)
print(backend.stdout.readline().strip(), flush=True)
flag = Path(sys.argv[2])
while not flag.exists():
    threading.Event().wait(.005)
"""
    child = subprocess.Popen([sys.executable, "-c", parent_code, backend_code, str(flag)],
                             stdout=subprocess.PIPE, text=True, start_new_session=True)
    unrelated = subprocess.Popen([sys.executable, "-c", "import threading;threading.Event().wait()"],
                                 start_new_session=True)
    original_cancel = qualification.cancel_owned_processes
    original_signal = qualification.signal_owned
    original_discovery = qualification.owned_processes
    original_identity = qualification.process_identity
    original_pin = qualification.pin_process
    owned = []
    cancellation_fds = []

    def wait_dead_owner():
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            identity = original_identity(child.pid)
            if identity is not None and identity.state == "Z":
                return
            time.sleep(.005)
        raise RuntimeError("test owner did not exit within three seconds")

    def record_pin(identity):
        process = original_pin(identity)
        if process is not None and process.fd is not None:
            cancellation_fds.append(process.fd)
        return process

    try:
        assert child.stdout is not None and select.select([child.stdout], [], [], 3)[0]
        backend_pid = int(child.stdout.readline())
        for pid in (child.pid, backend_pid, unrelated.pid):
            identity = qualification.process_identity(pid)
            assert identity is not None
            pinned = original_pin(identity)
            assert pinned is not None
            owned.append(pinned)
        backend = owned[1]
        monkeypatch.setattr(qualification, "pin_process", record_pin)
        if moment == "before_capture":
            def parent_exits_before_capture(process, audit):
                flag.touch()
                wait_dead_owner()
                original_cancel(process, audit)

            monkeypatch.setattr(qualification, "cancel_owned_processes", parent_exits_before_capture)
        elif moment == "before_freeze":
            def parent_exits_before_freeze(process, sig):
                if process.identity.pid == child.pid and sig == signal.SIGSTOP:
                    flag.touch()
                    wait_dead_owner()
                original_signal(process, sig)

            monkeypatch.setattr(qualification, "signal_owned", parent_exits_before_freeze)
        elif moment == "during_discovery":
            def parent_exits_during_discovery(owner):
                original_signal(owned[0], signal.SIGKILL)
                wait_dead_owner()
                return original_discovery(owner)

            monkeypatch.setattr(qualification, "owned_processes", parent_exits_during_discovery)
        else:
            triggered = False

            def parent_exits_while_rows_are_read(pid):
                nonlocal triggered
                if pid == backend_pid and not triggered:
                    triggered = True
                    original_signal(owned[0], signal.SIGKILL)
                    wait_dead_owner()
                return original_identity(pid)

            monkeypatch.setattr(qualification, "process_identity", parent_exits_while_rows_are_read)
        with pytest.raises(RuntimeError, match="Qualification parent exited"):
            wait_qualification(child, tmp_path, timeout=0)
        assert manifest.exists()
        audit = json.loads(next(tmp_path.glob("cleanup-*.log")).read_text())
        assert audit["cleanup_complete"] is False and "parent exited" in audit["error"]
        # Aucun PID de manifeste n'est utilisé pour réclamer cet ancien descendant.
        assert backend_pid not in {row["pid"] for row in audit["processes"]}
        assert qualification.living_processes([backend]) == [backend]
        assert unrelated.poll() is None
        for fd in cancellation_fds:
            with pytest.raises(OSError) as error:
                os.fstat(fd)
            assert error.value.errno == 9
    finally:
        # Le test connaît ses propres identités initiales ; le harnais ne les invente pas.
        for process in owned:
            original_signal(process, signal.SIGKILL)
        qualification.wait_owned_exit(owned, timeout=3)
        child.wait(timeout=3)
        unrelated.wait(timeout=3)
        for process in owned:
            if process.fd is not None:
                os.close(process.fd)
        if child.stdout is not None:
            child.stdout.close()
