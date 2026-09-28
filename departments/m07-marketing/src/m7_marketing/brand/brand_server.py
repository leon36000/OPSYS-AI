"""Serveur HTTP minimal du profil de marque OPSYS-AI — version contrat gelé v1."""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import yaml

from . import brand_schema
from .brand_schema import contract_version


class _BrandHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def _send_problem(self, status: int, title: str, detail: str) -> None:
        body = json.dumps(
            {
                "type": "about:blank",
                "title": title,
                "status": status,
                "detail": detail,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/problem+json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if status == 405:
            self.send_header("Allow", "GET")
        self.send_header("X-Contract-Version", contract_version())
        self.end_headers()
        self.wfile.write(body)

    def _method_not_allowed(self) -> None:
        self._send_problem(
            405,
            "Method Not Allowed",
            "Seule la méthode GET est autorisée.",
        )

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path != "/brand":
            self._send_problem(404, "Not Found", "Le chemin demandé n'existe pas.")
            return

        try:
            with open(self.server.profile_path, encoding="utf-8") as file:
                raw = yaml.safe_load(file)
        except Exception:
            self._send_problem(
                500,
                "Internal Server Error",
                "Impossible de lire ou parser le profil.",
            )
            return

        if not isinstance(raw, dict):
            self._send_problem(
                500,
                "Internal Server Error",
                "Le profil doit être un mapping YAML.",
            )
            return

        try:
            profile = brand_schema.validate_profile(raw)
        except brand_schema.ProfileError as exc:
            self._send_problem(
                500,
                "Internal Server Error",
                f"Erreur de validation du champ {exc.field}: {exc.message}",
            )
            return

        body = json.dumps(profile, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Contract-Version", contract_version())
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = do_OPTIONS = _method_not_allowed


def build_server(profile_path: str, host: str = "127.0.0.1", port: int = 0):
    """Construit un ThreadingHTTPServer prêt à servir le profil de marque."""
    server = ThreadingHTTPServer((host, port), _BrandHandler)
    server.profile_path = profile_path
    return server


def main() -> None:
    profile_path = os.path.join(os.path.dirname(__file__), "profile.yaml")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    srv = build_server(profile_path, port=port)
    host, real_port = srv.server_address
    print(f"Serveur brand sur http://{host}:{real_port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
