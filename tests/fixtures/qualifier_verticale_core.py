"""Run the real Core/HTTP affair qualification with closed process environments.

Evidence directories are unique and never overwritten, including failed executions.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import errno
import json
import os
import select
import signal
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = (
    "tests/e2e/test_verticale_affaire_durable.py::"
    "test_affaire_unique_reprise_rejoint_facture_mesures_strategie_et_memoire[42.0-True-114.00-sqlite]"
)


@dataclasses.dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    parent: int
    group: int
    session: int
    start_time: int
    state: str = dataclasses.field(compare=False)


def process_identity(pid: int) -> ProcessIdentity | None:
    """Read identity, including the start clock, without confusing reused PIDs."""
    try:
        data = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = data[data.rindex(")") + 2 :].split()
        return ProcessIdentity(pid, int(fields[1]), int(fields[2]), int(fields[3]), int(fields[19]), fields[0])
    except (OSError, ValueError, IndexError):
        return None


def require_live_owner(owner: ProcessIdentity) -> ProcessIdentity:
    current = process_identity(owner.pid)
    if current is None or current.state in ("Z", "X", "x"):
        raise RuntimeError("Qualification parent exited before descendant discovery completed")
    if current != owner:
        raise RuntimeError("Qualification owner identity changed during descendant discovery")
    return current


def owned_processes(owner: ProcessIdentity) -> dict[int, ProcessIdentity]:
    require_live_owner(owner)
    rows = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        identity = process_identity(int(path.parent.name))
        if identity is not None:
            rows[identity.pid] = identity
    if rows.get(owner.pid) != owner:
        raise RuntimeError("Qualification owner identity changed during descendant discovery")
    require_live_owner(owner)
    descendants = {owner.pid}
    while True:
        more = {child for child, identity in rows.items() if identity.parent in descendants}
        if more <= descendants:
            break
        descendants |= more
    return {child: rows[child] for child in descendants if child in rows}


@dataclasses.dataclass
class PinnedProcess:
    identity: ProcessIdentity
    fd: int | None


def pin_process(identity: ProcessIdentity) -> PinnedProcess | None:
    """Open before revalidation so Linux signals target the exact captured process."""
    fd = None
    if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
        try:
            fd = os.pidfd_open(identity.pid)
        except ProcessLookupError:
            return None
        except OSError as error:
            if error.errno not in (errno.ENOSYS, errno.EINVAL):
                raise
    if process_identity(identity.pid) != identity:
        if fd is not None:
            os.close(fd)
        return None
    return PinnedProcess(identity, fd)


def signal_owned(process: PinnedProcess, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        if process.fd is not None:
            signal.pidfd_send_signal(process.fd, sig)
        elif (current := process_identity(process.identity.pid)) is not None and (
            current.start_time == process.identity.start_time
        ):
            # Older Linux kernels lack pidfds. Revalidate each individual PID;
            # never send a group signal that could include an unrelated owner.
            os.kill(process.identity.pid, sig)


def living_processes(processes: list[PinnedProcess]) -> list[PinnedProcess]:
    return [
        process
        for process in processes
        if (current := process_identity(process.identity.pid)) is not None
        and current.start_time == process.identity.start_time
        and current.state not in ("Z", "X", "x")
    ]


def wait_owned_exit(processes: list[PinnedProcess], timeout: float) -> list[PinnedProcess]:
    deadline = time.monotonic() + timeout
    while remaining := living_processes(processes):
        delay = deadline - time.monotonic()
        if delay <= 0:
            return remaining
        fds = [process.fd for process in remaining if process.fd is not None]
        if fds:
            select.select(fds, [], [], min(delay, 0.05))
        else:
            time.sleep(min(delay, 0.01))
    return []


def cancel_owned_processes(child, audit: dict) -> None:
    processes: dict[int, PinnedProcess] = {}
    try:
        root = process_identity(child.pid)
        if root is None or root.state in ("Z", "X", "x"):
            raise RuntimeError("Qualification parent exited before owned descendants could be established")
        if root.parent != os.getpid() or root.group != child.pid or root.session != child.pid:
            raise RuntimeError("Qualification parent identity is not an owned isolated session")
        pinned = pin_process(root)
        if pinned is None:
            raise RuntimeError("Qualification parent identity changed before cancellation")
        processes[child.pid] = pinned
        signal_owned(pinned, signal.SIGSTOP)
        # Freeze every captured descendant, including separately-sessioned ones.
        # Re-discover until all known parents are stopped and no child is new.
        deadline = time.monotonic() + 2
        while require_live_owner(root).state not in ("T", "t"):
            if time.monotonic() >= deadline:
                raise RuntimeError("Qualification parent did not stop within 2 seconds")
            time.sleep(0.005)
        while True:
            discovered = owned_processes(root)
            added = False
            for pid, identity in discovered.items():
                if pid not in processes and (pinned := pin_process(identity)) is not None:
                    processes[pid] = pinned
                    signal_owned(pinned, signal.SIGSTOP)
                    added = True
            active = living_processes(list(processes.values()))
            if (
                not added
                and all(
                    (current := process_identity(process.identity.pid)) is None
                    or current.start_time != process.identity.start_time
                    or current.state in ("T", "t", "Z")
                    for process in active
                )
                and require_live_owner(root).state in ("T", "t")
            ):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Owned process discovery did not quiesce within 2 seconds")
            time.sleep(0.005)
        audit["processes"] = [dataclasses.asdict(process.identity) for process in processes.values()]
        audit["signal_strategy"] = (
            "pidfd" if all(process.fd is not None for process in processes.values()) else "revalidated_pid"
        )
        for process in processes.values():
            signal_owned(process, signal.SIGTERM)
            signal_owned(process, signal.SIGCONT)
        remaining = wait_owned_exit(list(processes.values()), timeout=10)
        for process in remaining:
            signal_owned(process, signal.SIGKILL)
        remaining = wait_owned_exit(remaining, timeout=10)
        audit["remaining"] = [dataclasses.asdict(process.identity) for process in remaining]
        if remaining:
            raise RuntimeError("Owned process cancellation did not quiesce within 10 seconds after SIGKILL")
        child.wait(timeout=10)
    except Exception:
        audit["processes"] = [dataclasses.asdict(process.identity) for process in processes.values()]
        # A discovery/observation failure must remain red and keep manifests,
        # while every process already pinned is released and cancelled safely.
        for process in processes.values():
            signal_owned(process, signal.SIGKILL)
            signal_owned(process, signal.SIGCONT)
        wait_owned_exit(list(processes.values()), timeout=10)
        with contextlib.suppress(subprocess.TimeoutExpired):
            child.wait(timeout=10)
        raise
    finally:
        for process in processes.values():
            if process.fd is not None:
                os.close(process.fd)


def wait_qualification(child, destination: Path, *, timeout: float) -> int:
    """Cancel and observe all owned processes before removing private manifests."""
    try:
        return child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        audit = {"fictif": True, "parent_pid": child.pid, "cleanup_complete": False}
        try:
            cancel_owned_processes(child, audit)
            audit["cleanup_complete"] = True
            for pattern in ("restauration-entree-fictive.json", "restauration-*-manifest-fictif.json"):
                for manifest in destination.glob(pattern):
                    manifest.unlink(missing_ok=True)
        except Exception as error:
            audit["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            with (destination / f"cleanup-{uuid.uuid4().hex}.log").open("x", encoding="utf-8") as log:
                json.dump(audit, log, ensure_ascii=False, indent=2)
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
