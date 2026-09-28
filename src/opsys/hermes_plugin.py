"""Plugin Hermes « opsys » : comptabilité des tokens, alertes de budget, troncature.

Chargé par Hermes via `$HERMES_HOME/plugins/opsys/__init__.py`, qui délègue à `register`.
Il n'utilise que l'API publique des plugins : `ctx.register_hook` et les hooks documentés
`post_api_request`, `post_auxiliary_call`, `pre_llm_call` et `transform_tool_result`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from . import etat, jetons
from .departements import Departement, charger_departements

logger = logging.getLogger("opsys")

DEPARTEMENT_PAR_DEFAUT = "direction"


def departement_courant(environ: dict[str, str] | None = None) -> str:
    """OPSYS_DEPARTEMENT, sinon le nom du profil Hermes actif (dossier de HERMES_HOME)."""
    env = environ if environ is not None else os.environ
    explicite = env.get("OPSYS_DEPARTEMENT", "").strip()
    if explicite:
        return explicite
    home = env.get("HERMES_HOME", "").strip()
    if home and Path(home).parent.name == "profiles":
        return Path(home).name
    return DEPARTEMENT_PAR_DEFAUT


class PluginOpsys:
    def __init__(self, departement: str, departements: dict[str, Departement], cnx_factory=etat.session,
                 limite_sortie: int = jetons.LIMITE_SORTIE_DEFAUT) -> None:
        self.departement = departement
        self.fiche = departements.get(departement)
        self._cnx_factory = cnx_factory
        self._limite = limite_sortie

    def _compter(self, **kwargs: Any) -> None:
        modele = kwargs.get("response_model") or kwargs.get("model") or "inconnu"
        with self._cnx_factory() as cnx:
            jetons.enregistrer_usage(cnx, self.departement, str(modele), kwargs.get("usage"))

    def post_api_request(self, **kwargs: Any) -> None:
        self._compter(**kwargs)

    def post_auxiliary_call(self, **kwargs: Any) -> None:
        if kwargs.get("usage"):
            self._compter(**kwargs)

    def pre_llm_call(self, **kwargs: Any) -> dict[str, str] | None:
        if self.fiche is None:
            return None
        with self._cnx_factory() as cnx:
            etat_budget = jetons.etat_budget(cnx, self.departement, self.fiche.budget)
        if etat_budget["niveau"] == "ok":
            return None
        jour, mois = etat_budget["jour"], etat_budget["mois"]
        if etat_budget["niveau"] == "epuise":
            texte = (f"[OPSYS] Budget de tokens ÉPUISÉ ({jour['pct']} % jour, {mois['pct']} % mois). "
                     "Termine en une phrase et escalade à un humain ; n'entame rien de nouveau.")
        else:
            texte = (f"[OPSYS] Budget de tokens à {max(jour['pct'], mois['pct'])} %. "
                     "Sois bref, évite les outils non indispensables.")
        return {"context": texte}

    def transform_tool_result(self, tool_name: str = "", result: Any = None, **kwargs: Any) -> str | None:
        if not isinstance(result, str) or len(result) <= self._limite or "opsys" in tool_name:
            return None
        with self._cnx_factory() as cnx:
            return jetons.tronquer(cnx, result, tool_name or "outil", self._limite)


def register(ctx: Any) -> PluginOpsys:
    """Point d'entrée Hermes. Une panne de configuration OPSYS ne doit pas tuer l'agent."""
    departement = departement_courant()
    try:
        departements = charger_departements()
    except (OSError, ValueError) as exc:
        logger.error("OPSYS : manifestes illisibles, budgets désactivés (%s)", exc)
        departements = {}
    plugin = PluginOpsys(departement, departements)
    ctx.register_hook("post_api_request", plugin.post_api_request)
    ctx.register_hook("post_auxiliary_call", plugin.post_auxiliary_call)
    ctx.register_hook("pre_llm_call", plugin.pre_llm_call)
    ctx.register_hook("transform_tool_result", plugin.transform_tool_result)
    logger.info("OPSYS : plugin actif pour le département %s", departement)
    return plugin
