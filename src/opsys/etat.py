"""État du plan de contrôle OPSYS (SQLite en WAL, partagé par tous les processus d'un hôte).

Plan de contrôle et données métier sont séparés :
- ici (SQLite) : approbations, consommation de tokens, artefacts tronqués, modes des départements ;
- PostgreSQL : données métier et mémoire RAG (voir `opsys.stockage`, `opsys.memoire`).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approbations (
    id TEXT PRIMARY KEY,
    cree_le TEXT NOT NULL,
    departement TEXT NOT NULL,
    outil TEXT NOT NULL,
    arguments TEXT NOT NULL,
    motif_demande TEXT NOT NULL DEFAULT '',
    statut TEXT NOT NULL CHECK (statut IN ('en_attente','en_cours','refusee','executee','echec')),
    decide_par TEXT,
    decide_le TEXT,
    motif_decision TEXT,
    resultat TEXT
);
CREATE INDEX IF NOT EXISTS approbations_statut ON approbations(statut, cree_le);

CREATE TABLE IF NOT EXISTS usage_tokens (
    jour TEXT NOT NULL,
    departement TEXT NOT NULL,
    modele TEXT NOT NULL,
    appels INTEGER NOT NULL DEFAULT 0,
    tokens_entree INTEGER NOT NULL DEFAULT 0,
    tokens_sortie INTEGER NOT NULL DEFAULT 0,
    tokens_cache_lus INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (jour, departement, modele)
);

CREATE TABLE IF NOT EXISTS artefacts (
    id TEXT PRIMARY KEY,
    cree_le TEXT NOT NULL,
    source TEXT NOT NULL,
    taille INTEGER NOT NULL,
    contenu TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quand TEXT NOT NULL,
    par TEXT NOT NULL,
    action TEXT NOT NULL,
    cible TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS modes_departements (
    departement TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('ombre','supervise','autonome')),
    modifie_par TEXT NOT NULL,
    modifie_le TEXT NOT NULL
);
"""


def dossier_opsys() -> Path:
    """Dossier d'état : OPSYS_HOME, sinon ~/.opsys."""
    return Path(os.environ.get("OPSYS_HOME", Path.home() / ".opsys"))


def connexion(chemin: Path | None = None) -> sqlite3.Connection:
    """Ouvre (et migre) la base d'état. Une connexion par appelant : SQLite gère le partage."""
    fichier = chemin or dossier_opsys() / "etat.db"
    fichier.parent.mkdir(parents=True, exist_ok=True)
    cnx = sqlite3.connect(fichier, timeout=30, isolation_level=None)
    cnx.row_factory = sqlite3.Row
    cnx.execute("PRAGMA journal_mode=WAL")
    cnx.execute("PRAGMA busy_timeout=30000")
    cnx.executescript(_SCHEMA)
    return cnx


@contextmanager
def session(chemin: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Connexion courte, toujours fermée : à utiliser pour chaque opération."""
    cnx = connexion(chemin)
    try:
        yield cnx
    finally:
        cnx.close()


def journaliser(cnx: sqlite3.Connection, par: str, action: str, cible: str, details: dict | None = None) -> None:
    """Journal d'audit append-only des décisions humaines et changements de configuration."""
    cnx.execute(
        "INSERT INTO journal (quand, par, action, cible, details) VALUES (?, ?, ?, ?, ?)",
        (dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), par, action, cible,
         json.dumps(details or {}, ensure_ascii=False, default=str)),
    )


def lire_journal(cnx: sqlite3.Connection, limite: int = 200) -> list[dict]:
    lignes = cnx.execute("SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    return [{**dict(ligne), "details": json.loads(ligne["details"])} for ligne in lignes]
