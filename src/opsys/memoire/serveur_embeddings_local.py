"""Provider local OpenAI-compatible BGE-M3, sans téléchargement ni import lourd au démarrage global."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import os
import socket
import sys
import threading
import time
from contextlib import suppress
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any

from .embeddings import DIMENSION
from .profil_embeddings_local import (
    MODELE_LOCAL,
    PROFILE_SHA256,
    SHA_MODELE_LOCAL,
    SHA_TOKENIZER_LOCAL,
    recette_embedding,
)

MODELE = MODELE_LOCAL
SHA_MODELE = SHA_MODELE_LOCAL
SHA_TOKENIZER = SHA_TOKENIZER_LOCAL
TAILLE_MODELE = 569_694_530
TAILLE_TOKENIZER = 17_082_821
MAX_TOKENS = 512
MAX_CARACTERES = 20_000
MAX_CORPS_OCTETS = 128 * 1024
DELAI_ENTETES_CORPS_S = 10.0
DELAI_INACTIVITE_SOCKET_S = 5.0

RECETTE_EMBEDDING = recette_embedding()


def _profil_embedding() -> dict[str, Any]:
    return {"id": PROFILE_SHA256, "recipe": recette_embedding()}


class ErreurRequete(ValueError):
    """Requête d'embedding refusée avant inférence."""

    def __init__(self, message: str, code: str = "invalid_input") -> None:
        super().__init__(message)
        self.code = code


def encoder_entree(tokeniseur: Any, texte: str) -> tuple[list[int], list[int]]:
    """Encode sans troncature; la séquence tokenisée doit respecter la limite du provider."""
    if not isinstance(texte, str) or not texte.strip():
        raise ErreurRequete("input doit être un texte non vide")
    try:
        texte.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ErreurRequete("input contient une séquence Unicode invalide") from exc
    if len(texte) > MAX_CARACTERES:
        raise ErreurRequete(f"input dépasse {MAX_CARACTERES} caractères", "input_character_limit_exceeded")
    try:
        encodage = tokeniseur.encode(texte, add_special_tokens=True)
        ids = list(encodage.ids)
        masque = list(encodage.attention_mask)
    except Exception as exc:
        raise ErreurRequete("input non encodable") from exc
    if not ids or len(ids) != len(masque):
        raise ErreurRequete("encodage vide ou incohérent")
    if len(ids) > MAX_TOKENS:
        raise ErreurRequete(f"input dépasse la limite de {MAX_TOKENS} tokens", "input_token_limit_exceeded")
    return ids, masque


def _inference_avec_watchdog(session: Any, entrees: dict[str, Any], ort: Any, delai_s: float) -> Any:
    """Exécute dans le thread appelant; le timer annule ORT et est joint avant le retour."""
    options = ort.RunOptions()
    expire = threading.Event()

    def annuler() -> None:
        expire.set()
        with suppress(Exception):
            options.terminate = True

    minuteur = threading.Timer(delai_s, annuler)
    minuteur.daemon = True
    minuteur.start()
    try:
        try:
            resultat = session.run(["last_hidden_state"], entrees, run_options=options)
        except Exception:
            if expire.is_set():
                raise TimeoutError("délai d'inférence dépassé") from None
            raise RuntimeError("échec d'inférence locale") from None
    finally:
        minuteur.cancel()
        minuteur.join()
    if expire.is_set():
        raise TimeoutError("délai d'inférence dépassé")
    return resultat


class MoteurBgeLocal:
    """Adaptateur ONNX CPU reprenant tokenisation, CLS et normalisation R35."""

    def __init__(self, tokeniseur: Any, session: Any, ort: Any, np: Any, delai_s: float):
        self.tokeniseur = tokeniseur
        self.session = session
        self.ort = ort
        self.np = np
        self.delai_s = delai_s

    def embed_one(self, texte: str, delai_s: float) -> tuple[list[float], int]:
        debut = time.monotonic()
        ids, masque = encoder_entree(self.tokeniseur, texte)
        entrees = {
            "input_ids": self.np.asarray([ids], dtype=self.np.int64),
            "attention_mask": self.np.asarray([masque], dtype=self.np.int64),
        }
        restant = min(delai_s, self.delai_s) - (time.monotonic() - debut)
        if restant <= 0:
            raise TimeoutError("délai total dépassé avant inférence")
        sorties = _inference_avec_watchdog(self.session, entrees, self.ort, restant)
        if time.monotonic() - debut > delai_s:
            raise TimeoutError("délai total dépassé")
        if not isinstance(sorties, (list, tuple)) or len(sorties) != 1:
            raise RuntimeError("sortie ONNX inattendue")
        dernier = self.np.asarray(sorties[0])
        if dernier.shape != (1, len(ids), DIMENSION):
            raise RuntimeError("forme de sortie ONNX inattendue")
        vecteur = self.np.asarray(dernier[0, 0, :], dtype=self.np.float32)
        if vecteur.shape != (DIMENSION,) or not self.np.isfinite(vecteur).all():
            raise RuntimeError("vecteur ONNX absent, non fini ou de dimension inattendue")
        norme = float(self.np.linalg.norm(vecteur))
        if not math.isfinite(norme) or norme <= 0:
            raise RuntimeError("norme du vecteur ONNX invalide")
        vecteur = vecteur / norme
        if abs(float(self.np.linalg.norm(vecteur)) - 1.0) > 1e-5:
            raise RuntimeError("normalisation L2 invalide")
        return [float(valeur) for valeur in vecteur], len(ids)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fichier:
        for bloc in iter(lambda: fichier.read(1024 * 1024), b""):
            digest.update(bloc)
    return digest.hexdigest()


def _verifier_python_qualifie() -> None:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("provider local qualifié seulement sous Python 3.12; utiliser l'image R41")


def _charger_dependances_runtime() -> tuple[Any, Any, Any, Any]:
    """Charge les extras uniquement au lancement du serveur et diagnostique leur absence."""
    _verifier_python_qualifie()
    try:
        import numpy as np
        import onnxruntime as ort
        import tokenizers
        from tokenizers import Tokenizer
    except ImportError as exc:
        raise RuntimeError(
            "dépendances locales absentes : installer l'extra optionnel `.[embeddings-local]` sous Python 3.12"
        ) from exc
    if (np.__version__, ort.__version__, tokenizers.__version__) != ("2.3.5", "1.23.2", "0.23.2"):
        raise RuntimeError("versions runtime différentes des versions R35 qualifiées")
    return np, ort, tokenizers, Tokenizer


def charger_moteur(dossier: str | Path, delai_s: float = 25.0) -> MoteurBgeLocal:
    """Valide assets et API graphe avant de créer le seul moteur CPU autorisé."""
    _verifier_python_qualifie()
    racine = Path(dossier).expanduser().resolve(strict=True)
    modele = racine / "model-int8.onnx"
    tokenizer_json = racine / "tokenizer.json"
    for chemin, taille, empreinte, nom in (
        (modele, TAILLE_MODELE, SHA_MODELE, "modèle"),
        (tokenizer_json, TAILLE_TOKENIZER, SHA_TOKENIZER, "tokenizer"),
    ):
        if not chemin.is_file() or chemin.stat().st_size != taille or _sha256(chemin) != empreinte:
            raise RuntimeError(f"assets BGE-M3 locaux absents ou empreinte invalide ({nom})")

    # Dépendances optionnelles : aucun import ONNX/tokenizers depuis les commandes mémoire usuelles.
    np, ort, _tokenizers, Tokenizer = _charger_dependances_runtime()
    tokeniseur = Tokenizer.from_file(str(tokenizer_json))
    tokeniseur.no_truncation()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.enable_mem_pattern = False
    session = ort.InferenceSession(str(modele), sess_options=options, providers=["CPUExecutionProvider"])
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("le moteur doit utiliser exclusivement CPUExecutionProvider")
    entrees = session.get_inputs()
    sorties = session.get_outputs()
    if {item.name: item.type for item in entrees} != {"input_ids": "tensor(int64)", "attention_mask": "tensor(int64)"}:
        raise RuntimeError("entrées du graphe ONNX inattendues")
    if (
        len(sorties) != 1
        or sorties[0].name != "last_hidden_state"
        or sorties[0].type != "tensor(float)"
        or not sorties[0].shape
        or sorties[0].shape[-1] != DIMENSION
    ):
        raise RuntimeError("sortie du graphe ONNX inattendue")
    return MoteurBgeLocal(tokeniseur, session, ort, np, delai_s)


def _objet_json(paires: list[tuple[str, Any]]) -> dict[str, Any]:
    objet: dict[str, Any] = {}
    for cle, valeur in paires:
        if cle in objet:
            raise ValueError("clé JSON dupliquée")
        objet[cle] = valeur
    return objet


def _json_fini(valeur: str) -> Any:
    raise ValueError(f"constante JSON invalide: {valeur}")


class _HandlerEmbeddings(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        # Les journaux de base contiennent path/client et des valeurs d'en-tête pouvant être sensibles.
        return

    def _finir_lecture(self) -> None:
        self.server.finir_deadline_lecture()  # type: ignore[attr-defined]

    def _authentifie(self) -> bool:
        autorisation = self.headers.get("Authorization", "")
        attendu = f"Bearer {self.server.cle}".encode()  # type: ignore[attr-defined]
        return hmac.compare_digest(autorisation.encode("utf-8", "surrogatepass"), attendu)

    def _repondre(self, code: int, contenu: dict[str, Any] | None = None) -> None:
        self.close_connection = True
        brut = json.dumps(contenu or {}, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(brut)))
        self.send_header("Connection", "close")
        if code == HTTPStatus.SERVICE_UNAVAILABLE:
            self.send_header("Retry-After", "1")
        self.end_headers()
        with suppress(TimeoutError, BrokenPipeError, ConnectionResetError):
            self.wfile.write(brut)

    def _erreur(self, code: int, message: str, code_machine: str | None = None) -> None:
        erreur = {"message": message, "type": "invalid_request_error"}
        if code_machine:
            erreur["code"] = code_machine
        self._repondre(code, {"error": erreur})

    def _autorisation_requise(self) -> bool:
        if self._authentifie():
            return True
        self._finir_lecture()
        self._erreur(HTTPStatus.UNAUTHORIZED, "unauthorized")
        return False

    def do_GET(self) -> None:
        self._finir_lecture()
        if not self._autorisation_requise():
            return
        if self.path != "/healthz":
            self._erreur(HTTPStatus.NOT_FOUND, "not found")
            return
        moteur = self.server.moteur  # type: ignore[attr-defined]
        self._repondre(
            HTTPStatus.OK,
            {
                "status": "ready",
                "model": MODELE,
                "dimension": DIMENSION,
                "model_sha256": SHA_MODELE,
                "tokenizer_sha256": SHA_TOKENIZER,
                "opsys_embedding_profile": _profil_embedding(),
            }
            if moteur is not None
            else {"status": "unavailable"},
        )

    def do_POST(self) -> None:
        if not self._autorisation_requise():
            return
        if self.path != "/v1/embeddings":
            self._finir_lecture()
            self._erreur(HTTPStatus.NOT_FOUND, "not found")
            return
        contenu_type = self.headers.get("Content-Type", "").split(";", 1)
        media = contenu_type[0].strip().lower()
        charset = contenu_type[1].strip().lower().replace("'", '"') if len(contenu_type) == 2 else ""
        if media != "application/json" or (charset and charset not in {"charset=utf-8", 'charset="utf-8"'}):
            self._finir_lecture()
            self._erreur(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "content type must be UTF-8 application/json")
            return
        if self.headers.get("Transfer-Encoding"):
            self._finir_lecture()
            self._erreur(HTTPStatus.BAD_REQUEST, "transfer encoding is unsupported")
            return
        longueurs = self.headers.get_all("Content-Length", [])
        if len(longueurs) != 1 or len(longueurs[0]) > 9 or not longueurs[0].isascii() or not longueurs[0].isdigit():
            self._finir_lecture()
            self._erreur(HTTPStatus.BAD_REQUEST, "invalid content length")
            return
        taille = int(longueurs[0])
        if not 1 <= taille <= MAX_CORPS_OCTETS:
            self._finir_lecture()
            self._erreur(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large", "request_body_too_large")
            return
        try:
            brut = self.rfile.read(taille)
        except (TimeoutError, OSError):
            self.close_connection = True
            return
        self._finir_lecture()
        if len(brut) != taille:
            self._erreur(HTTPStatus.BAD_REQUEST, "incomplete request body")
            return
        try:
            texte_json = brut.decode("utf-8", "strict")
            donnees = json.loads(texte_json, object_pairs_hook=_objet_json, parse_constant=_json_fini)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            self._erreur(HTTPStatus.BAD_REQUEST, "invalid UTF-8 JSON")
            return
        if not isinstance(donnees, dict) or set(donnees) != {"model", "input"}:
            self._erreur(HTTPStatus.BAD_REQUEST, "expected model and input")
            return
        if donnees["model"] != MODELE:
            self._erreur(HTTPStatus.UNPROCESSABLE_ENTITY, "unsupported model")
            return
        entree = donnees["input"]
        if isinstance(entree, str):
            texte = entree
        elif isinstance(entree, list) and len(entree) == 1 and isinstance(entree[0], str):
            texte = entree[0]
        else:
            self._erreur(HTTPStatus.UNPROCESSABLE_ENTITY, "local provider accepts exactly one text")
            return
        try:
            texte.encode("utf-8", "strict")
        except UnicodeEncodeError:
            self._erreur(HTTPStatus.UNPROCESSABLE_ENTITY, "input contains invalid Unicode")
            return
        if not texte.strip():
            self._erreur(HTTPStatus.UNPROCESSABLE_ENTITY, "input must be non-empty text")
            return
        if len(texte) > MAX_CARACTERES:
            self._erreur(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "input exceeds character limit",
                         "input_character_limit_exceeded")
            return
        moteur = self.server.moteur  # type: ignore[attr-defined]
        try:
            vecteur, tokens = moteur.embed_one(texte, self.server.delai_s)  # type: ignore[attr-defined]
        except ErreurRequete as exc:
            statut = (HTTPStatus.REQUEST_ENTITY_TOO_LARGE
                      if exc.code == "input_token_limit_exceeded" else HTTPStatus.UNPROCESSABLE_ENTITY)
            self._erreur(statut, str(exc), exc.code)
            return
        except TimeoutError:
            self._erreur(HTTPStatus.GATEWAY_TIMEOUT, "inference deadline exceeded")
            return
        except Exception:
            self._erreur(HTTPStatus.INTERNAL_SERVER_ERROR, "local inference failed")
            return
        norme = math.sqrt(sum(valeur * valeur for valeur in vecteur)) if len(vecteur) == DIMENSION else 0.0
        if (
            len(vecteur) != DIMENSION
            or any(not math.isfinite(valeur) for valeur in vecteur)
            or not math.isfinite(norme)
            or abs(norme - 1.0) > 1e-5
        ):
            self._erreur(HTTPStatus.INTERNAL_SERVER_ERROR, "local inference returned invalid vector")
            return
        self._repondre(
            HTTPStatus.OK,
            {
                "object": "list",
                "model": MODELE,
                "opsys_embedding_profile": _profil_embedding(),
                "data": [{"object": "embedding", "index": 0, "embedding": vecteur}],
                "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
            },
        )


class ServeurEmbeddingsLocal(ThreadingMixIn, HTTPServer):
    """Serveur mono-inférence, threads plafonnés et rejet 503 avant travail en file."""

    daemon_threads = False
    block_on_close = True
    request_queue_size = 4
    allow_reuse_address = True

    def __init__(self, adresse: tuple[str, int], *, cle: str, moteur: Any, delai_s: float = 25.0):
        if not cle or len(cle) < 24:
            raise ValueError("OPSYS_EMBEDDINGS_CLE doit contenir au moins 24 caractères")
        if not math.isfinite(delai_s) or not 0.1 <= delai_s <= 25:
            raise ValueError("délai local doit être entre 0,1 et 25 secondes")
        try:
            ipaddress.ip_address(adresse[0])
        except ValueError as exc:
            raise ValueError("l'adresse de bind doit être une adresse IP numérique") from exc
        self.cle = cle
        self.moteur = moteur
        self.delai_s = delai_s
        self._slot = threading.BoundedSemaphore(1)
        self._local = threading.local()
        super().__init__(adresse, _HandlerEmbeddings)

    def process_request(self, request: socket.socket, client_address: Any) -> None:
        request.settimeout(DELAI_INACTIVITE_SOCKET_S)
        if not self._slot.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n"
                    b"Connection: close\r\nRetry-After: 1\r\n\r\n"
                )
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slot.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: Any) -> None:
        minuteur = threading.Timer(DELAI_ENTETES_CORPS_S, self._fermer_socket, (request,))
        minuteur.daemon = True
        self._local.deadline_lecture = minuteur
        minuteur.start()
        try:
            super().process_request_thread(request, client_address)
        finally:
            minuteur.cancel()
            minuteur.join()
            self._slot.release()

    @staticmethod
    def _fermer_socket(request: socket.socket) -> None:
        with suppress(OSError):
            request.shutdown(socket.SHUT_RDWR)

    def finir_deadline_lecture(self) -> None:
        minuteur = getattr(self._local, "deadline_lecture", None)
        if minuteur is not None:
            minuteur.cancel()
            if threading.current_thread() is not minuteur:
                minuteur.join()

    def handle_error(self, request: socket.socket, client_address: Any) -> None:
        # Aucune trace de requête, texte, adresse client ou valeur d'en-tête.
        return


def _configuration(environ: dict[str, str]) -> tuple[str, int, str, Path, float]:
    cle = environ.get("OPSYS_EMBEDDINGS_CLE", "")
    dossier = environ.get("OPSYS_EMBEDDINGS_ASSETS", "")
    hote = environ.get("OPSYS_EMBEDDINGS_HOST", "127.0.0.1")
    port_brut = environ.get("OPSYS_EMBEDDINGS_PORT", "8001")
    delai_brut = environ.get("OPSYS_EMBEDDINGS_DELAI_S", "25")
    if len(cle) < 24:
        raise ValueError("OPSYS_EMBEDDINGS_CLE manquante ou trop courte (24 caractères minimum)")
    if not dossier:
        raise ValueError("OPSYS_EMBEDDINGS_ASSETS doit désigner les assets locaux BGE-M3")
    try:
        ipaddress.ip_address(hote)
        if not port_brut.isascii() or not port_brut.isdigit() or len(port_brut) > 5:
            raise ValueError
        port = int(port_brut)
        delai = float(delai_brut)
        if not 1 <= port <= 65535 or not math.isfinite(delai) or not 0.1 <= delai <= 25:
            raise ValueError
    except ValueError as exc:
        raise ValueError("OPSYS_EMBEDDINGS_HOST, PORT ou DELAI_S invalide") from exc
    return hote, port, cle, Path(dossier), delai


def main() -> int:
    try:
        hote, port, cle, dossier, delai = _configuration(dict(os.environ))
        moteur = charger_moteur(dossier, delai)
        serveur = ServeurEmbeddingsLocal((hote, port), cle=cle, moteur=moteur, delai_s=delai)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"provider embeddings local: {exc}", file=sys.stderr)
        return 2
    try:
        serveur.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        serveur.shutdown()
        serveur.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
