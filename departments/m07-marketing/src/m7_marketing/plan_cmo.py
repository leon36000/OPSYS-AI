"""Projection M7.11a d'actions préparatoires, déterministe et sans prévision."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

VERSION_REGLES = "m7-cmo-regles.v1"
LIMITE_SOURCES = 100


def date_iso(valeur: Any, nom: str) -> date:
    if not isinstance(valeur, str) or len(valeur) != 10:
        raise ValueError(f"{nom}_INVALIDE")
    try:
        resultat = date.fromisoformat(valeur)
    except ValueError as exc:
        raise ValueError(f"{nom}_INVALIDE") from exc
    if resultat.isoformat() != valeur:
        raise ValueError(f"{nom}_INVALIDE")
    return resultat


def _bornes(valeurs: Sequence[Any]) -> tuple[list[Any], bool, int]:
    total = len(valeurs)
    return list(valeurs[:LIMITE_SOURCES]), total > LIMITE_SOURCES, total


def _date_creneau(valeur: Any) -> date:
    if not isinstance(valeur, str):
        raise ValueError("CALENDRIER_DATE_SOURCE_INVALIDE")
    try:
        instant = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("CALENDRIER_DATE_SOURCE_INVALIDE") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("CALENDRIER_DATE_SOURCE_SANS_FUSEAU")
    return instant.date()


def projeter(
    *,
    date_depart: str,
    debut: str,
    fin: str,
    profil_marque: Mapping[str, Any],
    calendrier: Mapping[str, Any],
    performance: Mapping[str, Any],
) -> dict[str, Any]:
    """Projette observations M7 en fenêtres calendaires et actions à arbitrer.

    Les sources sont exclusivement les résultats des trois outils M7 T0. Les indicateurs
    absents restent absents et aucune somme, prévision ou dépense cible n'est calculée ici.
    """
    depart = date_iso(date_depart, "DATE_DEPART")
    periode_debut, periode_fin = date_iso(debut, "DEBUT"), date_iso(fin, "FIN")
    if periode_debut > periode_fin:
        raise ValueError("PERIODE_INVERSEE")
    if (periode_fin - periode_debut).days > 365:
        raise ValueError("PERIODE_TROP_LONGUE")
    if depart > date.max - timedelta(days=89):
        raise ValueError("HORIZON_DATE_DEPASSE")
    if not isinstance(profil_marque, Mapping) or not isinstance(calendrier, Mapping):
        raise ValueError("SOURCE_M7_INVALIDE")
    if not isinstance(performance, Mapping):
        raise ValueError("SOURCE_PERFORMANCE_INVALIDE")

    statut_marque = profil_marque.get("statut")
    if not isinstance(statut_marque, str) or not statut_marque:
        raise ValueError("SOURCE_PROFIL_MARQUE_INVALIDE")
    revision_marque = profil_marque.get("revision")
    marque_source = {
        "outil": "m7_lire_profil_marque_courant",
        "statut": statut_marque,
        "revision": revision_marque if type(revision_marque) is int and revision_marque > 0 else None,
    }

    creneaux_source = calendrier.get("creneaux")
    if not isinstance(creneaux_source, list) or any(not isinstance(item, Mapping) for item in creneaux_source):
        raise ValueError("SOURCE_CALENDRIER_INVALIDE")
    creneaux, calendrier_tronque, total_creneaux = _bornes(creneaux_source)
    parsed_slots = []
    for slot in creneaux:
        planifie_le = slot.get("planifie_le")
        if planifie_le is None:
            # L'absence d'échéance est une source incomplète; elle n'est pas imputée à une fenêtre.
            parsed_slots.append({"slot": slot, "date": None})
        else:
            parsed_slots.append({"slot": slot, "date": _date_creneau(planifie_le)})

    periode_performance = performance.get("periode")
    if not isinstance(periode_performance, Mapping):
        raise ValueError("SOURCE_PERFORMANCE_PERIODE_ABSENTE")
    if periode_performance.get("debut") != debut or periode_performance.get("fin") != fin:
        raise ValueError("SOURCE_PERFORMANCE_PERIODE_DIFFERENTE")
    couverture = performance.get("couverture")
    if not isinstance(couverture, str) or not couverture:
        raise ValueError("SOURCE_PERFORMANCE_COUVERTURE_ABSENTE")
    campagnes_source = performance.get("campagnes")
    refs_source = performance.get("source_refs")
    manques_source = performance.get("manque")
    if not isinstance(campagnes_source, list) or any(not isinstance(item, Mapping) for item in campagnes_source):
        raise ValueError("SOURCE_PERFORMANCE_CAMPAGNES_INVALIDE")
    if not isinstance(refs_source, list) or not isinstance(manques_source, list):
        raise ValueError("SOURCE_PERFORMANCE_REFERENCES_INCOMPLETES")
    campagnes_brutes, campagnes_tronque, total_campagnes = _bornes(campagnes_source)
    campagnes = []
    references_campagnes_tronquees = False
    for campagne in campagnes_brutes:
        refs_campagne = campagne.get("source_refs")
        manque_campagne = campagne.get("manque")
        if not isinstance(refs_campagne, list) or not isinstance(manque_campagne, list):
            raise ValueError("SOURCE_PERFORMANCE_CAMPAGNE_INCOMPLETE")
        if any(not isinstance(item, str) or not item for item in manque_campagne):
            raise ValueError("SOURCE_PERFORMANCE_MANQUE_INVALIDE")
        refs_bornees, refs_campagne_tronquees, refs_campagne_total = _bornes(refs_campagne)
        manque_borne, manque_campagne_tronque, manque_campagne_total = _bornes(manque_campagne)
        references_campagnes_tronquees = (
            references_campagnes_tronquees or refs_campagne_tronquees or manque_campagne_tronque
        )
        campagnes.append({
            "source": campagne.get("source"),
            "campagne": campagne.get("campagne"),
            "leads_associes_observes": campagne.get("leads_associes_observes"),
            "devis_acceptes": campagne.get("devis_acceptes"),
            "chantiers_marge_constatee": campagne.get("chantiers_marge_constatee"),
            "marge_constatee_M5_cad": campagne.get("marge_constatee_M5_cad"),
            "statut_financier": campagne.get("statut_financier"),
            "couverture": campagne.get("couverture"),
            "manque": manque_borne,
            "manques_observes_total": manque_campagne_total,
            "manques_tronques": manque_campagne_tronque,
            "source_refs": refs_bornees,
            "source_refs_observees_total": refs_campagne_total,
            "source_refs_tronquees": refs_campagne_tronquees,
            "cout_ads_cad": campagne.get("cout_ads_cad"),
            "cout_par_lead_cad": campagne.get("cout_par_lead_cad"),
            "roi": campagne.get("roi"),
        })
    refs, refs_tronque, total_refs = _bornes(refs_source)
    manque, manque_tronque, total_manques = _bornes(manques_source)
    if any(not isinstance(item, str) or not item for item in manque):
        raise ValueError("SOURCE_PERFORMANCE_MANQUE_INVALIDE")
    exclusions = performance.get("exclusions")
    if not isinstance(exclusions, Mapping):
        raise ValueError("SOURCE_PERFORMANCE_EXCLUSIONS_ABSENTES")

    fenetres = []
    actions = []
    for ident, offset in (("J1-30", 0), ("J31-60", 30), ("J61-90", 60)):
        debut_fenetre = depart + timedelta(days=offset)
        fin_fenetre = debut_fenetre + timedelta(days=29)
        slots_fenetre = [
            item["slot"] for item in parsed_slots
            if item["date"] is not None and debut_fenetre <= item["date"] <= fin_fenetre
        ]
        slots_sans_date = sum(1 for item in parsed_slots if item["date"] is None)
        slot_ids = [slot.get("creneau_id") for slot in slots_fenetre if isinstance(slot.get("creneau_id"), str)]
        if calendrier_tronque and not slots_fenetre:
            statut_calendrier = "INDETERMINE_SOURCE_TRONQUEE"
        elif calendrier_tronque:
            statut_calendrier = "OBSERVE_SOURCE_TRONQUEE"
        elif slots_sans_date:
            statut_calendrier = "INDETERMINE_DATE_ABSENTE"
        else:
            statut_calendrier = "OBSERVE" if slots_fenetre else "AUCUN_CRENEAU_OBSERVE"
        fenetres.append({
            "id": ident,
            "debut": debut_fenetre.isoformat(),
            "fin": fin_fenetre.isoformat(),
            "calendrier": {
                "statut": statut_calendrier,
                "references": slot_ids[:LIMITE_SOURCES],
                "references_tronquees": len(slot_ids) > LIMITE_SOURCES or calendrier_tronque,
                "creneaux_sans_date_observable": slots_sans_date if slots_sans_date else None,
            },
            "performance": {"periode_observee": {"debut": debut, "fin": fin}, "couverture": couverture},
        })
        if slots_sans_date and not calendrier_tronque:
            actions.append({
                "regle": "CALENDRIER_DATE_A_COMPLETER_V1",
                "fenetre": ident,
                "action": "Compléter la date des créneaux sans échéance avant de conclure sur cette fenêtre.",
                "motif": "La date source est absente; ces créneaux ne peuvent être rattachés à aucune fenêtre.",
                "sources": [{
                    "outil": "m7_lister_calendrier",
                    "statut_observe": statut_calendrier,
                    "references": slot_ids,
                    "creneaux_sans_date_observable": slots_sans_date,
                }],
                "statut": "a_arbitrer",
            })
        elif calendrier_tronque:
            actions.append({
                "regle": "CALENDRIER_SOURCE_A_COMPLETER_V1",
                "fenetre": ident,
                "action": "Vérifier la liste complète des créneaux avant de conclure sur cette fenêtre.",
                "motif": "La source calendrier a été bornée; l'absence de créneau n'est pas établie.",
                "sources": [{
                    "outil": "m7_lister_calendrier",
                    "statut_observe": statut_calendrier,
                    "references": slot_ids,
                    "references_tronquees": calendrier_tronque,
                }],
                "statut": "a_arbitrer",
            })
        elif not slots_fenetre:
            actions.append({
                "regle": "CALENDRIER_A_REVOIR_V1",
                "fenetre": ident,
                "action": "Réviser et, si utile, proposer des créneaux éditoriaux pour cette période.",
                "motif": "Aucun créneau avec date vérifiable n'est observé dans la fenêtre.",
                "sources": [{
                    "outil": "m7_lister_calendrier",
                    "statut_observe": statut_calendrier,
                    "references": slot_ids,
                    "references_tronquees": calendrier_tronque,
                }],
                "statut": "a_arbitrer",
            })

    if statut_marque != "configure":
        actions.insert(0, {
            "regle": "PROFIL_MARQUE_A_CONFIGURER_V1",
            "fenetre": "J1-30",
            "action": "Réviser et configurer le profil de marque avant de proposer des contenus.",
            "motif": "Le registre M7 ne fournit pas de profil de marque configuré.",
            "sources": [marque_source],
            "statut": "a_arbitrer",
        })
    if couverture != "COMPLETE" or manque:
        actions.insert(0 if statut_marque == "configure" else 1, {
            "regle": "COMPLETER_BASELINE_SOURCEE_V1",
            "fenetre": "J1-30",
            "action": "Compléter ou vérifier les sources manquantes avant toute comparaison de rendement.",
            "motif": "La couverture des observations n'est pas complète ou M7 signale des manques.",
            "sources": [{
                "outil": "m7_lire_performance_campagnes",
                "periode": {"debut": debut, "fin": fin},
                "couverture": couverture,
                "manques": manque,
                "manques_tronques": manque_tronque,
                "references": refs,
                "references_tronquees": refs_tronque,
            }],
            "statut": "a_arbitrer",
        })

    fin_par_fenetre = {fenetre["id"]: fenetre["fin"] for fenetre in fenetres}
    for action in actions:
        action["date_arbitrage"] = fin_par_fenetre[action["fenetre"]]
        action["date_arbitrage_regle"] = "fin_fenetre"

    manques_projection = list(manque)
    if statut_marque != "configure":
        manques_projection.append("PROFIL_MARQUE_NON_CONFIGURE")
    if calendrier_tronque:
        manques_projection.append("CALENDRIER_SOURCE_TRONQUEE")
    if any(item["date"] is None for item in parsed_slots):
        manques_projection.append("CALENDRIER_DATE_ABSENTE")
    elif not creneaux_source:
        manques_projection.append("CALENDRIER_AUCUN_CRENEAU_OBSERVE")
    if campagnes_tronque:
        manques_projection.append("CAMPAGNES_SOURCE_TRONQUEE")
    if refs_tronque or references_campagnes_tronquees:
        manques_projection.append("REFERENCES_SOURCE_TRONQUEES")

    return {
        "type": "PLAN_CMO_PREPARATOIRE",
        "version_regles": VERSION_REGLES,
        "regle_date_arbitrage": {
            "date": "fin_fenetre",
            "qualification": "Date proposée pour arbitrage; elle ne constitue ni prévision ni échéance imposée.",
        },
        "date_depart": date_depart,
        "periode_observee": {"debut": debut, "fin": fin},
        "fenetres": fenetres,
        "profil_marque": marque_source,
        "performance": {
            "periode": {"debut": debut, "fin": fin},
            "couverture": couverture,
            "campagnes": campagnes,
            "campagnes_observees_total": total_campagnes,
            "campagnes_tronquees": campagnes_tronque,
            "references_campagnes_tronquees": references_campagnes_tronquees,
            "manque": manque,
            "manques_observes_total": total_manques,
            "manques_tronques": manque_tronque,
            "source_refs": refs,
            "source_refs_observees_total": total_refs,
            "source_refs_tronquees": refs_tronque,
            "exclusions": dict(exclusions),
            "couts_ads_cad": None,
            "cout_par_lead_cad": None,
            "roi": None,
            "limite_financiere": (
                "Marge M5 observée ne signifie pas encaissement; aucune dépense marketing n'est reliée."
            ),
        },
        "calendrier": {
            "outil": "m7_lister_calendrier",
            "publication": calendrier.get("publication", "non précisée par la source"),
            "creneaux_observes_total": total_creneaux,
            "references_tronquees": calendrier_tronque,
        },
        "sources": {
            "profil_marque": marque_source,
            "calendrier": {"outil": "m7_lister_calendrier", "creneaux_observes_total": total_creneaux},
            "performance": {
                "outil": "m7_lire_performance_campagnes",
                "periode": {"debut": debut, "fin": fin},
                "source_refs": refs,
                "source_refs_observees_total": total_refs,
                "source_refs_tronquees": refs_tronque,
            },
        },
        "manques": list(dict.fromkeys(manques_projection)),
        "actions": actions,
        "limites": [
            "Horizon de travail calendaire, pas une prévision de résultat.",
            "Aucun score, budget, dépense ou retour futur calculé.",
            "Les absences restent inconnues; marge M5 observée n'est pas un encaissement.",
            "Les actions sont des suggestions déterministes à arbitrer; aucune publication ni écriture n'est faite.",
            (
                "La date d'arbitrage affichée est une proposition égale à la fin de sa fenêtre, "
                "pas une échéance ni une prédiction."
            ),
        ],
        "sources_tronquees": {
            "calendrier": calendrier_tronque,
            "campagnes": campagnes_tronque,
            "references_performance": refs_tronque,
            "references_par_campagne": references_campagnes_tronquees,
            "manques_performance": manque_tronque,
        },
    }
