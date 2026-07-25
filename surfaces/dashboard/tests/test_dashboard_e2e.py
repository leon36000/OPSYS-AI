"""Tests e2e HTTP pour dashboard_server (P0-5a)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers

DASHBOARD = _helpers.import_dashboard_server()


@pytest.fixture
def config_path(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("mode: horaire\n", encoding="utf-8")
    return p


@pytest.fixture
def modules_valides(tmp_path):
    p = tmp_path / "modules.yaml"
    data = [
        {"nom": "module-a", "statut": "ok"},
        {"nom": "module-b", "statut": "degraded"},
    ]
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_get_root_html(config_path, modules_valides):
    with _helpers.running_server(DASHBOARD.build_server, config_path, modules_valides) as base_url:
        status, headers, body = _helpers.http_request(base_url, "/")
        text = body.decode("utf-8").lower()
        assert status == 200
        assert headers.get("content-type") == "text/html; charset=utf-8"
        assert "content-length" in headers
        assert '<html lang="fr"' in text
        assert "<header" in text
        assert "<main" in text
        assert "<footer" in text
        assert "<h1" in text
        assert '<th scope="col"' in text
        assert "horaire" in text
        assert "/health" in text
        assert "<script" not in text


def test_xss_module_name_est_echappe(config_path, tmp_path):
    modules_path = tmp_path / "modules.yaml"
    modules_path.write_text(
        yaml.safe_dump([{"nom": "<script>alert(1)</script>", "statut": "ok"}]),
        encoding="utf-8",
    )
    with _helpers.running_server(DASHBOARD.build_server, config_path, modules_path) as base_url:
        status, _, body = _helpers.http_request(base_url, "/")
        text = body.decode("utf-8").lower()
        assert status == 200
        assert "<script" not in text
        assert "&lt;script&gt;" in text


def test_get_health_json(config_path, modules_valides):
    with _helpers.running_server(DASHBOARD.build_server, config_path, modules_valides) as base_url:
        status, headers, body = _helpers.http_request(base_url, "/health")
        data = json.loads(body.decode("utf-8"))
        assert status == 200
        assert headers.get("content-type") == "application/json"
        assert "content-length" in headers
        assert data["status"] == "ok"
        assert data["mode"] == "horaire"
        assert data["mode_source"] == "config"
        assert data["modules_lisibles"] is True
        assert data["nb_modules"] == 2
        assert "ts" in data


def test_health_degraded_si_modules_illisibles(config_path, tmp_path):
    modules_path = tmp_path / "modules.yaml"
    modules_path.write_text("[ invalide", encoding="utf-8")
    with _helpers.running_server(DASHBOARD.build_server, config_path, modules_path) as base_url:
        status, _, body = _helpers.http_request(base_url, "/health")
        data = json.loads(body.decode("utf-8"))
        assert status == 200
        assert data["status"] == "degraded"
        assert data["modules_lisibles"] is False


def test_not_found_problem_json(config_path, modules_valides):
    with _helpers.running_server(DASHBOARD.build_server, config_path, modules_valides) as base_url:
        status, headers, body = _helpers.http_request(base_url, "/inexistant")
        data = json.loads(body.decode("utf-8"))
        assert status == 404
        assert headers.get("content-type") == "application/problem+json"
        assert "content-length" in headers
        assert data["status"] == 404
        assert "title" in data


def test_method_not_allowed(config_path, modules_valides):
    with _helpers.running_server(DASHBOARD.build_server, config_path, modules_valides) as base_url:
        status, headers, body = _helpers.http_request(base_url, "/", method="POST")
        data = json.loads(body.decode("utf-8"))
        assert status == 405
        assert headers.get("allow") == "GET"
        assert headers.get("content-type") == "application/problem+json"
        assert "content-length" in headers
        assert data["status"] == 405
