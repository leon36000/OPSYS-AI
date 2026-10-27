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
import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
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
_MUTATION_NOTE_M6 = "m6_enregistrer_note_commande"
_LECTURE_NOTE_M6 = "m6_lire_note_commande"
_LISTE_NOTES_M6 = "m6_lister_notes_commande"
_MUTATION_CLASSEMENT_M6 = "m6_classer_cause_variance_appareil"
_LECTURES_CLASSEMENT_M6 = frozenset({
    "m6_lister_variances_classables_wct_appareil",
    "m6_lire_historique_classement_variance_appareil",
})
_LECTURE_RAPPELS_M1 = "m1_lister_rappels_appareil"
_MUTATION_RAPPEL_M1 = "m1_prendre_en_charge_rappel_appareil"
_LECTURE_REVUE_M4 = "m4_lire_dossier_revue_completion_appareil"
_PROPOSITION_REVUE_M4 = "m4_resoudre_revue_completion_sources"
_LEGACY_REVUE_M4 = "m4_resoudre_revue_completion"
_LECTURE_OBLIGATIONS_M5 = "m5_lire_obligations_preparees_appareil"
_MUTATION_OBLIGATIONS_M5 = "m5_enregistrer_obligation_preparee_appareil"
_LECTURE_PROVENANCE_M8 = "m8_lire_provenance_m5_appareil"
_DETAIL_PROVENANCE_M8 = "Le diagnostic ne satisfait pas son contrat ; aucun détail partiel n’est transmis."
_CODES_PROVENANCE_M8 = frozenset({
    "REJ-M8-PROVENANCE-ARGUMENTS-INVALIDES", "REJ-M8-PROVENANCE-IDENTITE-INVALIDE",
    "REJ-M8-PROVENANCE-REGISTRE-INVALIDE", "REJ-M8-PROVENANCE-SOURCE-INVALIDE",
    "REJ-M8-PROVENANCE-BUDGET-SOURCE-DEPASSE", "REJ-M8-PROVENANCE-PROJECTION-INVALIDE",
    "REJ-M8-PROVENANCE-SORTIE-TROP-VOLUMINEUSE",
})


_OUTILS_DOCUMENTAIRES_M10 = {
    "m10_deposer_version_document_appareil": "deposer",
    "m10_activer_version_document_appareil": "activer",
    "m10_retirer_document_appareil": "retirer",
}
_LECTURES_DOCUMENTAIRES_M10 = {
    "m10_lister_documents_affaire_appareil": "lister",
    "m10_lire_version_document_affaire_appareil": "lire",
}
_REFUS_LECTURE_DOCUMENTAIRE_M10 = frozenset(
    "REJ-M10-LECTURE-" + suffixe for suffixe in (
        "AUTORITE-INVALIDE", "MODE-NON-ADMIS", "FORME-INVALIDE", "AFFAIRE-INCONNUE",
        "REFERENCE-INVALIDE", "REGISTRE-INVALIDE", "CONNEXION-INVALIDE", "DIALECTE-NON-ADMIS",
        "QUOTA-DEPASSE", "INDISPONIBLE",
    )
)
_ERREURS_DOCUMENTAIRES_M10 = {
    "REJ-M10-TRANSACTION-CONNEXION-INVALIDE": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
    "REJ-M10-TRANSACTION-DIALECTE-NON-ADMIS": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
    "REJ-M10-TRANSACTION-AUTORITE-INVALIDE": "REJ-M10-DOC-AUTORITE-INVALIDE",
    "REJ-M10-TRANSACTION-MODE-NON-ADMIS": "REJ-M10-DOC-MODE-NON-ADMIS",
    "REJ-M10-TRANSACTION-FORME-INVALIDE": "REJ-M10-DOC-FORME-INVALIDE",
    "REJ-M10-TRANSACTION-AFFAIRE-INCONNUE": "REJ-M10-DOC-AFFAIRE-INCONNUE",
    "REJ-M10-TRANSACTION-REGISTRE-INVALIDE": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
    "REJ-M10-TRANSACTION-QUOTA-DEPASSE": "QUOTA-DEPASSE",
    "REJ-M10-TRANSACTION-PRECONDITION-REFUSEE": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
    "REJ-M10-TRANSACTION-CONFIRMATION-INCONNUE": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
    "REJ-M10-TRANSACTION-PANNE-TRANSACTION": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
}


class _RefusDocumentaireCap(RuntimeError):
    """Code constant interne ; doit sortir du SAVEPOINT et de la factory avant traduction."""

    def __init__(self, code):
        self.code = code
        super().__init__("CONFIRMATION-INCONNUE")


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
        if nom in {"m6_lister_fournisseurs_console", "m6_lire_fournisseur_console",
                   "m6_enregistrer_fournisseur_console",
                   "m6_lister_fournisseurs_tarif_console", "m6_preparer_tarif_console", "m6_confirmer_tarif_console",
                   "m6_enregistrer_materiau_console", "m6_lire_materiau_console", "m6_lister_materiaux_console",
                   "m3_lister_fournisseurs_modele", "m3_enregistrer_lignes_modele", "m3_lire_lignes_modele",
                   "m3_lire_tarif_modele", "m3_creer_devis_prefill",
                   "m3_enregistrer_modele_soumission", "m3_lire_modele_soumission", "m3_lister_modeles_soumission",
                   "m3_creer_devis_depuis_modele", "m3_document_devis_console",
                   "m2_enregistrer_rendez_vous", "m2_lire_agenda_vendeur", "m2_historique_rendez_vous",
                   "m2_lire_rencontres_lead",
                   "m4_enregistrer_annotation_calendrier", "m4_lire_annotations_calendrier",
                   "m4_resumer_annotations_calendrier", "m4_definir_couleur_calendrier",
                   "m4_lire_couleurs_calendrier", "m4_resumer_couleurs_calendrier", "m4_lire_apercu_mois",
                   "m4_lire_page_cedule_semaine", "m4_lire_journal_quotidien",
                   "m4_lire_composition_journaliere_console", "m4_declarer_composition_journaliere_console",
                   "m4_lire_absence_journaliere_console", "m4_declarer_absence_journaliere_console"}:
            # Aucun texte privé dans approbations, reçus ou artefacts génériques.
            # Le port humain privé de console appelle les outils M4 directement.
            return {"ok": False, "erreur": "port_console_prive_requis"}
        if nom in _LECTURES_DOCUMENTAIRES_M10:
            return self.refus_lecture_documentaire_appareil("REJ-M10-LECTURE-AUTORITE-INVALIDE")
        if nom in _OUTILS_DOCUMENTAIRES_M10:
            return self.refus_documentaire_appareil("REJ-M10-DOC-AUTORITE-INVALIDE", avant_factory=True)
        from . import admission_agents

        if self.appelant is None or server != f"opsys_{self.appelant.prefixe_outils}":
            return {"ok": False, "erreur": "admission_profil_refusee", "details": "serveur hors profil"}
        outil_complet = f"{server}__{nom}"
        try:
            with self._cnx_factory() as cnx:
                admission_agents.verifier_outil_generique_runtime(
                    cnx, profile_id, self.departements, outil_complet, profile_revision, verrouiller=True
                )
                # `cnx_factory` is the storage ContextVar transaction: nested capability/tool
                # transactions remain under this profile row lock until dispatch returns.
                return self.appeler(nom, arguments, meta, ticket_cible, ticket_memoire)
        except admission_agents.AdmissionRefusee as exc:
            return {"ok": False, "erreur": "admission_profil_refusee", "details": str(exc)}

    def appeler(
        self,
        nom: str,
        arguments: Mapping[str, Any] | None,
        meta: idempotence.Meta | None = None,
        ticket_cible: liaison_cibles.TicketMeta | None = None,
        ticket_memoire: str | None = None,
    ) -> dict[str, Any]:
        """Exécute `nom`. `meta` (idempotence d'appareil, T1.4-b) vient du `_meta` MCP de
        `tools/call` (`serveur_mcp.appeler_outil`), jamais des arguments produits par le modèle.
        Sans identité d'appareil et sans `meta`, le comportement interne reste inchangé.
        Une identité d'appareil seule permet une lecture T0/N0 ; toute autre opération
        exige l'enveloppe d'idempotence avant le répartiteur métier.
        """
        if nom in {"m6_lister_fournisseurs_console", "m6_lire_fournisseur_console",
                   "m6_enregistrer_fournisseur_console",
                   "m6_lister_fournisseurs_tarif_console", "m6_preparer_tarif_console", "m6_confirmer_tarif_console",
                   "m6_enregistrer_materiau_console", "m6_lire_materiau_console", "m6_lister_materiaux_console",
                   "m3_lister_fournisseurs_modele", "m3_enregistrer_lignes_modele", "m3_lire_lignes_modele",
                   "m3_lire_tarif_modele", "m3_creer_devis_prefill",
                   "m3_enregistrer_modele_soumission", "m3_lire_modele_soumission", "m3_lister_modeles_soumission",
                   "m3_creer_devis_depuis_modele", "m3_document_devis_console",
                   "m2_enregistrer_rendez_vous", "m2_lire_agenda_vendeur", "m2_historique_rendez_vous",
                   "m2_lire_rencontres_lead",
                   "m4_enregistrer_annotation_calendrier", "m4_lire_annotations_calendrier",
                   "m4_resumer_annotations_calendrier", "m4_definir_couleur_calendrier",
                   "m4_lire_couleurs_calendrier", "m4_resumer_couleurs_calendrier", "m4_lire_apercu_mois",
                   "m4_lire_page_cedule_semaine", "m4_lire_journal_quotidien",
                   "m4_lire_composition_journaliere_console", "m4_declarer_composition_journaliere_console",
                   "m4_lire_absence_journaliere_console", "m4_declarer_absence_journaliere_console"}:
            # Refus avant toute normalisation, réclamation ou approbation contenant du texte privé.
            return {"ok": False, "erreur": "port_console_prive_requis"}
        if nom in _LECTURES_DOCUMENTAIRES_M10:
            return self._appeler_lecture_documents_m10(nom, arguments, meta, ticket_cible, ticket_memoire)
        if nom in _OUTILS_DOCUMENTAIRES_M10:
            return self._appeler_documents_m10(nom, arguments, meta, ticket_cible, ticket_memoire)
        # Ce nouveau lecteur ferme aussi le conteneur brut avant la normalisation
        # historique : une liste de paires ne peut pas devenir un corps RPC valide.
        if nom == _LECTURE_PROVENANCE_M8 and nom in self.index:
            return self._appeler_provenance_m8(arguments, meta, ticket_cible, ticket_memoire)
        args = dict(arguments or {})
        appelante = identite_appelante()
        entree = self.index.get(nom)
        if entree is not None and nom == _MUTATION_NOTE_M6 and meta is None:
            # Aucun brouillon d'approbation ne doit copier une note privée sans intention authentifiée.
            with self._cnx_factory():
                refus = self._garder_note_m6()
                if refus is not None:
                    return refus
            return {"ok": False, "erreur": "idempotence_appareil_requise",
                    "details": "La note interne exige une intention authentifiée persistée."}
        if entree is not None and nom in {_LECTURE_OBLIGATIONS_M5, _MUTATION_OBLIGATIONS_M5}:
            return self._appeler_obligations_m5(nom, args, meta, ticket_cible, ticket_memoire)
        if nom == _LEGACY_REVUE_M4 and (
            meta is not None or (appelante is not None and appelante.source == "appareil")
        ):
            return {"ok": False, "erreur": "REJ-SOURCES-CHANGEES",
                    "details": "Une nouvelle proposition liée aux sources est requise depuis l’appareil."}
        if nom == _LECTURE_REVUE_M4 and entree is not None:
            if meta is not None:
                return {"ok": False, "erreur": "idempotence_hors_portee_lecture",
                        "details": "Cette lecture pure n’admet aucune enveloppe de mutation."}
            with self._cnx_factory() as cnx:
                refus = self._garder_revue_m4(nom, args, cnx)
                if refus is not None:
                    return refus
                with contexte_appel.sortie_bornee(min(5400, self._limite)):
                    return self._distribuer(nom, args)
        if nom == _PROPOSITION_REVUE_M4 and entree is not None:
            if meta is None:
                return {"ok": False, "erreur": "idempotence_appareil_requise",
                        "details": "Cette proposition exige une intention DEVICE persistée."}
            return self._appeler_idempotent(nom, args, meta, revalider_humain_cible=True,
                                           demander_n4_humain=True)
        if (
            nom in {"m6_lire_preuves_pertes_wct_appareil", _LECTURE_NOTE_M6, _LISTE_NOTES_M6}
            or nom in _LECTURES_CLASSEMENT_M6
            or nom == _LECTURE_RAPPELS_M1
        ) and meta is not None:
            return {"ok": False, "erreur": "idempotence_hors_portee_lecture",
                    "details": "Cette lecture pure n’admet aucune enveloppe de mutation."}
        if entree is not None and meta is None and nom in {_LECTURE_RAPPELS_M1, _MUTATION_RAPPEL_M1}:
            with self._cnx_factory():
                refus = self._garder_rappel_m1(nom, args)
                if refus is not None:
                    return refus
                if nom == _LECTURE_RAPPELS_M1:
                    with contexte_appel.sortie_bornee(min(5400, self._limite)):
                        return self._distribuer(nom, args)
            return {
                "ok": False,
                "erreur": "idempotence_appareil_requise",
                "details": "Cette prise en charge exige une intention DEVICE persistée.",
            }
        if entree is not None and meta is None and (
            nom == _MUTATION_CLASSEMENT_M6 or nom in _LECTURES_CLASSEMENT_M6
        ):
            with self._cnx_factory():
                refus = self._garder_classement_m6(nom, args)
                if refus is not None:
                    return refus
                if nom in _LECTURES_CLASSEMENT_M6:
                    with contexte_appel.sortie_bornee(min(5400, self._limite)):
                        return self._distribuer(nom, args)
            return {
                "ok": False,
                "erreur": "idempotence_appareil_requise",
                "details": "Ce classement exige la mutation DEVICE persistée.",
            }
        if nom == "m6_declarer_materiaux_avec_preuves_appareil" and entree is not None and meta is None:
            with self._cnx_factory():
                refus = self._garder_preuves_m6(args)
            if refus is not None:
                return refus
            return {
                "ok": False,
                "erreur": "idempotence_appareil_requise",
                "details": "Cette déclaration exige la mutation DEVICE persistée.",
            }
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
        outils_cibles = (
            liaison_cibles.OUTILS_CIBLES_CORE
            if contexte_appel.appel_provient_du_mcp() else liaison_cibles.OUTILS_CIBLES
        )
        if (
            appelante is not None
            and appelante.source == "appareil"
            and nom in outils_cibles
            and nom not in self._outils_du_role(appelante.role)
        ):
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
        if nom in outils_cibles:
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
                    "details": ("Cette mutation exige un ticket de session, sauf action N3 authentifiée d'un humain."),
                }
            if validation_au_depart_possible(outil.niveau_effectif) and self._humain_n3_cible_valide(nom):
                return self._appeler_idempotent(nom, args, meta, revalider_humain_n3=True)
            if outil.niveau_effectif is Niveau.N4 and self._humain_appareil_cible_valide(nom):
                return self._appeler_idempotent(nom, args, meta, revalider_humain_cible=True, demander_n4_humain=True)
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

    def refus_lecture_documentaire_appareil(self, code):
        """Refus T0 entier et constant, traduit uniquement hors transaction appelante."""
        if type(self._limite) is not int or self._limite < 40:
            raise RuntimeError("QUOTA-INSUFFISANT") from None
        if type(code) is not str or code not in _REFUS_LECTURE_DOCUMENTAIRE_M10:
            code = "REJ-M10-LECTURE-INDISPONIBLE"
        frame = {"ok": False, "erreur": code}
        if len(json.dumps(frame, ensure_ascii=False, allow_nan=False)) <= self._limite:
            return frame
        # Une lecture n'invente ni fragment ni artefact pour faire rentrer un refus.
        raise RuntimeError("LECTURE-DOCUMENTAIRE-INDISPONIBLE") from None

    @staticmethod
    def _arguments_lecture_documents_m10(nom, arguments):
        from m10_memoire import affaire
        from m10_memoire import documents_affaire as domaine

        args = domaine._copie(arguments)
        if _LECTURES_DOCUMENTAIRES_M10[nom] == "lister":
            domaine._forme(args, {"affaire_id", "decalage", "limite"})
            domaine._entier(args["decalage"], 0, 64)
            domaine._entier(args["limite"], 1, 8)
        else:
            domaine._forme(args, {"affaire_id", "document_ref", "version_source"})
            domaine._reference_forme(args["document_ref"])
            domaine._reference_forme(args["version_source"])
        if type(args["affaire_id"]) is not str or not affaire.valide(args["affaire_id"]):
            raise ValueError("forme documentaire")
        return args

    @staticmethod
    def _confirmation_lecture_documents_m10(response, *, nom, args, quota):
        """Copie JSON fermée et binding du DTO complet avant de sortir du SAVEPOINT."""
        from m10_memoire import documents_affaire as domaine

        value = domaine._copie(response)
        domaine._forme(value, {"ok", "resultat"})
        domaine._forme(value["resultat"], {"accepte", "resultat"})
        if value["ok"] is not True or value["resultat"]["accepte"] is not True:
            raise ValueError("projection documentaire")
        dto = value["resultat"]["resultat"]
        index = _LECTURES_DOCUMENTAIRES_M10[nom] == "lister"
        commun = {
            "version_schema", "affaire_id", "document_ref", "version_source", "statut", "titre",
            "methode", "source_sha256", "taille_points", "taille_octets", "auteur", "horodatage", "activation_ref",
        }
        if index:
            domaine._forme(dto, {
                "version_schema", "affaire_id", "decalage", "limite", "total_versions", "suivant_decalage", "versions",
            })
            domaine._entier(dto["version_schema"], 1, 1)
            domaine._entier(dto["decalage"], 0, 64)
            domaine._entier(dto["limite"], 1, 8)
            domaine._entier(dto["total_versions"], 0, 64)
            fin = args["decalage"] + args["limite"]
            suivant = fin if fin < dto["total_versions"] else None
            if dto["suivant_decalage"] is not None:
                domaine._entier(dto["suivant_decalage"], 1, 64)
            if (
                dto["affaire_id"] != args["affaire_id"] or dto["decalage"] != args["decalage"]
                or dto["limite"] != args["limite"] or dto["suivant_decalage"] != suivant
                or type(dto["versions"]) is not list
                or len(dto["versions"]) != max(0, min(args["limite"], dto["total_versions"] - args["decalage"]))
            ):
                raise ValueError("page documentaire")
            rows = dto["versions"]
        else:
            rows = [dto]
        precedent = -1
        for row in rows:
            if type(row) is not dict:
                raise ValueError("ligne documentaire")
            cles = commun | {"version_no", "version_precedente_attendue", "activation_attendue"} if index else commun
            if not index and row.get("statut") != "RETIREE":
                cles = cles | {"corps"}
            domaine._forme(row, cles)
            domaine._entier(row["version_schema"], 1, 1)
            if row["affaire_id"] != args["affaire_id"] or row["statut"] not in (
                "DEPOSEE_NON_ACTIVEE", "COURANTE", "HISTORIQUE_NON_COURANTE", "RETIREE",
            ) or row["methode"] != "utf8-exact-v1":
                raise ValueError("identité documentaire")
            domaine._reference_forme(row["document_ref"])
            domaine._reference_forme(row["version_source"])
            if row["document_ref"]["index"] > row["version_source"]["index"]:
                raise ValueError("ordre documentaire")
            domaine._texte(row["titre"], 120)
            domaine._hash(row["source_sha256"])
            domaine._entier(row["taille_points"], 1, 2000)
            domaine._entier(row["taille_octets"], row["taille_points"], row["taille_points"] * 4)
            domaine._auteur(row["auteur"])
            domaine._hora(row["horodatage"])
            if row["activation_ref"] is not None:
                domaine._reference_forme(row["activation_ref"])
                if row["activation_ref"]["index"] <= row["version_source"]["index"]:
                    raise ValueError("activation documentaire")
            if (row["statut"] == "DEPOSEE_NON_ACTIVEE" and row["activation_ref"] is not None) or (
                row["statut"] in ("COURANTE", "HISTORIQUE_NON_COURANTE") and row["activation_ref"] is None
            ):
                raise ValueError("statut documentaire")
            if index:
                domaine._entier(row["version_no"], 1, 8)
                domaine._reference_forme(row["version_precedente_attendue"])
                if row["activation_attendue"] is not None:
                    domaine._reference_forme(row["activation_attendue"])
                if row["version_source"]["index"] <= precedent or (
                    row["version_precedente_attendue"]["index"] < row["version_source"]["index"]
                ):
                    raise ValueError("ordre de page documentaire")
                precedent = row["version_source"]["index"]
            else:
                if row["document_ref"] != args["document_ref"] or row["version_source"] != args["version_source"]:
                    raise ValueError("référence documentaire")
                if row["statut"] != "RETIREE":
                    corps = row["corps"]
                    if type(corps) is not str:
                        raise ValueError("corps documentaire")
                    raw = corps.encode("utf-8", "strict")
                    if len(corps) != row["taille_points"] or len(raw) != row["taille_octets"] or (
                        hashlib.sha256(raw).hexdigest() != row["source_sha256"]
                    ):
                        raise ValueError("empreinte documentaire")
        domaine.borner_enveloppe(value, quota)
        return value

    def _appeler_lecture_documents_m10(self, nom, arguments, meta, ticket_cible, ticket_memoire):
        """Deux lectures DEVICE T0, hors chemins historiques de mutation et d'artefact."""
        if type(self._limite) is not int or self._limite < 40:
            raise RuntimeError("QUOTA-INSUFFISANT") from None
        acteur = identite_appelante()
        entree = self.index.get(nom)
        if (
            type(acteur) is not IdentiteAppelante or type(acteur.personne) is not str
            or type(acteur.role) is not str or type(acteur.source) is not str
            or acteur.role != "admin" or acteur.source != "appareil"
            or entree is None or entree[0] is None or entree[0].id != "m10-memoire"
            or (self.appelant is not None and self.appelant is not entree[0])
            or entree[1].nom != nom or entree[1].autonomie is not Autonomie.T0
            or entree[1].niveau_effectif is not Niveau.N0 or nom not in self._outils_du_role("admin")
            or ticket_cible is not None or ticket_memoire is not None or contexte_appel.ticket_agent_cfo() is not None
        ):
            return self.refus_lecture_documentaire_appareil("REJ-M10-LECTURE-AUTORITE-INVALIDE")
        departement, outil = entree
        from m10_memoire import humain

        if not humain.acteur_valide(acteur.personne, acteur.role, acteur.source):
            return self.refus_lecture_documentaire_appareil("REJ-M10-LECTURE-AUTORITE-INVALIDE")
        if type(departement.mode) is not str or departement.mode not in ("ombre", "supervise", "autonome"):
            return self.refus_lecture_documentaire_appareil("REJ-M10-LECTURE-MODE-NON-ADMIS")
        try:
            if meta is not None:
                raise ValueError("meta de mutation")
            args = self._arguments_lecture_documents_m10(nom, arguments)
        except Exception:
            return self.refus_lecture_documentaire_appareil("REJ-M10-LECTURE-FORME-INVALIDE")
        try:
            from m10_memoire import outils as facade

            from .stockage import connexion_courante

            with self._cnx_factory() as cnx:
                if (
                    type(cnx) is not Connection or cnx is not connexion_courante()
                    or cnx.closed or not cnx.in_transaction()
                ):
                    raise RuntimeError("lecture documentaire")
                with cnx.begin_nested():
                    signataire = approbations.signataire_valide(cnx, acteur)
                    if signataire is None or signataire.role != "admin":
                        raise _RefusDocumentaireCap("REJ-M10-LECTURE-AUTORITE-INVALIDE")
                    with (
                        appeler_en_tant_que(departement.id),
                        facade.invocation_lecture_documentaire_appareil(
                            cnx, quota=self._limite, mode_manifeste=departement.mode,
                        ),
                    ):
                        response = outil.fonction(**args)
                        response = self._confirmation_lecture_documents_m10(
                            response, nom=nom, args=args, quota=self._limite,
                        )
            return response
        except Exception as exc:
            from .documents_affaire_lecture_appareil import ErreurLectureDocumentaire

            code = "REJ-M10-LECTURE-INDISPONIBLE"
            if type(exc) is _RefusDocumentaireCap:
                code = exc.code
            elif type(exc) is ErreurLectureDocumentaire:
                attrs = vars(exc)
                if type(attrs.get("code")) is str and type(attrs.get("detail")) is str:
                    code = attrs["code"]
            return self.refus_lecture_documentaire_appareil(code)

    def refus_documentaire_appareil(self, code, *, avant_factory=False):
        """Cadre nommé fermé, jamais artefact ; inconnu trop grand reste technique."""
        quota = self._limite
        if type(quota) is not int or quota < 40:
            message = "QUOTA-INSUFFISANT" if avant_factory or code == "QUOTA-DEPASSE" else "CONFIRMATION-INCONNUE"
            raise RuntimeError(message) from None
        codes = set(_ERREURS_DOCUMENTAIRES_M10.values())
        if type(code) is not str or code not in codes:
            code = "REJ-M10-DOC-CONFIRMATION-INCONNUE"
        frame = {"ok": False, "erreur": code}
        if len(json.dumps(frame, ensure_ascii=False, allow_nan=False)) <= quota:
            return frame
        if avant_factory and code in {
            "REJ-M10-DOC-FORME-INVALIDE", "REJ-M10-DOC-AUTORITE-INVALIDE", "REJ-M10-DOC-MODE-NON-ADMIS",
        }:
            return {"ok": False, "erreur": "QUOTA-DEPASSE"}
        raise RuntimeError("CONFIRMATION-INCONNUE") from None

    @staticmethod
    def _confirmation_documentaire_m10(response, *, nom, args, meta, acteur, quota):
        """Forme et binding de l'ACK positif entier, à vérifier avant de quitter le SAVEPOINT."""
        from m10_memoire import documents_affaire as domaine
        from m10_memoire import humain

        # This pure copy/size guard rejects subclasses, nonfinite values and untyped nested objects
        # before accessing fields. Both transport flags are budgeted, never just the cached body.
        for flag in (False, True):
            if type(response) is not dict:
                raise RuntimeError("CONFIRMATION-INCONNUE")
            domaine.borner_enveloppe({**response, "rejoue": flag}, quota)
        if (
            set(response) != {"ok", "resultat", "rejoue"} or response["ok"] is not True
            or type(response["rejoue"]) is not bool or type(response["resultat"]) is not dict
            or set(response["resultat"]) != {"accepte", "resultat"}
            or response["resultat"]["accepte"] is not True
        ):
            raise RuntimeError("CONFIRMATION-INCONNUE")
        ack = response["resultat"]["resultat"]
        if type(ack) is not dict or set(ack) != {
            "version_schema", "operation", "document_ref", "reference", "version_source", "source_sha256",
            "auteur", "intention", "horodatage_appareil_declare", "horodatage",
        }:
            raise RuntimeError("CONFIRMATION-INCONNUE")
        operation = _OUTILS_DOCUMENTAIRES_M10[nom]
        if (
            type(ack["version_schema"]) is not int or ack["version_schema"] != 1
            or ack["operation"] != operation
            or ack["auteur"] != {"personne": acteur.personne, "role": "admin", "source": "appareil"}
            or ack["intention"] != {"appareil": meta.appareil, "cle": meta.cle, "outil": nom,
                                   "empreinte_arguments": idempotence.empreinte_arguments(args)}
            or ack["horodatage_appareil_declare"] != meta.horodatage_appareil
            or type(ack["horodatage"]) is not str or len(ack["horodatage"]) > 40
            or not humain.horodatage_valide(ack["horodatage"])
        ):
            raise RuntimeError("CONFIRMATION-INCONNUE")
        for ref in (ack["document_ref"], ack["reference"], ack["version_source"]):
            if ref is None and operation == "retirer":
                continue
            if (
                type(ref) is not dict or set(ref) != {"registre", "index", "ligne_id"}
                or ref["registre"] != "documents_affaire" or type(ref["index"]) is not int
                or not 0 <= ref["index"] < 512 or type(ref["ligne_id"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", ref["ligne_id"]) is None
            ):
                raise RuntimeError("CONFIRMATION-INCONNUE")
        if ack["document_ref"] is None or ack["reference"] is None:
            raise RuntimeError("CONFIRMATION-INCONNUE")
        if args["document_ref"] is not None and ack["document_ref"] != args["document_ref"]:
            raise RuntimeError("CONFIRMATION-INCONNUE")
        if operation == "deposer":
            if (
                ack["version_source"] != ack["reference"]
                or (args["document_ref"] is None and ack["document_ref"] != ack["reference"])
                or ack["source_sha256"] != hashlib.sha256(args["corps"].encode("utf-8", "strict")).hexdigest()
            ):
                raise RuntimeError("CONFIRMATION-INCONNUE")
        elif operation == "activer":
            if ack["version_source"] != args["version_source"]:
                raise RuntimeError("CONFIRMATION-INCONNUE")
            if type(ack["source_sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", ack["source_sha256"]) is None:
                raise RuntimeError("CONFIRMATION-INCONNUE")
        elif ack["version_source"] is not None or ack["source_sha256"] is not None:
            raise RuntimeError("CONFIRMATION-INCONNUE")

    def _appeler_documents_m10(self, nom, arguments, meta, ticket_cible, ticket_memoire):
        """Voie DEVICE nommée : zéro répartiteur/claim/trace/troncature générique."""
        if type(self._limite) is not int or self._limite < 40:
            raise RuntimeError("QUOTA-INSUFFISANT") from None
        acteur = identite_appelante()
        entree = self.index.get(nom)
        if (
            type(acteur) is not IdentiteAppelante or type(acteur.personne) is not str
            or type(acteur.role) is not str or type(acteur.source) is not str
            or acteur.source != "appareil" or acteur.role != "admin"
            or entree is None or entree[0] is None or entree[0].id != "m10-memoire"
            or entree[1].nom != nom or entree[1].autonomie is not Autonomie.T1
            or entree[1].niveau_effectif is not Niveau.N3
            or nom not in self._outils_du_role(acteur.role)
            or ticket_cible is not None or ticket_memoire is not None
            or contexte_appel.ticket_agent_cfo() is not None
        ):
            return self.refus_documentaire_appareil("REJ-M10-DOC-AUTORITE-INVALIDE", avant_factory=True)
        departement, outil = entree
        if type(departement.mode) is not str or departement.mode not in {"ombre", "supervise", "autonome"}:
            return self.refus_documentaire_appareil("REJ-M10-DOC-MODE-NON-ADMIS", avant_factory=True)
        from m10_memoire import documents_affaire as domaine
        from m10_memoire import humain

        if not humain.acteur_valide(acteur.personne, acteur.role, acteur.source):
            return self.refus_documentaire_appareil("REJ-M10-DOC-AUTORITE-INVALIDE", avant_factory=True)
        try:
            if type(meta) is not idempotence.Meta or set(vars(meta)) != {"cle", "appareil", "horodatage_appareil"}:
                raise ValueError("forme")
            for value in (meta.cle, meta.appareil):
                if type(value) is not str or not value.strip() or len(value) > 128:
                    raise ValueError("forme")
                value.encode("utf-8", "strict")
            if (
                type(meta.horodatage_appareil) is not str or len(meta.horodatage_appareil) > 40
                or not humain.horodatage_valide(meta.horodatage_appareil)
            ):
                raise ValueError("forme")
            args = domaine.valider_commande(_OUTILS_DOCUMENTAIRES_M10[nom], arguments)
        except Exception:
            return self.refus_documentaire_appareil("REJ-M10-DOC-FORME-INVALIDE", avant_factory=True)
        try:
            from m10_memoire import outils as facade

            from .stockage import connexion_courante

            with self._cnx_factory() as cnx:
                if not isinstance(cnx, Connection) or cnx is not connexion_courante() or cnx.closed:
                    raise RuntimeError("CONFIRMATION-INCONNUE")
                if not cnx.in_transaction():
                    raise RuntimeError("CONFIRMATION-INCONNUE")
                with cnx.begin_nested():
                    signataire = approbations.signataire_valide(cnx, acteur)
                    if signataire is None or signataire.role != "admin":
                        raise _RefusDocumentaireCap("REJ-M10-DOC-AUTORITE-INVALIDE")
                    with (
                        appeler_en_tant_que(departement.id, origine=self.appelant.id if self.appelant else None),
                        facade.invocation_documentaire_appareil(
                            cnx, meta=meta, quota=self._limite, mode_manifeste=departement.mode,
                        ),
                    ):
                        response = outil.fonction(**args)
                        self._confirmation_documentaire_m10(
                            response, nom=nom, args=args, meta=meta, acteur=signataire, quota=self._limite,
                        )
            return response
        except Exception as exc:
            # All caller contexts (including SQL rollback) have ended here. Never forward
            # str/repr/detail from SQL, codecs, an unexpected handler or the backend.
            from .documents_affaire_transactions import ErreurTransactionDocumentaire

            code = "REJ-M10-DOC-CONFIRMATION-INCONNUE"
            if type(exc) is _RefusDocumentaireCap:
                code = exc.code
            elif type(exc) is ErreurTransactionDocumentaire:
                attrs = vars(exc)
                if (
                    type(attrs.get("code")) is str and type(attrs.get("issue")) is str
                    and attrs["issue"] == "inconnue" and type(attrs.get("detail")) is str
                ):
                    code = _ERREURS_DOCUMENTAIRES_M10.get(attrs["code"], code)
            return self.refus_documentaire_appareil(code)

    def _appeler_provenance_m8(self, arguments, meta, ticket_cible, ticket_memoire):
        """T0 admin DEVICE : admission actuelle, aucune intention de mutation."""
        actor = identite_appelante()
        if (
            actor is None or actor.source != "appareil" or actor.role != "admin"
            or _LECTURE_PROVENANCE_M8 not in self._outils_du_role(actor.role)
        ):
            return {"ok": False, "erreur": "hors_portee_role", "details": _DETAIL_PROVENANCE_M8}
        if ticket_cible is not None or ticket_memoire is not None:
            return {"ok": False, "erreur": "ticket_hors_portee_provenance_m8"}
        if meta is not None:
            return {"ok": False, "erreur": "idempotence_hors_portee_lecture"}
        from m8_analytics import outils as facade
        from m8_analytics import provenance_m5 as domaine

        try:
            with self._cnx_factory() as cnx, contexte_appel.sortie_bornee(min(5400, self._limite)):
                try:
                    args = facade.autoriser_provenance_m5_appareil(arguments, cnx=cnx)
                except domaine.Refus as exc:
                    return self._tronquer({"ok": True, "resultat": {"accepte": False, "verdict": {
                        "code": exc.verdict["code"], "detail": _DETAIL_PROVENANCE_M8,
                    }}}, _LECTURE_PROVENANCE_M8)
                return self._distribuer(_LECTURE_PROVENANCE_M8, args, appel_appareil=True)
        except Exception:
            # Cette frontière est propre à la lecture : jamais de détail de codec,
            # de source ou de driver SQL dans une réponse technique.
            return self._erreur_provenance_m8()

    @staticmethod
    def _erreur_provenance_m8():
        return {"ok": False, "erreur": "provenance_m8_indisponible", "details": _DETAIL_PROVENANCE_M8}

    @staticmethod
    def _refus_volume_provenance_m8():
        return {"ok": True, "resultat": {"accepte": False, "verdict": {
            "code": "REJ-M8-PROVENANCE-SORTIE-TROP-VOLUMINEUSE", "detail": _DETAIL_PROVENANCE_M8,
        }}}

    @staticmethod
    def _confirmation_obligations_m5_inconnue():
        return {"ok": False, "erreur": "confirmation_transport_indisponible",
                "details": "L’intention M5 reste inconnue et doit conserver son identité originale."}

    def _appeler_obligations_m5(self, nom, arguments, meta, ticket_cible, ticket_memoire):
        """Chemin DEVICE fermé des seules déclarations préparatoires, transaction unique."""
        from m5_financecore import obligations_preparees as domaine
        from m5_financecore import outils as facade
        from sqlalchemy import select

        from . import intentions_obligations_m5 as liaison
        from .stockage.schema import MUTATIONS_APPLIQUEES

        actor = identite_appelante()
        if (
            actor is None or actor.source != "appareil" or actor.role != "admin"
            or nom not in self._outils_du_role(actor.role)
        ):
            return {"ok": False, "erreur": "hors_portee_role",
                    "details": "La déclaration préparatoire exige la portée admin DEVICE courante."}
        if ticket_cible is not None or ticket_memoire is not None:
            return {"ok": False, "erreur": "ticket_hors_portee_obligations_preparees"}
        lecture = nom == _LECTURE_OBLIGATIONS_M5
        if lecture and meta is not None:
            return {"ok": False, "erreur": "idempotence_hors_portee_lecture"}
        if not lecture and not isinstance(meta, idempotence.Meta):
            return {"ok": False, "erreur": "idempotence_appareil_requise"}
        with self._cnx_factory() as cnx, contexte_appel.sortie_bornee(min(5400, self._limite)):
            if lecture:
                try:
                    facade.autoriser_obligation_preparee_appareil(arguments, nom=nom)
                except domaine.Refus as exc:
                    return {"ok": False, "erreur": exc.verdict["code"], "details": exc.verdict["detail"]}
                return self._distribuer(nom, arguments, appel_appareil=True)
            try:
                # Closed domain validation rejects NaN and Unicode surrogates before
                # publication of the JSON correlation context, claim or business source.
                domaine.valider_mutation(arguments)
            except domaine.Refus as exc:
                return {"ok": False, "erreur": exc.verdict["code"], "details": exc.verdict["detail"]}
            try:
                reception = dt.datetime.now(dt.UTC)
                heure = HorodatageAppareil(
                    meta.appareil, dt.datetime.fromisoformat(meta.horodatage_appareil), reception,
                )
            except (TypeError, ValueError):
                return self._confirmation_obligations_m5_inconnue()
            with liaison.contexte_intention(meta, arguments), receptionne_de(heure):
                try:
                    facade.autoriser_obligation_preparee_appareil(arguments, nom=nom)
                except domaine.Refus as exc:
                    return {"ok": False, "erreur": exc.verdict["code"], "details": exc.verdict["detail"]}
                # The generic claim compares arguments, but not its original hour/status.
                row = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
                    MUTATIONS_APPLIQUEES.c.appareil == meta.appareil,
                    MUTATIONS_APPLIQUEES.c.cle_idempotence == meta.cle,
                )).mappings().first()
                if row is not None and (
                    row["outil"] != nom or row["empreinte_arguments"] != idempotence.empreinte_arguments(arguments)
                    or row["horodatage_appareil"] != meta.horodatage_appareil or row["statut"] != "ok"
                ):
                    return self._confirmation_obligations_m5_inconnue()
                try:
                    claim = idempotence.reclamer(cnx, meta, nom, arguments, reception)
                except (ValueError, TypeError):
                    return self._confirmation_obligations_m5_inconnue()
                if claim.rejouee:
                    try:
                        facade.verifier_rejeu_obligation_preparee_appareil(arguments, claim.reponse)
                    except (domaine.Refus, TypeError, ValueError):
                        return self._confirmation_obligations_m5_inconnue()
                    return {**claim.reponse, "rejoue": True}
                response = self._distribuer(nom, arguments, appel_appareil=True, meta=meta)
                if any(len(json.dumps({**response, "rejoue": flag}, ensure_ascii=False))
                       > min(5400, self._limite) for flag in (False, True)):
                    raise RuntimeError("confirmation M5 hors borne après exécution atomique")
                idempotence.finaliser(cnx, meta, response)
                return {**response, "rejoue": False}

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

    def _garder_revue_m4(
        self, nom: str, arguments: dict[str, Any], cnx: Connection, *, frais: bool = True,
    ) -> dict[str, Any] | None:
        """Autorité actuelle et proposition signable avant claim ou lecture métier."""
        signataire = self._signataire_appareil_cible_valide(nom, cnx)
        if signataire is None or signataire.source != "appareil" or signataire.role != "admin":
            return {"ok": False, "erreur": "REJ-HUMAIN-REQUIS",
                    "details": "Une personne DEVICE admin actuellement active est requise."}
        if valider_arguments(self.index[nom][1].parametres, arguments):
            return {"ok": False, "erreur": "arguments_invalides",
                    "details": "Le contrat fermé de revue de complétion n’est pas satisfait."}
        if nom == _PROPOSITION_REVUE_M4:
            try:
                taille = len(json.dumps(arguments, ensure_ascii=False, allow_nan=False))
            except (TypeError, ValueError):
                return {"ok": False, "erreur": "arguments_invalides",
                        "details": "Les arguments ne forment pas une proposition JSON complète."}
            if taille > 1500:
                return {"ok": False, "erreur": "arguments_trop_volumineux",
                        "details": "La proposition dépasse les 1500 caractères lisibles sur l’appareil."}
            if frais:
                from m4_field_ops import revue_completion_sources, sources_revue_completion

                try:
                    with contexte_appel.sortie_bornee(min(5400, self._limite)):
                        sources_revue_completion.autoriser_proposition(arguments, frais=True)
                except revue_completion_sources.Refus as exc:
                    refus = revue_completion_sources.verdict(exc.suffixe)
                    return {"ok": False, "erreur": refus["code"], "details": refus["detail"]}
        return None

    @staticmethod
    def _contexte_decision_revue_m4(nom, meta, arguments):
        if nom != "m9_decider_demande_approbation":
            return nullcontext()
        from .approbations_completion_m4 import contexte_decision

        return contexte_decision(meta, arguments)

    @staticmethod
    def _confirmation_revue_inconnue():
        return {"ok": False, "erreur": "confirmation_transport_indisponible", "issue": "inconnue",
                "details": "L’intention reste inconnue ; aucune nouvelle décision ne doit en être dérivée."}

    def _preflight_creation_revue_m4(self, arguments, meta, signataire):
        from .approbations_completion_m4 import _hora, _texte

        if not _texte(meta.appareil) or not _texte(meta.cle) or not _hora(meta.horodatage_appareil):
            return self._confirmation_revue_inconnue()
        # creer_demande produit exactement douze caractères hexadécimaux. Leur
        # valeur n'affecte pas la taille ; aucun identifiant fictif n'est persisté.
        ident = "0" * 12
        preuve = {"demande_id": ident, "departement": "m04-field-ops", "outil": _PROPOSITION_REVUE_M4,
                  "niveau": "N4", "empreinte_arguments": idempotence.empreinte_arguments(arguments),
                  "proposant": {"personne": signataire.personne, "role": signataire.role,
                                "appareil_id": meta.appareil, "intention_uuid": meta.cle}}
        attendue = {"ok": True, "version_schema": 1, "statut": "en_attente_approbation", "demande_id": ident,
                    "details": "Demande N4 créée par un appareil humain authentifié. Le propriétaire doit "
                               "l’approuver avant toute exécution.", "preuve_proposition": preuve}
        if any(len(json.dumps({**attendue, "rejoue": flag}, ensure_ascii=False)) > min(5400, self._limite)
               for flag in (False, True)):
            return self._confirmation_revue_inconnue()
        return None

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

    @staticmethod
    def _garder_preuves_m6(arguments: dict[str, Any]) -> dict[str, Any] | None:
        from m6_material_control import contexte_materiaux_appareil as c
        from m6_material_control import outils as outils_m6
        from m6_material_control import preuves_pertes_bris_appareil as p

        try:
            outils_m6.autoriser_declaration_preuves(arguments.get("wct_id"))
        except (p.Refus, c.Refus) as exc:
            return {
                "ok": False,
                "erreur": "REJ-M6-PREUVES-" + exc.suffixe,
                "details": "Identité, cible ou formulaire non admis ; aucune mutation réclamée ou rejouée.",
            }
        return None

    @staticmethod
    def _confirmation_preuves_inconnue() -> dict[str, Any]:
        return {
            "ok": False,
            "erreur": "confirmation_transport_indisponible",
            "issue": "inconnue",
            "details": "La confirmation entière ne tient pas dans le quota ; conserver et rejouer la même clé.",
        }

    def _borner_confirmation_preuves(self, reponse: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(reponse, ensure_ascii=False)) > min(5400, self._limite):
            return self._confirmation_preuves_inconnue()
        return reponse

    @staticmethod
    def _refus_classement_inconnu(suffixe: str) -> dict[str, Any]:
        return {
            "ok": False,
            "erreur": "REJ-M6-CLASSEMENT-" + suffixe,
            "issue": "inconnue",
            "details": "La confirmation actuelle est indisponible ; conserver la même clé et ses arguments.",
        }

    @staticmethod
    def _garder_classement_m6(nom: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        from m6_material_control import classement_variance_appareil as c
        from m6_material_control import outils as outils_m6

        try:
            outils_m6.autoriser_classement_variance_appareil(arguments, nom=nom)
        except c.Refus as exc:
            return Capacites._refus_classement_inconnu(exc.suffixe)
        return None

    @staticmethod
    def _verifier_rejeu_classement_m6(
        arguments: dict[str, Any], reponse: dict[str, Any]
    ) -> dict[str, Any] | None:
        from m6_material_control import classement_variance_appareil as c
        from m6_material_control import outils as outils_m6

        try:
            outils_m6.verifier_rejeu_classement_variance_appareil(arguments, reponse)
        except c.Refus as exc:
            return Capacites._refus_classement_inconnu(exc.suffixe)
        return None

    @staticmethod
    def _refus_rappel_m1_inconnu(suffixe: str, *, lecture: bool = False) -> dict[str, Any]:
        return {
            "ok": False,
            "erreur": "REJ-M1-RAPPEL-" + suffixe,
            "issue": "inconnue",
            "details": (
                "La lecture actuelle est indisponible ; rechargez les rappels importés."
                if lecture else
                "La confirmation actuelle est indisponible ; conserver la même clé et ses arguments."
            ),
        }

    def _garder_rappel_m1(self, nom: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        appelante = identite_appelante()
        if (
            appelante is None or appelante.source != "appareil"
            or appelante.role != "admin" or nom not in self._outils_du_role(appelante.role)
        ):
            return self._refus_rappel_m1_inconnu("IDENTITE-OU-PORTEE", lecture=nom == _LECTURE_RAPPELS_M1)
        from m1_front_office import outils as outils_m1
        from m1_front_office import rappels_appareil as r

        try:
            outils_m1.autoriser_prise_rappel_appareil(arguments, nom=nom)
        except r.Refus as exc:
            return self._refus_rappel_m1_inconnu(exc.suffixe, lecture=nom == _LECTURE_RAPPELS_M1)
        return None

    @staticmethod
    def _contexte_mutation_rappel_m1(nom: str, meta: idempotence.Meta) -> AbstractContextManager:
        if nom != _MUTATION_RAPPEL_M1:
            return nullcontext()
        from m1_front_office import rappels_appareil as r

        return r.contexte_mutation(meta)

    @staticmethod
    def _contexte_mutation_note_m6(nom: str, meta: idempotence.Meta) -> AbstractContextManager:
        if nom != _MUTATION_NOTE_M6:
            return nullcontext()
        from m6_material_control import outils as outils_m6

        return outils_m6.contexte_mutation_note_commande(meta)

    @staticmethod
    def _garder_note_m6(arguments=None, reponse=None):
        from m6_material_control import notes_commande as n
        from m6_material_control import outils as outils_m6

        try:
            outils_m6.autoriser_note_commande()
            if reponse is not None:
                outils_m6.verifier_rejeu_note_commande(arguments, reponse)
        except n.Refus as exc:
            return {"ok": True, "resultat": n.refuser(exc.suffixe), "rejoue": False}
        return None

    @staticmethod
    def _contexte_mutation_classement_m6(nom: str, meta: idempotence.Meta) -> AbstractContextManager:
        if nom != _MUTATION_CLASSEMENT_M6:
            return nullcontext()
        from m6_material_control import classement_variance_contexte as c

        return c.contexte_mutation(meta)

    @staticmethod
    def _verifier_rejeu_rappel_m1(arguments: dict[str, Any], reponse: dict[str, Any]) -> dict[str, Any] | None:
        from m1_front_office import outils as outils_m1
        from m1_front_office import rappels_appareil as r

        try:
            outils_m1.verifier_rejeu_prise_rappel_appareil(arguments, reponse)
        except r.Refus as exc:
            return Capacites._refus_rappel_m1_inconnu(exc.suffixe)
        return None

    def _borner_confirmation_rappel_m1(self, reponse: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(reponse, ensure_ascii=False)) > min(5400, self._limite):
            return self._refus_rappel_m1_inconnu("SORTIE-TROP-VOLUMINEUSE")
        return reponse

    def _appeler_idempotent(
        self,
        nom: str,
        arguments: dict[str, Any],
        meta: idempotence.Meta,
        *,
        revalider_humain_n3: bool = False,
        revalider_humain_cible: bool = False,
        demander_n4_humain: bool = False,
        role_refuse: str | None = None,
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
        with (
            self._cnx_factory() as cnx,
            self._contexte_mutation_rappel_m1(nom, meta),
            self._contexte_mutation_classement_m6(nom, meta),
            self._contexte_mutation_note_m6(nom, meta),
            contexte_appel.sortie_bornee(self._limite) if nom == _MUTATION_NOTE_M6 else nullcontext(),
            self._contexte_decision_revue_m4(nom, meta, arguments),
        ):
            if nom == _MUTATION_NOTE_M6:
                refus = self._garder_note_m6()
                if refus is not None:
                    return refus
            decision_revue = False
            if nom == _PROPOSITION_REVUE_M4:
                # Autorité avant même la lecture de son claim ; la création historique
                # ne dépend pas de la dernière classification métier.
                refus = self._garder_revue_m4(nom, arguments, cnx, frais=False)
                if refus is not None:
                    return refus
                if idempotence._lire(cnx, meta) is None:
                    signataire = self._signataire_appareil_cible_valide(nom, cnx)
                    refus = self._preflight_creation_revue_m4(arguments, meta, signataire)
                    if refus is not None:
                        return refus
                    refus = self._garder_revue_m4(nom, arguments, cnx, frais=True)
                if refus is not None:
                    return refus
            if nom == "m9_decider_demande_approbation":
                from . import approbations_appareil
                from .approbations_completion_m4 import _demande, cible_revue

                signataire, _ = approbations_appareil._signataire(cnx, identite_appelante())
                decision_revue = cible_revue(cnx, arguments.get("demande_id"))
                if decision_revue:
                    if signataire is None or not signataire.proprietaire:
                        return self._confirmation_revue_inconnue()
                    demande_revue = _demande(cnx, arguments.get("demande_id"))
                    if demande_revue is None:
                        return self._confirmation_revue_inconnue()
                    # Une confirmation minimale complète est nécessaire avant le claim.
                    # Le producteur M4 préflight ensuite sa preuve positive entière.
                    minimale = {"ok": True, "resultat": {"accepte": True, "resultat": {
                        "demande_id": demande_revue["id"], "decision": arguments.get("decision"),
                        "statut": "echec", "outil": demande_revue["outil"],
                        "departement": demande_revue["departement"], "niveau": "N4",
                        "decide_par": signataire.personne.identifiant, "role": "nathan_owner",
                        "decide_le": recu_le.isoformat(timespec="seconds"), "preuve_completion": None,
                    }}, "rejoue": False}
                    if len(json.dumps(minimale, ensure_ascii=False)) > min(5400, self._limite):
                        return self._confirmation_revue_inconnue()
            if nom == _MUTATION_RAPPEL_M1:
                refus = self._garder_rappel_m1(nom, arguments)
                if refus is not None:
                    return refus
            if nom == _MUTATION_CLASSEMENT_M6:
                refus = self._garder_classement_m6(nom, arguments)
                if refus is not None:
                    return refus
            if nom == "m6_declarer_materiaux_avec_preuves_appareil":
                refus = self._garder_preuves_m6(arguments)
                if refus is not None:
                    return refus
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
            except (ValueError, TypeError):
                if nom == _PROPOSITION_REVUE_M4 or decision_revue:
                    return self._confirmation_revue_inconnue()
                raise
            if refus_role is not None:
                # Un refus de portée est rejouable, mais ne peut jamais dévoiler une ancienne
                # réponse réussie ni la nature d'un conflit : l'autorité précède toute restitution.
                if not reclamation.rejouee:
                    idempotence.finaliser(cnx, meta, refus_role)
                refus_rejoue = reclamation.rejouee and reclamation.reponse.get("erreur") == "hors_portee_role"
                return {**refus_role, "rejoue": refus_rejoue}
            if reclamation.rejouee:
                if nom == _MUTATION_NOTE_M6:
                    refus = self._garder_note_m6(arguments, reclamation.reponse)
                    if refus is not None:
                        return refus
                # L'autorité propriétaire COURANTE, relue après le claim, précède toute restitution
                # d'une décision M9 en cache ; rien n'est écrit, le claim original reste intact.
                if nom == "m9_decider_demande_approbation":
                    signataire_cache, _ = approbations_appareil._signataire(cnx, identite_appelante())
                    if signataire_cache is None or not signataire_cache.proprietaire:
                        return self._confirmation_revue_inconnue()
                if nom == "m4_demarrer_route":
                    from m4_field_ops import outils as outils_m4

                    refus = outils_m4.verifier_identite_rejeu_route_appareil(arguments)
                    if refus is not None:
                        return {"ok": True, "resultat": refus, "rejoue": True}
                if nom == "m4_confirmer_dates_cedule":
                    from m4_field_ops import outils as outils_m4

                    refus = outils_m4.verifier_autorite_calendrier()
                    if refus is not None:
                        return {"ok": True, "resultat": refus, "rejoue": True}
                if nom == "m2_enregistrer_interaction":
                    from m2_revenue_crm import outils as outils_m2

                    refus = outils_m2.verifier_autorite_rejeu_interaction_appareil(arguments)
                    if refus is not None:
                        return {"ok": True, "resultat": refus, "rejoue": True}
                if nom == "m2_corriger_contact_client":
                    from m2_revenue_crm import outils as outils_m2

                    refus = outils_m2.verifier_autorite_rejeu_contact_appareil()
                    if refus is not None:
                        return {"ok": True, "resultat": refus, "rejoue": True}
                if (nom == _PROPOSITION_REVUE_M4 or decision_revue) and type(reclamation.reponse) is not dict:
                    return self._confirmation_revue_inconnue()
                reponse = {**reclamation.reponse, "rejoue": True}
                if nom == _PROPOSITION_REVUE_M4:
                    from .approbations_completion_m4 import verifier_rejeu_proposition

                    signataire = self._signataire_appareil_cible_valide(nom, cnx)
                    if (not verifier_rejeu_proposition(cnx, arguments, reclamation.reponse, meta, signataire.personne)
                            or len(json.dumps(reponse, ensure_ascii=False)) > min(5400, self._limite)):
                        return self._confirmation_revue_inconnue()
                    return reponse
                if nom == "m9_decider_demande_approbation":
                    from .approbations_completion_m4 import accuse_revue, cible_revue, verifier_rejeu_decision

                    if cible_revue(cnx, arguments.get("demande_id")) or accuse_revue(reclamation.reponse):
                        if (not verifier_rejeu_decision(cnx, arguments, reclamation.reponse)
                                or len(json.dumps(reponse, ensure_ascii=False)) > min(5400, self._limite)):
                            return self._confirmation_revue_inconnue()
                        return reponse
                if nom == _MUTATION_RAPPEL_M1:
                    with contexte_appel.sortie_bornee(min(5400, self._limite)):
                        refus = self._verifier_rejeu_rappel_m1(arguments, reclamation.reponse)
                    if refus is not None:
                        return refus
                    return self._borner_confirmation_rappel_m1(reponse)
                if nom == _MUTATION_CLASSEMENT_M6:
                    refus = self._verifier_rejeu_classement_m6(arguments, reclamation.reponse)
                    if refus is not None:
                        return refus
                    return self._borner_confirmation_preuves(reponse)
                if nom == "m6_declarer_materiaux_avec_preuves_appareil":
                    return self._borner_confirmation_preuves(reponse)
                return reponse
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
                    if nom == _PROPOSITION_REVUE_M4:
                        from .approbations_completion_m4 import preuve_proposition

                        preuve, refus = preuve_proposition(cnx, ident, arguments)
                        if refus is not None:
                            raise RuntimeError("preuve de création N4 propre indisponible après insertion")
                        reponse["version_schema"] = 1
                        reponse["preuve_proposition"] = preuve
                        if any(len(json.dumps({**reponse, "rejoue": flag}, ensure_ascii=False))
                               > min(5400, self._limite) for flag in (False, True)):
                            raise RuntimeError("confirmation de création N4 hors de sa borne atomique")
                idempotence.finaliser(cnx, meta, reponse)
                return {**reponse, "rejoue": False}
            horodatage = HorodatageAppareil(
                appareil=meta.appareil,
                horodatage_appareil=dt.datetime.fromisoformat(meta.horodatage_appareil),
                recu_le=recu_le,
            )
            with receptionne_de(horodatage):
                decision_revue = False
                if nom == "m9_decider_demande_approbation":
                    from .approbations_completion_m4 import cible_revue

                    decision_revue = cible_revue(cnx, arguments.get("demande_id"))
                if decision_revue or nom in {
                    "m6_declarer_materiaux_avec_preuves_appareil", _MUTATION_CLASSEMENT_M6, _MUTATION_RAPPEL_M1,
                }:
                    with contexte_appel.sortie_bornee(min(5400, self._limite)):
                        reponse = self._distribuer(nom, arguments, appel_appareil=True, meta=meta)
                else:
                    reponse = self._distribuer(nom, arguments, appel_appareil=True, meta=meta)
            finale = {**reponse, "rejoue": False}
            if nom == _MUTATION_RAPPEL_M1 and (
                reponse.get("erreur", "").startswith("REJ-M1-RAPPEL-SORTIE-TROP-VOLUMINEUSE")
                or len(json.dumps(finale, ensure_ascii=False)) > min(5400, self._limite)
            ):
                raise RuntimeError("confirmation fraîche de rappel hors de sa borne atomique")
            if nom == _MUTATION_CLASSEMENT_M6 and (
                reponse.get("erreur") == "confirmation_transport_indisponible"
                or len(json.dumps(finale, ensure_ascii=False)) > min(5400, self._limite)
            ):
                # Le producteur pré/postflight avant son commit. Une divergence technique
                # ne doit sceller ni l'append, ni sa trace, ni la réclamation extérieure.
                raise RuntimeError("confirmation fraîche de classement hors de sa borne atomique")
            idempotence.finaliser(cnx, meta, reponse)
            if nom == "m6_declarer_materiaux_avec_preuves_appareil":
                return self._borner_confirmation_preuves(finale)
            return finale

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
            return {
                "ok": False,
                "erreur": "hors_portee_role",
                "details": f"{outil.nom} est hors de la portée du rôle {signataire.role} "
                "(openclaw.roles_outils) : ni exécuté ni mis en attente.",
            }
        reception = horodatage_reception()
        with cnx.begin_nested():
            origine = self.appelant.id if self.appelant else None
            with appeler_en_tant_que(departement.id, origine=origine):
                reponse = executer_atomique(outil, arguments)
            if reponse.get("ok") and (
                outil.nom not in {"m6_declarer_materiaux_avec_preuves_appareil", _MUTATION_CLASSEMENT_M6,
                                 _MUTATION_OBLIGATIONS_M5, _MUTATION_NOTE_M6}
                or reponse.get("resultat", {}).get("accepte") is True
            ) and not (outil.nom == _MUTATION_NOTE_M6 and reponse.get("resultat", {}).get("rejoue") is True):
                approbations.tracer_validation_au_depart(
                    cnx,
                    departement.id,
                    outil.nom,
                    arguments,
                    niveau=outil.niveau_effectif,
                    signataire=signataire,
                    reponse=reponse,
                    appareil=reception.appareil if reception is not None else None,
                )
        return self._tronquer(
            reponse,
            outil.nom,
            departement=departement.id,
            origine=self.appelant.id if self.appelant else None,
        )

    def _tronquer(
        self,
        reponse: dict[str, Any],
        source: str,
        *,
        departement: str | None = None,
        origine: str | None = None,
    ) -> dict[str, Any]:
        if source in {_MUTATION_NOTE_M6, _LECTURE_NOTE_M6, _LISTE_NOTES_M6}:
            # Notes privées : jamais copiées dans un artefact générique de sortie.
            from m6_material_control import notes_commande as n

            frames = [{**reponse, "rejoue": flag} for flag in (False, True)]
            if all(len(json.dumps(frame, ensure_ascii=False)) <= self._limite for frame in frames):
                return reponse
            if source == _MUTATION_NOTE_M6 and reponse.get("resultat", {}).get("accepte") is True:
                raise RuntimeError("confirmation note M6 hors borne dans sa transaction")
            return {"ok": True, "resultat": n.refuser("SORTIE-TROP-VOLUMINEUSE")}
        if source == _LECTURE_PROVENANCE_M8:
            # Toutes les issues de ce nom sortent ici, avant le fallback artefact.
            # Les cadres d'erreur constants sans données peuvent dépasser quota40.
            if not isinstance(reponse, dict) or set(reponse) != {"ok", "resultat"} or reponse.get("ok") is not True:
                return self._erreur_provenance_m8()
            couple = reponse["resultat"]
            if not isinstance(couple, dict):
                return self._erreur_provenance_m8()
            if couple.get("accepte") is False:
                verdict = couple.get("verdict")
                if (
                    set(couple) == {"accepte", "verdict"} and isinstance(verdict, dict)
                    and set(verdict) == {"code", "detail"}
                    and isinstance(verdict.get("code"), str) and verdict["code"] in _CODES_PROVENANCE_M8
                    and verdict.get("detail") == _DETAIL_PROVENANCE_M8
                ):
                    return reponse
                return self._erreur_provenance_m8()
            if couple.get("accepte") is not True or set(couple) != {"accepte", "resultat"}:
                return self._erreur_provenance_m8()
            try:
                texte = json.dumps(reponse, ensure_ascii=False, allow_nan=False)
                texte.encode("utf-8", errors="strict")
            except (TypeError, ValueError, UnicodeError, RecursionError):
                return self._erreur_provenance_m8()
            return reponse if len(texte) <= min(5400, self._limite) else self._refus_volume_provenance_m8()
        if source == "m9_decider_demande_approbation":
            from .approbations_completion_m4 import decision_revue_en_cours

            with self._cnx_factory() as cnx:
                if decision_revue_en_cours(cnx):
                    if any(len(json.dumps({**reponse, "rejoue": flag}, ensure_ascii=False))
                           > min(5400, self._limite) for flag in (False, True)):
                        raise RuntimeError("confirmation de décision M4 hors de sa borne atomique")
                    return reponse  # Jamais d'artefact partiel pour une décision source-liée.
        if source == _LECTURE_REVUE_M4:
            if len(json.dumps(reponse, ensure_ascii=False)) <= min(5400, self._limite):
                return reponse
            return {"ok": False, "erreur": "confirmation_transport_indisponible", "issue": "inconnue",
                    "details": "La lecture complète dépasse sa borne ; aucun artefact n’est créé."}
        if source in {_MUTATION_OBLIGATIONS_M5, _LECTURE_OBLIGATIONS_M5}:
            frames = (
                [{**reponse, "rejoue": flag} for flag in (False, True)]
                if source == _MUTATION_OBLIGATIONS_M5 else [reponse]
            )
            if all(len(json.dumps(frame, ensure_ascii=False)) <= min(5400, self._limite) for frame in frames):
                return reponse
            if source == _MUTATION_OBLIGATIONS_M5:
                raise RuntimeError("confirmation M5 hors borne dans la transaction métier")
            return {"ok": False, "erreur": "REJ-M5-OBLIGATIONS-SORTIE-TROP-VOLUMINEUSE"}
        if source in {_LECTURE_RAPPELS_M1, _MUTATION_RAPPEL_M1}:
            if reponse.get("erreur") == "arguments_invalides":
                reponse = {
                    "ok": False, "erreur": "arguments_invalides",
                    "details": "La demande ne satisfait pas le contrat fermé des rappels importés.",
                }
            entiere = {**reponse, "rejoue": False} if source == _MUTATION_RAPPEL_M1 else reponse
            if len(json.dumps(entiere, ensure_ascii=False)) <= min(5400, self._limite):
                return reponse
            return self._refus_rappel_m1_inconnu(
                "SORTIE-TROP-VOLUMINEUSE", lecture=source == _LECTURE_RAPPELS_M1,
            )
        if source == _MUTATION_CLASSEMENT_M6 or source in _LECTURES_CLASSEMENT_M6:
            if reponse.get("erreur") == "arguments_invalides":
                reponse = {"ok": False, "erreur": "arguments_invalides",
                           "details": "La demande ne satisfait pas le contrat fermé de classement."}
            entiere = {**reponse, "rejoue": False} if source == _MUTATION_CLASSEMENT_M6 else reponse
            if len(json.dumps(entiere, ensure_ascii=False)) <= min(5400, self._limite):
                return reponse
            if source == _MUTATION_CLASSEMENT_M6:
                return self._confirmation_preuves_inconnue()
            return {
                "ok": False,
                "erreur": "REJ-M6-CLASSEMENT-SORTIE-TROP-VOLUMINEUSE",
                "details": "La lecture entière dépasse la borne ; aucun détail partiel n'est transmis.",
            }
        if source == "m6_declarer_materiaux_avec_preuves_appareil" and reponse.get("erreur") == "arguments_invalides":
            reponse = {"ok": False, "erreur": "arguments_invalides",
                       "details": "La demande ne satisfait pas le contrat fermé de déclaration."}
        texte = json.dumps(reponse, ensure_ascii=False)
        if len(texte) <= self._limite:
            return reponse
        if source == "m6_declarer_materiaux_avec_preuves_appareil":
            return self._confirmation_preuves_inconnue()
        if source == "m10_paquet_contexte_affaire":
            # Le moteur Core refuse déjà ce contexte ; sa lecture ne doit pas créer d'artefact.
            return {
                "ok": False,
                "erreur": "REJ-PAQUET-AFFAIRE-SORTIE-TROP-VOLUMINEUSE",
                "details": (
                    "le paquet dépasse la borne de sortie du contexte privé ; aucun détail partiel n'est transmis"
                ),
            }
        refus_lecture_appareil = {
            "m9_preparer_dossier_direction": "REJ-DOSSIER-SORTIE-TROP-VOLUMINEUSE",
            "m9_diagnostiquer_dossier_direction": "REJ-DIAGNOSTIC-SORTIE-TROP-VOLUMINEUSE",
            "m10_lire_paquet_affaire_appareil": "REJ-PAQUET-AFFAIRE-SORTIE-TROP-VOLUMINEUSE",
            "m10_rechercher_affaire_appareil": "REJ-RECHERCHE-AFFAIRE-SORTIE-TROP-VOLUMINEUSE",
            "m6_lister_wct_pertes_appareil": "REJ-M6-WCT-SORTIE-TROP-VOLUMINEUSE",
            "m6_lire_pertes_alertes_wct_appareil": "REJ-M6-PERTES-SORTIE-TROP-VOLUMINEUSE",
            "m6_lire_reapprovisionnement_appareil": "REJ-M6-REAPPRO-SORTIE-TROP-VOLUMINEUSE",
            "m6_lire_contexte_materiaux_appareil": "REJ-M6-CONTEXTE-SORTIE-TROP-VOLUMINEUSE",
            "m6_lire_preuves_pertes_wct_appareil": "REJ-M6-PREUVES-SORTIE-TROP-VOLUMINEUSE",
        }.get(source)
        if refus_lecture_appareil is not None:
            # Le plafond de cette capacité peut être inférieur au budget fixe du producteur.
            return {
                "ok": False,
                "erreur": refus_lecture_appareil,
                "details": ("la lecture dépasse la borne de sortie appareil ; aucun détail partiel n'est transmis"),
            }
        departement_artifact = departement or contexte_appel.DEPARTEMENT_APPELANT.get()
        origine_artifact = origine or contexte_appel.departement_origine_appelante()
        with self._cnx_factory() as cnx:
            return {
                "ok": reponse.get("ok", False),
                "tronque": True,
                "apercu": jetons.tronquer(
                    cnx,
                    texte,
                    source,
                    self._limite,
                    departement=departement_artifact,
                    origine=origine_artifact,
                ),
            }
