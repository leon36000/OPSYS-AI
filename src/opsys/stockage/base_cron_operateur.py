"""Garde d'identité de la base canonique, partagée par l'opérateur cron privé et les mutations console.

SQLite : le fichier (chemin résolu). PostgreSQL : le serveur, le port et le nom de la base ; ni le compte ni le mot de
passe n'en font partie (une identité ne porte aucun secret, et deux comptes de la même base sont la même base)."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from .. import stockage


def identite_url_cron_operateur(url: Any) -> tuple[str, str, tuple[tuple[str, Any], ...]]:
    valeur = make_url(url)
    moteur = valeur.get_backend_name()
    if moteur == "postgresql":
        if not valeur.database or not valeur.host:
            raise ValueError("base non canonique")
        cible = f"{valeur.host.lower()}:{valeur.port or 5432}/{valeur.database}"
        return (valeur.drivername, cible, tuple(sorted(valeur.query.items())))
    if (moteur == "sqlite" and valeur.database
            and valeur.database != ":memory:" and not valeur.database.startswith("file:")):
        chemin = str(Path(valeur.database).expanduser().resolve())
        return (valeur.drivername, chemin, tuple(sorted(valeur.query.items())))
    raise ValueError("base non canonique")


def verifier_base_cron_operateur(cnx_factory: Any) -> tuple[str, str, tuple[tuple[str, Any], ...]]:
    try:
        canonique = identite_url_cron_operateur(stockage.url_base())
        with cnx_factory() as cnx:
            effective = identite_url_cron_operateur(cnx.engine.url)
            if stockage.connexion_courante() is not cnx:
                raise ValueError("factory non liée au stockage canonique")
    except Exception:
        raise ValueError("canal cron opérateur indisponible pour cette base") from None
    if effective != canonique:
        raise ValueError("canal cron opérateur réservé à la base canonique")
    return canonique


def dans_base_cron_operateur(
    cnx_factory: Any, identite_base: tuple[str, str, tuple[tuple[str, Any], ...]], operation: Callable[[], Any]
) -> Any:
    with cnx_factory() as cnx:
        if (stockage.connexion_courante() is not cnx
                or identite_url_cron_operateur(cnx.engine.url) != identite_base
                or identite_url_cron_operateur(stockage.url_base()) != identite_base):
            raise ValueError("base de données non autorisée")
        return operation()
