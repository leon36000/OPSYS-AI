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

from . import approbations, idempotence, jetons, liaison_cibles, openclaw
from . import contexte as contexte_appel
from .contexte import (
    HorodatageAppareil,
    IdentiteAppelante,
    appeler_en_tant_que,
    horodatage_reception,
    identite_appelante,
    receptionne_de,
)
from .departements import Departement, tous_les_outils
from .outils import Autonomie, Niveau, Outil, executer_atomique, valider_arguments
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
        memoire_politique: Callable[[], dict[str, Any]] | None = None,
        memoire_versionnee: bool = False,
    ) -> None:
        """`appelant` : département d'origine fixé par le point d'accès MCP (`/mcp/<département>` ou
        `/mcp/contexte/<département>`), au nom duquel les outils communs s'exécutent. Sans appelant,
        les outils communs au-delà de T0 sont refusés."""
        inconnus = (filtre or set()) - set(departements)
        if inconnus:
            raise ValueError(f"départements inconnus : {sorted(inconnus)}")
        if appelant is not None and appelant not in departements:
            raise ValueError(f"département appelant inconnu : {appelant}")
        self.departements = {k: v for k, v in departements.items() if not filtre or k in filtre}
        self.appelant = departements[appelant] if appelant else None
        self._cnx_factory = cnx_factory
        self._memoire_politique = memoire_politique
        self._memoire_versionnee = memoire_versionnee
        self._limite = limite_sortie
        self._portees_roles: dict[str, frozenset[str]] | None = None  # calculé au besoin, voir _outils_du_role
        ports_prives: dict[str, Mapping[str, Any]] = {}
        if "m05-financecore" in self.departements:
            ports_prives["m05-financecore"] = {
                "lecteur_heures_m4": self._lecteur_heures_m4(departements, cnx_factory)
            }
        self.index: dict[str, tuple[Departement | None, Outil]] = dict(
            tous_les_outils(self.departements.values(), ports_prives=ports_prives)
        )
        communs = self._outils_communs() + list(_outils_memoire() if memoire else ())
        for outil in communs:
            self.index[outil.nom] = (None, outil)

    @staticmethod
    def _lecteur_heures_m4(
        departements: Mapping[str, Departement],
        cnx_factory: Callable[[], AbstractContextManager[Connection]],
    ) -> Callable[..., dict[str, Any]]:
        """Compose M5 vers l'unique lecture M4 autorisée sans exposer sa Capacité au métier."""
        nom_outil = "m4_lire_heures_regulieres_validees"
        if "m04-field-ops" not in departements:
            def indisponible(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
                return {
                    "ok": False,
                    "erreur": "lecteur_heures_m4_indisponible",
                    "details": "Le département M4 n'est pas installé.",
                }

            return indisponible

        lecteur = Capacites(
            departements,
            cnx_factory,
            filtre={"m04-field-ops"},
            appelant="m05-financecore",
            memoire=False,
        )

        def lire(*args: Any, **kwargs: Any) -> dict[str, Any]:
            if kwargs or len(args) != 4:
                return {
                    "ok": False,
                    "erreur": "arguments_lecteur_heures_invalides",
                    "details": "Le lecteur M4 exige exactement quatre arguments positionnels.",
                }
            identite = contexte_appel.identite_appelante()
            if (
                identite is None
                or identite.source != "console"
                or identite.role != "nathan_owner"
                or contexte_appel.DEPARTEMENT_APPELANT.get() != "m05-financecore"
                or contexte_appel.departement_origine_appelante() != "m05-financecore"
            ):
                return {
                    "ok": False,
                    "erreur": "identite_console_proprietaire_requise",
                    "details": "La lecture M4 privée exige le contexte M5 et l'identité owner de console.",
                }
            entree = lecteur.index.get(nom_outil)
            if entree is None or entree[0] is None:
                return {
                    "ok": False,
                    "erreur": "lecteur_heures_m4_indisponible",
                    "details": "L'outil M4 de lecture validée n'est pas disponible.",
                }
            return lecteur.appeler(nom_outil, dict(zip(
                ("technicien_id", "debut", "fin", "fuseau"), args, strict=True
            )))

        return lire

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

    def appeler_profil_runtime(
        self,
        nom: str,
        arguments: Mapping[str, Any] | None,
        meta: idempotence.Meta | None,
        ticket_cible: liaison_cibles.TicketMeta | None,
        *,
        profile_id: str,
        profile_revision: int,
        server: str,
        ticket_memoire: str | None = None,
    ) -> dict[str, Any]:
        """Revérifie et dispatch un outil Core profilé sous le verrou de sa ligne de profil."""
        from . import admission_agents

        if self.appelant is None or server != f"opsys_{self.appelant.prefixe_outils}":
            return {"ok": False, "erreur": "admission_profil_refusee", "details": "serveur hors profil"}
        outil_complet = f"{server}__{nom}"
        try:
            with self._cnx_factory() as cnx:
                admission_agents.verifier_outil_runtime(
                    cnx, profile_id, self.departements, outil_complet, profile_revision, verrouiller=True
                )
                # `cnx_factory` is the storage ContextVar transaction: nested capability/tool
                # transactions remain under this profile row lock until dispatch returns.
                return self.appeler(nom, arguments, meta, ticket_cible, ticket_memoire)
        except admission_agents.AdmissionRefusee as exc:
            return {"ok": False, "erreur": "admission_profil_refusee", "details": str(exc)}

    def appeler(
        self, nom: str, arguments: Mapping[str, Any] | None, meta: idempotence.Meta | None = None,
        ticket_cible: liaison_cibles.TicketMeta | None = None,
        ticket_memoire: str | None = None,
    ) -> dict[str, Any]:
        """Exécute `nom`. `meta` (idempotence d'appareil, T1.4-b) vient du `_meta` MCP de
        `tools/call` (`serveur_mcp.appeler_outil`), jamais des arguments produits par le modèle.
        Sans identité d'appareil et sans `meta`, le comportement interne reste inchangé.
        Une identité d'appareil seule permet une lecture T0/N0 ; toute autre opération
        exige l'enveloppe d'idempotence avant le répartiteur métier.
        """
        args = dict(arguments or {})
        appelante = identite_appelante()
        entree = self.index.get(nom)
        if meta is None and appelante is not None and appelante.source == "appareil" and entree is not None:
            outil = entree[1]
            # Autonomie T0 alone is insufficient: some internal drafts/tasks explicitly use N1/N2.
            # The business registry owns this decision; MCP readOnlyHint is not an authorization policy.
            if outil.autonomie is not Autonomie.T0 or outil.niveau_effectif is not Niveau.N0:
                return {
                    "ok": False,
                    "erreur": "idempotence_appareil_requise",
                    "details": "Une mutation d'appareil exige une clé, un appareil et un horodatage validés.",
                }
        if nom == "opsys_memoire_rechercher":
            if ticket_cible is not None:
                return {"ok": False, "erreur": "ticket_cible_hors_portee_memoire"}
            return self._appeler_memoire(args, ticket_memoire)
        if ticket_memoire is not None:
            return {"ok": False, "erreur": "memoire_ticket_hors_portee"}
        # Les outils cibles sortent du dispatch normal ci-dessous. Appliquer ici la même
        # portée d'appareil que le chemin `_valider_au_depart`, avant les refus de ticket,
        # sinon un rôle non autorisé observe `ticket_cible_requis` au lieu du refus de portée.
        if (appelante is not None and appelante.source == "appareil" and nom in liaison_cibles.OUTILS_CIBLES
                and nom not in self._outils_du_role(appelante.role)):
            if meta is not None:
                return self._appeler_idempotent(nom, args, meta, role_refuse=appelante.role)
            return {
                "ok": False,
                "erreur": "hors_portee_role",
                "details": f"{nom} est hors de la portée du rôle {appelante.role} "
                           "(openclaw.roles_outils) : ni exécuté ni mis en attente.",
            }
        if ticket_cible is not None:
            return self._appeler_avec_ticket(nom, args, ticket_cible)
        if nom in liaison_cibles.OUTILS_CIBLES:
            entree = self.index.get(nom)
            dept, outil = entree if entree is not None else (None, None)
            if dept is None or (self.appelant is not None and dept.id != self.appelant.id):
                return {
                    "ok": False,
                    "erreur": "ticket_cible_requis",
                    "details": "Cette mutation doit être appelée depuis le département propriétaire de l'outil.",
                }
            if meta is None:
                return {
                    "ok": False,
                    "erreur": "ticket_cible_requis",
                    "details": (
                        "Cette mutation exige un ticket de session, sauf action N3 "
                        "authentifiée d'un humain."
                    ),
                }
            if validation_au_depart_possible(outil.niveau_effectif) and self._humain_n3_cible_valide(nom):
                return self._appeler_idempotent(nom, args, meta, revalider_humain_n3=True)
            if outil.niveau_effectif is Niveau.N4 and self._humain_appareil_cible_valide(nom):
                return self._appeler_idempotent(
                    nom, args, meta, revalider_humain_cible=True, demander_n4_humain=True
                )
            return {
                "ok": False,
                "erreur": "ticket_cible_requis",
                "details": (
                    "Cette mutation exige un ticket de session, sauf action N3 authentifiée d'un humain "
                    "ou demande N4 authentifiée et dans la portée de l'appareil."
                ),
            }
        if meta is None:
            return self._distribuer(nom, args)
        return self._appeler_idempotent(nom, args, meta)

    def _appeler_memoire(self, args: dict[str, Any], ticket: str | None) -> dict[str, Any]:
        from .memoire import autorite

        try:
            if contexte_appel.identite_appelante() is not None:
                raise ValueError("MEMOIRE-APPAREIL-FERME")
            if self._memoire_politique is None:
                if ticket is not None:
                    raise ValueError("MEMOIRE-AUTORITE-TRANSPORT-ABSENTE")
                return self._distribuer(autorite.NOM_OUTIL, args)
            policy = autorite.valider_politique(self._memoire_politique())
            if self.appelant is None or self.appelant.id not in policy["departements"]:
                raise ValueError("MEMOIRE-DEPARTEMENT-NON-CLASSE")
            dep = self.appelant.id
            if policy["departements"][dep] == "global":
                if ticket is not None:
                    raise ValueError("MEMOIRE-TICKET-HORS-VOIE-CLIENT")
                empreinte = autorite.empreinte_politique(policy)
                reponse = self._distribuer(autorite.NOM_OUTIL, args)
                if empreinte != autorite.empreinte_politique(autorite.valider_politique(self._memoire_politique())):
                    raise ValueError("MEMOIRE-CLASSIFICATION-MODIFIEE")
                return reponse
            if not self._memoire_versionnee:
                raise ValueError("MEMOIRE-ROUTE-CLIENT-OBSOLETE: régénérer la configuration Core")
            # Procédures seules, explicitement autorisées par le manifeste et le fragment serveur.
            if (ticket is None and args.get("portees") == ["procedures"]
                    and "procedures" in self.appelant.memoire_lecture):
                with autorite.lecture_bornee((), ("procedures",)):
                    reponse = self._distribuer(autorite.NOM_OUTIL, args)
                if autorite.empreinte_politique(policy) != autorite.empreinte_politique(
                        autorite.valider_politique(self._memoire_politique())):
                    raise ValueError("MEMOIRE-CLASSIFICATION-MODIFIEE")
                return reponse
            if ticket is None:
                raise ValueError("MEMOIRE-TICKET-CLIENT-REQUIS")
            with self._cnx_factory() as cnx:
                sujets = autorite.verifier(cnx, policy, dep, ticket, args)
                with autorite.lecture_bornee(sujets, tuple(policy["procedures_globales"])):
                    reponse = self._distribuer(autorite.NOM_OUTIL, args)
                # Aucun cache personnel ni branche de replay avant cette revalidation vivante.
                autorite.verifier(cnx, self._memoire_politique(), dep, ticket, args)
                if reponse.get("ok"):
                    autorite.consommer(cnx, ticket)
                return reponse
        except (ValueError, KeyError, TypeError) as exc:
            return {"ok": False, "erreur": "memoire_autorite_refusee", "details": str(exc)}

    def _humain_n3_cible_valide(self, nom: str, cnx: Connection | None = None) -> bool:
        entree = self.index.get(nom)
        if entree is None or entree[0] is None:
            return False
        outil = entree[1]
        if not validation_au_depart_possible(outil.niveau_effectif):
            return False
        return self._humain_appareil_cible_valide(nom, cnx)

    def _humain_appareil_cible_valide(self, nom: str, cnx: Connection | None = None) -> bool:
        return self._signataire_appareil_cible_valide(nom, cnx) is not None

    def _signataire_appareil_cible_valide(
        self, nom: str, cnx: Connection | None = None
    ) -> IdentiteAppelante | None:
        entree = self.index.get(nom)
        appelante = identite_appelante()
        if entree is None or entree[0] is None or appelante is None:
            return None
        if nom not in self._outils_du_role(appelante.role):
            return None
        if cnx is not None:
            return approbations.signataire_valide(cnx, appelante)
        with self._cnx_factory() as connexion:
            return approbations.signataire_valide(connexion, appelante)

    def _appeler_avec_ticket(
        self, nom: str, arguments: dict[str, Any], ticket_meta: liaison_cibles.TicketMeta
    ) -> dict[str, Any]:
        """Vérifie, exécute et consomme le ticket dans une seule transaction SQLite."""
        try:
            dept, _ = self.index[nom]
            if dept is None or self.appelant is None or dept.id != self.appelant.id:
                raise liaison_cibles.CibleRefusee("route d'origine différente du département de l'outil")
            with self._cnx_factory() as cnx:
                ticket = liaison_cibles.verifier_ticket(
                    cnx, ticket_meta, departement=dept.id, outil=nom, arguments=arguments
                )
                if ticket.reponse_rejouee is not None:
                    return {**ticket.reponse_rejouee, "rejoue": True}
                reponse = self._distribuer(nom, arguments)
                demande_id = reponse.get("demande_id") if reponse.get("statut") == "en_attente_approbation" else None
                if demande_id:
                    from sqlalchemy import update

                    from .stockage.schema import APPROBATIONS

                    cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == demande_id).values(
                        ticket_cible_hash=ticket.empreinte
                    ))
                    liaison_cibles.sceller_ticket(cnx, ticket, demande_id, reponse)
                else:
                    liaison_cibles.consommer_ticket(cnx, ticket, reponse)
                return reponse
        except (KeyError, liaison_cibles.CibleRefusee) as exc:
            return {"ok": False, "erreur": "cible_refusee", "details": str(exc)}

    def _appeler_idempotent(
        self, nom: str, arguments: dict[str, Any], meta: idempotence.Meta, *,
        revalider_humain_n3: bool = False, revalider_humain_cible: bool = False,
        demander_n4_humain: bool = False, role_refuse: str | None = None,
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
            if revalider_humain_n3 and not self._humain_n3_cible_valide(nom, cnx):
                return {
                    "ok": False,
                    "erreur": "ticket_cible_requis",
                    "details": "Identité humaine inactive ou autorisation N3 retirée avant l'écriture.",
                }
            signataire_n4 = None
            if revalider_humain_cible:
                signataire_n4 = self._signataire_appareil_cible_valide(nom, cnx)
                if signataire_n4 is None:
                    return {
                        "ok": False,
                        "erreur": "ticket_cible_requis",
                        "details": "Identité humaine inactive ou autorisation retirée avant la création de la demande.",
                    }
            refus_role = None
            if role_refuse is not None:
                refus_role = {
                    "ok": False,
                    "erreur": "hors_portee_role",
                    "details": f"{nom} est hors de la portée du rôle {role_refuse} "
                               "(openclaw.roles_outils) : ni exécuté ni mis en attente.",
                }
            try:
                reclamation = idempotence.reclamer(cnx, meta, nom, arguments, recu_le)
            except idempotence.MutationConflit as exc:
                if refus_role is not None:
                    return {**refus_role, "rejoue": False}
                return {"ok": False, "erreur": "mutation_conflit", "details": str(exc)}
            if refus_role is not None:
                # Un refus de portée est rejouable, mais ne peut jamais dévoiler une ancienne
                # réponse réussie ni la nature d'un conflit : l'autorité précède toute restitution.
                if not reclamation.rejouee:
                    idempotence.finaliser(cnx, meta, refus_role)
                refus_rejoue = reclamation.rejouee and reclamation.reponse.get("erreur") == "hors_portee_role"
                return {**refus_role, "rejoue": refus_rejoue}
            if reclamation.rejouee:
                return {**reclamation.reponse, "rejoue": True}
            if demander_n4_humain:
                if signataire_n4 is None:
                    raise ValueError("création N4 humaine sans signataire revérifié en base")
                departement, outil = self.index[nom]
                assert departement is not None and outil.niveau_effectif is Niveau.N4
                erreurs = valider_arguments(outil.parametres, arguments)
                if erreurs:
                    reponse = {"ok": False, "erreur": "arguments_invalides", "details": erreurs}
                else:
                    ident = approbations.creer_demande(
                        cnx,
                        departement.id,
                        nom,
                        arguments,
                        niveau=outil.niveau_effectif,
                        provenance_humaine=(signataire_n4, meta.appareil, meta.cle),
                    )
                    reponse = {
                        "ok": True,
                        "statut": "en_attente_approbation",
                        "demande_id": ident,
                        "details": (
                            "Demande N4 créée par un appareil humain authentifié. Le propriétaire doit "
                            "l'approuver avant toute exécution."
                        ),
                    }
                idempotence.finaliser(cnx, meta, reponse)
                return {**reponse, "rejoue": False}
            horodatage = HorodatageAppareil(
                appareil=meta.appareil,
                horodatage_appareil=dt.datetime.fromisoformat(meta.horodatage_appareil),
                recu_le=recu_le,
            )
            with receptionne_de(horodatage):
                reponse = self._distribuer(nom, arguments, appel_appareil=True, meta=meta)
            idempotence.finaliser(cnx, meta, reponse)
            return {**reponse, "rejoue": False}

    def _distribuer(
        self, nom: str, arguments: Mapping[str, Any] | None, *, appel_appareil: bool = False,
        meta: idempotence.Meta | None = None,
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
                origine = self.appelant.id if self.appelant else None
                with appeler_en_tant_que(origine, origine=origine):
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
                provenance_humaine = None
                if appel_appareil and meta is not None and outil.niveau_effectif is Niveau.N4:
                    signataire = self._signataire_appareil_cible_valide(nom, cnx)
                    if (
                        signataire is not None
                        and signataire.source == "appareil"
                        and signataire.role not in approbations.ROLES_NON_HUMAINS
                    ):
                        provenance_humaine = (signataire, meta.appareil, meta.cle)
                ident = approbations.creer_demande(cnx, departement.id, nom, arguments,
                                                   niveau=outil.niveau_effectif,
                                                   provenance_humaine=provenance_humaine)
                return {"ok": True, "statut": "en_attente_approbation", "demande_id": ident,
                        "details": f"Action {outil.autonomie.value} ({outil.niveau_effectif.value}) en mode "
                                   f"{mode} : un humain doit l'approuver dans la console OPSYS. Ne la "
                                   "présente pas comme faite."}
        origine = self.appelant.id if self.appelant else None
        with appeler_en_tant_que(departement.id, origine=origine):
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
            origine = self.appelant.id if self.appelant else None
            with appeler_en_tant_que(departement.id, origine=origine):
                reponse = executer_atomique(outil, arguments)
            if reponse.get("ok"):
                approbations.tracer_validation_au_depart(
                    cnx, departement.id, outil.nom, arguments, niveau=outil.niveau_effectif,
                    signataire=signataire, reponse=reponse,
                    appareil=reception.appareil if reception is not None else None)
        return self._tronquer(
            reponse, outil.nom, departement=departement.id,
            origine=self.appelant.id if self.appelant else None,
        )

    def _tronquer(
        self, reponse: dict[str, Any], source: str, *, departement: str | None = None,
        origine: str | None = None,
    ) -> dict[str, Any]:
        texte = json.dumps(reponse, ensure_ascii=False)
        if len(texte) <= self._limite:
            return reponse
        if source == "m10_paquet_contexte_affaire":
            # Le moteur Core refuse déjà ce contexte ; sa lecture ne doit pas créer d'artefact.
            return {
                "ok": False,
                "erreur": "REJ-PAQUET-AFFAIRE-SORTIE-TROP-VOLUMINEUSE",
                "details": (
                    "le paquet dépasse la borne de sortie du contexte privé ; "
                    "aucun détail partiel n'est transmis"
                ),
            }
        departement_artifact = departement or contexte_appel.DEPARTEMENT_APPELANT.get()
        origine_artifact = origine or contexte_appel.departement_origine_appelante()
        with self._cnx_factory() as cnx:
            return {"ok": reponse.get("ok", False), "tronque": True,
                    "apercu": jetons.tronquer(
                        cnx, texte, source, self._limite,
                        departement=departement_artifact, origine=origine_artifact,
                    )}
