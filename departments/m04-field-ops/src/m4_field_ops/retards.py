"""Reports et incidents ouverts, pour l'admin (PLAN T4.27-a, §9.5 M4 « dispatch du jour, retards, incidents »).

Module pur (stdlib et modules de M4 ; aucun import ``opsys``, aucune horloge, aucun aléa, aucun réseau ; un test le
vérifie par analyse du code). Il ne fait QUE lire : rien n'est écrit au registre, aucun statut ne change (outil T0).

CE QUE M4 ENREGISTRE DÉJÀ, et que ce relevé montre, sans rien en déduire de plus :

    les REPORTS      une intervention dont le statut courant est ``reportee`` (``m4_signaler_report``) ; la dernière
                     transition de report donne le motif (``client_absent``, ``meteo`` ou ``decision_admin``) et l'heure
                     que le registre a gardée ;
    les INCIDENTS    les demandes de revue SANS résolution (``ecarts.lister_pending_review``) : un écart métier (durée,
                     périmètre ou matériaux déclarés autrement que prévus) ou une anomalie de pointage.

Pour chacun, l'âge en heures pleines, à partir de ``horodatage_reference`` que l'appelant fournit (M4 n'a pas
d'horloge : même règle que le digest). Une référence antérieure à l'heure du fait (l'horloge de l'appareil retarde) ne
donne pas d'âge : ``heures_ecoulees`` vaut ``None``, jamais un nombre négatif ni zéro. Une demande de revue ouverte
depuis ``SEUIL_BLOCAGE_HEURES`` heures ou plus est « bloquée » : c'est le seuil du digest
(``digest.SEUIL_BLOCAGE_HEURES``), jamais un second.

CE QUE M4 NE SAIT PAS, et que ce relevé dit au lieu de l'inventer : le retard sur la cédule. Le plan d'une cédule
numérote ses jours (0, 1, ...) sans date civile, et le registre ne garde aucune fenêtre planifiée : un créneau dépassé
sans départ ne se détecte pas. Aucun « aucun retard » n'est jamais écrit ici ; ``retard_sur_cedule`` est
``non_mesurable`` et dit pourquoi.

Les heures des reports et des demandes d'écart sont celles que le registre a gardées : l'appelant les a écrites
(contrairement au pointage, au départ ou à la complétion, dont l'heure de réception du serveur fait foi). Le relevé ne
les corrige pas.

Ordre, stable : du plus ancien au plus récent (les plus en retard d'abord), puis par identifiant. Chaque liste est
bornée (``LIMITE_PAR_LISTE``) pour tenir dans une réponse d'appareil ; le reste est compté (``reste``), jamais perdu en
silence, et la liste complète se lit avec ``m4_lister_interventions`` (statut ``reportee``, paginé) et
``m4_lister_pending_review``. Aucun texte libre du terrain (périmètre, matériaux, notes) ni contact ne sort d'ici : des
identifiants, un motif, des heures."""

from __future__ import annotations

from datetime import datetime, timedelta

from . import cedule_tournees, digest, ecarts, etats, horodatage, verdicts

TYPE_RELEVE = "RETARDS_INCIDENTS"
SEUIL_BLOCAGE_HEURES = digest.SEUIL_BLOCAGE_HEURES
LIMITE_PAR_LISTE = 8
MANQUE_RETARD_SUR_CEDULE = (
    "aucun calendrier : la cédule numérote ses jours (0, 1, ...) sans date civile et le registre ne garde aucune "
    "fenêtre planifiée ; un créneau dépassé sans départ ne se détecte pas ici"
)

__all__ = [
    "LIMITE_PAR_LISTE",
    "MANQUE_RETARD_SUR_CEDULE",
    "SEUIL_BLOCAGE_HEURES",
    "TYPE_RELEVE",
    "incidents_ouverts",
    "lire",
    "presenter",
    "reports_courants",
]


def _instant(texte):
    return datetime.fromisoformat(texte)


def _heures_ecoulees(depuis, reference):
    """Heures pleines écoulées entre ``depuis`` et ``reference`` ; ``None`` si la référence précède le fait."""
    ecart = reference - _instant(depuis)
    if ecart < timedelta(0):
        return None
    return int(ecart.total_seconds() // 3600)


def _plus_anciens_d_abord(entrees, cle_identifiant):
    return sorted(entrees, key=lambda entree: (_instant(entree["depuis"]), entree[cle_identifiant]))


def reports_courants(instantane):
    """Les reports EN COURS : ``[{intervention_id, motif, depuis}]``, une entrée par intervention au statut
    ``reportee``.

    ``instantane`` : un objet qui a ``lire()`` (un registre, ou ``cedule_tournees.instantane_du_registre``). Le statut
    courant est celui de ``etats.lister_interventions`` (une seule définition de « reportée maintenant ») ; le motif et
    l'heure sont ceux de la DERNIÈRE transition de report de l'intervention. Lecture pure."""
    courantes = {ligne["intervention_id"] for ligne in etats.lister_interventions(instantane, statut="reportee")}
    derniers = {}
    for maillon in instantane.lire():
        if (
            maillon["type_entree"] == etats.TYPE_TRANSITION
            and maillon["statut"] == "reportee"
            and maillon["intervention_id"] in courantes
        ):
            derniers[maillon["intervention_id"]] = maillon
    return [
        {"intervention_id": identifiant, "motif": maillon["motif"], "depuis": maillon["horodatage"]}
        for identifiant, maillon in derniers.items()
    ]


def incidents_ouverts(instantane):
    """Les demandes de revue sans résolution : ``[{demande_id, intervention_id, type_demande, depuis}]``. Lecture
    pure."""
    return [
        {
            "demande_id": demande["demande_id"],
            "intervention_id": demande["intervention_id"],
            "type_demande": demande["type_demande"],
            "depuis": demande["horodatage"],
        }
        for demande in ecarts.lister_pending_review(instantane)
    ]


def _suite(reste, outil):
    if not reste:
        return None
    return f"{reste} de plus, du moins ancien au plus récent : {outil} les rend tous"


def lire(registre_cible, horodatage_reference, limite_par_liste=None):
    """``(relevé, None)`` ou ``(None, verdict)`` : les reports en cours et les incidents ouverts, avec leur âge.

    ``horodatage_reference`` : heure ISO 8601 avec fuseau que l'appelant donne (illisible : ``REJ-HORODATAGE-INVALIDE``,
    rien n'est écrit, la fonction n'écrit jamais). ``limite_par_liste`` : ``None`` pour ``LIMITE_PAR_LISTE``.

    Le relevé porte, pour chaque liste, son ``total``, la ventilation (``par_motif``, ``par_type``), ce qui est
    ``affiches`` et ce qui ``reste`` ; pour les incidents, ``bloques`` (comptés sur TOUS, pas seulement sur ceux qui
    sont affichés). ``retard_sur_cedule`` est toujours ``non_mesurable``, avec la raison."""
    try:
        horodatage.valider_horodatage(horodatage_reference)
    except ValueError:
        return None, verdicts.construire_verdict(
            "REJ-HORODATAGE-INVALIDE",
            detail="horodatage_reference : une heure ISO 8601 avec fuseau est attendue (ex. 2026-09-29T09:00:00-04:00)",
        )
    limite = LIMITE_PAR_LISTE if limite_par_liste is None else limite_par_liste
    reference = _instant(horodatage_reference)
    instantane = cedule_tournees.instantane_du_registre(registre_cible)

    reports = _plus_anciens_d_abord(reports_courants(instantane), "intervention_id")
    par_motif = {motif: 0 for motif in etats.MOTIFS_REPORT}
    for report in reports:
        par_motif[report["motif"]] = par_motif.get(report["motif"], 0) + 1
    liste_reports = [
        {
            "intervention_id": report["intervention_id"],
            "motif": report["motif"],
            "depuis": report["depuis"],
            "heures_ecoulees": _heures_ecoulees(report["depuis"], reference),
        }
        for report in reports[:limite]
    ]

    incidents = _plus_anciens_d_abord(incidents_ouverts(instantane), "demande_id")
    par_type = {type_demande: 0 for type_demande in ecarts.TYPES_DEMANDE}
    bloques = 0
    for incident in incidents:
        par_type[incident["type_demande"]] = par_type.get(incident["type_demande"], 0) + 1
        heures = _heures_ecoulees(incident["depuis"], reference)
        if heures is not None and heures >= SEUIL_BLOCAGE_HEURES:
            bloques += 1
    liste_incidents = []
    for incident in incidents[:limite]:
        heures = _heures_ecoulees(incident["depuis"], reference)
        liste_incidents.append(
            {
                "demande_id": incident["demande_id"],
                "intervention_id": incident["intervention_id"],
                "type_demande": incident["type_demande"],
                "depuis": incident["depuis"],
                "heures_ecoulees": heures,
                "bloquee": heures is not None and heures >= SEUIL_BLOCAGE_HEURES,
            }
        )

    return {
        "type": TYPE_RELEVE,
        "reference": horodatage_reference,
        "seuil_blocage_heures": SEUIL_BLOCAGE_HEURES,
        "reports": {
            "total": len(reports),
            "par_motif": par_motif,
            "affiches": len(liste_reports),
            "reste": len(reports) - len(liste_reports),
            "suite": _suite(len(reports) - len(liste_reports), "m4_lister_interventions (statut reportee)"),
            "liste": liste_reports,
        },
        "incidents": {
            "total": len(incidents),
            "par_type": par_type,
            "bloques": bloques,
            "affiches": len(liste_incidents),
            "reste": len(incidents) - len(liste_incidents),
            "suite": _suite(len(incidents) - len(liste_incidents), "m4_lister_pending_review"),
            "liste": liste_incidents,
        },
        "retard_sur_cedule": {"statut": "non_mesurable", "manque": MANQUE_RETARD_SUR_CEDULE},
    }, None


def presenter(releve, tient):
    """``(relevé, None)`` ou ``(None, verdict)`` : le relevé, s'il ``tient`` dans une réponse d'appareil.

    ``tient(relevé)`` : prédicat de l'appelant, qui mesure la place que la réponse prend. Les listes sont déjà bornées ;
    un relevé qui ne tient pas quand même est refusé avec la consigne, jamais tronqué ni raccourci en silence."""
    if tient(releve):
        return releve, None
    return None, verdicts.construire_verdict(
        "REJ-CONTRAT-INVALIDE",
        detail="le relevé est trop grand pour une réponse d'appareil : m4_lister_pending_review et "
        "m4_lister_interventions (statut reportee, paginé) rendent les listes en entier",
    )
