from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parent / "fixtures" / "memoire" / "doubles.py"
SPEC = importlib.util.spec_from_file_location("pg_fixture_under_test_r5", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
fixture = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fixture
SPEC.loader.exec_module(fixture)

CONTAINER_ID = "a" * 64
SECRET = "fixture-secret-must-never-be-reported"
NAME_TOKEN = "cafef00d" * 2


class FakeOperationalError(Exception):
    pass


def _completed(args, *, code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, code, stdout=stdout, stderr=stderr)


def _tokens(monkeypatch):
    monkeypatch.setattr(fixture.secrets, "token_hex", lambda n: SECRET if n == 12 else NAME_TOKEN)


def _install_pg_connect_error(monkeypatch):
    class FakePsycopg:
        OperationalError = FakeOperationalError

        @staticmethod
        def connect(url, **kwargs):
            raise FakeOperationalError(f"connection refused: {url}")

    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg)


def _install_pg_connect_success(monkeypatch):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _sql):
            return None

    class FakePsycopg:
        OperationalError = FakeOperationalError

        @staticmethod
        def connect(_url, **_kwargs):
            return Connection()

    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg)


def _state_response(args, status):
    assert args[1:4] == ["inspect", "--format", "{{json .State}}"]
    return _completed(
        args,
        stdout=json.dumps({"Status": status, "ExitCode": 1, "OOMKilled": False, "Error": ""}),
    )


def test_partial_create_failure_diagnoses_and_cleans_only_its_unique_name(monkeypatch):
    calls = []
    name = f"opsys-pg-test-{NAME_TOKEN}"

    def run(args, **kwargs):
        calls.append(list(args))
        if args[1] == "create":
            assert args[args.index("--name") + 1] == name
            assert "--rm" not in args
            return _completed(args, code=1, stdout=f"{CONTAINER_ID}\n", stderr=f"create failed {SECRET}")
        if args[1] == "inspect":
            assert args[-1] == name
            return _state_response(args, "created")
        if args[1] == "logs":
            assert args[-1] == name
            return _completed(args, stdout=f"partial init {SECRET}", stderr="stderr detail")
        if args[1] == "rm":
            assert args == ["docker", "rm", "-f", "-v", name]
            return _completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(fixture.subprocess, "run", run)
    _tokens(monkeypatch)

    with pytest.raises(RuntimeError, match="docker create PostgreSQL a échoué") as caught, fixture.postgres_ephemere():
        pytest.fail("partial create must not yield")

    message = str(caught.value)
    assert "partial init [SECRET]" in message
    assert "stderr detail" in message
    assert SECRET not in message
    assert calls.index(["docker", "inspect", "--format", "{{json .State}}", name]) < calls.index(
        ["docker", "logs", "--tail", "50", "--timestamps", name]
    ) < calls.index(["docker", "rm", "-f", "-v", name])


def test_start_failure_captures_state_and_logs_before_id_cleanup(monkeypatch):
    calls = []
    name = f"opsys-pg-test-{NAME_TOKEN}"

    def run(args, **kwargs):
        calls.append(list(args))
        if args[1] == "create":
            assert args[args.index("--name") + 1] == name
            return _completed(args, stdout=f"{CONTAINER_ID}\n")
        if args[1] == "start":
            assert args[-1] == CONTAINER_ID
            return _completed(args, code=1, stderr=f"start failed {SECRET}")
        if args[1] == "inspect":
            assert args[-1] == CONTAINER_ID
            return _state_response(args, "created")
        if args[1] == "logs":
            assert args[-1] == CONTAINER_ID
            return _completed(args, stdout="start log", stderr=f"start stderr {SECRET}")
        if args[1] == "rm":
            assert args == ["docker", "rm", "-f", "-v", CONTAINER_ID]
            return _completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(fixture.subprocess, "run", run)
    _tokens(monkeypatch)

    with pytest.raises(RuntimeError, match="docker start PostgreSQL a échoué") as caught, fixture.postgres_ephemere():
        pytest.fail("failed start must not yield")

    message = str(caught.value)
    assert "start log" in message and "start stderr [SECRET]" in message
    assert SECRET not in message
    assert calls.index(["docker", "inspect", "--format", "{{json .State}}", CONTAINER_ID]) < calls.index(
        ["docker", "logs", "--tail", "50", "--timestamps", CONTAINER_ID]
    ) < calls.index(["docker", "rm", "-f", "-v", CONTAINER_ID])


def test_port_failure_keeps_error_and_removes_only_created_id(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(list(args))
        if args[1] == "create":
            return _completed(args, stdout=f"{CONTAINER_ID}\n")
        if args[1] == "start":
            return _completed(args, stdout=f"{CONTAINER_ID}\n")
        if args[1] == "port":
            raise subprocess.CalledProcessError(1, args, stderr="port mapping unavailable")
        if args[1] == "inspect":
            return _state_response(args, "running")
        if args[1] == "logs":
            return _completed(args, stdout="server log", stderr="daemon log")
        if args[1] == "rm":
            assert args == ["docker", "rm", "-f", "-v", CONTAINER_ID]
            return _completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(fixture.subprocess, "run", run)
    _tokens(monkeypatch)

    with pytest.raises(RuntimeError, match="publication du port") as caught, fixture.postgres_ephemere():
        pytest.fail("port failure must not yield")

    assert "server log" in str(caught.value) and "daemon log" in str(caught.value)
    assert calls.index(["docker", "inspect", "--format", "{{json .State}}", CONTAINER_ID]) < calls.index(
        ["docker", "logs", "--tail", "50", "--timestamps", CONTAINER_ID]
    ) < calls.index(["docker", "rm", "-f", "-v", CONTAINER_ID])


def test_readiness_exit_is_detected_without_waiting_and_redacts_secret(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr(fixture.subprocess, "run", lambda args, **kwargs: _run_readiness(args, kwargs, calls))
    monkeypatch.setattr(fixture.time, "sleep", sleeps.append)
    _tokens(monkeypatch)
    _install_pg_connect_error(monkeypatch)

    with pytest.raises(RuntimeError, match="a quitté avant readiness") as caught, fixture.postgres_ephemere():
        pytest.fail("readiness failure must not yield")

    assert "init exited [SECRET]" in str(caught.value)
    assert "stderr detail" in str(caught.value)
    assert SECRET not in str(caught.value)
    assert sleeps == []
    assert calls.index(["docker", "inspect", "--format", "{{json .State}}", CONTAINER_ID]) < calls.index(
        ["docker", "logs", "--tail", "50", "--timestamps", CONTAINER_ID]
    ) < calls.index(["docker", "rm", "-f", "-v", CONTAINER_ID])


def _run_readiness(args, kwargs, calls):
    calls.append(list(args))
    if args[1] == "create":
        return _completed(args, stdout=f"{CONTAINER_ID}\n")
    if args[1] == "start":
        return _completed(args, stdout=f"{CONTAINER_ID}\n")
    if args[1] == "port":
        return _completed(args, stdout="127.0.0.1:55432\n")
    if args[1] == "inspect":
        return _state_response(args, "exited")
    if args[1] == "logs":
        return _completed(args, stdout=f"init exited {SECRET}", stderr="stderr detail")
    if args[1] == "rm":
        assert args == ["docker", "rm", "-f", "-v", CONTAINER_ID]
        return _completed(args)
    raise AssertionError(f"unexpected command: {args}")


def test_cleanup_failure_is_reported_with_redacted_pre_remove_diagnostics(monkeypatch):
    calls = []
    _tokens(monkeypatch)
    _install_pg_connect_success(monkeypatch)

    def run(args, **kwargs):
        calls.append(list(args))
        if args[1] == "create":
            return _completed(args, stdout=f"{CONTAINER_ID}\n")
        if args[1] == "start":
            return _completed(args, stdout=f"{CONTAINER_ID}\n")
        if args[1] == "port":
            return _completed(args, stdout="127.0.0.1:55432\n")
        if args[1] == "rm":
            assert args == ["docker", "rm", "-f", "-v", CONTAINER_ID]
            return _completed(args, code=1, stderr=f"remove refused {SECRET}")
        if args[1] == "inspect":
            return _state_response(args, "running")
        if args[1] == "logs":
            return _completed(args, stdout=f"server log {SECRET}", stderr="stderr detail")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(fixture.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="nettoyage du conteneur") as caught, fixture.postgres_ephemere():
        pass

    message = str(caught.value)
    assert "server log [SECRET]" in message and "stderr detail" in message
    assert SECRET not in message
    assert calls[-1] == ["docker", "logs", "--tail", "50", "--timestamps", CONTAINER_ID]
    assert calls[-3] == ["docker", "rm", "-f", "-v", CONTAINER_ID]


@pytest.mark.parametrize("en_memoire", [False, True])
def test_creation_optionnelle_tmpfs_est_bornee_et_nettoie_seulement_son_conteneur(monkeypatch, en_memoire):
    calls = []
    monkeypatch.setattr(fixture.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(fixture, "_attendre", lambda *_args: None)
    _tokens(monkeypatch)

    def run(args, **kwargs):
        calls.append(list(args))
        assert kwargs["check"] is (args[1] == "port")
        if args[1] == "create":
            assert args[args.index("--name") + 1] == f"opsys-pg-test-{NAME_TOKEN}"
            return _completed(args, stdout=f"{CONTAINER_ID}\n")
        if args[1] == "start":
            assert args[-1] == CONTAINER_ID
            return _completed(args)
        if args[1] == "port":
            assert args[-2:] == [CONTAINER_ID, "5432/tcp"]
            return _completed(args, stdout="127.0.0.1:55432\n")
        if args[1] == "rm":
            assert args == ["docker", "rm", "-f", "-v", CONTAINER_ID]
            return _completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(fixture.subprocess, "run", run)

    with fixture.postgres_ephemere(stockage_en_memoire=en_memoire) as url:
        assert url.endswith("@127.0.0.1:55432/postgres")

    creation = calls[0]
    options = creation[creation.index("-p") + 2 : -1]
    if en_memoire:
        assert options == [
            "--pull=never",
            "--memory=512m",
            "--tmpfs",
            "/var/lib/postgresql/data:rw,noexec,nosuid,size=256m",
        ]
    else:
        assert options == []
    assert creation[-1] == fixture.IMAGE_PGVECTOR
    assert calls[-1] == ["docker", "rm", "-f", "-v", CONTAINER_ID]
    assert all(call[0] == "docker" for call in calls)


@pytest.mark.parametrize("valeur", [None, 0, 1, "true"])
def test_option_stockage_en_memoire_refuse_type_non_booleen_avant_docker(monkeypatch, valeur):
    appels_docker = []
    monkeypatch.setattr(fixture.subprocess, "run", lambda *args, **kwargs: appels_docker.append(args))

    with pytest.raises(TypeError, match="booléen strict"), fixture.postgres_ephemere(stockage_en_memoire=valeur):
        pytest.fail("une configuration invalide ne doit pas créer de conteneur")

    assert appels_docker == []
