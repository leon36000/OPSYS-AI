from __future__ import annotations

import importlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from _helpers import http_request, import_dashboard_server, running_server

REPO_ROOT = Path(__file__).resolve().parents[3]


def _dashboard_server_module():
    for key in list(sys.modules):
        if key == "dashboard_server" or key.startswith("dashboard_server."):
            del sys.modules[key]
    core_src = REPO_ROOT / "core" / "src"
    original_path = list(sys.path)
    sys.path.insert(0, str(core_src))
    try:
        return import_dashboard_server()
    finally:
        sys.path[:] = original_path


def _totp_module():
    auth_dir = REPO_ROOT / "core" / "src" / "auth"
    original_path = list(sys.path)
    for key in list(sys.modules):
        if key in ("totp",) or key.startswith("totp."):
            del sys.modules[key]
    sys.path.insert(0, str(auth_dir))
    try:
        return importlib.import_module("totp")
    finally:
        sys.path[:] = original_path


def _valid_secret() -> str:
    return "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def _admin_get(base_url: str, code: str | None = None):
    req = urllib.request.Request(f"{base_url}/admin")
    if code is not None:
        req.add_header("X-Admin-Totp", code)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def _problem(body: bytes) -> dict:
    return json.loads(body.decode("utf-8"))


@pytest.fixture
def mfa_config_path(tmp_path: Path) -> Path:
    cfg = tmp_path / "dashboard_config.json"
    cfg.write_text(json.dumps({"title": "Test Dashboard"}), encoding="utf-8")
    return cfg


@pytest.fixture
def mfa_modules_path(tmp_path: Path) -> Path:
    p = tmp_path / "modules"
    p.mkdir()
    return p


def test_admin_missing_header_returns_401(mfa_config_path, mfa_modules_path, monkeypatch):
    # Configurer un secret MFA pour que le fail-closed ne s'applique pas
    monkeypatch.setenv("OPSYS_ADMIN_TOTP_SECRET", _valid_secret())
    srv = _dashboard_server_module()
    with running_server(srv.build_server, mfa_config_path, mfa_modules_path) as base_url:
        status, headers, body = _admin_get(base_url)  # pas d'en-tête
        assert status == 401
        assert headers.get("WWW-Authenticate") == "TOTP"
        assert "application/problem+json" in headers.get("Content-Type", "")


def test_admin_bad_code_returns_403(mfa_config_path, mfa_modules_path, monkeypatch):
    secret = _valid_secret()  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    monkeypatch.setenv("OPSYS_ADMIN_TOTP_SECRET", secret)
    srv = _dashboard_server_module()
    with running_server(srv.build_server, mfa_config_path, mfa_modules_path) as base_url:
        status, headers, body = _admin_get(base_url, code="000000")
        assert status == 403
        assert "application/problem+json" in headers.get("Content-Type", "")
        problem = _problem(body)
        assert "detail" in problem


def test_admin_valid_code_returns_200(mfa_config_path, mfa_modules_path, monkeypatch):
    secret = _valid_secret()  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    monkeypatch.setenv("OPSYS_ADMIN_TOTP_SECRET", secret)
    srv = _dashboard_server_module()
    totp = _totp_module()
    code = totp.generate_totp(secret)
    with running_server(srv.build_server, mfa_config_path, mfa_modules_path) as base_url:
        status, headers, body = _admin_get(base_url, code=code)
        assert status == 200
        assert "text/html" in headers.get("Content-Type", "")
        assert b'lang="fr"' in body


def test_admin_no_secret_returns_503(mfa_config_path, mfa_modules_path, monkeypatch):
    monkeypatch.delenv("OPSYS_ADMIN_TOTP_SECRET", raising=False)
    srv = _dashboard_server_module()
    with running_server(srv.build_server, mfa_config_path, mfa_modules_path) as base_url:
        status, headers, body = _admin_get(base_url)
        assert status == 503
        assert "application/problem+json" in headers.get("Content-Type", "")
        problem = _problem(body)
        detail = problem.get("detail", "")
        assert "MFA non configur" in detail or "mfa_non_configure" in detail


def test_root_and_health_regression(mfa_config_path, mfa_modules_path):
    srv = _dashboard_server_module()
    with running_server(srv.build_server, mfa_config_path, mfa_modules_path) as base_url:
        status, _, _ = http_request(base_url, "/")
        assert status == 200
        status, _, _ = http_request(base_url, "/health")
        assert status == 200
