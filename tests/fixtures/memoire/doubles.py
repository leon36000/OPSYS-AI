"""Doubles de test de la mémoire d'entreprise, pour les services externes uniquement.

- `plonger` : embeddings déterministes locaux à la place de bge-m3, qui est un service externe.
  C'est un sac haché de mots et de trigrammes de caractères, normalisé L2. Comme le plein texte, il
  récompense le vocabulaire partagé. Il tolère en plus les fautes de frappe et les mots collés, ce
  qu'un stemmer ne fait pas. Il n'a aucune prétention sémantique.
- `serveur_embeddings` : faux endpoint `/v1/embeddings` OpenAI-compatible qui sert `plonger`, avec des
  pannes paramétrables.
- `postgres_ephemere` : ce n'est pas un double. C'est un vrai PostgreSQL 17 + pgvector, dans un conteneur
  jetable.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import math
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import unicodedata
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

IMAGE_PGVECTOR = "pgvector/pgvector:pg17"
DOSSIER = Path(__file__).parent
DIMENSION = 1024


# -- embeddings déterministes -------------------------------------------------------------------
def _caracteristiques(texte: str) -> list[str]:
    decompose = unicodedata.normalize("NFKD", texte.lower())
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    caracteristiques = []
    for mot in re.findall(r"[a-z0-9]+", sans_accents):
        caracteristiques.append(f"m:{mot}")
        borne = f"<{mot}>"
        caracteristiques.extend(f"t:{borne[i:i + 3]}" for i in range(len(borne) - 2))
    return caracteristiques


def plonger(texte: str, dimension: int = DIMENSION) -> list[float]:
    """Vecteur unitaire déterministe du texte (sac haché de mots et de trigrammes)."""
    vecteur = [0.0] * dimension
    for caracteristique in _caracteristiques(texte):
        empreinte = hashlib.blake2b(caracteristique.encode("utf-8"), digest_size=8).digest()
        vecteur[int.from_bytes(empreinte, "big") % dimension] += 1.0
    norme = math.sqrt(sum(v * v for v in vecteur))
    if norme == 0.0:
        vecteur[0] = 1.0
        return vecteur
    return [v / norme for v in vecteur]


def plonger_lot(textes: list[str]) -> list[list[float]]:
    return [plonger(texte) for texte in textes]


# -- faux endpoint /v1/embeddings ---------------------------------------------------------------
@dataclasses.dataclass
class ServeurEmbeddings:
    url: str
    cle: str | None
    comportement: str
    delai_s: float
    ordre_inverse: bool
    requetes: list[dict[str, Any]] = dataclasses.field(default_factory=list)


class _Gestionnaire(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature imposée
        del format, args  # journal HTTP du double volontairement muet

    def _repondre(self, statut: int, corps: bytes) -> None:
        self.send_response(statut)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_POST(self) -> None:  # noqa: N802 - nom imposé par http.server
        etat: ServeurEmbeddings = self.server.etat
        longueur = int(self.headers.get("Content-Length", "0"))
        corps = json.loads(self.rfile.read(longueur) or b"{}")
        etat.requetes.append({"chemin": self.path, "autorisation": self.headers.get("Authorization"),
                              "corps": corps})
        if self.path != "/v1/embeddings":
            self._repondre(404, b'{"error": {"message": "route inconnue"}}')
            return
        if etat.cle is not None and self.headers.get("Authorization") != f"Bearer {etat.cle}":
            self._repondre(401, b'{"error": {"message": "cle invalide"}}')
            return
        if etat.delai_s:
            time.sleep(etat.delai_s)
        if etat.comportement == "http_500":
            self._repondre(500, b'{"error": {"message": "moteur d embeddings en panne"}}')
            return
        if etat.comportement == "json_invalide":
            self._repondre(200, b"<html>pas du JSON</html>")
            return
        entrees = corps.get("input", [])
        entrees = [entrees] if isinstance(entrees, str) else list(entrees)
        dimension = DIMENSION - 1 if etat.comportement == "dimension_fausse" else DIMENSION
        donnees = [{"object": "embedding", "index": i, "embedding": plonger(t, dimension)}
                   for i, t in enumerate(entrees)]
        if etat.comportement == "nombre_faux":
            donnees = donnees[:-1]
        if etat.comportement == "valeur_non_finie" and donnees:
            donnees[0]["embedding"][0] = float("nan")
        if etat.ordre_inverse:
            donnees.reverse()
        reponse = {"object": "list", "data": donnees, "model": corps.get("model"),
                   "usage": {"prompt_tokens": 0, "total_tokens": 0}}
        self._repondre(200, json.dumps(reponse).encode("utf-8"))


@contextlib.contextmanager
def serveur_embeddings(*, cle: str | None = None, comportement: str = "normal", delai_s: float = 0.0,
                       ordre_inverse: bool = False) -> Iterator[ServeurEmbeddings]:
    """Démarre le faux endpoint sur 127.0.0.1 (port libre) ; `url` se termine par `/v1`."""
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), _Gestionnaire)
    serveur.daemon_threads = True
    etat = ServeurEmbeddings(url=f"http://127.0.0.1:{serveur.server_address[1]}/v1", cle=cle,
                             comportement=comportement, delai_s=delai_s, ordre_inverse=ordre_inverse)
    serveur.etat = etat
    fil = threading.Thread(target=serveur.serve_forever, name="faux-embeddings", daemon=True)
    fil.start()
    try:
        yield etat
    finally:
        serveur.shutdown()
        serveur.server_close()
        fil.join(timeout=5)


def port_ferme() -> int:
    """Un port TCP local sur lequel rien n'écoute (pour simuler un service injoignable)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sonde:
        sonde.bind(("127.0.0.1", 0))
        return int(sonde.getsockname()[1])


# -- PostgreSQL 17 + pgvector réel, conteneur éphémère ------------------------------------------
def raison_sans_docker() -> str | None:
    """None si le démon docker répond ; sinon la raison exacte du SKIP (jamais un faux vert)."""
    docker = shutil.which("docker")
    if docker is None:
        return "docker introuvable dans le PATH : tests réels PostgreSQL + pgvector impossibles"
    try:
        sortie = subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"],
                                capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"démon docker injoignable ({exc}) : tests réels PostgreSQL + pgvector impossibles"
    if sortie.returncode != 0:
        detail = (sortie.stderr or sortie.stdout).strip().splitlines()[-1:] or ["sans détail"]
        return f"démon docker injoignable ({detail[0]}) : tests réels PostgreSQL + pgvector impossibles"
    return None


def _port_publie(conteneur: str) -> int:
    sortie = subprocess.run(["docker", "port", conteneur, "5432/tcp"], capture_output=True, text=True,
                            timeout=30, check=True)
    ligne = sortie.stdout.strip().splitlines()[0]
    return int(ligne.rsplit(":", 1)[1])


def _attendre(url: str, conteneur: str, delai_s: float) -> None:
    import psycopg

    limite = time.monotonic() + delai_s
    derniere: Exception | None = None
    while time.monotonic() < limite:
        try:
            with psycopg.connect(url, connect_timeout=2) as cnx:
                cnx.execute("SELECT 1")
                return
        except psycopg.OperationalError as exc:
            derniere = exc
            time.sleep(0.5)
    journal = subprocess.run(["docker", "logs", "--tail", "20", conteneur], capture_output=True, text=True,
                             timeout=30, check=False)
    raise TimeoutError(f"PostgreSQL pas prêt après {delai_s} s ({derniere}) ; journal :\n{journal.stderr}")


@contextlib.contextmanager
def postgres_ephemere(delai_s: float = 120.0) -> Iterator[str]:
    """`docker run -d --rm … -p 127.0.0.1::5432 pgvector/pgvector:pg17`, attend, rend l'URL, arrête."""
    mot_de_passe = secrets.token_hex(12)
    lancement = subprocess.run(
        ["docker", "run", "-d", "--rm", "-e", f"POSTGRES_PASSWORD={mot_de_passe}", "-p", "127.0.0.1::5432",
         IMAGE_PGVECTOR],
        capture_output=True, text=True, timeout=900, check=False,
    )
    if lancement.returncode != 0:
        raise RuntimeError(f"échec du démarrage de {IMAGE_PGVECTOR} : {lancement.stderr.strip()}")
    conteneur = lancement.stdout.strip()
    try:
        url = f"postgresql://postgres:{mot_de_passe}@127.0.0.1:{_port_publie(conteneur)}/postgres"
        _attendre(url, conteneur, delai_s)
        yield url
    finally:
        subprocess.run(["docker", "stop", "-t", "2", conteneur], capture_output=True, text=True, timeout=120,
                       check=False)


def vider(url: str) -> None:
    """Remet les tables de la mémoire à zéro entre deux tests (même conteneur)."""
    import psycopg

    with psycopg.connect(url) as cnx:
        cnx.execute("TRUNCATE memoire.fragments, memoire.documents, memoire.journal_effacements"
                    " RESTART IDENTITY CASCADE")


def jeu_or() -> dict[str, Any]:
    """Jeu d'or FR fictif (`fictif: true`) : fragments et questions annotées."""
    donnees = json.loads((DOSSIER / "jeu_or_fr.json").read_text(encoding="utf-8"))
    if donnees.get("fictif") is not True:
        raise ValueError("le jeu d'or de test doit porter fictif: true")
    return donnees
