"""Capacités d'agent du département M4 Field Ops.

Chaque outil enveloppe une fonction métier déterministe existante (etats,
cedule, pointage, ecarts, outbox, digest, preuves, temps) : aucune n'est
réécrite. Comme le
registre M4 (`registre.Registre`) est un journal que les fonctions métier
reçoivent en paramètre vivant — jamais un objet JSON-sérialisable —
`outils()` referme par fermeture (closure) sur chaque fonction exposée l'accès
au registre du département : c'est ce qui permet à l'agent d'enchaîner
inscription → pointage → complétion → digest par de simples appels d'outils,
sans jamais manipuler le registre lui-même.

Registre de production (ADR-0009) : par défaut, `outils()` adosse ce registre
au stockage durable de l'instance (`opsys.stockage.maillons`, dans la
transaction que `Capacites.appeler` ouvre pour chaque appel d'outil), relu à
chaque usage car la console et le serveur MCP écrivent la même chaîne —
`registre.py` reste pur (aucun import `opsys`/SQLAlchemy) et ignore que ses
maillons survivent au redémarrage : c'est cet adaptateur, seul, qui fait le
lien. Le paramètre `registre_cible` est le point d'injection : les tests
unitaires du département y passent explicitement un `registre.Registre()` EN
MÉMOIRE (aucune base montée), sans toucher au comportement par défaut utilisé
par `charger_outils()` en production.

`m4_planifier_intervention` compose inscription + cédule en un seul appel
(gain : deux allers-retours évités). Chaque outil unitaire reste disponible
pour les cas où seule une étape est nécessaire (ex. un pointage isolé).
"""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Outil, depuis_couple

from . import cedule, digest, ecarts, etats, outbox, pointage, preuves, registre, temps

_CONTRAT = {"type": "object", "description": "LeadQualifie M2 : sept clés gelées (lead_id, "
            "conversation_id, type_travaux, ville, canal, contact, urgence_declaree)."}
_MARQUEUR = {"type": "object", "description": "Marqueur de readiness signé par M2 (cinq clés)."}
_FIX_GPS = {"type": "object", "description": "{latitude, longitude}."}
_ATTESTATION = {"type": "object", "description": "{fictif: true, appareil_id} — mode ombre uniquement."}
_FENETRE = {"type": "object", "description": "{debut, fin} ISO-8601 avec fuseau."}
_REFERENTIEL_VILLES = {"type": "object", "description": "{ville_tokenisee: {latitude, longitude, rayon_km}}."}
_VERSION_METIER = {"type": "object", "description": "{duree_minutes, perimetre, materiaux}."}
_PREUVES_COMPLETION = {
    "type": "object",
    "description": (
        "{checklist_complete: bool (doit être true), photos_apres: [string,...] non vide, "
        "notes: string, signature: string|null}. Exigé pour clore une intervention (§6/§9.7)."
    ),
}
_PERIODE = {"type": "object", "description": "{debut, fin} AAAA-MM-JJ, bornes incluses."}


def outils(registre_cible: registre.Registre | None = None) -> tuple[Outil, ...]:
    """Capacités exposées aux agents, qui partagent le registre du département.

    `registre_cible` : `None` (défaut, utilisé par `charger_outils()` en production) adosse le
    registre au stockage durable de l'instance ; un `registre.Registre()` explicite (tests) reste
    en mémoire, jamais touché à la base.
    """
    if registre_cible is None:
        def registre_courant() -> registre.Registre:
            # Neuf à chaque usage : relu depuis la base dans la transaction de l'appel, il ne
            # garde jamais l'empreinte d'un état qu'un autre processus a depuis prolongé.
            return registre.Registre(stockage.maillons("m04-field-ops", "principal"))
    else:
        def registre_courant() -> registre.Registre:
            return registre_cible

    # -- fonctions enveloppes (closures sur registre_courant) ---------------

    def planifier_intervention(
        contrat: dict[str, Any], marqueur: dict[str, Any], horodatage: str, sel: str,
        techniciens_disponibles: list[str], fenetres_disponibles: list[dict[str, Any]],
        devis_id: str | None = None,
    ) -> dict[str, Any]:
        """Inscrit l'intervention PUIS calcule sa cédule en un seul appel."""
        accuse, verdict = etats.inscrire_intervention(
            contrat, marqueur, registre_courant(), horodatage, sel, devis_id=devis_id,
        )
        if verdict is not None:
            return {"etape": "inscription", "accepte": False, "verdict": verdict}
        intervention_pour_cedule = {
            "intervention_id": accuse["intervention_id"],
            "lead_id": contrat["lead_id"],
            "type_travaux": contrat["type_travaux"],
            "ville": contrat["ville"],
        }
        cedule_resultat, verdict_cedule = cedule.generer_cedule(
            [intervention_pour_cedule], techniciens_disponibles, fenetres_disponibles, sel
        )
        if verdict_cedule is not None:
            return {
                "etape": "cedule", "accepte": True, "intervention_id": accuse["intervention_id"],
                "statut": accuse["statut"], "assignation": None,
                "avertissement_cedule": verdict_cedule,
            }
        assignations = cedule_resultat["assignations"]
        assignation = assignations[0] if assignations else None
        return {
            "etape": "complet", "accepte": True, "intervention_id": accuse["intervention_id"],
            "statut": accuse["statut"], "tete_chaine": accuse["tete_chaine"],
            "assignation": assignation,
            "non_cedulee": assignation is None,
        }

    def demarrer_route(intervention_id: str, technicien_id: str, horodatage: str) -> dict[str, Any]:
        return depuis_couple(etats.transitionner(
            intervention_id, "en_route", registre_courant(), horodatage,
            assignation={"intervention_id": intervention_id, "technicien_id": technicien_id},
        ))

    def signaler_report(intervention_id: str, motif: str, horodatage: str) -> dict[str, Any]:
        return depuis_couple(
            etats.transitionner(intervention_id, "reportee", registre_courant(), horodatage, motif=motif)
        )

    def annuler_intervention(intervention_id: str, horodatage: str) -> dict[str, Any]:
        return depuis_couple(etats.transitionner(intervention_id, "annulee", registre_courant(), horodatage))

    def statut_intervention(intervention_id: str) -> dict[str, Any]:
        statut = etats.statut_courant(registre_courant(), intervention_id)
        return {"intervention_id": intervention_id, "statut": statut}

    def pointer(
        intervention_id: str, technicien_id: str, action: str, horodatage: str,
        fix_gps: dict[str, Any], attestation: dict[str, Any], fenetre_travail: dict[str, Any],
        referentiel_villes: dict[str, Any], ville: str, sel: str,
    ) -> dict[str, Any]:
        return depuis_couple(pointage.enregistrer_pointage(
            intervention_id, technicien_id, action, horodatage, fix_gps, attestation,
            {"intervention_id": intervention_id, "technicien_id": technicien_id},
            fenetre_travail, referentiel_villes, ville, sel, registre_courant(),
        ))

    def creer_demande_ecart(
        intervention_id: str, version_prevue: dict[str, Any], version_declaree: dict[str, Any], horodatage: str,
    ) -> dict[str, Any]:
        return depuis_couple(ecarts.creer_demande_ecart(
            intervention_id, version_prevue, version_declaree, horodatage, registre_courant()
        ))

    def resoudre_demande(demande_id: str, decision: str, horodatage: str, motif: str | None = None) -> dict[str, Any]:
        return depuis_couple(ecarts.resoudre_demande(demande_id, decision, horodatage, registre_courant(), motif=motif))

    def lister_pending_review(type_demande: str | None = None) -> list[dict[str, Any]]:
        return ecarts.lister_pending_review(registre_courant(), type_demande=type_demande)

    def volumetrie_pending_review() -> dict[str, Any]:
        return ecarts.volumetrie_pending_review(registre_courant())

    def completer_intervention(
        intervention_id: str, horodatage: str, ecart_detecte: bool,
        preuves_completion: dict[str, Any], signature_requise: bool = False,
    ) -> dict[str, Any]:
        # Contrat PreuvesCompletion (T1.1-b#3) : validé AVANT tout appel à
        # l'outbox — aucune écriture si le dossier de preuves est incomplet.
        ok, verdict = preuves.valider_preuves_completion(preuves_completion, signature_requise)
        if not ok:
            return {"accepte": False, "verdict": verdict}
        return depuis_couple(outbox.completer_intervention(
            intervention_id, horodatage, registre_courant(), ecart_detecte=ecart_detecte,
        ))

    def lire_outbox(depuis_index: int = 0) -> list[dict[str, Any]]:
        return [{"index": i, "wct": w} for i, w in outbox.lire_outbox(registre_courant(), depuis_index)]

    def notifier_client_completion(intervention_id: str) -> dict[str, Any]:
        """Prépare le brouillon de message client (T2) : jamais GPS/technicien/lead_id en clair."""
        wct = None
        for _, candidat in outbox.lire_outbox(registre_courant()):
            if candidat["intervention_id"] == intervention_id:
                wct = candidat
        if wct is None:
            raise ValueError(f"aucun WCT trouvé pour l'intervention {intervention_id}")
        return {
            "intervention_id": intervention_id,
            "message_client": (
                "Votre intervention est terminée. Merci de votre confiance."
            ),
            "horodatage_completion": wct["horodatage_completion"],
            "duree_reelle_minutes": wct["duree_reelle_minutes"],
        }

    def produire_digest(date_cible: str, horodatage_reference: str) -> dict[str, Any]:
        return depuis_couple(digest.produire_digest(registre_courant(), date_cible, horodatage_reference))

    def lister_interventions(statut: str | None = None) -> list[dict[str, Any]]:
        return etats.lister_interventions(registre_courant(), statut=statut)

    def produire_brouillon_temps(
        periode: dict[str, Any], seuil_minutes: int | None = None,
    ) -> dict[str, Any]:
        return depuis_couple(
            temps.produire_brouillon_temps(registre_courant(), periode, seuil_minutes=seuil_minutes)
        )

    return (
        Outil(
            nom="m4_planifier_intervention",
            description=(
                "Inscrit une intervention à partir d'un lead M2 qualifié PUIS calcule sa cédule "
                "(technicien, fenêtre horaire) en un seul appel. Bloque avec un verdict nommé si "
                "le contrat ou le marqueur de readiness est invalide."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "contrat": _CONTRAT, "marqueur": _MARQUEUR,
                    "horodatage": {"type": "string"}, "sel": {"type": "string"},
                    "techniciens_disponibles": {"type": "array", "items": {"type": "string"}},
                    "fenetres_disponibles": {"type": "array", "items": _FENETRE},
                    "devis_id": {
                        "type": ["string", "null"],
                        "description": "Identifiant du devis M3 accepté, si déjà connu. Omis, reste null.",
                    },
                },
                "required": ["contrat", "marqueur", "horodatage", "sel",
                             "techniciens_disponibles", "fenetres_disponibles"],
                "additionalProperties": False,
            },
            fonction=planifier_intervention,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m4_demarrer_route",
            description=(
                "Fait passer une intervention planifiee -> en_route : exige l'assignation "
                "effective d'un technicien (PRD §4), jamais un départ fictif."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string"}, "technicien_id": {"type": "string"},
                    "horodatage": {"type": "string"},
                },
                "required": ["intervention_id", "technicien_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=demarrer_route,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m4_signaler_report",
            description="Reporte une intervention (client_absent, meteo ou decision_admin).",
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string"},
                    "motif": {"type": "string", "enum": list(etats.MOTIFS_REPORT)},
                    "horodatage": {"type": "string"},
                },
                "required": ["intervention_id", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=signaler_report,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m4_annuler_intervention",
            description="Annule une intervention planifiee ou en_route (avant tout pointage validé).",
            parametres={
                "type": "object",
                "properties": {"intervention_id": {"type": "string"}, "horodatage": {"type": "string"}},
                "required": ["intervention_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=annuler_intervention,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m4_statut_intervention",
            description="Lit le statut courant d'une intervention (rejoue le registre).",
            parametres={
                "type": "object",
                "properties": {"intervention_id": {"type": "string"}},
                "required": ["intervention_id"],
                "additionalProperties": False,
            },
            fonction=statut_intervention,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m4_pointer",
            description=(
                "Enregistre un pointage terrain (arrivee/depart) horodaté et géolocalisé. "
                "Vérifie la cohérence GPS contre le référentiel des villes ET l'assignation "
                "contre celle réellement envoyée en_route (registre) — jamais la seule "
                "déclaration de l'appelant. Route automatiquement vers sur_site ou en_revue."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string"}, "technicien_id": {"type": "string"},
                    "action": {"type": "string", "enum": list(pointage.ACTIONS)},
                    "horodatage": {"type": "string"}, "fix_gps": _FIX_GPS, "attestation": _ATTESTATION,
                    "fenetre_travail": _FENETRE, "referentiel_villes": _REFERENTIEL_VILLES,
                    "ville": {"type": "string"}, "sel": {"type": "string"},
                },
                "required": ["intervention_id", "technicien_id", "action", "horodatage", "fix_gps",
                             "attestation", "fenetre_travail", "referentiel_villes", "ville", "sel"],
                "additionalProperties": False,
            },
            fonction=pointer,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m4_creer_demande_ecart",
            description="Ouvre une demande d'écart métier (durée/périmètre/matériaux prévu vs déclaré).",
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string"}, "version_prevue": _VERSION_METIER,
                    "version_declaree": _VERSION_METIER, "horodatage": {"type": "string"},
                },
                "required": ["intervention_id", "version_prevue", "version_declaree", "horodatage"],
                "additionalProperties": False,
            },
            fonction=creer_demande_ecart,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m4_resoudre_demande",
            description=(
                "Arbitre une demande en attente. validee sur un écart métier complète "
                "l'intervention (WCT) ; validee sur une anomalie de pointage reprend sur_site "
                "(PRD §4) ; rejetee annule toujours l'intervention."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "demande_id": {"type": "string"},
                    "decision": {"type": "string", "enum": list(ecarts.DECISIONS)},
                    "horodatage": {"type": "string"}, "motif": {"type": ["string", "null"]},
                },
                "required": ["demande_id", "decision", "horodatage"],
                "additionalProperties": False,
            },
            fonction=resoudre_demande,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m4_lister_pending_review",
            description="Liste les demandes de revue en attente (écarts métier et anomalies de pointage).",
            parametres={
                "type": "object",
                "properties": {
                    "type_demande": {"type": ["string", "null"], "enum": list(ecarts.TYPES_DEMANDE) + [None]},
                },
                "additionalProperties": False,
            },
            fonction=lister_pending_review,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m4_volumetrie_pending_review",
            description="Compte les demandes en attente, par type (CA-M4-14).",
            parametres={"type": "object", "properties": {}, "additionalProperties": False},
            fonction=volumetrie_pending_review,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m4_completer_intervention",
            description=(
                "Termine une intervention et émet le Work Completion Trigger dans l'outbox, "
                "en une seule écriture atomique (CA-M4-11). Exige le dossier PreuvesCompletion "
                "(checklist, photos après, notes, signature si requise, §6/§9.7) et un signal "
                "explicite ecart_detecte, jamais déduit : vrai -> completed_pending_review, "
                "faux -> completed_verified. Calcule la durée réelle depuis les pointages, nette "
                "des pauses ; refuse fail-closed si indéterminable ou si les preuves manquent."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string"}, "horodatage": {"type": "string"},
                    "ecart_detecte": {
                        "type": "boolean",
                        "description": "vrai -> completed_pending_review ; faux -> completed_verified.",
                    },
                    "preuves_completion": _PREUVES_COMPLETION,
                    "signature_requise": {"type": "boolean", "description": "Défaut : faux."},
                },
                "required": ["intervention_id", "horodatage", "ecart_detecte", "preuves_completion"],
                "additionalProperties": False,
            },
            fonction=completer_intervention,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m4_lire_outbox",
            description="Lit les Work Completion Trigger émis depuis un index (pour les modules aval).",
            parametres={
                "type": "object",
                "properties": {"depuis_index": {"type": "integer"}},
                "additionalProperties": False,
            },
            fonction=lire_outbox,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m4_notifier_client_completion",
            description=(
                "Prépare le message de confirmation de fin de travaux pour le client, à partir "
                "du WCT (jamais de GPS, technicien ou identifiant interne exposé). Action externe "
                "réversible : approbation requise en mode ombre/supervisé."
            ),
            parametres={
                "type": "object",
                "properties": {"intervention_id": {"type": "string"}},
                "required": ["intervention_id"],
                "additionalProperties": False,
            },
            fonction=notifier_client_completion,
            autonomie=Autonomie.T2,
        ),
        Outil(
            nom="m4_produire_digest",
            description=(
                "Digest quotidien déterministe (interventions complétées, en revue, volumétrie "
                "de la file) pour une date cible, hash-chaîné."
            ),
            parametres={
                "type": "object",
                "properties": {"date_cible": {"type": "string"}, "horodatage_reference": {"type": "string"}},
                "required": ["date_cible", "horodatage_reference"],
                "additionalProperties": False,
            },
            fonction=produire_digest,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m4_lister_interventions",
            description=(
                "Liste les interventions connues (id, statut, lead, type de travaux, devis), "
                "sans aucune donnée de contact. Filtre optionnel par statut."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "statut": {"type": ["string", "null"], "enum": list(etats.ETATS) + [None]},
                },
                "additionalProperties": False,
            },
            fonction=lister_interventions,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m4_produire_brouillon_temps",
            description=(
                "Brouillon de temps agrégé par intervention complétée, pour une période "
                "(minutes travaillées, déplacement, pause) — aucun taux ni montant, M5 validera "
                "la paie. Signale un dépassement d'heures par technicien si seuil_minutes est fourni."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "periode": _PERIODE,
                    "seuil_minutes": {"type": ["integer", "null"]},
                },
                "required": ["periode"],
                "additionalProperties": False,
            },
            fonction=produire_brouillon_temps,
            autonomie=Autonomie.T0,
        ),
    )
