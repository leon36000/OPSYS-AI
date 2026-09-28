import json
import os
import threading
import urllib.error
import urllib.request

import pytest
import yaml
from m7_marketing.brand import brand_schema
from m7_marketing.brand.brand_server import build_server

VALID_PROFILE = {
    "name": "OPSYS-AI",
    "tagline": "Systèmes complets d'automatisation d'entreprise par intelligence artificielle",
    "tone": "professionnel, factuel, français d'abord",
    "colors": ["#000000", "#FFFFFF"],
    "langue": "fr",
}


@pytest.fixture
def valid_profile_path(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text(
        yaml.safe_dump(VALID_PROFILE, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def server(valid_profile_path):
    srv = build_server(str(valid_profile_path), host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _server_url(srv, path="/brand"):
    host, port = srv.server_address
    return f"http://{host}:{port}{path}"


def _request(srv, path="/brand", method="GET"):
    req = urllib.request.Request(_server_url(srv, path), method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def _assert_problem(status, headers, body, expected_status):
    assert status == expected_status
    ct = headers.get("Content-Type", "")
    assert ct.startswith("application/problem+json")
    assert "Content-Length" in headers
    problem = json.loads(body.decode("utf-8"))
    assert problem["type"] == "about:blank"
    assert isinstance(problem["title"], str)
    assert problem["status"] == expected_status
    assert isinstance(problem["detail"], str)
    return problem


def test_get_brand_returns_200_and_valid_json(server, valid_profile_path):
    status, headers, body = _request(server)

    assert status == 200
    assert headers.get("Content-Type") == "application/json; charset=utf-8"
    assert "Content-Length" in headers

    payload = json.loads(body.decode("utf-8"))
    independently_loaded = yaml.safe_load(
        valid_profile_path.read_text(encoding="utf-8")
    )
    assert payload == independently_loaded
    assert set(payload.keys()) >= set(brand_schema.REQUIRED_FIELDS)


@pytest.mark.parametrize(
    "label, content",
    [
        ("missing_field", "tagline: x\ntone: x\ncolors:\n  - '#000'\nlangue: fr\n"),
        ("type_invalid", "name: OPSYS-AI\ntagline: 2024-01-01\ntone: x\ncolors:\n  - '#000'\nlangue: fr\n"),
        ("malformed_yaml", "name: [unclosed\n"),
        ("empty_file", ""),
    ],
)
def test_invalid_profile_returns_500_problem_json(tmp_path, label, content):
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(content, encoding="utf-8")

    srv = build_server(str(profile_path), host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, body = _request(srv)
        problem = _assert_problem(status, headers, body, 500)
        assert str(profile_path) not in problem["detail"]
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("path", ["/brand/", "/unknown", "/brand/extra"])
def test_unknown_paths_return_404(server, path):
    status, headers, body = _request(server, path=path)
    _assert_problem(status, headers, body, 404)


def test_post_to_brand_returns_405_with_allow_header(server):
    status, headers, body = _request(server, method="POST")
    problem = _assert_problem(status, headers, body, 405)
    assert headers.get("Allow") == "GET"
    assert "GET" in problem["detail"] or "GET" in problem["title"]


def test_python_object_tag_is_rejected_not_executed(tmp_path, monkeypatch):
    executed = []
    monkeypatch.setattr(os, "system", lambda cmd: executed.append(cmd) or 0)

    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        '!!python/object/apply:os.system ["true"]\n', encoding="utf-8"
    )

    srv = build_server(str(profile_path), host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, body = _request(srv)
        _assert_problem(status, headers, body, 500)
        assert not executed
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_unknown_date_yaml_field_returns_500_problem_json(tmp_path):
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "name: OPSYS-AI\n"
        "tagline: Systèmes complets d'automatisation d'entreprise par intelligence artificielle\n"
        "tone: professionnel, factuel, français d'abord\n"
        "colors:\n  - '#000000'\n  - '#FFFFFF'\n"
        "langue: fr\n"
        "created: 2026-07-24\n",
        encoding="utf-8",
    )

    srv = build_server(str(profile_path), host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, body = _request(srv)
        _assert_problem(status, headers, body, 500)
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_get_brand_with_query_string_returns_200(server):
    status, headers, body = _request(server, path="/brand?x=1")
    assert status == 200
    assert headers.get("Content-Type") == "application/json; charset=utf-8"
    payload = json.loads(body.decode("utf-8"))
    assert payload["name"] == "OPSYS-AI"

