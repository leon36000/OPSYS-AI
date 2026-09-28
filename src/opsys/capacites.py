"""Capacités exposées aux agents : outils des départements + outils communs OPSYS.

Logique pure, indépendante du transport. Elle fait trois choses :
- appliquer la politique d'autonomie (approbation humaine) ;
- appliquer le budget ;
- appliquer la troncature des sorties.
`opsys.serveur_mcp` l'expose en MCP ; les tests l'appellent directement.

Politique d'autonomie et humain qui agit (ADR-0009 §4, addendum T1.4-h) : la file d'approbation
sert les actions qu'un agent PROPOSE. Un appel d'appareil dont l'identité de jeton est valide est
l'action d'un humain, qui a déjà validé au départ en la lançant : `Capacites._valider_au_depart`
l'exécute sans file d'attente, à quatre conditions cumulées (niveau N3 au plus, identité relue en
base, outil dans la portée du rôle, appel d'appareil), et la trace dans le journal des approbations.
N4 et N5, et tout appel sans identité valide, suivent le chemin de la file, inchangé.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy import Connection

from . import approbations, idempotence, jetons, openclaw
from .contexte import (
    HorodatageAppareil,
    appeler_en_tant_que,
    horodatage_reception,
    identite_appelante,
    receptionne_de,
)
from .departements import Departement, tous_les_outils
from .outils import Autonomie, Outil, executer_atomique, valider_arguments
from .politiques import approbation_requise_niveau, validation_au_depart_possible

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
        self._portees_roles: dict[str, frozenset[str]] | None = None  # calculé au besoin, voir _outils_du_role
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
        toujours — sauf pour l'humain qui agit lui-même : voir `_valider_au_depart`, seul endroit où
        un appel d'appareil échappe à la file, et seulement quand l'approbation serait requise.
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
                if appel_appareil:
                    au_depart = self._valider_au_depart(cnx, departement, outil, arguments)
                    if au_depart is not None:
                        return au_depart
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

    def _outils_du_role(self, role: str) -> frozenset[str]:
        """Noms des outils dans la portée du rôle de jeton d'appareil `role` ; vide si le rôle est
        inconnu (fail-closed : un rôle sans entrée n'a aucune portée).

        SOURCE UNIQUE : c'est `openclaw.roles_outils`, la fonction même qui génère `roles.json` que le
        core applique avant d'émettre `tools/call` — aucune règle recopiée ici, donc socle et core ne
        peuvent pas diverger. Calculée à la première demande puis gardée : les départements d'une
        instance `Capacites` ne changent pas (`self.index` est figé de la même façon).
        """
        if self._portees_roles is None:
            self._portees_roles = {r: frozenset(noms)
                                   for r, noms in openclaw.roles_outils(self.departements).items()}
        return self._portees_roles.get(role, frozenset())

    def _valider_au_depart(
        self, cnx: Connection, departement: Departement, outil: Outil, arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Voie de l'humain qui agit (ADR-0009 §4, addendum T1.4-h). Appelée seulement pour un appel
        d'appareil dont l'approbation serait requise. Rend None (chemin normal : l'appelant continue
        vers la file d'approbation, RIEN n'a changé) ou la réponse finale de l'appel.

        ADR-0009 §4 définit N3 comme « validation humaine au départ » ; quand la personne authentifiée
        lance elle-même l'action, cette validation est faite : la mettre en attente du propriétaire
        rendrait chaque geste de terrain inutilisable. Conditions, vérifiées dans cet ordre, la
        première qui manque renvoie au chemin normal (sauf la 3, un refus nommé) :

        1. le niveau effectif de l'outil est N3 au plus (`politiques.validation_au_depart_possible`) ;
           N4 et N5 vont TOUJOURS au propriétaire, N5 exigeant toujours l'attestation ;
        2. l'appel porte une identité de jeton d'appareil (`contexte.identite_appelante`) que la base
           confirme à l'instant même : personne active portant ce rôle (`approbations.signataire_valide`).
           Sans identité (agent, secret partagé) ou avec une identité invalide, révoquée ou périmée :
           chemin normal, aucun passe-droit ;
        3. l'outil est dans la portée du rôle (`_outils_du_role`) ; sinon refus nommé `hors_portee_role`,
           ni exécuté ni mis en attente (le core le refuse déjà en amont : défense en profondeur).

        Alors l'outil s'exécute au nom du département, comme après une approbation, et — si l'exécution
        réussit — `approbations.tracer_validation_au_depart` écrit la trace DANS LE MÊME point de
        sauvegarde : l'exécution et sa trace réussissent ou échouent ensemble, sans trace pour une
        exécution annulée ni exécution sans trace. Un refus ou une panne de l'outil ne laisse aucune
        trace (rien n'a changé) : refus métier rendu tel quel, panne propagée comme partout ailleurs.

        Ne lit que `contexte.identite_appelante()`, posé par la plateforme d'après `_meta`, jamais un
        argument produit par le modèle. L'idempotence d'appareil (`_appeler_idempotent`) enveloppe cet
        appel : un renvoi rejoue la réponse enregistrée sans repasser ici, donc sans seconde trace.
        """
        if not validation_au_depart_possible(outil.niveau_effectif):
            return None
        signataire = approbations.signataire_valide(cnx, identite_appelante())
        if signataire is None:
            return None
        if outil.nom not in self._outils_du_role(signataire.role):
            return {"ok": False, "erreur": "hors_portee_role",
                    "details": f"{outil.nom} est hors de la portée du rôle {signataire.role} "
                               "(openclaw.roles_outils) : ni exécuté ni mis en attente."}
        reception = horodatage_reception()
        with cnx.begin_nested():
            with appeler_en_tant_que(departement.id):
                reponse = executer_atomique(outil, arguments)
            if reponse.get("ok"):
                approbations.tracer_validation_au_depart(
                    cnx, departement.id, outil.nom, arguments, niveau=outil.niveau_effectif,
                    signataire=signataire, reponse=reponse,
                    appareil=reception.appareil if reception is not None else None)
        return self._tronquer(reponse, outil.nom)

    def _tronquer(self, reponse: dict[str, Any], source: str) -> dict[str, Any]:
        texte = json.dumps(reponse, ensure_ascii=False)
        if len(texte) <= self._limite:
            return reponse
        with self._cnx_factory() as cnx:
            return {"ok": reponse.get("ok", False), "tronque": True,
                    "apercu": jetons.tronquer(cnx, texte, source, self._limite)}

