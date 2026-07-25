from __future__ import annotations

import importlib
import logging
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
AUTH_DIR = REPO_ROOT / "core" / "src" / "auth"


def _load_auth_module(name: str):
    original_path = list(sys.path)
    for key in list(sys.modules):
        if key == name or key.startswith(f"{name}."):
            del sys.modules[key]
    sys.path.insert(0, str(AUTH_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path[:] = original_path


@pytest.fixture(scope="module")
def auth_modules():
    return (_load_auth_module("totp"), _load_auth_module("admin_gate"))


def _valid_secret() -> str:
    # 160 bits, 32 caractères Base32.
    return "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def _short_secret() -> str:
    # 80 bits, rejeté car < 128 bits.
    return "JBSWY3DPEHPK3PXP"


def _verify_or_false(totp, secret: str, code: str):  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    try:
        return totp.verify_totp(secret, code, window=1)
    except ValueError:
        return (False, None)


def test_source_sanity(auth_modules):
    totp_src = (AUTH_DIR / "totp.py").read_text(encoding="utf-8")
    gate_src = (AUTH_DIR / "admin_gate.py").read_text(encoding="utf-8")
    assert "compare_digest" in totp_src
    assert "X-Forwarded-For" not in gate_src


def test_totp_current_ok(auth_modules):
    totp, _ = auth_modules
    secret = _valid_secret()  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    now = int(time.time()) // 30
    code = totp.generate_totp(secret, timestep=now)
    ok, timestep = totp.verify_totp(secret, code, window=1)
    assert ok is True
    assert timestep == now


def test_totp_window_ok(auth_modules):
    totp, _ = auth_modules
    secret = _valid_secret()  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    now = int(time.time()) // 30
    for delta in (-1, 1):
        code = totp.generate_totp(secret, timestep=now + delta)
        ok, _ = totp.verify_totp(secret, code, window=1)
        assert ok is True


def test_totp_outside_window_ko(auth_modules):
    totp, _ = auth_modules
    secret = _valid_secret()  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    now = int(time.time()) // 30
    for delta in (-2, 2):
        code = totp.generate_totp(secret, timestep=now + delta)
        ok, _ = totp.verify_totp(secret, code, window=1)
        assert ok is False


@pytest.mark.parametrize(
    "bad_code",
    [
        "12345",
        "12345a",
        "١٢٣٤٥٦",
        "-12345",
        "1234567",
        "",
    ],
)
def test_totp_malformed_code_returns_false(auth_modules, bad_code):
    totp, _ = auth_modules
    secret = _valid_secret()  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    ok, _ = totp.verify_totp(secret, bad_code, window=1)
    assert ok is False


def test_totp_invalid_secret_returns_false(auth_modules):
    totp, _ = auth_modules
    ok, _ = totp.verify_totp("NOT@BASE32!", "000000", window=1)
    assert ok is False


def test_totp_short_secret_rejected(auth_modules):
    totp, _ = auth_modules
    short = _short_secret()
    with pytest.raises(ValueError):
        totp.generate_totp(short)
    ok, _ = _verify_or_false(totp, short, "000000")
    assert ok is False


def test_gate_brute_force_locks(auth_modules, monkeypatch):
    totp, admin_gate = auth_modules
    secret = _valid_secret()  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    monkeypatch.setenv("OPSYS_ADMIN_TOTP_SECRET", secret)
    gate = admin_gate.AdminGate()
    ip = "10.0.0.1"
    for _ in range(5):
        res = gate.verifier("000000", ip)
        assert res["autorise"] is False
    good = totp.generate_totp(secret)
    res = gate.verifier(good, ip)
    assert res["autorise"] is False
    assert res["raison"] == "verrouille"


def test_gate_replay_rejects(auth_modules, monkeypatch):
    totp, admin_gate = auth_modules
    secret = _valid_secret()  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    monkeypatch.setenv("OPSYS_ADMIN_TOTP_SECRET", secret)
    gate = admin_gate.AdminGate()
    ip = "10.0.0.2"
    code = totp.generate_totp(secret)
    assert gate.verifier(code, ip)["autorise"] is True
    res = gate.verifier(code, ip)
    assert res["autorise"] is False
    assert res["raison"] == "rejoue"


def test_gate_race_atomic(auth_modules, monkeypatch):
    totp, admin_gate = auth_modules
    secret = _valid_secret()  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    monkeypatch.setenv("OPSYS_ADMIN_TOTP_SECRET", secret)
    gate = admin_gate.AdminGate()
    ip = "10.0.0.3"
    code = totp.generate_totp(secret)
    results = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(8)

    def _worker():
        barrier.wait()
        res = gate.verifier(code, ip)
        with results_lock:
            results.append(res)

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    successes = [r for r in results if r["autorise"]]
    assert len(successes) == 1


def test_gate_secret_rotation_clears_replay(auth_modules, monkeypatch):
    totp, admin_gate = auth_modules
    old_secret = _valid_secret()  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    new_secret = "MZXW6YTBMZXW6YTBMZXW6YTBMZXW6YTB"  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    monkeypatch.setenv("OPSYS_ADMIN_TOTP_SECRET", old_secret)
    gate = admin_gate.AdminGate()
    ip = "10.0.0.4"
    old_code = totp.generate_totp(old_secret)
    assert gate.verifier(old_code, ip)["autorise"] is True
    monkeypatch.setenv("OPSYS_ADMIN_TOTP_SECRET", new_secret)
    new_code = totp.generate_totp(new_secret)
    assert gate.verifier(new_code, ip)["autorise"] is True


def test_gate_secret_absent_refuses(auth_modules, monkeypatch):
    _, admin_gate = auth_modules
    monkeypatch.delenv("OPSYS_ADMIN_TOTP_SECRET", raising=False)
    gate = admin_gate.AdminGate()
    res = gate.verifier("000000", "10.0.0.5")
    assert res["autorise"] is False
    assert res["raison"] == "mfa_non_configure"


def test_gate_logs_never_leak_secret_or_code(auth_modules, monkeypatch, caplog):
    totp, admin_gate = auth_modules
    secret = _valid_secret()  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    monkeypatch.setenv("OPSYS_ADMIN_TOTP_SECRET", secret)
    caplog.set_level(logging.INFO)
    gate = admin_gate.AdminGate()
    code = totp.generate_totp(secret)
    gate.verifier(code, "10.0.0.6")
    gate.verifier("000000", "10.0.0.6")
    assert secret not in caplog.text
    assert code not in caplog.text
