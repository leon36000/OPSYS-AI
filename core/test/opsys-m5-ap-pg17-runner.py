"""Test-only, owned PostgreSQL17 runner for the single Core HTTP stale-invoice case.

Uses the existing ephemeral fixture; never configures or restarts a Docker daemon.
The generated credential is shared with subprocesses only through a private temporary file.
"""

from __future__ import annotations

import contextlib
import ctypes
import dataclasses
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
TITLE = (
    "refuses an owner decision on an M5 AP correction made stale by a newer one on the same invoice"
    " on real PostgreSQL17"
)
SUITE = "OPSYS M5 AP N4 and owner M9 decisions through production Core leases and real Python HTTP"
TARGET = "src/agents/agent-bundle-mcp-runtime.opsys-m5-ap-postcommit.python-http.integration.test.ts"


def _interrupt(_signal, _frame) -> None:
    raise KeyboardInterrupt


class PidfdBackend:
    """Exact-process signals via Python wrappers or explicitly typed libc exports."""

    def __init__(self, *, force_libc: bool = False) -> None:
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.native = force_libc or not (
            callable(getattr(os, "pidfd_open", None)) and callable(getattr(signal, "pidfd_send_signal", None))
        )
        self.name = "libc" if self.native else "python"
        if self.native:
            try:
                self.native_open = self.libc.pidfd_open
                self.native_signal = self.libc.pidfd_send_signal
            except AttributeError:
                raise RuntimeError("Linux libc pidfd exports are unavailable") from None
            self.native_open.argtypes = [ctypes.c_int, ctypes.c_uint]
            self.native_open.restype = ctypes.c_int
            self.native_signal.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
            self.native_signal.restype = ctypes.c_int
        else:
            self.python_open = os.pidfd_open
            self.python_signal = signal.pidfd_send_signal
        # Prove open and signal permission before any child can be launched.
        fd = self.open(os.getpid())
        try:
            self.send(fd, 0)
        finally:
            os.close(fd)

    def open(self, pid: int) -> int:
        if not self.native:
            return self.python_open(pid, 0)
        fd = self.native_open(pid, 0)
        if fd < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return fd

    def send(self, fd: int, sig: int) -> None:
        if not self.native:
            self.python_signal(fd, sig, None, 0)
        elif self.native_signal(fd, sig, None, 0) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))


class OwnedProcessTree:
    """Linux-only live ownership anchor; no group signals or numeric-PID signal fallback."""

    def __init__(self, *, pidfds: PidfdBackend | None = None) -> None:
        sys.path.insert(0, str(REPO / "tests/fixtures"))
        # Reuse the repository's identity census and PinnedProcess record.
        import qualifier_verticale_core as processes

        self.processes = processes
        self.anchor = processes.process_identity(os.getpid())
        if self.anchor is None:
            raise RuntimeError("owned PG17 runner requires Linux /proc identity support")
        self.pidfds = pidfds if pidfds is not None else PidfdBackend()
        self.libc = self.pidfds.libc
        self.libc.prctl.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        self.libc.prctl.restype = ctypes.c_int
        previous = ctypes.c_int()
        if self.libc.prctl(37, ctypes.byref(previous), 0, 0, 0) != 0:
            raise RuntimeError("cannot read Linux child-subreaper state")
        self.previous_subreaper = previous.value
        self.pinned = {}
        self.audit = {"signal_strategy": "pidfd", "pidfd_backend": self.pidfds.name, "processes": [], "remaining": []}
        if len(processes.owned_processes(self.anchor)) != 1:
            raise RuntimeError("owned PG17 runner must have no existing descendants at launch")
        if self.libc.prctl(36, 1, 0, 0, 0) != 0:
            raise RuntimeError("cannot establish Linux child subreaper before launch")
        enabled = ctypes.c_int()
        if self.libc.prctl(37, ctypes.byref(enabled), 0, 0, 0) != 0 or enabled.value != 1:
            self.close()
            raise RuntimeError("Linux child subreaper could not be verified before launch")

    def close(self) -> None:
        for process in self.pinned.values():
            os.close(process.fd)
        self.pinned.clear()
        if self.libc.prctl(36, self.previous_subreaper, 0, 0, 0) != 0:
            raise RuntimeError("cannot restore Linux child-subreaper state")

    def descendants(self):
        # Parent/session metadata can change; the live anchor's PID/start identity cannot.
        current = self.processes.process_identity(self.anchor.pid)
        if (current is None or current.start_time != self.anchor.start_time
                or current.state in ("Z", "X", "x")):
            raise RuntimeError("owned PG17 runner anchor identity changed")
        return {
            pid: identity for pid, identity in self.processes.owned_processes(current).items()
            if pid != self.anchor.pid
        }

    def pin(self, identity):
        try:
            fd = self.pidfds.open(identity.pid)
        except ProcessLookupError:
            return None
        try:
            if self.processes.process_identity(identity.pid) != identity:
                os.close(fd)
                return None
            return self.processes.PinnedProcess(identity, fd)
        except BaseException:
            os.close(fd)
            raise

    def signal(self, process, sig: int) -> None:
        if process.fd is None:
            raise RuntimeError("pidfd required for every owned descendant signal")
        with contextlib.suppress(ProcessLookupError):
            self.pidfds.send(process.fd, sig)

    def capture(self):
        added = []
        for identity in self.descendants().values():
            key = (identity.pid, identity.start_time)
            if key not in self.pinned:
                process = self.pin(identity)
                if process is None:
                    continue
                if process.fd is None:
                    raise RuntimeError("pidfd required for every owned descendant")
                self.pinned[key] = process
                self.audit["processes"].append(dataclasses.asdict(identity))
                added.append(process)
                self.signal(process, signal.SIGSTOP)
        return added

    def freeze(self, timeout: float = 2) -> None:
        deadline = time.monotonic() + timeout
        while True:
            self.capture()
            for process in self.pinned.values():
                self.signal(process, signal.SIGSTOP)
            current = self.descendants()
            live = [p for p in current.values() if p.state not in ("Z", "X", "x")]
            if all((p.pid, p.start_time) in self.pinned and p.state in ("T", "t") for p in live):
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("owned descendant discovery did not freeze within deadline")
            time.sleep(0.005)

    def reap(self, child: subprocess.Popen | None) -> None:
        # Let Popen collect its own exit status before reaping adopted direct children.
        if child is not None:
            child.poll()
        for identity in self.descendants().values():
            if (child is None or identity.pid != child.pid) and identity.parent == self.anchor.pid:
                current = self.processes.process_identity(identity.pid)
                if current is not None and current.start_time == identity.start_time:
                    with contextlib.suppress(ChildProcessError):
                        os.waitpid(identity.pid, os.WNOHANG)

    def stop(self, child: subprocess.Popen | None) -> dict:
        # Repeated cancellation must not interrupt ownership cleanup halfway through.
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
        try:
            return self._stop(child)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)

    def _stop(self, child: subprocess.Popen | None) -> dict:
        """Cleanup also runs after leader exit; subreaper adoption retains detached orphans."""
        try:
            self.freeze()
            for process in self.pinned.values():
                self.signal(process, signal.SIGTERM)
                self.signal(process, signal.SIGCONT)
            deadline = time.monotonic() + 1
            while self.descendants() and time.monotonic() < deadline:
                self.reap(child)
                # A TERM handler may fork. Capture those children under the same live anchor.
                for process in self.capture():
                    self.signal(process, signal.SIGTERM)
                    self.signal(process, signal.SIGCONT)
                time.sleep(0.005)
        finally:
            # Freeze a closed descendant set again before KILL: stopped parents cannot fork.
            # Keep the anchor alive until adopted children have exited and been reaped.
            freeze_error = None
            try:
                self.freeze()
            except Exception as exc:
                freeze_error = exc
            finally:
                # Even an observation/freeze failure must cancel every safely pinned process.
                for process in self.pinned.values():
                    self.signal(process, signal.SIGKILL)
            deadline = time.monotonic() + 2
            while self.descendants():
                # Keep the live anchor until late-adopted or newly discovered processes are gone.
                for process in self.capture():
                    self.signal(process, signal.SIGKILL)
                self.reap(child)
                if time.monotonic() >= deadline:
                    self.audit["remaining"] = [dataclasses.asdict(p) for p in self.descendants().values()]
                    raise RuntimeError("owned descendants remain after bounded pidfd cleanup")
                time.sleep(0.005)
            if child is not None:
                child.wait(timeout=2)
            if freeze_error is not None:
                raise freeze_error
        return self.audit


def _require_one_pass(report: Path) -> None:
    root = ET.parse(report)
    cases = list(root.iter("testcase"))
    if (len(cases) != 1 or cases[0].get("name") != SUITE + " > " + TITLE
            or cases[0].get("classname") != TARGET):
        raise RuntimeError("PG17 proof requires exactly the explicitly named single test case")
    if any(list(cases[0].iter(tag)) for tag in ("skipped", "failure", "error")):
        raise RuntimeError("PG17 case did not pass without skip, failure or error")
    if any(list(root.iter(tag)) for tag in ("failure", "error")):
        raise RuntimeError("PG17 report contains a suite failure or error")


def main() -> int:
    sys.path.insert(0, str(REPO / "tests/fixtures"))
    from memoire.doubles import postgres_ephemere

    pnpm = json.loads(os.environ.get("OPSYS_TEST_PNPM_ARGV", '["pnpm"]'))
    if not isinstance(pnpm, list) or not pnpm or any(not isinstance(arg, str) or not arg for arg in pnpm):
        raise ValueError("OPSYS_TEST_PNPM_ARGV requires a nonempty JSON string array")
    pidfds = PidfdBackend()  # Fail closed on missing/denied APIs before Docker startup.
    previous = signal.signal(signal.SIGTERM, _interrupt)
    try:
        with tempfile.TemporaryDirectory(prefix="opsys-core-m5-pg17-") as directory:
            # TemporaryDirectory is private (0700), including transient output/JUnit reports.
            private = Path(directory)
            with postgres_ephemere(stockage_en_memoire=True) as url:
                url_file = private / "database-url"
                with open(url_file, "x", encoding="utf-8", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
                    stream.write(url.replace("postgresql://", "postgresql+psycopg://", 1))
                report = private / "result.xml"
                env = {
                    **os.environ,
                    "OPSYS_TEST_PYTHON": sys.executable,
                    "OPSYS_TEST_M5_AP_PG17_URL_FILE": str(url_file),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
                owned = OwnedProcessTree(pidfds=pidfds)
                child = None
                try:
                    try:
                        child = subprocess.Popen(
                            [*pnpm, "test", TARGET, "--testNamePattern", TITLE + "$",
                             "--reporter=default", "--reporter=junit", "--outputFile=" + str(report)],
                            cwd=REPO / "core", env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, start_new_session=True,
                        )
                        output, _ = child.communicate(timeout=300)
                    finally:
                        # Also covers cancellation after fork but before Popen returns its handle.
                        owned.stop(child)
                finally:
                    owned.close()
                # Redact even on failed SQL connections; never publish a generated DSN/password.
                password = urlsplit(url).password
                output = output.replace(url, "[PRIVATE_TEST_DSN]")
                if password:
                    output = output.replace(password, "[PRIVATE_TEST_PASSWORD]")
                artifact_dir = os.environ.get("OPSYS_TEST_M5_AP_PG17_ARTIFACT_DIR")
                if artifact_dir and report.is_file():
                    destination = Path(artifact_dir)
                    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
                    safe_report = report.read_text().replace(url, "[PRIVATE_TEST_DSN]")
                    if password:
                        safe_report = safe_report.replace(password, "[PRIVATE_TEST_PASSWORD]")
                    with open(
                        destination / "junit.xml", "x", encoding="utf-8",
                        opener=lambda p, flags: os.open(p, flags, 0o600)
                    ) as stream:
                        stream.write(safe_report)
                print(output, end="")
                if child.returncode:
                    raise RuntimeError("targeted Core PostgreSQL17 test process failed")
                _require_one_pass(report)
                print("PG17: exactly one named stale-invoice case passed; read-only server witness asserted")
        return 0
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Owned PostgreSQL17 test cancelled; cleanup requested", file=sys.stderr)
        raise SystemExit(130) from None
