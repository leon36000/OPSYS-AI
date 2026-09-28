"""Capacités exposées aux agents : outils des départements + outils communs OPSYS.

Logique pure, indépendante du transport. Elle fait trois choses :
- appliquer la politique d'autonomie (approbation humaine) ;
- appliquer le budget ;
- appliquer la troncature des sorties.
`opsys.serveur_mcp` l'expose en MCP ; les tests l'appellent directement.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy import Connection

from . import approbations, idempotence, jetons
from .contexte import HorodatageAppareil, appeler_en_tant_que, receptionne_de
from .departements import Departement, tous_les_outils
from .outils import Autonomie, Outil, executer_atomique, valider_arguments
from .politiques import approbation_requise_niveau

_SCHEMA_VIDE = {"type": "object", "properties": {}, "additionalProperties": False}
logger = logging.getLogger("opsys.capacites")


def _outils_memoire() -> tuple[Outil, ...]:
    """Outils de la mémoire d'entreprise, si le module (et psycopg) est disponible."""
    try:
        from .memoire.outils import outils
    except ImportError as exc:  # installation sans l'extra « postgres »
        logger.warning("mémoire d'entreprise non exposée : %s", exc)
        return ()
    return outils()


def outils_executables(
    departements: Mapping[str, Departement],
    cnx_factory: Callable[[], AbstractContextManager[Connection]],
) -> dict[str, Outil]:
    """Tout ce qu'une approbation humaine peut exécuter : outils des départements et outils communs.

    Source unique pour la CLI et la console. L'exécution se fait au nom du département de la
    demande (`approbations.decider`), jamais au nom d'un appelant fixé ici.
    """
    return {outil.nom: outil for outil in Capacites(departements, cnx_factory).lister()}


class Capacites:
    def __init__(
        self,
        departements: Mapping[str, Departement],
        cnx_factory: Callable[[], AbstractContextManager[Connection]],
        filtre: set[str] | None = None,
        limite_sortie: int = jetons.LIMITE_SORTIE_DEFAUT,
        appelant: str | None = None,
        memoire: bool = True,
    ) -> None:
        """`appelant` : département au nom duquel les outils communs s'exécutent (point d'accès
        `/mcp/<département>`). Sans appelant, les outils communs au-delà de T0 sont refusés."""
        inconnus = (filtre or set()) - set(departements)
        if inconnus:
            raise ValueError(f"départements inconnus : {sorted(inconnus)}")
        if appelant is not None and appelant not in departements:
            raise ValueError(f"département appelant inconnu : {appelant}")
        self.departements = {k: v for k, v in departements.items() if not filtre or k in filtre}
        self.appelant = departements[appelant] if appelant else None
        self._cnx_factory = cnx_factory
        self._limite = limite_sortie
        self.index: dict[str, tuple[Departement | None, Outil]] = dict(
            tous_les_outils(self.departements.values())
        )
        communs = self._outils_communs() + list(_outils_memoire() if memoire else ())
        for outil in communs:
            self.index[outil.nom] = (None, outil)

    # -- outils communs -----------------------------------------------------------------
    def _outils_communs(self) -> list[Outil]:
        return [
            Outil(
                nom="opsys_lire_artefact",
                description="Lit la suite d'une sortie d'outil tronquée (artefact) par tranches.",
                parametres={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "debut": {"type": "integer"},
                        "longueur": {"type": "integer"},
                    },
                    "required": ["id"],
                    "additionalProperties": False,
                },
                fonction=self._lire_artefact,
            ),
            Outil(
                nom="opsys_etat_budget",
                description="Consommation de tokens du jour et du mois face au budget du département.",
                parametres=_SCHEMA_VIDE,
                fonction=self._etat_budget,
            ),
            Outil(
                nom="opsys_demandes_approbation",
                description="Liste les demandes d'approbation humaine de ce département et leur statut.",
                parametres={
                    "type": "object",
                    "properties": {"statut": {"type": "string",
                                              "enum": ["en_attente", "refusee", "executee", "echec"]}},
                    "additionalProperties": False,
                },
                fonction=self._demandes,
            ),
        ]

    def _lire_artefact(self, id: str, debut: int = 0, longueur: int = 4000) -> dict[str, Any]:  # noqa: A002
        with self._cnx_factory() as cnx:
            return jetons.lire_artefact(cnx, id, debut, longueur)

    def _etat_budget(self) -> list[dict[str, Any]]:
        with self._cnx_factory() as cnx:
            return [jetons.etat_budget(cnx, d.id, d.budget) for d in self.departements.values()]

    def _demandes(self, statut: str | None = None) -> list[dict[str, Any]]:
        with self._cnx_factory() as cnx:
            return [d for d in approbations.lister(cnx, statut) if d["departement"] in self.departements]

    # -- API ------------------------------------------------------------------------------
    def lister(self) -> list[Outil]:
        return [outil for _, outil in self.index.values()]

    def appeler(
        self, nom: str, arguments: Mapping[str, Any] | None, meta: idempotence.Meta | None = None
    ) -> dict[str, Any]:
        """Exécute `nom`. `meta` (idempotence d'appareil, T1.4-b) vient du `_meta` MCP de
        `tools/call` (`serveur_mcp.appeler_outil`), jamais des arguments produits par le modèle.
        Sans `meta`, comportement strictement inchangé : voir `docs/architecture/IDEMPOTENCE.md`.
        """
        if meta is None:
            return self._distribuer(nom, arguments)
        return self._appeler_idempotent(nom, dict(arguments or {}), meta)

    def _appeler_idempotent(
        self, nom: str, arguments: dict[str, Any], meta: idempotence.Meta
    ) -> dict[str, Any]:
        """Réclame `(appareil, cle)` puis exécute, dans une seule transaction : un renvoi de la
        même clé, du même outil et des mêmes arguments rejoue la réponse enregistrée sans
        ré-exécuter ni redemander d'approbation ; une clé réutilisée pour un outil ou des arguments
        différents est un refus nommé (`mutation_conflit`), rien n'est exécuté ; une panne interne
        annule toute la transaction, réclamation comprise, pour qu'un renvoi réel réessaie.

        `stockage.transaction` (ADR-0009) imbrique `_distribuer` — donc `executer_atomique` et la
        création d'une demande d'approbation — comme point de sauvegarde de cette même transaction :
        aucun changement à ces fonctions n'est requis pour obtenir l'atomicité demandée.
        """
        recu_le = dt.datetime.now(dt.UTC)
        with self._cnx_factory() as cnx:
            try:
                reclamation = idempotence.reclamer(cnx, meta, nom, arguments, recu_le)
            except idempotence.MutationConflit as exc:
                return {"ok": False, "erreur": "mutation_conflit", "details": str(exc)}
            if reclamation.rejouee:
                return {**reclamation.reponse, "rejoue": True}
            horodatage = HorodatageAppareil(
                appareil=meta.appareil,
                horodatage_appareil=dt.datetime.fromisoformat(meta.horodatage_appareil),
                recu_le=recu_le,
            )
            with receptionne_de(horodatage):
                reponse = self._distribuer(nom, arguments, appel_appareil=True)
            idempotence.finaliser(cnx, meta, reponse)
            return {**reponse, "rejoue": False}

    def _distribuer(
        self, nom: str, arguments: Mapping[str, Any] | None, *, appel_appareil: bool = False
    ) -> dict[str, Any]:
        """Aiguille un appel : outil commun, approbation requise, ou exécution atomique.

        `appel_appareil` : appel déterministe d'un appareil apparié (`_meta` d'idempotence, T1.4-b),
        sans tour de modèle. Le budget de jetons borne la dépense de modèle d'un département ; un tel
        appel n'en consomme aucun et n'y est donc pas soumis. Les approbations, elles, s'appliquent
        toujours.
        """
        entree = self.index.get(nom)
        if entree is None:
            return {"ok": False, "erreur": "outil_inconnu", "details": nom}
        departement, outil = entree
        arguments = dict(arguments or {})
        if departement is None:  # outil commun : exécuté au nom du département appelant
            if outil.autonomie is Autonomie.T0:
                with appeler_en_tant_que(self.appelant.id if self.appelant else None):
                    return self._tronquer(executer_atomique(outil, arguments), nom)
            if self.appelant is None:
                return {"ok": False, "erreur": "departement_appelant_inconnu",
                        "details": "Cette action doit passer par le point d'accès MCP d'un département."}
            departement = self.appelant
        with self._cnx_factory() as cnx:
            budget = jetons.etat_budget(cnx, departement.id, departement.budget)
            if not appel_appareil and budget["niveau"] == "epuise" and outil.autonomie is not Autonomie.T0:
                return {"ok": False, "erreur": "budget_epuise",
                        "details": "Budget de tokens épuisé : termine brièvement et escalade à un humain.",
                        "budget": budget}
            mode = approbations.mode_effectif(cnx, departement.id, departement.mode)
            if approbation_requise_niveau(outil.niveau_effectif, mode):
                erreurs = valider_arguments(outil.parametres, arguments)
                if erreurs:
                    return {"ok": False, "erreur": "arguments_invalides", "details": erreurs}
                ident = approbations.creer_demande(cnx, departement.id, nom, arguments,
                                                   niveau=outil.niveau_effectif)
                return {"ok": True, "statut": "en_attente_approbation", "demande_id": ident,
                        "details": f"Action {outil.autonomie.value} ({outil.niveau_effectif.value}) en mode "
                                   f"{mode} : un humain doit l'approuver dans la console OPSYS. Ne la "
                                   "présente pas comme faite."}
        with appeler_en_tant_que(departement.id):
            return self._tronquer(executer_atomique(outil, arguments), nom)

    def _tronquer(self, reponse: dict[str, Any], source: str) -> dict[str, Any]:
        texte = json.dumps(reponse, ensure_ascii=False)
        if len(texte) <= self._limite:
            return reponse
        with self._cnx_factory() as cnx:
            return {"ok": reponse.get("ok", False), "tronque": True,
                    "apercu": jetons.tronquer(cnx, texte, source, self._limite)}

