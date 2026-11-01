"""Pont entre une action demandée à voix et le sas d'approbation EXISTANT du socle.

`PortCapacites` implémente `session.PortActions` sur les vrais objets : le registre d'outils (`opsys.capacites`), la
validation de schéma (`outils.valider_arguments`) et la file d'approbation (`approbations.creer_demande`). Ce module :

- ne décide d'AUCUN niveau : il lit `Outil.niveau_effectif` ;
- ne contient aucun appel à `approbations.decider` ni à `outils.executer_atomique` : une action N3 ou plus est mise en
  attente, jamais exécutée, quel que soit le mode du département (`ombre`, `supervise` ou `autonome`). Là où le registre
  d'outils laisserait passer un N3 ou un N4 en mode `autonome`, la voix, elle, passe TOUJOURS par la file ;
- ne s'authentifie pas : la décision revient à une personne dotée du rôle voulu, depuis la console ou l'appareil.

`tests/test_avatars_voix_session.py` épingle ces deux absences par lecture du code source.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy import Connection

from .. import approbations
from ..capacites import Capacites
from ..outils import valider_arguments
from .session import DescriptionOutil


class PortCapacites:
    def __init__(self, capacites: Capacites, cnx_factory: Callable[[], AbstractContextManager[Connection]]) -> None:
        self._capacites = capacites
        self._cnx_factory = cnx_factory

    def decrire(self, departement: str, outil: str) -> DescriptionOutil | None:
        entree = self._capacites.index.get(outil)
        if entree is None:
            return None
        proprietaire, definition = entree
        return DescriptionOutil(definition.niveau_effectif, proprietaire is None or proprietaire.id == departement)

    def verifier_arguments(self, departement: str, outil: str, arguments: Mapping[str, Any]) -> list[str]:
        entree = self._capacites.index.get(outil)
        if entree is None:
            return ["outil inconnu"]
        return valider_arguments(entree[1].parametres, arguments)

    def executer_autonome(self, departement: str, outil: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._capacites.appeler(outil, dict(arguments))

    def mettre_en_attente(self, departement: str, outil: str, arguments: Mapping[str, Any], motif: str) -> str:
        entree = self._capacites.index.get(outil)
        if entree is None:
            raise ValueError("outil inconnu")
        with self._cnx_factory() as cnx:
            return approbations.creer_demande(cnx, departement, outil, dict(arguments),
                                              niveau=entree[1].niveau_effectif, motif=motif)
