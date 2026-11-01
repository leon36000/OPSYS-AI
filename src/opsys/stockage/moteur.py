"""Connexion à la base de l'instance et transaction par appel d'outil (ADR-0009).

- `dossier_opsys()` : racine `OPSYS_HOME` (défaut `~/.opsys`) — la base par défaut, l'ancien
  `etat.db` (migration, voir `opsys.etat`) et les fichiers de configuration y vivent tous.
- URL : `OPSYS_BASE_URL`, sinon SQLite `opsys.db` dans ce dossier.
- SQLite : WAL, clés étrangères, déclencheurs récursifs (sans eux, `INSERT OR REPLACE` supprime la ligne en conflit
  SANS déclencher les `BEFORE DELETE` d'immuabilité des journaux), attente de 5 s sur verrou, `BEGIN IMMEDIATE`
  (l'écrivain prend le verrou dès le début : pas d'échec de promotion lecture → écriture entre deux processus).
- `transaction()` ouvre une transaction, ou un point de sauvegarde si une transaction est déjà en
  cours dans ce contexte : un échec interne n'annule que sa part. Une autre base explicitement
  demandée est refusée avant toute écriture : elle ne peut pas rejoindre la transaction courante.
- `inserer(cnx)` rend le constructeur `insert()` du dialecte de la connexion (SQLite ou
  PostgreSQL) : les deux comprennent `ON CONFLICT ... DO UPDATE`, mais pas depuis le même module.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.engine import make_url

ENV_URL = "OPSYS_BASE_URL"

_CONNEXION: ContextVar[Connection | None] = ContextVar("opsys_connexion", default=None)
_MOTEURS: dict[str, Engine] = {}
_APRES_VALIDATION: ContextVar[list[Callable[[], None]] | None] = ContextVar("opsys_apres_validation", default=None)
_LOG = logging.getLogger(__name__)
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
    # recursive_triggers=ON : un REPLACE qui supprime une ligne en conflit fait alors déclencher les `BEFORE DELETE`
    # (journaux et registres immuables) ; à OFF (défaut SQLite) il les contournerait en silence.
    # synchronous=FULL par défaut (revue adverse D-5) : en WAL, NORMAL peut perdre les dernières validations lors d'une
    # coupure de courant ; pour un envoi (courriel, publication, paiement préparé) cela rejouerait une action déjà
    # faite hors de la base. `OPSYS_SQLITE_SYNCHRONOUS` (NORMAL ou EXTRA) existe pour les bancs de test.
    synchrone = os.environ.get("OPSYS_SQLITE_SYNCHRONOUS", "FULL").strip().upper() or "FULL"
    if synchrone not in {"NORMAL", "FULL", "EXTRA"}:
        raise RuntimeError(f"OPSYS_SQLITE_SYNCHRONOUS invalide : {synchrone!r} (NORMAL, FULL ou EXTRA)")
    for pragma in ("journal_mode=WAL", "foreign_keys=ON", "recursive_triggers=ON", "busy_timeout=5000",
                   f"synchronous={synchrone}"):
        curseur.execute(f"PRAGMA {pragma}")
    fichier = next((ligne[2] for ligne in curseur.execute("PRAGMA database_list") if ligne[1] == "main"), "")
    curseur.close()
    restreindre_base(fichier)


def restreindre_base(chemin: str) -> None:
    """La base (et son journal WAL) porte des renseignements personnels, des empreintes de mots de passe et les clés de
    chiffrement destructibles : retire tout accès au groupe et aux autres (0644 -> 0600), jamais l'inverse. Un
    compte qui n'est pas propriétaire, ou Windows (ACL), laisse le mode tel quel (relevé en qualification conteneur)."""
    if not chemin or os.name == "nt":
        return
    for suffixe in ("", "-wal", "-shm"):
        try:
            mode = os.stat(chemin + suffixe).st_mode
            if mode & 0o077:
                os.chmod(chemin + suffixe, mode & ~0o077 & 0o777)
        except OSError:
            continue


def _debuter_sqlite(connexion: Connection) -> None:
    connexion.exec_driver_sql("BEGIN IMMEDIATE")


def connexion_courante() -> Connection | None:
    return _CONNEXION.get()


def apres_validation(rappel: Callable[[], None]) -> bool:
    """Réveil borné après le vrai commit extérieur ; une file durable reste nécessaire."""
    rappels = _APRES_VALIDATION.get()
    if rappels is None or len(rappels) >= 4:
        return False
    rappels.append(rappel)
    return True


@contextmanager
def transaction(url: str | None = None) -> Iterator[Connection]:
    courante = _CONNEXION.get()
    if courante is not None:
        if url is not None and make_url(url or url_base()) != courante.engine.url:
            raise ValueError("transaction imbriquée vers une autre base explicitement demandée")
        parent = _APRES_VALIDATION.get()
        rappels: list[Callable[[], None]] = []
        jeton_rappels = _APRES_VALIDATION.set(rappels)
        try:
            with courante.begin_nested():
                yield courante
            if parent is not None:
                parent.extend(rappels[:max(0, 4 - len(parent))])
        finally:
            _APRES_VALIDATION.reset(jeton_rappels)
        return
    rappels = []
    with moteur(url).begin() as connexion:
        jeton = _CONNEXION.set(connexion)
        jeton_rappels = _APRES_VALIDATION.set(rappels)
        try:
            yield connexion
        finally:
            _APRES_VALIDATION.reset(jeton_rappels)
            _CONNEXION.reset(jeton)
    # Hors transaction ET contexte : une panne ne peut plus annuler le commit acquis.
    for rappel in rappels:
        try:
            rappel()
        except Exception:  # noqa: BLE001 — la file durable reste en attente, sans faux rollback
            _LOG.warning("maintenance après commit non terminée ; reprise durable requise")


def liberer(url: str | None = None) -> None:
    """Ferme les connexions ouvertes (fin de processus, tests) ; avec `url`, seulement celles de cette base
    (une instance temporaire, ex. l'évaluation) sans toucher à la base de l'instance courante."""
    with _VERROU:
        if url is not None:
            ouvert = _MOTEURS.pop(url, None)
            if ouvert is not None:
                ouvert.dispose()
            return
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
