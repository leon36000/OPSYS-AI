from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from _harness import assert_brand_contract


class _StubHandler(BaseHTTPRequestHandler):
    """Serveur stub qui renvoie sciemment des réponses en dehors du contrat."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/brand":
            self._send(200, "text/plain; charset=utf-8", b"pas json")
        else:
            self._send(
                404,
                "application/problem+json",
                json.dumps(
                    {"status": 500, "title": "oops", "detail": "incohérent"}
                ).encode("utf-8"),
            )

    def do_POST(self) -> None:
        # 405 sans header Allow et avec mauvais media-type
        self._send(405, "application/json", b"{}")

    def do_HEAD(self) -> None:
        self._send(405, "text/plain", b"")


@contextmanager
def _stub_server():
    srv = HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = srv.server_address
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_meta_harness_catches_bad_contract() -> None:
    with _stub_server() as base_url:
        with pytest.raises(AssertionError):
            assert_brand_contract(base_url)


if __name__ == "__main__":
    try:
        test_meta_harness_catches_bad_contract()
    except AssertionError:
        print("OK: le harnais a mordu sur le stub", file=sys.stderr)
        raise SystemExit(0)
    print("FAIL: le harnais n'a pas levé sur le stub", file=sys.stderr)
    raise SystemExit(1)
