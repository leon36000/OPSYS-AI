"""Garde d'identité SQLite partagée par l'opérateur cron privé et les mutations console."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from .. import stockage


def identite_url_cron_operateur(url: Any) -> tuple[str, str, tuple[tuple[str, Any], ...]]:
    valeur = make_url(url)
    if (valeur.get_backend_name() != "sqlite" or not valeur.database
            or valeur.database == ":memory:" or valeur.database.startswith("file:")):
        raise ValueError("base non canonique")
    return (valeur.drivername, str(Path(valeur.database).expanduser().resolve()), tuple(sorted(valeur.query.items())))


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
        raise ValueError("canal cron opérateur réservé à la base SQLite canonique")
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
