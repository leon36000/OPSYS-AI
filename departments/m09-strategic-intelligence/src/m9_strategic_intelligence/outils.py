"""Capacités d'agent du département M9 Strategic Intelligence.

M9 v1 est un harnais déterministe pur (PRD §0/§3.1) : aucun Council d'agents, aucun contenu
délibératif — il agrège les snapshots que les autres modules lui rapportent dans un état
consolidé (Business State Graph) et signale les contradictions internes, sans jamais inventer
ni recommander. `m9_etat_consolide` compose ingestion → écriture au registre → construction de
l'état consolidé (contradictions comprises) en un seul appel.

PLAN T3.2 (M9.5, briefing du matin) : `m9_produire_briefing_matin` compose la file du
propriétaire (`opsys.approbations.file_proprietaire`), les alertes M8 déjà reçues par le bus
(`m8.alerte_proposee`, `_recevoir_alerte_proposee`) et les faits déjà consolidés par M9 en un
gabarit déterministe (`briefing_matin.assembler_briefing_matin`, module pur). Boucle M8 → M9 des
preuves (ADR-0009 §3) : M9 ne lit jamais le registre M8 directement, seulement le bus.

PLAN T1.4-f (étape 6) : `m9_lister_demandes_approbation` et `m9_decider_demande_approbation` sont les deux
outils de l'app du propriétaire pour la file d'approbation du socle. M9 les PORTE (il lit déjà cette
file, et son mobile est réservé à l'admin, §7 M9) ; la logique est dans `opsys.approbations_appareil`,
qui décide par le chemin de la console. Ce ne sont pas des outils de l'agent M9, qui ne décide jamais :
sans l'identité authentifiée d'un appareil, ils refusent. PLAN T1.5-e : la liste rend les attentes des
départements par pages bornées (`decalage_attentes`, `attentes_suivant`), comme `m9_lire_suite_briefing`
pour le briefing ; un rang est un entier, jamais une personne.

PLAN T1.5-d : le briefing est BORNÉ par le code sous la limite de sortie de `Capacites`
(`jetons.LIMITE_SORTIE_DEFAUT`) — ce qui ne tient pas est compté (« N autres éléments non affichés ») et
se lit par `m9_lire_suite_briefing`, jamais une troncature silencieuse. `m9_produire_lecture_strategique`
lit les alertes de mesure de M8 (chantier terminé : temps réel contre prévu, marge, matériaux) et cite
leurs preuves sans décider : la décision revient au propriétaire. `m9_lire_alertes_m8` est borné de la même
façon (`lecture_alertes.lire_alertes_m8` : `depart`, `prochain_depart`, sous `BUDGET_SORTIE`) ; sa réponse est
un objet (`alertes`, `total`, `prochain_depart`…), non plus la liste nue d'avant la borne.

Registre de production (ADR-0009) : par défaut, `outils()` adosse le registre de snapshots au
stockage durable de l'instance (`opsys.stockage.maillons`, dans la transaction que
`Capacites.appeler` ouvre pour chaque appel d'outil) — même convention que
m8_analytics/outils.py. `registre.py` reste pur (aucun import `opsys`/SQLAlchemy) et ignore que
ses maillons survivent au redémarrage : c'est cet adaptateur, seul, qui fait le lien. Le
paramètre `registre_cible` est le point d'injection : les tests unitaires du département y
passent explicitement un `registre.RegistreSnapshots()` EN MÉMOIRE (aucune base montée), sans
toucher au comportement par défaut utilisé par `charger_outils()` en production. `alertes_cible`
suit le même patron pour le registre durable des alertes M8 reçues (T3.2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from opsys import approbations, approbations_appareil, contexte, identite, jetons, stockage
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Niveau, Outil, depuis_couple

from . import (
    briefing_matin,
    contrats,
    lecture_alertes,
    lecture_strategique,
    rapport_strategique,
    registre,
    validation,
)
from . import etat_consolide as etat_consolide_module

_SNAPSHOT = {
    "type": "object",
    "description": (
        "SnapshotModule {module_source, horodatage, valeurs} — réutilisé tel quel de "
        "m8_analytics (patron mesuré). valeurs est TOUJOURS du texte."
    ),
}
_RAPPORT_STRATEGIQUE = {
    "type": "object",
    "description": (
        f"dict portant EXACTEMENT les {len(contrats.CHAMPS_RAPPORT_STRATEGIQUE)} clés de "
        "CHAMPS_RAPPORT_STRATEGIQUE (structure seulement, v1 ne valide pas le contenu)."
    ),
}
_MAINTENANT = {
    "type": "string",
    "description": "Instant de référence RFC 3339 (M9 n'a pas d'horloge) — jamais l'instant réel.",
}

_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"
# `Capacites._tronquer` mesure `{"ok": true, "resultat": ...}` : 25 caractères d'enveloppe, plus une marge.
# Le budget d'un outil de lecture est la limite du socle moins cette réserve : sous elle, jamais tronqué.
_RESERVE_ENVELOPPE = 100
BUDGET_SORTIE = jetons.LIMITE_SORTIE_DEFAUT - _RESERVE_ENVELOPPE
_SECTIONS_DU_BRIEFING = ["decisions_en_attente", "alertes_m8", "faits_veille"]


def _fenetre_alertes_jours() -> int:
    """`department.yaml/configuration.fenetre_alertes_jours` : nombre de jours d'alertes M8 relus par le
    briefing (une alerte de mesure porte l'instant du chantier, pas celui du matin). Absente ou invalide :
    0, le jour même — le comportement d'avant, jamais une fenêtre devinée."""
    donnees = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8")) or {}
    configuration = donnees.get("configuration")
    fenetre = configuration.get("fenetre_alertes_jours") if isinstance(configuration, dict) else None
    if isinstance(fenetre, bool) or not isinstance(fenetre, int) or fenetre < 0:
        return 0
    return fenetre


def _exiger_admin_pour_appareil() -> None:
    """Revérifie le rôle courant en transaction avant tout registre sensible, comme M8.

    La voie des agents/console sans identité d'appareil conserve ses permissions existantes.
    Un rôle admin dans un ancien jeton ne suffit pas : personne active et rôle encore porté.
    """
    appelante = contexte.identite_appelante()
    if appelante is None:
        return
    cnx = stockage.connexion_courante()
    personne = (
        identite.personne_active(cnx, appelante.personne) if cnx is not None and appelante.role == "admin" else None
    )
    if personne is None or "admin" not in personne.roles:
        raise ValueError(
            "REJ-IDENTITE-APPAREIL-INVALIDE : les lectures M9 sont réservées à l'admin authentifié "
            "(personne active portant encore le rôle admin)"
        )


def valider_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return depuis_couple(validation.valider_snapshot(snapshot))


def valider_rapport_strategique(rapport: dict[str, Any]) -> dict[str, Any]:
    return depuis_couple(rapport_strategique.valider_rapport_strategique(rapport))


# ---------------------------------------------------------------------------
# Bus d'événements (ADR-0009 §3, PLAN T3.2) : consommateur de m8.alerte_proposee
# ---------------------------------------------------------------------------
def _recevoir_alerte_proposee(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m8.alerte_proposee` (ADR-0009 §3, PLAN T3.2) : enregistre au registre durable
    des alertes M8 reçues par M9 (`stockage.maillons("m09-strategic-intelligence", "alertes_m8")`,
    même table que celle relue par `m9_lire_alertes_m8`/`m9_produire_briefing_matin`) — préférence
    explicite du PLAN pour un événement publié plutôt qu'une lecture directe du registre M8.

    Idempotent par `evenement_id` (même patron que `m8_analytics.outils._recevoir_travaux_termines`
    pour `wct_id`) : une relivraison (relivraison de l'événement, ou `repartir()` rejoué) n'ajoute
    jamais un second maillon — no-op qui rend `deja_recue=True`.
    """
    alertes_cible = stockage.maillons("m09-strategic-intelligence", "alertes_m8")
    evenement_id = charge["evenement_id"]
    for existante in alertes_cible:
        if existante["evenement_id"] == evenement_id:
            return {"enregistree": False, "deja_recue": True, "evenement_id": evenement_id}
    alertes_cible.append(dict(charge))
    return {"enregistree": True, "deja_recue": False, "evenement_id": evenement_id}


def consommateurs() -> dict[str, Any]:
    """Types d'événements consommés par M9 (ADR-0009 §3) — voir `department.yaml:evenements.consomme`
    et `docs/architecture/DEPARTEMENTS.md` § Événements."""
    return {"m8.alerte_proposee": _recevoir_alerte_proposee}


def outils(
    registre_cible: registre.RegistreSnapshots | None = None,
    alertes_cible: Any = None,
) -> tuple[Outil, ...]:
    """Capacités exposées aux agents. Une instance de RegistreSnapshots par installation.

    `registre_cible` : `None` (défaut, utilisé par `charger_outils()` en production) adosse le
    registre au stockage durable de l'instance ; un `registre.RegistreSnapshots()` explicite
    (tests) reste en mémoire, jamais touché à la base.

    `alertes_cible` (T3.2) : même patron pour le registre durable des alertes M8 reçues — `None`
    (défaut) l'adosse à `opsys.stockage.maillons("m09-strategic-intelligence", "alertes_m8")` ;
    une `list` explicite (tests) reste en mémoire.
    """
    maillons_snapshots = None
    if registre_cible is None:
        maillons_snapshots = stockage.maillons("m09-strategic-intelligence", "snapshots")
        registre_cible = registre.RegistreSnapshots(
            maillons=maillons_snapshots
        )
    if alertes_cible is None:
        alertes_cible = stockage.maillons("m09-strategic-intelligence", "alertes_m8")

    def exiger_chaine_snapshots_valide() -> registre.RegistreSnapshots:
        """Valide une copie par appel, réutilisable sans relire la source durable.

        Une altération après validation ne peut pas changer les faits restitués.
        Aucun cache entre appels ni réparation d'une source rompue ou illisible.
        """
        try:
            copie = registre.RegistreSnapshots(registre_cible.lire())
            valide, _ = copie.valider_chaine()
        except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
            valide = False
        if valide is not True:
            raise ValueError(
                "REJ-SNAPSHOT-CHAINE-INVALIDE : registre M9 de snapshots invalide ; "
                "faire vérifier la source avant lecture ou ajout"
            )
        return copie

    def lire_etat_consolide() -> dict[str, Any]:
        """État consolidé courant par relecture pure du registre — n'ingère rien de nouveau."""
        _exiger_admin_pour_appareil()
        copie = exiger_chaine_snapshots_valide()
        return etat_consolide_module.construire_etat_consolide(copie)

    def etat_consolide(snapshot: dict[str, Any]) -> dict[str, Any]:
        """Chaîne complète : validation → écriture registre → état consolidé.

        Bloque avant d'écrire si le snapshot est structurellement refusé (etape="validation").
        L'état consolidé retourné porte toujours `contradictions` (même liste vide) : une
        contradiction interne n'est jamais résolue automatiquement, seulement nommée.
        """
        _exiger_admin_pour_appareil()
        valide, verdict = validation.valider_snapshot(snapshot)
        if not valide:
            return {"etape": "validation", "accepte": False, "verdict": verdict}

        copie = exiger_chaine_snapshots_valide()
        if maillons_snapshots is not None:
            maillon, _ = copie.ajouter(snapshot)
            # Un append intercalé invalide le rang calculé, sans changer le
            # contrat natif d'annulation/rejeu de l'écriture concurrente.
            maillons_snapshots.append(maillon, rang_attendu=maillon["index"])
            etat = etat_consolide_module.construire_etat_consolide(copie)
        else:
            registre_cible.ajouter(snapshot)
            etat = etat_consolide_module.construire_etat_consolide(registre_cible)
        return {"etape": "complet", "accepte": True, "etat_consolide": etat}

    def lire_alertes_m8(depart: int = 0) -> dict[str, Any]:
        """Alertes M8 déjà reçues (`m8.alerte_proposee`), sans filtre — relecture pure, n'ingère
        rien de nouveau (même esprit que `lire_etat_consolide`). BORNÉE (T1.5-d) : une page à la fois, le
        plus récent d'abord, sous la limite de sortie du socle ; `depart` reprend à `prochain_depart`."""
        _exiger_admin_pour_appareil()
        return lecture_alertes.lire_alertes_m8(
            [dict(alerte) for alerte in alertes_cible], depart, budget_caracteres=BUDGET_SORTIE,
        )

    def sources_du_briefing() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Les trois sources déjà à jour, relues sans rien écrire : file du propriétaire, alertes M8 reçues
        par le bus, faits consolidés par M9. `stockage.transaction()` réutilise la transaction déjà ouverte
        par `executer_atomique` (ADR-0009) ou en ouvre une nouvelle si appelée hors de tout outil.

        La file est lue EN ENTIER : `file_proprietaire` borne par défaut à 100 demandes, les plus récentes,
        ce qui aurait écarté en silence les plus anciennes — les plus urgentes — au-delà de 100."""
        copie = exiger_chaine_snapshots_valide()
        with stockage.transaction() as cnx:
            en_attente = approbations.compter(cnx, "en_attente")
            decisions = approbations.file_proprietaire(cnx, charger_departements(), limite=max(en_attente, 1))
        alertes = [dict(alerte) for alerte in alertes_cible]
        return decisions, alertes, copie.lire()

    def produire_briefing_matin(maintenant: str) -> dict[str, Any]:
        """Assemble le briefing du matin pour `maintenant` (RFC 3339, fourni par l'appelant — jamais
        l'horloge, T3.2) : file du propriétaire (`opsys.approbations.file_proprietaire`, TOUS les
        départements installés), alertes M8 déjà reçues par le bus, faits déjà consolidés par M9 pour la
        veille — relecture pure des trois sources, aucune ingestion, aucune écriture (T0).

        Borné sous la limite de sortie du socle (T1.5-d) : ce qui ne tient pas est compté dans `affichage`
        et se lit par `m9_lire_suite_briefing`."""
        _exiger_admin_pour_appareil()
        decisions, alertes, faits = sources_du_briefing()
        return briefing_matin.assembler_briefing_matin(
            maintenant, decisions, alertes, faits,
            budget_caracteres=BUDGET_SORTIE, fenetre_alertes_jours=_fenetre_alertes_jours(),
        )

    def lire_suite_briefing(maintenant: str, section: str, depart: int = 0) -> dict[str, Any]:
        """La suite d'une section du briefing à partir de `depart` (T1.5-d) : mêmes sources, même filtre,
        même ordre que `produire_briefing_matin`, une page bornée à la fois."""
        _exiger_admin_pour_appareil()
        decisions, alertes, faits = sources_du_briefing()
        return briefing_matin.lire_suite_section(
            maintenant, section, depart, decisions, alertes, faits,
            budget_caracteres=BUDGET_SORTIE, fenetre_alertes_jours=_fenetre_alertes_jours(),
        )

    def produire_lecture_strategique(maintenant: str, depart: int = 0) -> dict[str, Any]:
        """Lecture stratégique des alertes de mesure de M8 (T1.5-d) : preuves citées, décision au
        propriétaire, jamais prise par M9. Relecture pure du registre d'alertes reçues (T0)."""
        _exiger_admin_pour_appareil()
        return lecture_strategique.assembler_lecture_strategique(
            maintenant, [dict(alerte) for alerte in alertes_cible],
            fenetre_alertes_jours=_fenetre_alertes_jours(), depart=depart, budget_caracteres=BUDGET_SORTIE,
        )

    def lister_demandes_approbation(
        limite: int = approbations_appareil.LIMITE_LISTE_DEFAUT, decalage_attentes: int = 0,
    ) -> dict[str, Any]:
        """Demandes d'approbation en attente, pour l'app du propriétaire (T1.4-f). L'identité vient du
        contexte authentifié, jamais des arguments (`opsys.approbations_appareil`). Lecture seule.
        `decalage_attentes` : rang de la première attente rendue (T1.5-e), donné par `attentes_suivant`."""
        with stockage.transaction() as cnx:
            return depuis_couple(approbations_appareil.lister_demandes(
                cnx, charger_departements(), contexte.identite_appelante(), limite=limite,
                decalage_attentes=decalage_attentes))

    def decider_demande_approbation(demande_id: str, decision: str, motif: str = "") -> dict[str, Any]:
        """Approuve ou refuse une demande, au nom de la personne authentifiée de l'appareil (T1.4-f). Le
        signataire et l'appareil viennent du contexte de l'appel (`_meta`), jamais des arguments."""
        reception = contexte.horodatage_reception()
        with stockage.transaction() as cnx:
            return depuis_couple(approbations_appareil.decider_demande(
                cnx, charger_departements(), contexte.identite_appelante(), demande_id, decision, motif,
                appareil=reception.appareil if reception is not None else None))

    return (
        Outil(
            nom="m9_etat_consolide",
            description=(
                "Ingère un snapshot (validation puis écriture au registre) et reconstruit "
                "l'état consolidé de bout en bout — dernier fait connu par module (comparaison "
                "chronologique, fuseaux compris), contradictions internes détectées. Bloque "
                "avant d'écrire si le snapshot est structurellement refusé."
            ),
            parametres={
                "type": "object",
                "properties": {"snapshot": _SNAPSHOT},
                "required": ["snapshot"],
                "additionalProperties": False,
            },
            fonction=etat_consolide,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m9_lire_etat_consolide",
            description=(
                "Reconstruit l'état consolidé courant par relecture pure du registre, sans "
                "ingérer de nouveau snapshot."
            ),
            parametres={"type": "object", "properties": {}, "additionalProperties": False},
            fonction=lire_etat_consolide,
            # §7 M9 mobile : « Admin/Nathan seulement » (décisions en attente).
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_valider_snapshot",
            description=(
                "Valide la structure d'un SnapshotModule (module_source, horodatage, valeurs "
                "toujours en texte), sans l'écrire au registre."
            ),
            parametres={
                "type": "object",
                "properties": {"snapshot": _SNAPSHOT},
                "required": ["snapshot"],
                "additionalProperties": False,
            },
            fonction=valider_snapshot,
        ),
        Outil(
            nom="m9_valider_rapport_strategique",
            description=(
                "Valide qu'un rapport stratégique porte EXACTEMENT les 15 clés attendues "
                "(structure seulement, jamais la pertinence du contenu — v1 n'a pas de Council)."
            ),
            parametres={
                "type": "object",
                "properties": {"rapport": _RAPPORT_STRATEGIQUE},
                "required": ["rapport"],
                "additionalProperties": False,
            },
            fonction=valider_rapport_strategique,
        ),
        Outil(
            nom="m9_lire_alertes_m8",
            description=(
                "Alertes proposées par M8 déjà reçues via le bus (m8.alerte_proposee), sans filtre de date — "
                "relecture pure du registre durable des alertes M9, n'ingère rien. Le plus récent d'abord "
                "(à instant égal, par identifiant d'événement). Bornée : rend autant d'alertes que la limite "
                "de sortie en laisse tenir, avec `total`, `reste` et `prochain_depart` (nul à la fin) ; quand "
                "`prochain_depart` n'est pas nul, rappeler avec `depart` égal à cette valeur. Un `depart` "
                "qui n'est pas un entier ≥ 0, ou au-delà de la fin, est refusé : reprendre à 0."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "depart": {
                        "type": "integer", "minimum": 0,
                        "description": "Rang de la première alerte rendue (0 = la plus récente, défaut) : "
                                       "reprendre à la valeur de `prochain_depart` de la page précédente.",
                    },
                },
                "additionalProperties": False,
            },
            fonction=lire_alertes_m8,
            # §7 M9 mobile : « Admin/Nathan seulement » (alertes critiques).
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_produire_briefing_matin",
            description=(
                "Assemble le briefing du matin (décisions en attente de la file du propriétaire, "
                "alertes M8 du jour, faits du bus consolidés la veille, manques) pour un instant "
                "de référence fourni — relecture pure de trois sources déjà à jour, aucune "
                "ingestion, aucun chiffre ni texte inventé ; une section sans donnée est déclarée "
                "vide, jamais remplie."
            ),
            parametres={
                "type": "object",
                "properties": {"maintenant": _MAINTENANT},
                "required": ["maintenant"],
                "additionalProperties": False,
            },
            fonction=produire_briefing_matin,
            # §7 M9 mobile : « Admin/Nathan seulement » (briefing du matin).
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_lire_suite_briefing",
            description=(
                "Lit la suite d'une section du briefing du matin quand celui-ci annonce « N autres éléments non "
                "affichés » : reprend à `depart` (indice dans la section, donné par `lire_la_suite`), autant "
                "d'éléments que la limite de sortie en laisse tenir, et rend `prochain_depart` (nul à la fin). "
                "Mêmes sources et même ordre que `m9_produire_briefing_matin` ; relecture pure, rien n'est écrit."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "maintenant": _MAINTENANT,
                    "section": {"type": "string", "enum": _SECTIONS_DU_BRIEFING},
                    "depart": {"type": "integer", "description": "Indice de départ dans la section (0 = début)."},
                },
                "required": ["maintenant", "section"],
                "additionalProperties": False,
            },
            fonction=lire_suite_briefing,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_produire_lecture_strategique",
            description=(
                "Lecture stratégique des alertes de mesure de chantier terminé proposées par M8 (temps réel contre "
                "prévu, marge, matériaux) reçues dans la fenêtre du briefing : chaque lecture cite ses preuves "
                "(métrique M8, version de sa définition, chantier, valeur, seuil, événement) et l'action que M8 "
                "propose. M9 ne décide pas : `decision.prise_par_m9` est faux, la décision revient au propriétaire. "
                "Les seuils à configurer sont des manques. Bornée ; `depart` reprend à la lecture suivante. "
                "Relecture pure."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "maintenant": _MAINTENANT,
                    "depart": {"type": "integer", "description": "Indice de la première lecture rendue (0 = début)."},
                },
                "required": ["maintenant"],
                "additionalProperties": False,
            },
            fonction=produire_lecture_strategique,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_lister_demandes_approbation",
            description=(
                "Liste les demandes d'approbation EN ATTENTE du socle, la plus ancienne d'abord, pour l'app "
                "du propriétaire : département, outil, niveau N, arguments exacts (donnée personnelle "
                "masquée), et si la demande se décide depuis l'app ou seulement à la console (N5, outil "
                "T3, arguments trop gros). La personne vient de l'identité authentifiée de l'appareil, "
                "jamais d'un argument ; sans elle, refus. Un `admin` qui n'est pas le propriétaire "
                "voit la file sans les arguments. Rend aussi les attentes des départements (complétion "
                "en revue avec écart de matériaux critique, facture prête à envoyer, chantier à "
                "réviser, besoin de commande) : informatives, elles ne se décident pas ici. Elles se "
                "lisent par pages bornées, la plus ancienne d'abord : quand `attentes_suivant` n'est pas "
                "nul, le rappeler avec `decalage_attentes` égal à cette valeur. Réservé à l'humain : "
                "l'agent M9 ne l'appelle pas."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "limite": {
                        "type": "integer", "minimum": 1, "maximum": approbations_appareil.LIMITE_LISTE_MAX,
                        "description": "Nombre maximal de demandes (défaut "
                                       f"{approbations_appareil.LIMITE_LISTE_DEFAUT}).",
                    },
                    "decalage_attentes": {
                        "type": "integer", "minimum": 0,
                        "description": "Rang de la première attente rendue (0 = la plus ancienne, défaut) : "
                                       "reprendre à la valeur de `attentes_suivant` de la page précédente. "
                                       "Au-delà de la fin : une page vide, jamais une erreur.",
                    },
                },
                "additionalProperties": False,
            },
            fonction=lister_demandes_approbation,
            # T0 : lecture pure, aucune écriture (même pas d'audit : rien n'est décidé).
            autonomie=Autonomie.T0,
            # §9.5 « Approbations » et §9.2 « le propriétaire approuve tout depuis le téléphone » : la file
            # elle-même. Admin seulement ; le propriétaire (personne) voit les arguments, l'admin non.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_decider_demande_approbation",
            description=(
                "Approuve ou refuse UNE demande d'approbation N3 ou N4 du socle, au nom du propriétaire "
                "authentifié de l'appareil, par le chemin de la console (mêmes vérifications, mêmes "
                "arguments exacts, même journal, plus l'appareil). Refuse sans identité de propriétaire, "
                "une demande N5 ou T3 (à la console), une demande déjà décidée. Idempotent par la clé de "
                "l'appel. Réservé à l'humain : l'agent M9 ne l'appelle jamais, et aucun paramètre ne "
                "désigne le décideur."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "demande_id": {"type": "string", "description": "Identifiant lu dans la liste."},
                    "decision": {"type": "string", "enum": list(approbations_appareil.DECISIONS)},
                    "motif": {
                        "type": "string",
                        "description": f"Note du propriétaire, facultative ({approbations_appareil.LIMITE_MOTIF} "
                                       "caractères au plus).",
                    },
                },
                "required": ["demande_id", "decision"],
                "additionalProperties": False,
            },
            fonction=decider_demande_approbation,
            # T1 (écriture interne : le registre d'approbation) mais N2, et non le N3 par défaut : cet outil
            # EST la décision humaine. Le mettre lui-même en attente d'une approbation serait circulaire
            # (le mode ombre le renverrait dans la file qu'il sert à vider) ; sa garde est ailleurs, dans
            # l'identité du propriétaire, le plafond N3/N4 et la portée du rôle (`approbations_appareil`).
            # Même choix que `m4_deposer_fichier`.
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
            # §9.5 et §9.2 : le propriétaire approuve depuis son téléphone. Admin seulement ; la PERSONNE doit
            # de plus être le propriétaire (`nathan_owner`), sinon refus nommé et trace d'audit.
            roles_appareil=frozenset({"admin"}),
        ),
    )
