from __future__ import annotations

import importlib
import json
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

BRAND_SRC = Path(__file__).resolve().parents[2] / "Modules M" / "M7-marketing" / "src" / "brand"
DEFAULT_PROFILE_PATH = BRAND_SRC / "profile.yaml"


def _purge_brand_modules() -> None:
    """Retire de sys.modules tout module brand_server/brand_schema pour forcer un rechargement frais."""
    for name in list(sys.modules.keys()):
        if name in ("brand_server", "brand_schema") or name.startswith(
            ("brand_server.", "brand_schema.")
        ):
            del sys.modules[name]


def load_brand_server():
    """Charge brand_server par importlib avec sys.path temporaire, puis restaure et purge."""
    original_path = list(sys.path)
    _purge_brand_modules()
    sys.path.insert(0, str(BRAND_SRC))
    try:
        brand_server = importlib.import_module("brand_server")
    finally:
        sys.path[:] = original_path
    _purge_brand_modules()
    return brand_server


def get_build_server():
    return load_brand_server().build_server


@contextmanager
def running_server(build_server, host: str = "127.0.0.1", port: int = 0) -> Iterator[str]:
    """Démarre un serveur dans un thread daemon et garantit le teardown."""
    srv = build_server(host=host, port=port)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        host_addr, real_port = srv.server_address
        yield f"http://{host_addr}:{real_port}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def http_request(url: str, method: str = "GET"):
    """Requête HTTP avec timeout 5 s ; retourne (code, headers, body)."""
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = b"" if method == "HEAD" else resp.read()
            return resp.status, resp.headers, body
    except urllib.error.HTTPError as exc:
        body = b"" if method == "HEAD" else exc.read()
        return exc.code, exc.headers, body


def http_get(url: str):
    return http_request(url, method="GET")


def media_type(headers) -> str:
    """Retourne le media-type sans paramètre charset."""
    return headers.get_content_type()


def _parse_json(body: bytes, context: str) -> dict:
    try:
        return json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise AssertionError(f"{context}: corps non JSON valide ({exc})")


def assert_get_brand_ok(base_url: str) -> None:
    code, headers, body = http_get(f"{base_url}/brand")
    assert code == 200, f"GET /brand attendu 200, obtenu {code}"
    assert media_type(headers) == "application/json", (
        f"GET /brand Content-Type inattendu: {headers.get('Content-Type')}"
    )
    data = _parse_json(body, "GET /brand")
    assert isinstance(data, dict), "GET /brand: le corps doit être un objet JSON"
    for key in ("name", "tagline", "tone", "colors", "langue"):
        assert key in data, f"GET /brand: clé '{key}' manquante"
    assert isinstance(data["name"], str)
    assert isinstance(data["tagline"], str)
    assert isinstance(data["tone"], str)
    assert isinstance(data["colors"], list)
    assert all(isinstance(c, str) for c in data["colors"])
    assert isinstance(data["langue"], str)


def assert_get_unknown_404(base_url: str) -> None:
    code, headers, body = http_get(f"{base_url}/inconnu")
    assert code == 404, f"GET /inconnu attendu 404, obtenu {code}"
    assert media_type(headers) == "application/problem+json", (
        f"GET /inconnu Content-Type inattendu: {headers.get('Content-Type')}"
    )
    problem = _parse_json(body, "GET /inconnu")
    assert problem.get("status") == 404, "problem+json.status doit valoir 404"
    assert "type" in problem, "problem+json doit contenir 'type'"
    assert "title" in problem, "problem+json doit contenir 'title'"
    assert "detail" in problem, "problem+json doit contenir 'detail'"


def assert_post_brand_405(base_url: str) -> None:
    code, headers, body = http_request(f"{base_url}/brand", method="POST")
    assert code == 405, f"POST /brand attendu 405, obtenu {code}"
    assert headers.get("Allow") == "GET", f"POST /brand header Allow manquant/incorrect: {headers.get('Allow')}"
    assert media_type(headers) == "application/problem+json", (
        f"POST /brand Content-Type inattendu: {headers.get('Content-Type')}"
    )


def assert_head_brand_405(base_url: str) -> None:
    # Comportement voulu : HEAD /brand -> 405 (pas de body attendu).
    code, _, _ = http_request(f"{base_url}/brand", method="HEAD")
    assert code == 405, f"HEAD /brand attendu 405, obtenu {code}"


def assert_get_brand_query_ok(base_url: str) -> None:
    code, _, _ = http_get(f"{base_url}/brand?x=1")
    assert code == 200, f"GET /brand?x=1 attendu 200, obtenu {code}"


def assert_get_brand_slash_404(base_url: str) -> None:
    code, _, _ = http_get(f"{base_url}/brand/")
    assert code == 404, f"GET /brand/ attendu 404, obtenu {code}"


def assert_brand_contract(base_url: str) -> None:
    """Ensemble des assertions structurelles du contrat /brand."""
    assert_get_brand_ok(base_url)
    assert_get_unknown_404(base_url)
    assert_post_brand_405(base_url)
    assert_head_brand_405(base_url)
    assert_get_brand_query_ok(base_url)
    assert_get_brand_slash_404(base_url)
