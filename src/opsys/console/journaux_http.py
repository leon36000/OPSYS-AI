"""Masque la recherche de contact dans les logs d'accès de la console Uvicorn."""

from __future__ import annotations

import copy
import logging
from urllib.parse import parse_qsl

from uvicorn.config import LOGGING_CONFIG


class MasquerRecherche(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Contrat AccessFormatter Uvicorn : client, méthode, cible HTTP, version, statut.
        if isinstance(record.args, tuple) and len(record.args) == 5 and isinstance(record.args[2], str):
            chemin, separateur, query = record.args[2].partition("?")
            if separateur and any(cle == "q" for cle, _ in parse_qsl(query, keep_blank_values=True)):
                record.args = (*record.args[:2], chemin + "?q=[MASQUE]", *record.args[3:])
        return True


def configuration_journaux() -> dict:
    configuration = copy.deepcopy(LOGGING_CONFIG)
    configuration.setdefault("filters", {})["recherche_privee"] = {"()": MasquerRecherche}
    configuration["handlers"]["access"].setdefault("filters", []).append("recherche_privee")
    return configuration
