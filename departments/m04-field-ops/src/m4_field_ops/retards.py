"""Retards et incidents, pour l'admin (PLAN T4.27-a, §9.5 M4 « dispatch du jour, retards, incidents » ; P4-04).

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

RETARD SUR LA CÉDULE (P4-04). Le retard se mesure à partir du créneau DATÉ (``cedule_datee`` de
``calendrier_civil`` : le plan appliqué dont les jours numérotés ont reçu une date civile) et du statut courant :
une intervention ``planifiee`` ou ``en_route`` dont la fin du créneau est dépassée à ``horodatage_reference``,
au-delà de la tolérance DÉCLARÉE par la direction (``tolerance_minutes``, entière >= 0), est « en retard » ;
les autres sont « à l'heure ». Sans tolérance déclarée (``None``), la règle est « non évaluée » et dit quoi
déclarer (fail-closed, jamais 0 ni « tout va bien »). Un créneau sans date civile (plan appliqué mais non daté)
n'est pas mesurable : il est nommé « sans date », jamais deviné. Aucun « aucun retard » n'est jamais écrit ici :
une liste vide dit seulement qu'aucune intervention datée n'est en retard à la référence donnée.

D'OÙ VIENT L'HEURE D'UN FAIT (PLAN T4.27-a2). Chaque ligne dit ``origine_heure`` :

    ``serveur``   l'heure du fait est celle de RÉCEPTION du serveur : un report, une demande d'écart ou un pointage
                  reçus d'un appareil. L'âge ne dépend plus de l'horloge du téléphone qui a fait le geste ;
    ``appelant``  l'heure du fait est celle que l'appelant a écrite : un fait inscrit avant T4.27-a2 (ces faits gardent
                  leur heure, le registre est immuable), ou par un agent, la console ou une demande approuvée. Son
                  âge dépend alors de l'horloge de celui qui l'a écrite ; le relevé ne la corrige pas, il le dit.

La règle est ``horodatage.origine`` (un fait d'appareil porte ``horodatage_appareil`` à côté de son heure). Pour une
anomalie de pointage, c'est le pointage lié (``pointage_ligne_id``) qui porte ce signe : sans lui, ``appelant``, jamais
``serveur`` par défaut. La référence, elle, reste celle que l'appelant fournit : l'horloge de l'appareil de l'admin qui
lit fausse encore l'âge (M4 n'a pas d'horloge, et une lecture n'en reçoit pas du socle).

Ordre, stable : du plus ancien au plus récent (les plus en retard d'abord), puis par identifiant. Chaque liste est
bornée (``LIMITE_PAR_LISTE``) pour tenir dans une réponse d'appareil ; le reste est compté (``reste``), jamais perdu en
silence, et la liste complète se lit avec ``m4_lister_interventions`` (statut ``reportee``, paginé) et
``m4_lister_pending_review``. Aucun texte libre du terrain (périmètre, matériaux, notes) ni contact ne sort d'ici : des
identifiants, un motif, des heures."""

from __future__ import annotations

from datetime import datetime, timedelta

from . import calendrier_civil, cedule_tournees, digest, ecarts, etats, horodatage, pointage, verdicts

TYPE_RELEVE = "RETARDS_INCIDENTS"
SEUIL_BLOCAGE_HEURES = digest.SEUIL_BLOCAGE_HEURES
LIMITE_PAR_LISTE = 8
# Borne haute DÉCLARÉE par la direction (department.yaml, réglage CFG-1 `m4.tolerance_retard_cedule_minutes`). Le
# module pur ne lit pas le manifeste : la lecture (adaptateur) et le calcul refusent tous deux au-delà, pour que la
# déclaration et le runtime disent la même chose (481 n'est jamais servi ni évalué).
TOLERANCE_MAX_MINUTES = 480
# P4-04 : un créneau daté dont la fin est dépassée ne suffit pas sans la TOLÉRANCE de la direction.
MANQUE_TOLERANCE_RETARD = (
    "tolérance sur la cédule à déclarer par la direction (configuration.retard_cedule.tolerance_minutes, "
    "m4.tolerance_retard_cedule_minutes) : sans elle, le retard sur la cédule n'est pas évalué"
)
MANQUE_RETARD_SUR_CEDULE = (
    "aucun calendrier : la cédule numérote ses jours (0, 1, ...) sans date civile et le registre ne garde aucune "
    "fenêtre planifiée ; un créneau dépassé sans départ ne se détecte pas ici"
)
MANQUE_DATE_CIVILE = (
    "plan appliqué mais jour sans date civile confirmée (m4_confirmer_dates_cedule) : "
    "le retard de ce créneau n'est pas mesurable"
)
# Statuts dont le créneau daté compte encore (avant le départ ou en route) : un report a quitté son créneau,
# une intervention sur site ou terminée n'a plus de créneau à dépasser.
STATUTS_A_CRENEAU_MESURABLE = ("planifiee", "en_route")

__all__ = [
    "LIMITE_PAR_LISTE",
    "MANQUE_DATE_CIVILE",
    "MANQUE_RETARD_SUR_CEDULE",
    "MANQUE_TOLERANCE_RETARD",
    "SEUIL_BLOCAGE_HEURES",
    "STATUTS_A_CRENEAU_MESURABLE",
    "TOLERANCE_MAX_MINUTES",
    "TYPE_RELEVE",
    "attente_tolerance_retard",
    "incidents_ouverts",
    "lire",
    "presenter",
    "reports_courants",
    "retards_cedule",
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
    """Les reports EN COURS : ``[{intervention_id, motif, depuis, origine_heure}]``, une entrée par intervention au
    statut ``reportee``.

    ``instantane`` : un objet qui a ``lire()`` (un registre, ou ``cedule_tournees.instantane_du_registre``). Le statut
    courant est celui de ``etats.lister_interventions`` (une seule définition de « reportée maintenant ») ; le motif,
    l'heure et son origine (``serveur`` ou ``appelant``) sont ceux de la DERNIÈRE transition de report de
    l'intervention. Lecture pure."""
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
        {
            "intervention_id": identifiant,
            "motif": maillon["motif"],
            "depuis": maillon["horodatage"],
            "origine_heure": horodatage.origine(maillon),
        }
        for identifiant, maillon in derniers.items()
    ]


def _origine_de_la_demande(demande, pointages):
    """``serveur`` ou ``appelant`` : d'où vient l'heure d'une demande de revue ouverte.

    Une demande d'écart porte elle-même le signe de l'appareil (``m4_creer_demande_ecart``). Une anomalie de pointage
    est née de son pointage, dont elle prend l'heure : c'est ce pointage (``pointage_ligne_id``) qui le porte, même pour
    une anomalie d'avant T4.27-a2 (le pointage garde l'heure du serveur depuis T1.4-d). Pointage introuvable : le
    signe manque, donc ``appelant`` (jamais ``serveur`` sans preuve)."""
    if demande.get("type_demande") == pointage.TYPE_REVUE_ANOMALIE:
        return horodatage.origine(pointages.get(demande.get("pointage_ligne_id")))
    return horodatage.origine(demande)


def incidents_ouverts(instantane):
    """Les demandes de revue sans résolution : ``[{demande_id, intervention_id, type_demande, depuis, origine_heure}]``.
    Lecture pure."""
    pointages = {
        maillon["ligne_id"]: maillon
        for maillon in instantane.lire()
        if maillon["type_entree"] == pointage.TYPE_POINTAGE
    }
    return [
        {
            "demande_id": demande["demande_id"],
            "intervention_id": demande["intervention_id"],
            "type_demande": demande["type_demande"],
            "depuis": demande["horodatage"],
            "origine_heure": _origine_de_la_demande(demande, pointages),
        }
        for demande in ecarts.lister_pending_review(instantane)
    ]


def attente_tolerance_retard(tolerance_minutes, depuis=""):
    """L'attente « tolérance à déclarer » pour la file de l'admin (P4-04), ou ``None`` si elle est déclarée.

    ``tolerance_minutes`` : la valeur lue par l'adaptateur (``None`` = absente ou illisible). Sans elle, la règle
    « retard sur la cédule » est « non évaluée » (``retards_cedule`` et ``lire`` disent quoi déclarer, jamais 0) :
    cette attente N2 le rappelle dans la file, avec le geste (déclarer la tolérance, N3). Tolérance déclarée :
    le retard se mesure, aucune attente. Une valeur hors de ``0..TOLERANCE_MAX_MINUTES`` est illisible comme une
    absence (jamais servie). Pure : ne lit ni le registre ni l'horloge (``depuis`` laissée vide)."""
    if type(tolerance_minutes) is int and 0 <= tolerance_minutes <= TOLERANCE_MAX_MINUTES:
        return None
    return {
        "type": "tolerance_retard_a_configurer",
        "id": "tolerance_retard_a_configurer",
        "resume": (
            "Tolérance de retard non déclarée : le retard sur la cédule n'est pas évalué "
            "(m4_lire_retards_incidents, bloc retards_cedule « non évalué »). "
            "Déclarer configuration.retard_cedule.tolerance_minutes, en minutes."
        ),
        "niveau": "N2",
        "depuis": depuis,
        "action_proposee": (
            "Déclarer la tolérance (réglage de direction m4.tolerance_retard_cedule_minutes, "
            "geste N3 du propriétaire)"
        ),
    }


def _suite(reste, outil):
    if not reste:
        return None
    return f"{reste} de plus, du moins ancien au plus récent : {outil} les rend tous"


def _minutes_de_retard(fin_creneau_texte, reference, tolerance_minutes):
    """Minutes entières de retard d'un créneau daté à la référence, au-delà de la tolérance ; ``None`` à l'heure.

    ``fin_creneau_texte`` : fin ISO 8601 avec fuseau du créneau daté (``calendrier_civil``). Illisible ou sans
    fuseau : ``None`` (le créneau est « sans date », jamais deviné). Une référence antérieure à la fin + tolérance,
    ou un dépassement de moins d'une minute pleine, donne ``None`` : jamais un nombre négatif, jamais zéro."""
    try:
        fin = _instant(fin_creneau_texte)
    except ValueError:
        return None
    if fin.tzinfo is None:
        return None
    ecart = reference - fin - timedelta(minutes=tolerance_minutes)
    if ecart < timedelta(minutes=1):
        return None
    return int(ecart.total_seconds() // 60)


def retards_cedule(registre_cible, horodatage_reference, tolerance_minutes):
    """Le retard mesurable sur la cédule datée (P4-04), ou ``(None, verdict)``.

    ``tolerance_minutes`` : tolérance DÉCLARÉE par la direction (entière entre 0 et
    ``TOLERANCE_MAX_MINUTES``) ; ``None`` ou hors bornes : règle « non évaluée » (fail-closed,
    ``REJ-RETARD-TOLERANCE-A-DECLARER``, jamais un relevé sans dire quoi déclarer). Chaque ligne :
    l'intervention, son créneau daté (début, fin, équipe, validité), son statut courant et ``statut_retard``
    (``en_retard`` ou ``a_l_heure``), les minutes de retard (``None`` à l'heure, jamais zéro ni négatif). Les
    interventions sans créneau daté (plan non daté, report en cours, sur site, terminée, annulée) ne sont pas
    mesurables : elles sont comptées ``sans_date``, jamais devinées — y compris celles que la projection range
    d'emblée « sans date ». Un calendrier civil illisible rend un verdict (``REJ-REGISTRE-INVALIDE``), jamais une
    cédule vide « évaluée à zéro ». Aucun nom d'employé, aucune position, aucun texte libre du terrain. Une référence
    antérieure à la fin + tolérance donne « à l'heure », jamais un nombre négatif ; une fin illisible donne « sans
    date », jamais un retard deviné."""
    try:
        horodatage.valider_horodatage(horodatage_reference)
    except ValueError:
        return None, verdicts.construire_verdict(
            "REJ-HORODATAGE-INVALIDE",
            detail="horodatage_reference : une heure ISO 8601 avec fuseau est attendue (ex. 2026-09-29T09:00:00-04:00)",
        )
    if (tolerance_minutes is None or type(tolerance_minutes) is not int
            or not 0 <= tolerance_minutes <= TOLERANCE_MAX_MINUTES):
        return None, verdicts.construire_verdict(
            "REJ-RETARD-TOLERANCE-A-DECLARER",
            detail=MANQUE_TOLERANCE_RETARD,
        )
    reference = _instant(horodatage_reference)
    try:
        lignes_datees, sans_date_projection = calendrier_civil._projection(calendrier_civil._index(registre_cible))
    except (cedule_tournees.PreuvePlanInvalide, ValueError, KeyError):
        return None, verdicts.construire_verdict(
            "REJ-REGISTRE-INVALIDE",
            detail="calendrier civil illisible : " + MANQUE_DATE_CIVILE,
        )
    par_intervention = {}
    for ligne in lignes_datees:
        par_intervention.setdefault(ligne["intervention_id"], []).append(ligne)
    lignes, en_retard, sans_date = [], 0, len(sans_date_projection)
    for identifiant in sorted(par_intervention):
        for ligne in sorted(par_intervention[identifiant], key=lambda creneau: creneau["debut"]):
            if ligne["statut"] not in STATUTS_A_CRENEAU_MESURABLE or ligne["validite"] != "date_confirmee":
                sans_date += 1
                continue
            try:
                fin = _instant(ligne["fin"])
            except ValueError:
                fin = None
            if fin is None or fin.tzinfo is None:
                sans_date += 1
                continue
            minutes = _minutes_de_retard(ligne["fin"], reference, tolerance_minutes)
            en_retard += 1 if minutes is not None else 0
            lignes.append(
                {
                    "intervention_id": identifiant,
                    "lead_id": ligne["lead_id"],
                    "plan_id": ligne["plan_id"],
                    "equipe_id": ligne["equipe_id"],
                    "debut": ligne["debut"],
                    "fin": ligne["fin"],
                    "statut": ligne["statut"],
                    "statut_retard": "en_retard" if minutes is not None else "a_l_heure",
                    "minutes_retard": minutes,
                    "tolerance_minutes": tolerance_minutes,
                    "confirme_le": ligne["confirme_le"],
                }
            )
    # Les plus en retard d'abord (minutes décroissantes), puis les à-l'heure par début : deux tris
    # séparés, sans valeur par défaut — un `or 0` serait un repli mort (les `None` sont déjà à part).
    lignes_en_retard = sorted(
        (ligne for ligne in lignes if ligne["minutes_retard"] is not None),
        key=lambda ligne: (-ligne["minutes_retard"], ligne["debut"], ligne["intervention_id"]))
    lignes_a_l_heure = sorted(
        (ligne for ligne in lignes if ligne["minutes_retard"] is None),
        key=lambda ligne: (ligne["debut"], ligne["intervention_id"]))
    lignes = lignes_en_retard + lignes_a_l_heure
    return {
        "statut": "evalue",
        "tolerance_minutes": tolerance_minutes,
        "total": len(lignes),
        "en_retard": en_retard,
        "sans_date": sans_date,
        "lignes": lignes[:LIMITE_PAR_LISTE],
        "reste": max(len(lignes) - LIMITE_PAR_LISTE, 0),
    }, None


def lire(registre_cible, horodatage_reference, limite_par_liste=None, tolerance_minutes="__absente__"):  # noqa: E501
    """``(relevé, None)`` ou ``(None, verdict)`` : les reports en cours et les incidents ouverts, avec leur âge.

    ``horodatage_reference`` : heure ISO 8601 avec fuseau que l'appelant donne (illisible : ``REJ-HORODATAGE-INVALIDE``,
    rien n'est écrit, la fonction n'écrit jamais). ``limite_par_liste`` : ``None`` pour ``LIMITE_PAR_LISTE``.

    Le relevé porte, pour chaque liste, son ``total``, la ventilation (``par_motif``, ``par_type``), ce qui est
    ``affiches`` et ce qui ``reste`` ; pour les incidents, ``bloques`` (comptés sur TOUS, pas seulement sur ceux qui
    sont affichés). Chaque ligne dit ``origine_heure`` (``serveur`` ou ``appelant``, voir le module).
    ``tolerance_minutes`` : tolérance DÉCLARÉE par la direction (entière >= 0) pour le retard sur la cédule ;
    absente (défaut) : la règle est « non évaluée » et ``retards_cedule`` dit quoi déclarer (P4-04, fail-closed)."""
    try:
        horodatage.valider_horodatage(horodatage_reference)
    except ValueError:
        return None, verdicts.construire_verdict(
            "REJ-HORODATAGE-INVALIDE",
            detail="horodatage_reference : une heure ISO 8601 avec fuseau est attendue (ex. 2026-09-29T09:00:00-04:00)",
        )
    if tolerance_minutes == "__absente__":
        bloc_retard = {"statut": "non_evalue", "manque": MANQUE_TOLERANCE_RETARD}
    else:
        retard, _verdict_retard = retards_cedule(registre_cible, horodatage_reference, tolerance_minutes)
        if _verdict_retard is not None:
            return None, _verdict_retard
        bloc_retard = {"statut": "evalue", **retard}
    limite = LIMITE_PAR_LISTE if limite_par_liste is None else limite_par_liste
    reference = _instant(horodatage_reference)
    instantane = cedule_tournees.instantane_du_registre(registre_cible)

    reports = _plus_anciens_d_abord(reports_courants(instantane), "intervention_id")
    par_motif = {motif: 0 for motif in etats.MOTIFS_REPORT}
    for report in reports:
        # Indexation directe : le motif est validé à l'écriture (`etats.transitionner`, refusé sinon) ;
        # un motif inconnu lève `KeyError` (fort) au lieu d'inventer une case silencieuse.
        par_motif[report["motif"]] = par_motif[report["motif"]] + 1
    liste_reports = [
        {
            "intervention_id": report["intervention_id"],
            "motif": report["motif"],
            "depuis": report["depuis"],
            "origine_heure": report["origine_heure"],
            "heures_ecoulees": _heures_ecoulees(report["depuis"], reference),
        }
        for report in reports[:limite]
    ]

    incidents = _plus_anciens_d_abord(incidents_ouverts(instantane), "demande_id")
    par_type = {type_demande: 0 for type_demande in ecarts.TYPES_DEMANDE}
    bloques = 0
    for incident in incidents:
        # Indexation directe : le type est validé à l'écriture (`ecarts`) ; un type inconnu lève `KeyError`
        # (fort) au lieu d'inventer une case silencieuse.
        par_type[incident["type_demande"]] = par_type[incident["type_demande"]] + 1
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
                "origine_heure": incident["origine_heure"],
                "heures_ecoulees": heures,
                "bloquee": heures is not None and heures >= SEUIL_BLOCAGE_HEURES,
            }
        )

    releve = {
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
        "retards_cedule": bloc_retard,
    }
    if bloc_retard["statut"] != "evalue":
        # Clé historique : elle ne reste que pour le cas « non évaluée », où elle dit la même chose que le bloc
        # nouveau (aucune mesure). Quand `retards_cedule` mesure, la garder à `non_mesurable` serait une seconde
        # vérité fausse : elle est absente, et le bloc mesuré est la seule source.
        releve["retard_sur_cedule"] = {"statut": "non_mesurable", "manque": MANQUE_RETARD_SUR_CEDULE}
    return releve, None


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
