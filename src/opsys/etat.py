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
import sqlite3
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy import Connection, func, insert, select

from .stockage.moteur import dossier_opsys, transaction
from .stockage.schema import APPROBATIONS, ARTEFACTS, JOURNAL, MODES_DEPARTEMENTS, USAGE_TOKENS

__all__ = ["dossier_opsys", "importer_etat_si_necessaire", "journaliser", "lire_journal", "session"]

# Tables du plan de contrôle héritées de l'ancien `etat.db` (ordre d'import : sans dépendance entre
# elles, le journal est traité à part pour ne pas rejouer ses anciens identifiants auto-incrémentés).
_TABLES_HERITEES = (APPROBATIONS, USAGE_TOKENS, ARTEFACTS, JOURNAL, MODES_DEPARTEMENTS)


def session() -> AbstractContextManager[Connection]:
    """Connexion transactionnelle à la base de l'instance ; alias de `stockage.transaction` (ADR-0009)."""
    return transaction()


def journaliser(cnx: Connection, par: str, action: str, cible: str, details: dict | None = None) -> None:
    """Journal d'audit append-only des décisions humaines et changements de configuration."""
    cnx.execute(insert(JOURNAL).values(
        quand=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), par=par, action=action, cible=cible,
        details=json.dumps(details or {}, ensure_ascii=False, default=str),
    ))


def lire_journal(cnx: Connection, limite: int = 200) -> list[dict[str, Any]]:
    lignes = cnx.execute(select(JOURNAL).order_by(JOURNAL.c.id.desc()).limit(limite)).mappings().all()
    return [{**dict(ligne), "details": json.loads(ligne["details"])} for ligne in lignes]


def importer_etat_si_necessaire(cnx: Connection) -> bool:
    """Importe une seule fois l'ancien `OPSYS_HOME/etat.db` (sqlite3 brut, pré-ADR-0009) dans la
    base de l'instance, puis renomme le fichier ; rend `True` si un import a eu lieu.

    N'écrit rien si l'ancien fichier est absent, ou si une des tables cibles contient déjà des
    lignes (installation déjà migrée, ou déjà utilisée depuis) : idempotent, et jamais destructeur
    (T3 — la suppression définitive est une frontière humaine), l'ancien fichier est renommé, pas
    effacé. Appelée par `stockage.migrer()`, donc au démarrage de la console et du serveur MCP.
    """
    ancien = dossier_opsys() / "etat.db"
    if not ancien.is_file():
        return False
    deja_peuplees = any(
        cnx.execute(select(func.count()).select_from(table)).scalar_one() > 0 for table in _TABLES_HERITEES
    )
    if deja_peuplees:
        return False
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
    horodatage = dt.datetime.now(dt.UTC).strftime("%Y%m%d")
    ancien.rename(ancien.with_name(f"etat.db.migre-{horodatage}"))
    return True
