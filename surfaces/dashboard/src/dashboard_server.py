#!/usr/bin/env python3
"""Squelette dashboard P0-5a."""
from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

ALLOWED_MODES = {"horaire", "temps-reel"}


def load_mode(config_path: Path | str) -> tuple[str, str]:
    """Renvoie (mode, source) avec priorité env > config > défaut."""
    raw_env = os.environ.get("OPSYS_MODE", "")
    if raw_env:
        if raw_env in ALLOWED_MODES:
            return raw_env, "env"
        return "horaire", "env"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and "mode" in data:
            if data["mode"] in ALLOWED_MODES:
                return data["mode"], "config"
            return "horaire", "config"
    except Exception:
        pass
    return "horaire", "default"


def load_modules(path: Path | str) -> tuple[list[dict[str, str]], bool]:
    """Charge le registre de modules. Renvoie (liste, lisible)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return [], False

    if data is None:
        return [], False

    modules_list: list[dict] = []
    if isinstance(data, dict):
        if "modules" in data and isinstance(data["modules"], list):
            modules_list = data["modules"]
        else:
            return [], False
    elif isinstance(data, list):
        modules_list = data
    else:
        return [], False

    result: list[dict[str, str]] = []
    for item in modules_list:
        if not isinstance(item, dict):
            return [], False
        name = item.get("nom") or item.get("name")
        if not isinstance(name, str) or not name:
            return [], False
        statut = item.get("statut", "inconnu")
        if not isinstance(statut, str):
            statut = "inconnu"
        result.append({"nom": name, "statut": statut})
    return result, True


def _render_html(mode: str, mode_source: str, modules: list[dict[str, str]]) -> bytes:
    rows = []
    for module in modules:
        name = html.escape(module["nom"])
        statut = html.escape(module["statut"])
        rows.append(f"<tr><td>{name}</td><td>{statut}</td></tr>")
    table_body = "\n".join(rows)

    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dashboard OPSYS-AI</title>
<style>
body {{ font-family: Arial, sans-serif; background: #ffffff; color: #111111; margin: 0; padding: 0; }}
header, footer {{ background: #f0f0f0; padding: 1rem; }}
main {{ padding: 1rem; }}
h1 {{ font-size: 1.5rem; }}
.mode-banner {{ background: #e8f4e8; border-left: 4px solid #2a6a2a; padding: 0.5rem; margin-bottom: 1rem; }}
table {{ border-collapse: collapse; width: 100%; max-width: 40rem; }}
th, td {{ border: 1px solid #333333; padding: 0.5rem; text-align: left; }}
th {{ background: #dddddd; }}
a {{ color: #005a9c; }}
</style>
</head>
<body>
<header>
  <h1>Dashboard OPSYS-AI</h1>
</header>
<main>
  <div class="mode-banner">Mode : {html.escape(mode)} (source : {html.escape(mode_source)})</div>
  <table>
    <thead>
      <tr><th scope="col">Module</th><th scope="col">Statut</th></tr>
    </thead>
    <tbody>
      {table_body}
    </tbody>
  </table>
  <p><a href="/health">État du système (/health)</a></p>
</main>
<footer>
  <p>OPSYS-AI — P0-5a</p>
</footer>
</body>
</html>"""
    return html_content.encode("utf-8")


class DashboardServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        config_path: Path | str,
        modules_path: Path | str,
        host: str = "127.0.0.1",
        port: int = 0,
    ):
        self.config_path = Path(config_path)
        self.modules_path = Path(modules_path)
        super().__init__((host, port), DashboardHandler)


class DashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002
        pass

    def _send_problem(
        self, status: int, title: str, allow: str | None = None
    ) -> None:
        body = json.dumps({"status": status, "title": title}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/problem+json")
        self.send_header("Content-Length", str(len(body)))
        if allow:
            self.send_header("Allow", allow)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        config_path = self.server.config_path
        modules_path = self.server.modules_path

        if self.path == "/":
            mode, mode_source = load_mode(config_path)
            modules, lisible = load_modules(modules_path)
            body = _render_html(mode, mode_source, modules)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            mode, mode_source = load_mode(config_path)
            modules, lisible = load_modules(modules_path)
            data = {
                "status": "ok" if lisible else "degraded",
                "mode": mode,
                "mode_source": mode_source,
                "modules_lisibles": lisible,
                "nb_modules": len(modules),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send_problem(404, "Not Found")

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/":
            self._send_problem(405, "Method Not Allowed", allow="GET")
        else:
            self._send_problem(404, "Not Found")


def build_server(
    config_path: Path | str,
    modules_registry_path: Path | str,
    host: str = "127.0.0.1",
    port: int = 0,
) -> DashboardServer:
    return DashboardServer(config_path, modules_registry_path, host, port)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dashboard OPSYS-AI P0-5a")
    parser.add_argument("port", nargs="?", type=int, default=0)
    args = parser.parse_args()

    here = Path(__file__).resolve().parent
    config_path = here.parent / "config.yaml"
    modules_path = here.parent.parent.parent / "registries" / "modules.yaml"

    server = build_server(config_path, modules_path, port=args.port)
    host, port = server.server_address
    print(f"Dashboard running on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
