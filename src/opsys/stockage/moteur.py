"""Connexion à la base de l'instance et transaction par appel d'outil (ADR-0009).

- `dossier_opsys()` : racine `OPSYS_HOME` (défaut `~/.opsys`) — la base par défaut, l'ancien
  `etat.db` (migration, voir `opsys.etat`) et les fichiers de configuration y vivent tous.
- URL : `OPSYS_BASE_URL`, sinon SQLite `opsys.db` dans ce dossier.
- SQLite : WAL, clés étrangères, attente de 5 s sur verrou, `BEGIN IMMEDIATE` (l'écrivain prend le
  verrou dès le début : pas d'échec de promotion lecture → écriture entre deux processus).
- `transaction()` ouvre une transaction, ou un point de sauvegarde si une transaction est déjà en
  cours dans ce contexte : un échec interne n'annule que sa part.
- `inserer(cnx)` rend le constructeur `insert()` du dialecte de la connexion (SQLite ou
  PostgreSQL) : les deux comprennent `ON CONFLICT ... DO UPDATE`, mais pas depuis le même module.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, event

ENV_URL = "OPSYS_BASE_URL"

_CONNEXION: ContextVar[Connection | None] = ContextVar("opsys_connexion", default=None)
_MOTEURS: dict[str, Engine] = {}
_VERROU = threading.Lock()


def dossier_opsys() -> Path:
    """Dossier d'état : OPSYS_HOME, sinon ~/.opsys."""
    return Path(os.environ.get("OPSYS_HOME", Path.home() / ".opsys"))


def url_base() -> str:
    url = os.environ.get(ENV_URL, "").strip()
    if url:
        return url
    dossier = dossier_opsys()
    dossier.mkdir(mode=0o700, parents=True, exist_ok=True)
    return f"sqlite:///{dossier / 'opsys.db'}"


def moteur(url: str | None = None) -> Engine:
    cible = url or url_base()
    with _VERROU:
        existant = _MOTEURS.get(cible)
        if existant is not None:
            return existant
        nouveau = create_engine(cible, pool_pre_ping=True)
        if nouveau.dialect.name == "sqlite":
            event.listen(nouveau, "connect", _preparer_sqlite)
            event.listen(nouveau, "begin", _debuter_sqlite)
        _MOTEURS[cible] = nouveau
        return nouveau


def _preparer_sqlite(connexion_dbapi, _enregistrement) -> None:
    # Le pilote sqlite3 ne gère plus les transactions : SQLAlchemy les pilote (événement « begin »).
    connexion_dbapi.isolation_level = None
    curseur = connexion_dbapi.cursor()
    for pragma in ("journal_mode=WAL", "foreign_keys=ON", "busy_timeout=5000", "synchronous=NORMAL"):
        curseur.execute(f"PRAGMA {pragma}")
    curseur.close()


def _debuter_sqlite(connexion: Connection) -> None:
    connexion.exec_driver_sql("BEGIN IMMEDIATE")


def connexion_courante() -> Connection | None:
    return _CONNEXION.get()


@contextmanager
def transaction(url: str | None = None) -> Iterator[Connection]:
    courante = _CONNEXION.get()
    if courante is not None:
        with courante.begin_nested():
            yield courante
        return
    with moteur(url).begin() as connexion:
        jeton = _CONNEXION.set(connexion)
        try:
            yield connexion
        finally:
            _CONNEXION.reset(jeton)


def liberer() -> None:
    """Ferme les connexions ouvertes (fin de processus, tests)."""
    with _VERROU:
        for moteur_ouvert in _MOTEURS.values():
            moteur_ouvert.dispose()
        _MOTEURS.clear()


def inserer(cnx: Connection) -> Callable[..., Any]:
    """`insert()` du dialecte de `cnx`, pour un upsert `ON CONFLICT` portable SQLite/PostgreSQL."""
    if cnx.engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert
