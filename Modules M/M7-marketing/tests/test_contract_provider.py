"""Test du serveur brand contre le contrat gelé v1 — D-015 provider side."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from contextlib import contextmanager
from typing import Iterator

import pytest
import yaml

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "brand"))

from brand_schema import contract_version
from brand_server import build_server


# ---------------------------------------------------------------------------
# Fixture : serveur avec profil valide, port éphémère, teardown garanti
# ---------------------------------------------------------------------------
@pytest.fixture
def server() -> Iterator[str]:
    """Démarre un serveur HTTP de test avec un profil YAML valide."""
    # Profil YAML valide (même contenu que le profil de référence)
    valid_profile = """
name: OPSYS-AI
tagline: "Systèmes complets d'automatisation d'entreprise par intelligence artificielle"
tone: "professionnel, factuel, français d'abord"
colors: ["#000000", "#FFFFFF"]
langue: fr
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(valid_profile)
        profile_path = f.name

    try:
        # Port 0 = auto-assigné
        server = build_server(profile_path, host="127.0.0.1", port=0)
        host, port = server.server_address
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # petite pause pour s'assurer que le serveur écoute
        time.sleep(0.1)
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if os.path.exists(profile_path):
            os.unlink(profile_path)


@pytest.fixture
def server_invalid() -> Iterator[str]:
    """Démarre un serveur avec un profil YAML invalide (non-mapping)."""
    invalid_profile = """
- name: OPSYS-AI
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(invalid_profile)
        profile_path = f.name

    try:
        server = build_server(profile_path, host="127.0.0.1", port=0)
        host, port = server.server_address
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if os.path.exists(profile_path):
            os.unlink(profile_path)


def _get(url: str, timeout: int = 5):
    req = urllib.request.Request(url, method="GET")
    return urllib.request.urlopen(req, timeout=timeout)


def _post(url: str, timeout: int = 5):
    req = urllib.request.Request(url, data=b"", method="POST")
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        return e


# ---------------------------------------------------------------------------
# Tests provider
# ---------------------------------------------------------------------------
def test_get_brand_200_contract(server: str) -> None:
    """GET /brand → 200, champs conformes au contrat, header X-Contract-Version."""
    resp = _get(f"{server}/brand")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "application/json; charset=utf-8"
    assert resp.headers["X-Contract-Version"] == contract_version()

    body = json.loads(resp.read().decode("utf-8"))
    # Vérifier que tous les champs requis sont présents et du bon type
    for field in ("name", "tagline", "tone", "colors", "langue"):
        assert field in body
    assert isinstance(body["name"], str) and body["name"]
    assert isinstance(body["tagline"], str)
    assert isinstance(body["tone"], str)
    assert isinstance(body["langue"], str)
    assert isinstance(body["colors"], list) and len(body["colors"]) > 0
    assert all(isinstance(c, str) for c in body["colors"])


def test_get_unknown_404(server: str) -> None:
    """GET /inconnu → 404 problem+json + X-Contract-Version."""
    try:
        _get(f"{server}/inconnu")
    except urllib.error.HTTPError as e:
        assert e.code == 404
        assert e.headers["Content-Type"] == "application/problem+json; charset=utf-8"
        assert e.headers["X-Contract-Version"] == contract_version()
        body = json.loads(e.read().decode("utf-8"))
        assert body["status"] == 404
        assert body["type"] == "about:blank"
    else:
        pytest.fail("Expected HTTPError 404")


def test_post_brand_405(server: str) -> None:
    """POST /brand → 405 problem+json + Allow: GET + X-Contract-Version."""
    resp = _post(f"{server}/brand")
    assert resp.status == 405
    assert resp.headers["Content-Type"] == "application/problem+json; charset=utf-8"
    assert resp.headers["Allow"] == "GET"
    assert resp.headers["X-Contract-Version"] == contract_version()
    body = json.loads(resp.read().decode("utf-8"))
    assert body["status"] == 405


def test_invalid_profile_500(server_invalid: str) -> None:
    """GET /brand avec profil non-mapping → 500 problem+json + X-Contract-Version."""
    try:
        _get(f"{server_invalid}/brand")
    except urllib.error.HTTPError as e:
        assert e.code == 500
        assert e.headers["Content-Type"] == "application/problem+json; charset=utf-8"
        assert e.headers["X-Contract-Version"] == contract_version()
        body = json.loads(e.read().decode("utf-8"))
        assert body["status"] == 500
        assert "mapping" in body["detail"].lower()
    else:
        pytest.fail("Expected HTTPError 500")
