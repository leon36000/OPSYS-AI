"""Faux serveur compatible OpenAI / LiteLLM (boucle locale, port éphémère) pour les tests de la passerelle de modèles.

Aucun réseau réel : le serveur n'écoute que 127.0.0.1. Il enregistre chaque requête (chemin, modèle, `max_tokens`,
authentification valide ou non) pour que les tests prouvent QUEL modèle a été appelé et avec quelle borne. Les pannes
sont programmables par modèle : `500`, `429`, `400`, `401`. Données fictives.
"""

from __future__ import annotations

import http.server
import json
import threading
from typing import Any

FICTIF = True
CLE_FICTIVE = "cle-fictive-passerelle-0123456789-ABCDEFGH"


class FauxLiteLLM:
    def __init__(self, cle: str | None = CLE_FICTIVE, dimension: int = 8) -> None:
        self.cle = cle
        self.dimension = dimension
        self.modeles: dict[str, dict[str, Any]] = {
            "opsys-haiku-5-5": {"mode": "chat", "in": 0.000001, "out": 0.000005},
            "opsys-sonnet-5-5": {"mode": "chat", "in": 0.000003, "out": 0.000015},
            "opsys-opus-5-5": {"mode": "chat", "in": 0.000015, "out": 0.000075},
            "opsys-vl-qwen3-30b": {"mode": "chat", "in": 0, "out": 0, "vision": True},
            "opsys-embed-e5-multilingue": {"mode": "embedding", "in": 0, "out": 0},
            "opsys-rerank-fictif": {"mode": "rerank", "in": 0, "out": 0},
        }
        self.pannes: dict[str, int] = {}
        self.appels: list[dict[str, Any]] = []
        self.verrou = threading.Lock()
        serveur = self

        class Gestionnaire(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return

            def _repondre(self, code: int, corps: Any) -> None:
                donnees = json.dumps(corps).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(donnees)))
                self.end_headers()
                self.wfile.write(donnees)

            def _autorise(self) -> bool:
                return serveur.cle is None or self.headers.get("Authorization") == f"Bearer {serveur.cle}"

            def do_GET(self) -> None:  # noqa: N802
                autorise = self._autorise()
                with serveur.verrou:
                    serveur.appels.append({"chemin": self.path, "methode": "GET", "autorise": autorise})
                if self.path == "/health/liveliness":
                    return self._repondre(200, "I'm alive!")
                if not autorise:
                    return self._repondre(401, {"error": {"message": "Authentication Error"}})
                if self.path == "/v1/models":
                    return self._repondre(
                        200, {"object": "list", "data": [{"id": nom, "object": "model"} for nom in serveur.modeles]}
                    )
                if self.path == "/model/info":
                    return self._repondre(
                        200,
                        {
                            "data": [
                                {
                                    "model_name": nom,
                                    "litellm_params": {
                                        "model": f"openrouter/amont/{nom}",
                                        "api_key": "cle-amont-piege-ne-doit-pas-sortir",
                                        "api_base": "http://interne.fictif",
                                    },
                                    "model_info": {
                                        "mode": m["mode"],
                                        "input_cost_per_token": m["in"],
                                        "output_cost_per_token": m["out"],
                                        "supports_vision": m.get("vision"),
                                    },
                                }
                                for nom, m in serveur.modeles.items()
                            ]
                        },
                    )
                return self._repondre(404, {"error": {"message": "inconnu"}})

            def do_POST(self) -> None:  # noqa: N802
                longueur = int(self.headers.get("Content-Length") or 0)
                corps = json.loads(self.rfile.read(longueur) or b"{}")
                autorise = self._autorise()
                modele = corps.get("model")
                with serveur.verrou:
                    serveur.appels.append(
                        {
                            "chemin": self.path,
                            "methode": "POST",
                            "modele": modele,
                            "max_tokens": corps.get("max_tokens"),
                            "autorise": autorise,
                            "corps": corps,
                        }
                    )
                if not autorise:
                    return self._repondre(401, {"error": {"message": "Authentication Error"}})
                if modele in serveur.pannes:
                    return self._repondre(serveur.pannes[modele], {"error": {"message": "panne programmée"}})
                if modele not in serveur.modeles:
                    return self._repondre(400, {"error": {"message": "modèle inconnu"}})
                if self.path == "/v1/chat/completions":
                    return self._repondre(
                        200,
                        {
                            "choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 12, "completion_tokens": 2},
                        },
                    )
                if self.path == "/v1/embeddings":
                    entrees = corps["input"]
                    return self._repondre(
                        200,
                        {
                            "data": [
                                {"index": i, "embedding": [round(0.1 * (j + 1), 3) for j in range(serveur.dimension)]}
                                for i in range(len(entrees))
                            ],
                            "usage": {"prompt_tokens": 3 * len(entrees)},
                        },
                    )
                if self.path == "/v1/rerank":
                    return self._repondre(
                        200,
                        {
                            "results": [
                                {"index": i, "relevance_score": 1.0 / (i + 1)} for i in range(len(corps["documents"]))
                            ],
                            "usage": {"prompt_tokens": 5},
                        },
                    )
                return self._repondre(404, {"error": {"message": "inconnu"}})

        self._http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self._fil = threading.Thread(target=self._http.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._http.server_address[1]}"

    def __enter__(self) -> FauxLiteLLM:
        self._fil.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self._http.shutdown()
        self._http.server_close()

    def appels_modele(self, modele: str) -> list[dict[str, Any]]:
        with self.verrou:
            return [a for a in self.appels if a.get("modele") == modele]
