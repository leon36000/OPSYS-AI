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

from collections.abc import Callable
from typing import Any

from opsys import contexte, evenements, stockage
from opsys.outils import Autonomie, Niveau, Outil, depuis_couple

from . import cedule, digest, ecarts, etats, outbox, pointage, preuves, registre, temps, verdicts

_DEPARTEMENT = "m04-field-ops"
_NOM_REGISTRE = "principal"

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
            return registre.Registre(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
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

    def resoudre_revue_completion(
        intervention_id: str, decision: str, horodatage: str, motif: str,
    ) -> dict[str, Any]:
        # PLAN T1.3-b : niveau N4 (déclaré sur l'Outil ci-dessous) — un agent PROPOSE, la
        # signature (personne, rôle) appartient au socle (opsys.approbations.decider), jamais à
        # cette fonction pure : voir outbox.resoudre_revue_completion.
        return depuis_couple(outbox.resoudre_revue_completion(
            intervention_id, decision, horodatage, registre_courant(), motif=motif,
        ))

    def lister_pending_review(type_demande: str | None = None) -> list[dict[str, Any]]:
        return ecarts.lister_pending_review(registre_courant(), type_demande=type_demande)

    def volumetrie_pending_review() -> dict[str, Any]:
        return ecarts.volumetrie_pending_review(registre_courant())

    def completer_intervention(
        intervention_id: str, horodatage: str,
        preuves_completion: dict[str, Any], signature_requise: bool = False,
        photos: Any = outbox.NON_FOURNI, description_factuelle: Any = outbox.NON_FOURNI,
        consentement_marketing: Any = outbox.NON_FOURNI, client_satisfait: Any = outbox.NON_FOURNI,
    ) -> dict[str, Any]:
        # T1.2-f : photos/description_factuelle/consentement_marketing/client_satisfait sont
        # des faits du CLIENT (Loi 25) — un agent ne peut JAMAIS les affirmer, même principe
        # que ecart_detecte déjà retiré du schéma de cet outil. Ils ne sont acceptés que
        # PENDANT un appel d'appareil (opsys.contexte.horodatage_reception() non None, socle
        # T1.4-b, docs/architecture/IDEMPOTENCE.md) : leur seule PRÉSENCE hors d'un tel appel
        # est un refus nommé — AVANT même de valider les preuves, rien n'est écrit ni publié.
        champs_client_fournis = any(
            v is not outbox.NON_FOURNI
            for v in (photos, description_factuelle, consentement_marketing, client_satisfait)
        )
        if champs_client_fournis and contexte.horodatage_reception() is None:
            return {
                "accepte": False,
                "verdict": verdicts.construire_verdict(
                    "REJ-CHAMPS-CLIENT-HORS-APPAREIL",
                    detail=(
                        "photos/description_factuelle/consentement_marketing/client_satisfait "
                        "ne sont acceptés que pendant un appel d'appareil (Loi 25) : un agent "
                        "ne peut jamais les affirmer à la place du client"
                    ),
                ),
            }

        # Contrat PreuvesCompletion (T1.1-b#3) : validé AVANT tout appel à
        # l'outbox — aucune écriture si le dossier de preuves est incomplet.
        ok, verdict = preuves.valider_preuves_completion(preuves_completion, signature_requise)
        if not ok:
            return {"accepte": False, "verdict": verdict}
        # Un agent ne peut pas affirmer l'absence d'écart : le matériel n'est pas encore comparé
        # au prévu à ce stade. La complétion reste donc à revoir ; completed_verified viendra du
        # code (variance M6 et preuves, PLAN T1.2) ou d'une décision humaine (T1.3).
        reg = registre_courant()
        accuse, verdict = outbox.completer_intervention(
            intervention_id, horodatage, reg, ecart_detecte=True,
            photos=photos, description_factuelle=description_factuelle,
            consentement_marketing=consentement_marketing, client_satisfait=client_satisfait,
        )
        if verdict is not None:
            return {"accepte": False, "verdict": verdict}
        # T1.2-b : publie m4.travaux_termines DANS LA MÊME TRANSACTION que le WCT qui vient
        # d'être écrit ci-dessus — `evenements.publier` ouvre un POINT DE SAUVEGARDE sur la
        # transaction déjà ouverte par `executer_atomique` (ADR-0009), jamais une transaction
        # indépendante ; un refus plus loin dans l'appelant annule les deux écritures ensemble.
        # Gardé par `stockage.connexion_courante() is not None` (même garde que
        # `m6_material_control.outils._registre_de_l_appel`) : seule la production (registre
        # durable, appel enveloppé par `executer_atomique`/`Capacites.appeler`) publie ; les
        # tests unitaires de ce fichier, qui injectent un `registre.Registre()` EN MÉMOIRE et
        # appellent `executer()` sans transaction, ne touchent jamais la base — publier quand
        # même y ouvrirait une transaction hors de propos pour un WCT qui n'existe que dans un
        # objet Python local, jamais dans `evenements_sortants`.
        if stockage.connexion_courante() is not None:
            wct = next(
                m[outbox.CLE_WCT] for m in reg.lire()
                if m.get("ligne_id") == accuse["ligne_id"]
            )
            evenements.publier(
                "m4.travaux_termines", _DEPARTEMENT, wct, evenement_id=wct["wct_id"],
            )
        return {"accepte": True, "resultat": accuse}

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
            nom="m4_resoudre_revue_completion",
            description=(
                "Revue HUMAINE d'une complétion completed_pending_review (PLAN T1.3-b), jamais "
                "un agent seul : decision=verifiee confirme (-> completed_verified, comme le "
                "ferait un signal M6 sans dépassement, mais décidé par une personne) ; "
                "decision=correction NOMME un problème SANS rouvrir le chantier (-> "
                "completed_pending_review, nouveau maillon d'audit ; motif obligatoire, la "
                "décision cite toujours pourquoi). Niveau N4 (écriture finale, ADR-0009 §4) : "
                "cet appel passe par la file d'approbation du socle — il PROPOSE seulement ; "
                "seule une personne dont le rôle figure dans department.yaml/approbations.n4 "
                "peut l'exécuter (opsys approbations decider, signé personne + rôle)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string"},
                    "decision": {"type": "string", "enum": list(outbox.DECISIONS_REVUE)},
                    "horodatage": {"type": "string"},
                    "motif": {
                        "type": "string",
                        "description": (
                            "Pourquoi cette décision : la confirmation, ou — pour une correction "
                            "— ce qui doit être corrigé. Jamais vide."
                        ),
                    },
                },
                "required": ["intervention_id", "decision", "horodatage", "motif"],
                "additionalProperties": False,
            },
            fonction=resoudre_revue_completion,
            # T1 (écriture interne, registre) : autonomie descriptive. Niveau EXPLICITE N4 plutôt
            # que le défaut T1->N3 (ADR-0009 §4, opsys.outils.niveau_par_defaut) — justification :
            # cette décision produit une ÉCRITURE FINALE (« engagement... écriture finale » de la
            # table ADR-0009 §4) — elle clôt définitivement, ou rouvre nommément, la vérification
            # d'une complétion déjà publiée aux 6 départements consommateurs (m4.travaux_termines) ;
            # contrairement aux autres outils T1 de M4 (pointer, compléter…), qui restent des
            # écritures INTERNES NON FINALES (N3), celle-ci ne l'est jamais : le niveau le plus
            # élevé de la paire l'emporte, pour les DEUX issues (verifiee ET correction), le
            # niveau étant fixé sur l'outil entier, jamais par argument.
            autonomie=Autonomie.T1,
            niveau=Niveau.N4,
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
                "(checklist, photos après, notes, signature si requise, §6/§9.7). Le statut est "
                "toujours completed_pending_review : la vérification se fait ensuite, par la "
                "variance des matériaux et une revue. Calcule la durée réelle depuis les "
                "pointages, nette des pauses ; refuse fail-closed si indéterminable ou si les "
                "preuves manquent. T1.2-f : consentement_marketing, client_satisfait, photos et "
                "description_factuelle sont des faits du CLIENT (Loi 25) — un agent ne peut "
                "JAMAIS les affirmer à sa place. Ils ne sont acceptés QUE pendant un appel "
                "d'appareil (formulaire de complétion de l'app mobile), jamais depuis une "
                "conversation avec un agent : les fournir hors d'un appel d'appareil est un "
                "refus nommé (REJ-CHAMPS-CLIENT-HORS-APPAREIL), rien n'est écrit ni publié."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string"}, "horodatage": {"type": "string"},
                    "preuves_completion": _PREUVES_COMPLETION,
                    "signature_requise": {"type": "boolean", "description": "Défaut : faux."},
                    "photos": {
                        "type": "array", "items": {"type": "string"},
                        "description": (
                            "Références de photos après-chantier (jamais de binaire). Fait "
                            "CLIENT (Loi 25) : accepté SEULEMENT pendant un appel d'appareil "
                            "(app mobile), jamais fourni par un agent."
                        ),
                    },
                    "description_factuelle": {
                        "type": "string",
                        "description": (
                            "Description factuelle du chantier. Fait CLIENT (Loi 25) : accepté "
                            "SEULEMENT pendant un appel d'appareil, jamais fourni par un agent."
                        ),
                    },
                    "consentement_marketing": {
                        "type": "boolean",
                        "description": (
                            "Consentement explicite du client à un usage marketing (Loi 25), "
                            "jamais déduit. Accepté SEULEMENT pendant un appel d'appareil, "
                            "jamais fourni ni affirmé par un agent."
                        ),
                    },
                    "client_satisfait": {
                        "type": ["boolean", "null"],
                        "description": (
                            "Signal de satisfaction du client ; null si demandé mais non "
                            "recueilli (jamais inventé). Fait CLIENT (Loi 25) : accepté "
                            "SEULEMENT pendant un appel d'appareil, jamais fourni par un agent."
                        ),
                    },
                },
                "required": ["intervention_id", "horodatage", "preuves_completion"],
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


# ---------------------------------------------------------------------------------------------
# Consommateurs d'événements (ADR-0009 §3, PLAN T1.2, point 4)
# ---------------------------------------------------------------------------------------------
# Même module que `outils()` (docs/architecture/DEPARTEMENTS.md) : seul cet adaptateur connaît
# `opsys`/`opsys.evenements` ; toute la logique de décision reste dans `outbox.confirmer_verification`
# (module pur, gardé par l'AST comme le WCT). Le répartiteur (`opsys.evenements.repartir`) n'appelle
# ces fonctions que dans une transaction déjà ouverte : le registre durable fait donc TOUJOURS
# autorité ici, sans le mode « en mémoire » des tests unitaires de `outils()` ci-dessus.
def _recevoir_variance_chantier(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m6.variance_chantier` : SEUL chemin qui fait passer une intervention de
    `completed_pending_review` à `completed_verified` (PLAN T1.2, point 4). DÉTERMINISTE :
    applique tel quel le verdict déjà calculé par M6 (statut_variance, signal_critique),
    n'invente rien. Les preuves de complétion sont déjà garanties par
    `m4_completer_intervention` (T1.1-b#3) : cette fonction n'a rien à revérifier de ce côté,
    la complétion n'existe pas sans elles.

    Idempotente à deux niveaux : le bus ne livre jamais deux fois le même `evenement_id`
    (`evenements_recus`, ADR-0009 §3) et, en plus, `confirmer_verification` lui-même est un
    no-op si l'intervention est déjà `completed_verified` — une redélivrance ou un second
    événement pour le même WCT ne change jamais rien.

    PLAN T1.3-b : quand ce signal ne mène PAS à une vérification automatique (branche
    ci-dessous), il est TRACÉ dans le registre de M4 (`outbox.enregistrer_signal_variance`) —
    sans ce maillon, `attentes()` (file du propriétaire) n'aurait aucun moyen de savoir, en ne
    lisant que le registre de M4, qu'un signal critique attend une revue humaine
    (`m4_resoudre_revue_completion`).
    """
    reg = registre.Registre(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    intervention_id = charge["intervention_id"]

    # Seul le code décide : `evaluee` + `signal_critique` explicitement faux, rien d'autre
    # (jamais une absence de signal traitée comme faux — le schéma du catalogue impose déjà
    # `signal_critique` non nul seulement quand `statut_variance == "evaluee"`).
    if charge["statut_variance"] != "evaluee" or charge["signal_critique"] is not False:
        outbox.enregistrer_signal_variance(intervention_id, charge, reg)
        return {
            "traite": True, "verifie": False,
            "intervention_id": intervention_id, "raison": charge["statut_variance"],
        }

    accuse, verdict = outbox.confirmer_verification(
        intervention_id, charge["horodatage_completion"], reg,
        evenement_id_variance=charge["evenement_id"],
    )
    if verdict is not None:
        return {
            "traite": True, "verifie": False,
            "intervention_id": intervention_id, "raison": verdict["code"],
        }
    return {
        "traite": True, "verifie": not accuse["deja_verifie"],
        "intervention_id": intervention_id, "statut": accuse["statut"],
    }


def consommateurs() -> dict[str, Callable[[dict], dict]]:
    return {"m6.variance_chantier": _recevoir_variance_chantier}


# ---------------------------------------------------------------------------------------------
# Attentes du propriétaire (ADR-0009 §5, PLAN T1.3-b)
# ---------------------------------------------------------------------------------------------
# Même mécanisme de découverte que `consommateurs()` (`opsys.departements.Departement.
# charger_attentes`) : fonction module-level, sans argument, appelée par
# `approbations.file_proprietaire` DANS SA transaction déjà ouverte — jamais construite en dehors
# de cet appel (aucune connexion garantie ailleurs, `departements.py`).
def attentes() -> list[dict[str, Any]]:
    """Une entrée par intervention actuellement `completed_pending_review` : la complétion
    existe déjà (WCT écrit, preuves garanties par `m4_completer_intervention`, T1.1-b#3), reste
    à vérifier ou à corriger par une personne autorisée (`m4_resoudre_revue_completion`, jamais
    un agent seul). Le résumé porte le signal de variance critique de M6 QUAND il existe
    (`outbox.dernier_signal_variance`, tracé par `_recevoir_variance_chantier` ci-dessus) — son
    absence est dite telle quelle (« pas encore de nouvelles »), jamais traitée comme « pas de
    problème » (fail-closed)."""
    reg = registre.Registre(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    return [
        {
            "type": "completion_en_revue",
            "id": pendante["intervention_id"],
            "resume": _resume_completion_en_revue(reg, pendante["intervention_id"]),
            "niveau": Niveau.N4.value,
            "depuis": _depuis_pending_review(reg, pendante["intervention_id"]),
            "action_proposee": (
                "m4_resoudre_revue_completion : verifiee (confirme) ou correction (nomme le "
                "problème)"
            ),
        }
        for pendante in etats.lister_interventions(reg, statut="completed_pending_review")
    ]


def _depuis_pending_review(reg: registre.Registre, intervention_id: str) -> str:
    """Horodatage du DERNIER maillon `completed_pending_review` de l'intervention — l'entrée en
    revue, ou la dernière correction nommée si une ou plusieurs ont déjà eu lieu. Jamais une
    horloge consultée ici (même garde d'esprit que `digest.py`) : uniquement des horodatages déjà
    écrits au registre. Ne peut pas être `None` : `attentes()` n'appelle cette fonction que pour
    une intervention dont `etats.lister_interventions` vient de constater ce statut courant, donc
    au moins un tel maillon existe forcément."""
    dernier = None
    for maillon in reg.lire():
        if (maillon.get("type_entree") == etats.TYPE_TRANSITION
                and maillon.get("intervention_id") == intervention_id
                and maillon.get("statut") == "completed_pending_review"):
            dernier = maillon["horodatage"]
    return dernier


def _resume_completion_en_revue(reg: registre.Registre, intervention_id: str) -> str:
    base = f"Complétion en revue ({intervention_id})"
    signal = outbox.dernier_signal_variance(reg, intervention_id)
    if signal is None:
        return f"{base} — variance M6 non encore reçue"
    if signal["statut_variance"] != "evaluee":
        return f"{base} — variance M6 non finalisée ({signal['statut_variance']})"
    if signal["signal_critique"] is True:
        return f"{base} — écart matériaux CRITIQUE signalé par M6 (seuil {signal['seuil_pourcentage']})"
    # Atteint seulement si confirmer_verification a, pour une autre raison, échoué à vérifier
    # malgré un signal non critique (défensif : jamais supposé impossible, jamais deviné).
    return f"{base} — variance M6 évaluée sans signal critique"
