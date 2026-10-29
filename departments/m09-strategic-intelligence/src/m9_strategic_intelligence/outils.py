"""Capacités d'agent du département M9 Strategic Intelligence.

M9 v1 est un harnais déterministe pur (PRD §0/§3.1) : aucun Council d'agents, aucun contenu
délibératif — il agrège les snapshots que les autres modules lui rapportent dans un état
consolidé (Business State Graph) et signale les contradictions internes, sans jamais inventer
ni recommander. `m9_etat_consolide` compose ingestion → écriture au registre → construction de
l'état consolidé (contradictions comprises) en un seul appel.

Le suivi interne enregistre une décision humaine dédiée avec responsable, échéance et preuve
M8 historique exacte ; il ne recommande ni n'exécute l'action et n'en déclare pas la complétion.
Sa clôture par revue humaine s'ajoute une seule fois au registre distinct `clotures_suivi_decisions`
sous sa propre demande N3 ; le plan d'origine reste intact. Elle n'atteste ni action terrain, ni
cause, amélioration ou fraîcheur. `m9_lister_suivis_decision` (M9.16) liste par pages bornées les suivis
encore ouverts, par échéance face à une référence explicite (`echeancier_suivis`, module pur) ; une reprise
exige la `vue` courante de tous les plans, clôtures et de la référence.

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

Faits de chantier (`m8.snapshot_chantier`, `_recevoir_snapshot_chantier`) : le premier snapshot WCT durable
de M8, enregistré après activation du transport, arrive par le bus et s'ajoute au registre de snapshots M9,
instant métier d'origine conservé. Confiance limitée : identifiant lié à l'empreinte et à la première enveloppe publiée,
jamais une authentification de M8, une couverture M1-M8, un instant de réception ni un rattrapage.
`m9_observations_chantier_periode` relit ces faits par période [debut, fin) (`observations_chantier`, module
pur) : registre complet validé, puis la première publication de chaque snapshot qui se déclare transporté,
hors période comprise, validée contre le catalogue ; rien n'est écrit, aucun consommateur n'est rappelé.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from opsys import approbations, approbations_appareil, contexte, evenements, identite, jetons, stockage
from opsys.departements import charger_departements
from opsys.evenements import schemas
from opsys.outils import Autonomie, Niveau, Outil, depuis_couple

from . import (
    audit_affirmations,
    bilan_suivis,
    briefing_matin,
    contrats,
    diagnostic_temporel,
    dossier_direction,
    echeancier_suivis,
    lecture_alertes,
    lecture_strategique,
    observations_chantier,
    outils_actions,
    outils_cadrage_decision,
    outils_conseil,
    outils_direction,
    outils_experiences,
    outils_graphe,
    outils_memoire,
    outils_metriques_executives,
    outils_plans,
    outils_playbooks,
    outils_previsions,
    outils_priorites,
    outils_questions_scenario,
    outils_radars,
    outils_semantique,
    outils_tendances,
    outils_tissu,
    outils_veille,
    rapport_activite,
    rapport_periode,
    rapport_strategique,
    registre,
    suivi_decisions,
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


# ---------------------------------------------------------------------------
# Bus d'événements : consommateur de m8.snapshot_chantier (premier snapshot WCT durable de M8)
# ---------------------------------------------------------------------------
_EVENEMENT_SNAPSHOT_CHANTIER = "m8.snapshot_chantier"
_PREFIXE_SNAPSHOT_CHANTIER = "m8-snapshot-chantier-"
_MODULE_SOURCE_TRAVAUX = "m04-field-ops"
_ID_SNAPSHOT_CHANTIER = re.compile(re.escape(_PREFIXE_SNAPSHOT_CHANTIER) + r"[0-9a-f]{64}")


def _refus_snapshot_chantier(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _horodatage_avec_fuseau(texte: str) -> bool:
    """Vrai si `texte` est un instant ISO 8601 à fuseau explicite (`Z` ou décalage). Analyse stdlib
    seulement, jamais l'horloge : la chaîne d'origine reste celle qui est enregistrée."""
    try:
        instant = datetime.fromisoformat(texte[:-1] + "+00:00" if texte.endswith("Z") else texte)
    except ValueError:
        return False
    return instant.tzinfo is not None and instant.utcoffset() is not None


def _copie_snapshots_valide(maillons) -> registre.RegistreSnapshots:
    """Une seule lecture native du registre M9, validée (chaîne et rangs) avant toute recherche ou
    ajout ; calquée sur la fermeture `exiger_chaine_snapshots_valide`, inaccessible hors `outils()`."""
    try:
        copie = registre.RegistreSnapshots(maillons=registre.RegistreSnapshots(maillons).lire())
        valide, _ = copie.valider_chaine()
        valide = valide and all(
            type(maillon["index"]) is int and maillon["index"] == index
            for index, maillon in enumerate(copie.lire())
        )
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        valide = False
    if valide is not True:
        raise _refus_snapshot_chantier(
            "REJ-SNAPSHOT-CHAINE-INVALIDE", "registre M9 de snapshots invalide ; vérifier la source avant ajout"
        )
    return copie


def _recevoir_snapshot_chantier(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m8.snapshot_chantier` : range au registre durable des snapshots M9 le premier
    snapshot WCT que M8 a enregistré, sans lire M8 ni son stockage. Tout refus est une `ValueError`
    levée AVANT l'unique append final : rien n'est écrit.

    Preuve vérifiée, et seulement elle : l'identifiant déclaré est lié à l'empreinte déclarée et nomme la
    première enveloppe immuable du bus de ce type, portant exactement cette charge. Ni authentification
    du producteur, ni revérification contre la chaîne M8, ni instant de réception. Idempotent par
    identifiant et par `m4_wct_id` : même fait = no-op ; fait différent = refus (le premier durable gagne).
    """
    if schemas.erreurs_charge(_EVENEMENT_SNAPSHOT_CHANTIER, charge):
        raise _refus_snapshot_chantier("REJ-SNAPSHOT-CHANTIER-CHARGE", "charge non conforme au schéma du catalogue")
    evenement_id = charge["evenement_id"]
    source = charge["source_m8"]
    fait = charge["snapshot"]
    if type(source["index"]) is not int:
        raise _refus_snapshot_chantier("REJ-SNAPSHOT-CHANTIER-CHARGE", "index source M8 non entier")
    if not _horodatage_avec_fuseau(fait["horodatage"]):
        raise _refus_snapshot_chantier(
            "REJ-SNAPSHOT-CHANTIER-HORODATAGE", "instant métier ISO 8601 avec fuseau explicite (Z ou décalage) requis"
        )
    if evenement_id != _PREFIXE_SNAPSHOT_CHANTIER + source["hash_maillon"]:
        raise _refus_snapshot_chantier("REJ-SNAPSHOT-CHANTIER-SOURCE", "identifiant non lié à l'empreinte déclarée")
    if evenements.charge_publiee(_EVENEMENT_SNAPSHOT_CHANTIER, evenement_id) != charge:
        raise _refus_snapshot_chantier(
            "REJ-SNAPSHOT-CHANTIER-SOURCE", "aucune première publication de ce type portant exactement cette charge"
        )

    wct_id = fait["valeurs"]["m4_wct_id"]
    snapshot = {
        "module_source": fait["module_source"],
        "horodatage": fait["horodatage"],
        "valeurs": dict(fait["valeurs"]) | {
            "m8_snapshot_evenement_id": evenement_id,
            "m8_snapshot_index": str(source["index"]),
            "m8_snapshot_hash_maillon": source["hash_maillon"],
        },
    }

    maillons = stockage.maillons("m09-strategic-intelligence", "snapshots")
    copie = _copie_snapshots_valide(maillons)
    for existant in copie.lire():
        valeurs = existant["valeurs"]
        if existant["module_source"] != _MODULE_SOURCE_TRAVAUX or "m8_snapshot_evenement_id" not in valeurs:
            continue
        if valeurs["m8_snapshot_evenement_id"] != evenement_id and valeurs.get("m4_wct_id") != wct_id:
            continue
        if existant["horodatage"] == snapshot["horodatage"] and valeurs == snapshot["valeurs"]:
            return {"enregistre": False, "deja_recu": True, "evenement_id": evenement_id, "wct_id": wct_id}
        raise _refus_snapshot_chantier(
            "REJ-SNAPSHOT-CHANTIER-CONTRADICTOIRE",
            "un snapshot transporté différent existe déjà pour cet événement ou ce WCT ; aucune réécriture",
        )

    valide, verdict = validation.valider_snapshot(snapshot)
    if not valide:
        raise _refus_snapshot_chantier("REJ-SNAPSHOT-CHANTIER-CHARGE", f"snapshot M9 refusé ({verdict})")
    maillon, _ = copie.ajouter(snapshot)
    # Un append intercalé invalide le rang lu : la transaction du répartiteur annule, l'événement est rejoué.
    maillons.append(maillon, rang_attendu=maillon["index"])
    return {"enregistre": True, "deja_recu": False, "evenement_id": evenement_id, "wct_id": wct_id}


def consommateurs() -> dict[str, Any]:
    """Types d'événements consommés par M9 (ADR-0009 §3) — voir `department.yaml:evenements.consomme`
    et `docs/architecture/DEPARTEMENTS.md` § Événements."""
    return {
        "m8.alerte_proposee": _recevoir_alerte_proposee,
        _EVENEMENT_SNAPSHOT_CHANTIER: _recevoir_snapshot_chantier,
    }


def outils(
    registre_cible: registre.RegistreSnapshots | None = None,
    alertes_cible: Any = None,
    *,
    lecteur_producteurs_m9: Any = None,
    proposeur_actions_m9: Any = None,
    captures_cible: Any = None,
    sessions_cible: Any = None,
    publications_cible: Any = None,
    veille_cible: Any = None,
    plans_cible: Any = None,
    experiences_cible: Any = None,
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

    def preparer_suivi_decision(evenement_id: str) -> dict[str, Any]:
        _exiger_admin_pour_appareil()
        source = suivi_decisions.preparer_source(alertes_cible, evenement_id)
        return suivi_decisions.borner({"accepte": True, "source": source}, BUDGET_SORTIE)

    def ouvrir_suivi_decision(
        evenement_id: str, empreinte_source: str, action: str, responsable_id: str, echeance: str,
    ) -> dict[str, Any]:
        # Le mandat est CETTE demande en cours et son propriétaire SQL courant.
        # Un rôle de jeton, une ingestion approuvée ou un appel direct ne le remplace pas.
        cnx = stockage.connexion_courante()
        approbateur = approbations.approbateur_en_cours(
            cnx, "m9_ouvrir_suivi_decision", "m09-strategic-intelligence",
            roles=frozenset({"nathan_owner"}),
        )
        if approbateur is None:
            return {"accepte": False, "verdict": {"code": "REJ-SUIVI-APPROBATION",
                    "detail": "Demande dédiée approuvée par le propriétaire encore actif requise"}}
        try:
            responsable = identite.personne_active(cnx, responsable_id)
            roles_internes = identite.ROLES - {"client", "system_agent"}
            if responsable is None or not responsable.roles.intersection(roles_internes):
                raise ValueError("REJ-SUIVI-RESPONSABLE : personne interne active requise")
            source = suivi_decisions.preparer_source(alertes_cible, evenement_id)
            demande_id = contexte.demande_approuvee_en_cours()
            demande = approbations.lire(cnx, demande_id)
            suivi = suivi_decisions.construire(
                source=source, empreinte_source=empreinte_source, action=action,
                responsable_id=responsable_id, echeance=echeance,
                demande_id=demande_id,
                decide_par=approbateur.personne, decide_role=approbateur.role,
                decide_le=demande["decide_le"],
            )
            resultat = suivi_decisions.borner({"accepte": True, "suivi": suivi}, BUDGET_SORTIE)
        except ValueError as exc:
            code, _, message = str(exc).partition(" : ")
            return {"accepte": False, "verdict": {"code": code, "detail": message}}
        suivis = stockage.maillons("m09-strategic-intelligence", "suivi_decisions")
        if any(s.get("suivi_id") == suivi["suivi_id"] for s in suivis):
            return {"accepte": False, "verdict": {"code": "REJ-SUIVI-DEJA-OUVERT"}}
        suivis.append(suivi)
        return resultat

    def lire_suivi_decision(suivi_id: str) -> dict[str, Any]:
        _exiger_admin_pour_appareil()
        suivi_decisions.texte(suivi_id, "suivi_id", 1024)
        suivis = stockage.maillons("m09-strategic-intelligence", "suivi_decisions")
        trouves = [s for s in suivis if s.get("suivi_id") == suivi_id]
        if len(trouves) != 1:
            return {"accepte": False, "verdict": {"code": "REJ-SUIVI-INTROUVABLE-OU-AMBIGU"}}
        cloture = suivi_decisions.trouver_cloture(
            stockage.maillons("m09-strategic-intelligence", "clotures_suivi_decisions"), suivi_id)
        return suivi_decisions.borner(suivi_decisions.projeter(trouves[0], cloture), BUDGET_SORTIE)

    def lister_suivis_decision(
        horodatage_reference: str, depart: int = 0, vue_attendue: str | None = None,
    ) -> dict[str, Any]:
        # Rôle SQL courant revérifié avant les registres ; plans et clôtures lus dans la même transaction.
        _exiger_admin_pour_appareil()
        suivis = list(stockage.maillons("m09-strategic-intelligence", "suivi_decisions"))
        clotures = list(stockage.maillons("m09-strategic-intelligence", "clotures_suivi_decisions"))
        return echeancier_suivis.lister_suivis_decision(
            suivis, clotures, horodatage_reference, depart, vue_attendue, budget_caracteres=BUDGET_SORTIE,
        )

    def bilan_suivis_decision(
        debut: str, fin: str, depart: int = 0, vue_attendue: str | None = None,
    ) -> dict[str, Any]:
        # Même garde que l'échéancier : rôle SQL revérifié, tous les plans et clôtures lus dans la même transaction.
        _exiger_admin_pour_appareil()
        suivis = list(stockage.maillons("m09-strategic-intelligence", "suivi_decisions"))
        clotures = list(stockage.maillons("m09-strategic-intelligence", "clotures_suivi_decisions"))
        return bilan_suivis.bilan_suivis_decision(
            suivis, clotures, debut, fin, depart, vue_attendue, budget_caracteres=BUDGET_SORTIE,
        )

    def lire_rapport_periode(
        debut: str, fin: str, depart: int = 0, vue_attendue: str | None = None,
    ) -> dict[str, Any]:
        # Rôle SQL revérifié avant les trois registres, lus dans la même transaction ; ni file ni état courant.
        _exiger_admin_pour_appareil()
        suivis = list(stockage.maillons("m09-strategic-intelligence", "suivi_decisions"))
        clotures = list(stockage.maillons("m09-strategic-intelligence", "clotures_suivi_decisions"))
        alertes = list(alertes_cible)
        # Schéma du catalogue sur CHAQUE alerte reçue, hors période comprise, avant tout filtre.
        for rang, alerte in enumerate(alertes):
            if schemas.erreurs_charge("m8.alerte_proposee", alerte):
                raise ValueError(
                    f"REJ-RAPPORT-ALERTE : alerte M8 reçue de rang {rang} non conforme au schéma m8.alerte_proposee"
                )
        return rapport_periode.assembler_rapport_periode(
            suivis, clotures, [dict(alerte) for alerte in alertes], debut, fin, depart, vue_attendue,
            budget_caracteres=BUDGET_SORTIE,
        )

    def preparer_cloture_suivi_decision(suivi_id: str, evenement_id: str) -> dict[str, Any]:
        _exiger_admin_pour_appareil()
        plan = suivi_decisions.trouver_plan(
            stockage.maillons("m09-strategic-intelligence", "suivi_decisions"), suivi_id)
        cloture = suivi_decisions.trouver_cloture(
            stockage.maillons("m09-strategic-intelligence", "clotures_suivi_decisions"), suivi_id)
        preparation = suivi_decisions.preparer_cloture(plan, cloture, alertes_cible, evenement_id)
        return suivi_decisions.borner({"accepte": True, "suivi_id": suivi_id} | preparation, BUDGET_SORTIE)

    def clore_suivi_decision(
        suivi_id: str, empreinte_suivi: str, evenement_id: str, empreinte_preuve: str, bilan: str,
    ) -> dict[str, Any]:
        # Même mandat que l'ouverture : CETTE demande de clôture en cours et son propriétaire SQL courant.
        # L'approbation d'ouverture, un appel direct ou une ancienne demande ne le remplacent pas.
        cnx = stockage.connexion_courante()
        approbateur = approbations.approbateur_en_cours(
            cnx, "m9_clore_suivi_decision", "m09-strategic-intelligence",
            roles=frozenset({"nathan_owner"}),
        )
        if approbateur is None:
            return {"accepte": False, "verdict": {"code": "REJ-SUIVI-APPROBATION",
                    "detail": "Demande dédiée de clôture approuvée par le propriétaire encore actif requise"}}
        clotures = stockage.maillons("m09-strategic-intelligence", "clotures_suivi_decisions")
        try:
            # Plan, clôtures et preuve relus au point d'effet ; les deux empreintes approuvées sont revérifiées.
            plan = suivi_decisions.trouver_plan(
                stockage.maillons("m09-strategic-intelligence", "suivi_decisions"), suivi_id)
            existantes = list(clotures)
            preparation = suivi_decisions.preparer_cloture(
                plan, suivi_decisions.trouver_cloture(existantes, suivi_id), alertes_cible, evenement_id)
            demande_id = contexte.demande_approuvee_en_cours()
            demande = approbations.lire(cnx, demande_id)
            cloture = suivi_decisions.construire_cloture(
                plan=plan, preparation=preparation, empreinte_suivi=empreinte_suivi,
                empreinte_preuve=empreinte_preuve, bilan=bilan, demande_id=demande_id,
                decide_par=approbateur.personne, decide_role=approbateur.role,
                decide_le=demande["decide_le"],
            )
            # La lecture ultérieure rend plan et clôture ensemble : la borne entière est vérifiée avant append.
            resultat = suivi_decisions.borner(suivi_decisions.projeter(plan, cloture), BUDGET_SORTIE)
        except ValueError as exc:
            code, _, message = str(exc).partition(" : ")
            return {"accepte": False, "verdict": {"code": code, "detail": message}}
        # Un append concurrent intercalé invalide le rang lu : aucune seconde clôture sur un instantané périmé.
        clotures.append(cloture, rang_attendu=len(existantes))
        return resultat

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

    def lire_observations_chantier(
        debut: str, fin: str, depart: int = 0, vue_attendue: str | None = None,
    ) -> dict[str, Any]:
        # Rôle SQL revérifié avant le registre et le bus ; ni file, ni registre M8, ni horloge, aucune écriture.
        _exiger_admin_pour_appareil()
        faits = exiger_chaine_snapshots_valide().lire()
        if not all(
            isinstance(maillon, dict) and type(maillon.get("index")) is int and maillon["index"] == rang
            for rang, maillon in enumerate(faits)
        ):
            raise ValueError(
                "REJ-SNAPSHOT-CHAINE-INVALIDE : rangs du registre M9 de snapshots non entiers exacts ; "
                "faire vérifier la source avant lecture"
            )
        publications: dict[str, Any] = {}
        for maillon in faits:
            valeurs = maillon.get("valeurs")
            evenement_id = valeurs.get("m8_snapshot_evenement_id") if isinstance(valeurs, dict) else None
            # Identifiant non canonique, doublon ou publication absente : refus nommé par le module pur.
            if (not isinstance(evenement_id, str) or not _ID_SNAPSHOT_CHANTIER.fullmatch(evenement_id)
                    or evenement_id in publications):
                continue
            charge = evenements.charge_publiee(_EVENEMENT_SNAPSHOT_CHANTIER, evenement_id)
            if charge is None:
                continue
            # Schéma complet du catalogue sur CHAQUE publication liée, hors période comprise, avant tout filtre.
            if schemas.erreurs_charge(_EVENEMENT_SNAPSHOT_CHANTIER, charge):
                raise ValueError(
                    f"REJ-OBSERVATIONS-BUS-CHARGE : publication {evenement_id} non conforme au schéma "
                    f"{_EVENEMENT_SNAPSHOT_CHANTIER}"
                )
            publications[evenement_id] = charge
        return observations_chantier.lister_observations_chantier(
            faits, publications, debut, fin, depart, vue_attendue, budget_caracteres=BUDGET_SORTIE,
        )

    def lire_rapport_activite(
        debut: str, fin: str, depart: int = 0, vue_attendue: str | None = None,
    ) -> dict[str, Any]:
        # Rôle SQL revérifié avant le registre et le bus ; ni file, ni registre M8, ni horloge, aucune écriture.
        _exiger_admin_pour_appareil()
        suivis = list(stockage.maillons("m09-strategic-intelligence", "suivi_decisions"))
        clotures = list(stockage.maillons("m09-strategic-intelligence", "clotures_suivi_decisions"))
        alertes = list(alertes_cible)
        for rang, alerte in enumerate(alertes):
            if schemas.erreurs_charge("m8.alerte_proposee", alerte):
                raise ValueError(
                    f"REJ-RAPPORT-ALERTE : alerte M8 reçue de rang {rang} non conforme au schéma m8.alerte_proposee"
                )
        faits = exiger_chaine_snapshots_valide().lire()
        if not all(
            isinstance(maillon, dict) and type(maillon.get("index")) is int and maillon["index"] == rang
            for rang, maillon in enumerate(faits)
        ):
            raise ValueError(
                "REJ-SNAPSHOT-CHAINE-INVALIDE : rangs du registre M9 de snapshots non entiers exacts ; "
                "faire vérifier la source avant lecture"
            )
        publications: dict[str, Any] = {}
        identifiants_lus: set[str] = set()
        for maillon in faits:
            valeurs = maillon.get("valeurs")
            evenement_id = valeurs.get("m8_snapshot_evenement_id") if isinstance(valeurs, dict) else None
            # Identifiant non canonique, doublon ou publication absente : refus nommé par le module pur.
            if (not isinstance(evenement_id, str) or not _ID_SNAPSHOT_CHANTIER.fullmatch(evenement_id)
                    or evenement_id in identifiants_lus):
                continue
            identifiants_lus.add(evenement_id)
            charge = evenements.charge_publiee(_EVENEMENT_SNAPSHOT_CHANTIER, evenement_id)
            if charge is None:
                continue
            # Schéma complet du catalogue sur CHAQUE publication liée, hors période comprise, avant tout filtre.
            if schemas.erreurs_charge(_EVENEMENT_SNAPSHOT_CHANTIER, charge):
                raise ValueError(
                    f"REJ-OBSERVATIONS-BUS-CHARGE : publication {evenement_id} non conforme au schéma "
                    f"{_EVENEMENT_SNAPSHOT_CHANTIER}"
                )
            publications[evenement_id] = charge
        return rapport_activite.assembler_rapport_activite(
            suivis, clotures, alertes, faits, publications, debut, fin, depart, vue_attendue,
            budget_caracteres=BUDGET_SORTIE,
        )

    def lire_etat_consolide() -> dict[str, Any]:
        """État consolidé courant par relecture pure du registre — n'ingère rien de nouveau."""
        _exiger_admin_pour_appareil()
        copie = exiger_chaine_snapshots_valide()
        return etat_consolide_module.construire_etat_consolide(copie)

    def preparer_dossier_direction(question: str, modules_attendus: list[str]) -> dict[str, Any]:
        _exiger_admin_pour_appareil()
        copie = exiger_chaine_snapshots_valide()
        return dossier_direction.construire_dossier(
            copie, question, modules_attendus, budget_caracteres=BUDGET_SORTIE,
        )

    def auditer_affirmations_conseil(
        question: str, modules_attendus: list[str], dossier_attendu: str, affirmations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        _exiger_admin_pour_appareil()
        audit_affirmations._valider_demande(
            question, modules_attendus, dossier_attendu, affirmations, budget_caracteres=BUDGET_SORTIE,
        )
        # Capture serveur unique ; aucun dossier fourni librement par le client.
        dossier = preparer_dossier_direction(question, modules_attendus)
        return audit_affirmations.auditer_affirmations(
            dossier, dossier_attendu, affirmations, budget_caracteres=BUDGET_SORTIE,
        )

    def diagnostiquer_dossier_direction(
        question: str, modules_attendus: list[str], horodatage_reference: str,
    ) -> dict[str, Any]:
        # La provenance vient de cette capture serveur autorisée, jamais d'un dossier
        # fourni par l'appelant ni des empreintes non secrètes du diagnostic pur.
        dossier = preparer_dossier_direction(question, modules_attendus)
        diagnostic = diagnostic_temporel.diagnostiquer_dossier(
            dossier, horodatage_reference, budget_caracteres=BUDGET_SORTIE,
        )
        resultat = {"dossier": dossier, "diagnostic": diagnostic}
        if len(json.dumps(resultat, ensure_ascii=False, allow_nan=False)) > BUDGET_SORTIE:
            raise ValueError("REJ-DIAGNOSTIC-BORNE : dossier et diagnostic complets dépassent la borne")
        return resultat

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

    outils_base = (
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
            nom="m9_preparer_dossier_direction",
            description=(
                "Prépare un dossier historique sourcé pour une question de direction, sans "
                "valider de décision. Conserve les variantes contradictoires et signale les "
                "modules attendus absents ; refuse si les preuves complètes dépassent la borne."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "minLength": 1, "maxLength": 2048},
                    "modules_attendus": {
                        "type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 128},
                        "minItems": 1, "maxItems": 16, "uniqueItems": True,
                    },
                },
                "required": ["question", "modules_attendus"],
                "additionalProperties": False,
            },
            fonction=preparer_dossier_direction,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_auditer_affirmations_conseil",
            description="Compare un lot de citations textuelles structurées à un dossier serveur sélectionné "
                        "dont l'empreinte est attendue, ou conserve des hypothèses explicitement déclarées. "
                        "Refuse tout le lot si une citation diverge, si sa source est contradictoire ou si le "
                        "dossier a changé. Rend le dossier et toutes les affirmations admises, sans troncature. "
                        "Lecture pure : ni vérité métier, fraîcheur, modèle, conseil, décision "
                        "ni approbation attestés.",
            parametres={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "minLength": 1, "maxLength": 2048},
                    "modules_attendus": {
                        "type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 128},
                        "minItems": 1, "maxItems": 16, "uniqueItems": True,
                    },
                    "dossier_attendu": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "affirmations": {
                        "type": "array", "minItems": 1, "maxItems": 16,
                        "items": {"oneOf": [
                            {"type": "object", "properties": {
                                "id": {"type": "string", "minLength": 1, "maxLength": 128},
                                "nature": {"type": "string", "enum": ["observation_source"]},
                                "reference": {"type": "object", "properties": {
                                    "module_source": {"type": "string", "minLength": 1, "maxLength": 128},
                                    "index": {"type": "integer", "minimum": 0},
                                    "hash_maillon": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                                    "cle": {"type": "string", "minLength": 1, "maxLength": 128},
                                }, "required": ["module_source", "index", "hash_maillon", "cle"],
                                    "additionalProperties": False},
                                "valeur": {"type": "string", "maxLength": 2048},
                            }, "required": ["id", "nature", "reference", "valeur"], "additionalProperties": False},
                            {"type": "object", "properties": {
                                "id": {"type": "string", "minLength": 1, "maxLength": 128},
                                "nature": {"type": "string", "enum": ["hypothese"]},
                                "enonce": {"type": "string", "minLength": 1, "maxLength": 1024},
                            }, "required": ["id", "nature", "enonce"], "additionalProperties": False},
                        ]},
                    },
                },
                "required": ["question", "modules_attendus", "dossier_attendu", "affirmations"],
                "additionalProperties": False,
            },
            fonction=auditer_affirmations_conseil,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_diagnostiquer_dossier_direction",
            description=(
                "Prépare un dossier historique sourcé et compare ses observations à une référence "
                "horaire explicite avec fuseau. Signale les observations futures sans déduire "
                "l'actualité métier ; refuse si dossier, preuves et diagnostic ne tiennent pas entiers."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "minLength": 1, "maxLength": 2048},
                    "modules_attendus": {
                        "type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 128},
                        "minItems": 1, "maxItems": 16, "uniqueItems": True,
                    },
                    "horodatage_reference": {
                        "type": "string", "minLength": 1,
                        "description": "Référence ISO 8601 avec fuseau explicite, fournie par l'appelant.",
                    },
                },
                "required": ["question", "modules_attendus", "horodatage_reference"],
                "additionalProperties": False,
            },
            fonction=diagnostiquer_dossier_direction,
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
        Outil(
            nom="m9_preparer_suivi_decision",
            description="Relit une preuve M8 reçue et calcule son empreinte pour une demande de suivi. "
                        "Lecture pure ; preuve historique, couverture et actualité métier non évaluées.",
            parametres={"type": "object", "properties": {"evenement_id": {"type": "string"}},
                        "required": ["evenement_id"], "additionalProperties": False},
            fonction=preparer_suivi_decision,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_ouvrir_suivi_decision",
            description="Propose un suivi INTERNE planifié avec preuve M8 exacte, responsable et échéance explicites. "
                        "Seule sa demande dédiée approuvée par le propriétaire actif l'ouvre. "
                        "N'exécute pas l'action et n'atteste ni sa complétion ni l'actualité métier.",
            parametres={
                "type": "object",
                "properties": {champ: {"type": "string"} for champ in (
                    "evenement_id", "empreinte_source", "action", "responsable_id", "echeance")},
                "required": ["evenement_id", "empreinte_source", "action", "responsable_id", "echeance"],
                "additionalProperties": False,
            },
            fonction=ouvrir_suivi_decision, autonomie=Autonomie.T1, niveau=Niveau.N3,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_lire_suivi_decision",
            description="Relit un suivi interne et sa preuve historique par identifiant, avec sa clôture par revue "
                        "humaine éventuelle, sans mutation ni exécution. Une clôture ambiguë est refusée.",
            parametres={"type": "object", "properties": {"suivi_id": {"type": "string"}},
                        "required": ["suivi_id"], "additionalProperties": False},
            fonction=lire_suivi_decision,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_lister_suivis_decision",
            description="Liste les suivis internes encore ouverts (sans clôture par revue humaine), échéance la plus "
                        "proche d'abord puis par identifiant, chacun avec son plan complet, sa preuve, son empreinte "
                        "et son état face à la référence fournie : EN_RETARD, A_ECHEANCE ou A_VENIR. Lecture pure, "
                        "bornée : quand `prochain_depart` n'est pas nul, rappeler avec ce `depart` et `vue_attendue` "
                        "égal à `vue` ; tout changement de plan, de clôture ou de référence refuse la reprise. "
                        "Plan ou clôture incohérent : refus. N'atteste ni action terrain ni actualité métier.",
            parametres={
                "type": "object",
                "properties": {
                    "horodatage_reference": {
                        "type": "string", "minLength": 1,
                        "description": "Référence ISO 8601 avec fuseau explicite, fournie par l'appelant.",
                    },
                    "depart": {
                        "type": "integer", "minimum": 0,
                        "description": "Rang du premier suivi rendu (0 = début, défaut) : `prochain_depart` "
                                       "de la page précédente.",
                    },
                    "vue_attendue": {
                        "type": "string",
                        "description": "`vue` (64 hexadécimaux) de la page précédente ; requise si `depart` > 0.",
                    },
                },
                "required": ["horodatage_reference"],
                "additionalProperties": False,
            },
            fonction=lister_suivis_decision,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_bilan_suivis_decision",
            description="Bilan INTERNE d'une période [debut, fin) explicite des suivis internes : ouverts dans la "
                        "période, clos par revue humaine dans la période, ou encore ouverts juste avant fin, par "
                        "instant d'ouverture puis identifiant, avec plan, empreinte et clôture d'origine exacts. "
                        "Une clôture à fin ou après n'est pas rendue : le suivi reste ouvert à fin. Lecture pure, "
                        "bornée : quand `prochain_depart` n'est pas nul, rappeler avec ce `depart` et `vue_attendue` "
                        "égal à `vue`. Plan ou clôture incohérent, même hors période : refus. N'atteste ni action "
                        "terrain, ni cause, amélioration ou actualité métier.",
            parametres={
                "type": "object",
                "properties": {
                    "debut": {
                        "type": "string", "minLength": 1,
                        "description": "Début inclus, ISO 8601 avec fuseau explicite, fourni par l'appelant.",
                    },
                    "fin": {
                        "type": "string", "minLength": 1,
                        "description": "Fin exclue, ISO 8601 avec fuseau explicite, postérieure à `debut`.",
                    },
                    "depart": {
                        "type": "integer", "minimum": 0,
                        "description": "Rang de la première ligne rendue (0 = début, défaut) : `prochain_depart` "
                                       "de la page précédente.",
                    },
                    "vue_attendue": {
                        "type": "string",
                        "description": "`vue` (64 hexadécimaux) de la page précédente ; requise si `depart` > 0.",
                    },
                },
                "required": ["debut", "fin"],
                "additionalProperties": False,
            },
            fonction=bilan_suivis_decision,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_rapport_periode",
            description="Synthèse INTERNE d'une période [debut, fin) explicite : compteurs, total et vue du bilan "
                        "des suivis internes (sans ses lignes) et alertes M8 reçues dont l'instant de référence "
                        "chantier tombe dans la période, connues à la lecture (une alerte reçue plus tard s'ajoute). "
                        "File d'approbation, snapshots et instant de réception non couverts : signalés dans "
                        "`manques`. Lecture pure, bornée : quand `prochain_depart` n'est pas nul, rappeler avec ce "
                        "`depart` et `vue_attendue` égal à `vue`. Alerte, plan ou clôture incohérent, même hors "
                        "période : refus. N'atteste ni action terrain, ni cause, ni actualité métier.",
            parametres={
                "type": "object",
                "properties": {
                    "debut": {
                        "type": "string", "minLength": 1,
                        "description": "Début inclus, ISO 8601 avec fuseau explicite, fourni par l'appelant.",
                    },
                    "fin": {
                        "type": "string", "minLength": 1,
                        "description": "Fin exclue, ISO 8601 avec fuseau explicite, postérieure à `debut`.",
                    },
                    "depart": {
                        "type": "integer", "minimum": 0,
                        "description": "Rang de la première alerte rendue (0 = début, défaut) : `prochain_depart` "
                                       "de la page précédente.",
                    },
                    "vue_attendue": {
                        "type": "string",
                        "description": "`vue` (64 hexadécimaux) de la page précédente ; requise si `depart` > 0.",
                    },
                },
                "required": ["debut", "fin"],
                "additionalProperties": False,
            },
            fonction=lire_rapport_periode,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_observations_chantier_periode",
            description="Observations de chantier d'une période [debut, fin) explicite : snapshots WCT transportés "
                        "par m8.snapshot_chantier dont l'instant métier d'origine tombe dans la période, par instant "
                        "puis identifiant, chacun avec son maillon M9 et sa publication d'origine exacts. Liés au "
                        "bus (source_bus_liee), producteur NON authentifié. Snapshots génériques sans métadonnées "
                        "M8 seulement comptés, jamais datés. Lecture pure, bornée : quand `prochain_depart` n'est "
                        "pas nul, rappeler avec ce `depart` et `vue_attendue` égal à `vue` ; tout ajout au registre "
                        "périme la reprise. Snapshot transporté incohérent, sans publication ou en double, même "
                        "hors période : refus. N'atteste ni réception, ni couverture M1-M8, ni actualité métier.",
            parametres={
                "type": "object",
                "properties": {
                    "debut": {
                        "type": "string", "minLength": 1,
                        "description": "Début inclus, ISO 8601 avec fuseau explicite, fourni par l'appelant.",
                    },
                    "fin": {
                        "type": "string", "minLength": 1,
                        "description": "Fin exclue, ISO 8601 avec fuseau explicite, postérieure à `debut`.",
                    },
                    "depart": {
                        "type": "integer", "minimum": 0,
                        "description": "Rang de la première observation rendue (0 = début, défaut) : "
                                       "`prochain_depart` de la page précédente.",
                    },
                    "vue_attendue": {
                        "type": "string",
                        "description": "`vue` (64 hexadécimaux) de la page précédente ; requise si `depart` > 0.",
                    },
                },
                "required": ["debut", "fin"],
                "additionalProperties": False,
            },
            fonction=lire_observations_chantier,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_rapport_activite_periode",
            description="Rapport INTERNE partiel d'activité [debut, fin) : observations WCT liées au bus, puis "
                        "alertes M8 connues à la lecture, puis suivis de décisions humaines juste avant fin. "
                        "Preuves natives complètes, compteurs natifs et bases temporelles distinctes ; aucun "
                        "as-of commun ni rapport complet. Lecture pure bornée avec curseur global ; reprendre "
                        "avec prochain_depart et vue_attendue=vue. Toute source modifiée périme la vue, même "
                        "hors période ; toute preuve invalide ou trop grande refuse avant la première page. "
                        "Aucune authentification M8, réception, finance ou couverture complète attestée.",
            parametres={
                "type": "object",
                "properties": {
                    "debut": {
                        "type": "string", "minLength": 1,
                        "description": "Début inclus, ISO 8601 avec fuseau explicite, fourni par l'appelant.",
                    },
                    "fin": {
                        "type": "string", "minLength": 1,
                        "description": "Fin exclue, ISO 8601 avec fuseau explicite, postérieure à `debut`.",
                    },
                    "depart": {
                        "type": "integer", "minimum": 0,
                        "description": "Rang de la première ligne composite rendue (0 = début, défaut) : "
                                       "`prochain_depart` de la page précédente.",
                    },
                    "vue_attendue": {
                        "type": "string",
                        "description": "`vue` (64 hexadécimaux) de la page précédente ; requise si `depart` > 0.",
                    },
                },
                "required": ["debut", "fin"],
                "additionalProperties": False,
            },
            fonction=lire_rapport_activite,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_preparer_cloture_suivi_decision",
            description="Relit un suivi interne planifié non clos et une preuve M8 reçue de même métrique, même "
                        "chantier et même définition, puis calcule leurs empreintes pour une demande de clôture. "
                        "Lecture pure ; la preuve d'origine est admise, sans valeur d'actualité ni de cause.",
            parametres={"type": "object",
                        "properties": {"suivi_id": {"type": "string"}, "evenement_id": {"type": "string"}},
                        "required": ["suivi_id", "evenement_id"], "additionalProperties": False},
            fonction=preparer_cloture_suivi_decision,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_clore_suivi_decision",
            description="Propose la clôture par revue humaine d'un suivi interne planifié, avec empreintes du plan "
                        "et de la preuve M8 et un bilan. Seule sa demande dédiée approuvée par le propriétaire actif "
                        "l'enregistre, une seule fois, à part du plan conservé. N'atteste ni action terrain, ni "
                        "cause, amélioration ou actualité métier.",
            parametres={
                "type": "object",
                "properties": {champ: {"type": "string"} for champ in (
                    "suivi_id", "empreinte_suivi", "evenement_id", "empreinte_preuve", "bilan")},
                "required": ["suivi_id", "empreinte_suivi", "evenement_id", "empreinte_preuve", "bilan"],
                "additionalProperties": False,
            },
            fonction=clore_suivi_decision, autonomie=Autonomie.T1, niveau=Niveau.N3,
            roles_appareil=frozenset({"admin"}),
        ),
    )
    return (
        *outils_base,
        *outils_tissu.construire_outils(
            lecteur=lecteur_producteurs_m9, budget_sortie=BUDGET_SORTIE, captures_cible=captures_cible
        ),
        *outils_conseil.construire_outils(
            budget_sortie=BUDGET_SORTIE, captures_cible=captures_cible, sessions_cible=sessions_cible
        ),
        *outils_graphe.construire_outils(budget_sortie=BUDGET_SORTIE, captures_cible=captures_cible),
        *outils_actions.construire_outils(budget_sortie=BUDGET_SORTIE, proposeur=proposeur_actions_m9),
        *outils_memoire.construire_outils(
            budget_sortie=BUDGET_SORTIE, sessions_cible=sessions_cible, captures_cible=captures_cible
        ),
        *outils_experiences.construire_outils(
            budget_sortie=BUDGET_SORTIE, experiences_cible=experiences_cible, captures_cible=captures_cible
        ),
        *outils_plans.construire_outils(
            budget_sortie=BUDGET_SORTIE, plans_cible=plans_cible, captures_cible=captures_cible
        ),
        *outils_playbooks.construire_outils(budget_sortie=BUDGET_SORTIE, captures_cible=captures_cible),
        *outils_veille.construire_outils(budget_sortie=BUDGET_SORTIE, veille_cible=veille_cible),
        *outils_radars.construire_outils(budget_sortie=BUDGET_SORTIE, captures_cible=captures_cible),
        *outils_previsions.construire_outils(budget_sortie=BUDGET_SORTIE, captures_cible=captures_cible),
        *outils_semantique.construire_outils(budget_sortie=BUDGET_SORTIE, captures_cible=captures_cible),
        *outils_metriques_executives.construire_outils(budget_sortie=BUDGET_SORTIE, captures_cible=captures_cible),
        *outils_cadrage_decision.construire_outils(budget_sortie=BUDGET_SORTIE, captures_cible=captures_cible),
        *outils_tendances.construire_outils(budget_sortie=BUDGET_SORTIE, captures_cible=captures_cible),
        *outils_questions_scenario.construire_outils(budget_sortie=BUDGET_SORTIE),
        *outils_priorites.construire_outils(budget_sortie=BUDGET_SORTIE, captures_cible=captures_cible),
        *outils_direction.construire_outils(
            budget_sortie=BUDGET_SORTIE,
            sources_briefing=sources_du_briefing,
            fenetre_alertes_jours=_fenetre_alertes_jours,
            captures_cible=captures_cible,
            sessions_cible=sessions_cible,
            publications_cible=publications_cible,
            plans_cible=plans_cible,
            experiences_cible=experiences_cible,
        ),
    )
