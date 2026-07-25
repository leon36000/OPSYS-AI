"""Helpers e2e minimaux pour surfaces/dashboard (copiés, pas importés)."""
from __future__ import annotations

import contextlib
import http.client
import importlib
import socket
import sys
import threading
import time
import urllib.parse
from pathlib import Path


def import_dashboard_server():
    """Importe surfaces/dashboard/src/dashboard_server sans polluer sys.path."""
    src_dir = Path(__file__).resolve().parent.parent / "src"
    path = str(src_dir)
    sys.path.insert(0, path)
    try:
        return importlib.import_module("dashboard_server")
    finally:
        sys.path.remove(path)


def _wait_for_server(host: str, port: int, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"Le serveur {host}:{port} n'a pas démarré")


@contextlib.contextmanager
def running_server(build_server, config_path, modules_path, host="127.0.0.1", port=0):
    server = build_server(str(config_path), str(modules_path), host=host, port=port)
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _wait_for_server(host, actual_port)
        yield f"http://{host}:{actual_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def http_request(base_url: str, path: str = "/", method: str = "GET", timeout: float = 5.0):
    parsed = urllib.parse.urlparse(base_url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
    try:
        conn.request(method, path)
        resp = conn.getresponse()
        body = resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        return resp.status, headers, body
    finally:
        conn.close()
