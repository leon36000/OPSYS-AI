"""Base de l'instance (ADR-0009) : SQLite par défaut, PostgreSQL en option, une transaction par appel.

Usage :
- `migrer()` au démarrage (idempotent) ;
- `transaction()` autour d'une unité de travail (fait par `Capacites.appeler` pour chaque outil) ;
- `maillons(departement, registre)` comme stockage d'un registre append-only de département.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from .maillons import EcritureConcurrente, MaillonsDurables, maillons
from .moteur import ENV_URL, connexion_courante, dossier_opsys, inserer, liberer, moteur, transaction, url_base

__all__ = [
    "ENV_URL", "EcritureConcurrente", "MaillonsDurables", "connexion_courante", "dossier_opsys", "inserer",
    "liberer", "maillons", "migrer", "moteur", "revision_courante", "transaction", "url_base",
]

_MIGRATIONS = Path(__file__).parent / "migrations"


def _config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS))
    return config


def migrer(url: str | None = None) -> str:
    """Applique les migrations manquantes (idempotent), importe une seule fois l'ancien `etat.db`
    si un en reste (ADR-0009), et rend la révision atteinte."""
    from ..etat import importer_etat_si_necessaire  # import différé : etat dépend de stockage

    config = _config()
    with moteur(url).begin() as connexion:
        config.attributes["connection"] = connexion
        command.upgrade(config, "head")
        importer_etat_si_necessaire(connexion)
    return revision_courante(url)


def revision_courante(url: str | None = None) -> str:
    from alembic.runtime.migration import MigrationContext

    with moteur(url).connect() as connexion:
        return MigrationContext.configure(connexion).get_current_revision() or "aucune"
