"""Plan de contrôle OPSYS : approbations, consommation de tokens, artefacts tronqués, journal
d'audit, modes des départements.

Depuis ADR-0009, ces tables vivent dans la base de l'instance (`opsys.stockage`), comme le métier :
une même transaction couvre la décision humaine sur une approbation et l'exécution de l'outil
approuvé. `session()` reste le nom public utilisé par la CLI, la console, le plugin Hermes et le
serveur MCP : c'est un alias de `stockage.transaction`, qui fournit une connexion SQLAlchemy
(SQLite par défaut, PostgreSQL en option).

`dossier_opsys()` est ré-exportée ici pour compatibilité ; elle est définie dans
`opsys.stockage.moteur`, qui en a besoin pour situer la base par défaut.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, func, insert, select

from .stockage.moteur import connexion_courante, dossier_opsys, transaction
from .stockage.schema import APPROBATIONS, ARTEFACTS, JOURNAL, MODES_DEPARTEMENTS, USAGE_TOKENS

__all__ = ["dossier_opsys", "importer_etat_si_necessaire", "journaliser", "lire_journal", "session"]

# Tables du plan de contrôle héritées de l'ancien `etat.db` (ordre d'import : sans dépendance entre
# elles, le journal est traité à part pour ne pas rejouer ses anciens identifiants auto-incrémentés).
_TABLES_HERITEES = (APPROBATIONS, USAGE_TOKENS, ARTEFACTS, JOURNAL, MODES_DEPARTEMENTS)


def session() -> AbstractContextManager[Connection]:
    """Connexion transactionnelle à la base de l'instance ; alias de `stockage.transaction` (ADR-0009)."""
    return transaction()


def _inserer_journal(cnx: Connection, par: str, action: str, cible: str, details: dict | None = None):
    return cnx.execute(insert(JOURNAL).values(
        quand=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), par=par, action=action, cible=cible,
        details=json.dumps(details or {}, ensure_ascii=False, default=str),
    ))


def journaliser(cnx: Connection, par: str, action: str, cible: str, details: dict | None = None) -> None:
    """Journal d'audit append-only des décisions humaines et changements de configuration."""
    _inserer_journal(cnx, par, action, cible, details)


class CaptureTraceDocumentaireErreur(RuntimeError):
    """Panne technique fermée : l'appelant doit laisser sortir son SAVEPOINT."""


def _connexion_documentaire_m10(cnx: Connection) -> None:
    if (
        not isinstance(cnx, Connection) or cnx is not connexion_courante()
        or cnx.closed or not cnx.in_transaction() or cnx.get_nested_transaction() is None
    ):
        raise CaptureTraceDocumentaireErreur("capture documentaire indisponible")


def _journaliser_documentaire_m10(
    cnx: Connection, par: str, action: str, cible: str, details: dict | None = None,
) -> int:
    """PK native d'INSERT dans le SAVEPOINT canonique fourni, sans scan ou repli."""
    _connexion_documentaire_m10(cnx)
    try:
        result = _inserer_journal(cnx, par, action, cible, details)
        pk = result.inserted_primary_key
        if len(pk) != 1 or type(pk[0]) is not int or not 0 < pk[0] <= 2**63 - 1:
            raise CaptureTraceDocumentaireErreur("capture documentaire indisponible")
        return pk[0]
    except Exception:
        raise CaptureTraceDocumentaireErreur("capture documentaire indisponible") from None


def lire_journal(cnx: Connection, limite: int = 200) -> list[dict[str, Any]]:
    lignes = cnx.execute(select(JOURNAL).order_by(JOURNAL.c.id.desc()).limit(limite)).mappings().all()
    return [{**dict(ligne), "details": json.loads(ligne["details"])} for ligne in lignes]


def importer_etat_si_necessaire(cnx: Connection) -> bool:
    """Importe une seule fois l'ancien `OPSYS_HOME/etat.db` (sqlite3 brut, pré-ADR-0009) dans la
    base de l'instance ; rend `True` si un import a eu lieu.

    N'écrit rien si l'ancien fichier est absent, ou si une des tables cibles contient déjà des
    lignes (installation déjà migrée, ou déjà utilisée depuis). L'import et son état durable sont
    dans la même transaction ; la source est conservée pour permettre une reprise après arrêt brutal.
    Appelée par `stockage.migrer()`, donc au démarrage de la console et du serveur MCP.
    """
    dossier = dossier_opsys()
    ancien = dossier / "etat.db"
    source_archivee = False
    if not ancien.is_file():
        # Les versions précédentes renommaient la source avant le commit. Si le processus s'arrêtait dans cette
        # fenêtre, la transaction annulait les lignes et seule cette copie restait. Elle demeure reprenable.
        archives = sorted(
            chemin for chemin in dossier.glob("etat.db.migre-*")
            if chemin.is_file() and not chemin.name.endswith(("-wal", "-shm"))
        )
        if not archives:
            return False
        ancien = archives[-1]
        source_archivee = True
    deja_peuplees = any(
        cnx.execute(select(func.count()).select_from(table)).scalar_one() > 0 for table in _TABLES_HERITEES
    )
    if deja_peuplees:
        return False
    if source_archivee:
        # Une ancienne version pouvait déplacer le fichier principal en laissant son WAL sous le nom d'origine.
        # Le fichier principal est renommé uniquement après les écritures : réassocier ces preuves avant lecture.
        orphelin_wal = Path(f"{dossier / 'etat.db'}-wal")
        wal_archive = Path(f"{ancien}-wal")
        if orphelin_wal.is_file() and not wal_archive.exists():
            os.replace(orphelin_wal, wal_archive)
    # Lecture ponctuelle de l'ancien format : le plan de contrôle n'écrit plus jamais en sqlite3 brut.
    source = sqlite3.connect(ancien)
    source.row_factory = sqlite3.Row
    try:
        for table in (MODES_DEPARTEMENTS, ARTEFACTS, APPROBATIONS, USAGE_TOKENS):
            lignes = [dict(ligne) for ligne in source.execute(f"SELECT * FROM {table.name}").fetchall()]
            if lignes:
                cnx.execute(insert(table), lignes)
        journal = [dict(ligne) for ligne in source.execute("SELECT * FROM journal ORDER BY id").fetchall()]
        for ligne in journal:
            del ligne["id"]  # nouvel identifiant auto ; l'ordre d'insertion préserve la chronologie
            cnx.execute(insert(JOURNAL).values(**ligne))
    finally:
        source.close()
    # Le fichier reste disponible après le commit. Les lignes insérées dans la même transaction constituent l'état
    # durable d'import : si elles existent au prochain démarrage, le garde ci-dessus évite tout rejeu ; si le
    # processus s'arrête avant commit, SQLite annule tout et la source (originale ou ancienne copie renommée) repart.
    return True
