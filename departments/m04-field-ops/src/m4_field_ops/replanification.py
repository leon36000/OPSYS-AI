"""Replanification d'une intervention reportée ou perturbée (P4-05).

Module pur (stdlib et modules de M4 ; aucun import ``opsys``, aucune horloge, aucun aléa, aucun réseau ; un test le
vérifie par analyse du code). Il ne fait QUE lire et proposer l'ordre des gestes : c'est l'outil N3 qui écrit,
jamais ce module.

REPLANIFIER, c'est remettre une intervention dans le cycle : vérifier sa préparation (``preparation.evaluer``),
la refaire passer à ``planifiee`` quand elle est ``reportee`` (``etats.transitionner``, motif déjà enregistré),
puis la rendre à la cédule existante (``cedule_tournees.proposer`` avec ``intervention_ids``, puis ``appliquer``).
Le plan de secours, quand la proposition échoue, dit quoi faire sans rien inventer : garder le report avec son
motif, ou attendre la préparation « prête » (``a_fournir``). L'historique des reports (``historique_reports``) relit
les transitions ``reportee`` du registre : motifs, heures, origines — jamais de nom d'employé, jamais de position.

Seules une ``reportee`` (sortie de son créneau) ou une ``planifiee`` perturbée (préparation non prête, créneau perdu)
se replanifient : tout autre statut est refusé (fail-closed, ``REJ-REPLANIFICATION-REFUS``). Une préparation non
« prête » refuse aussi (``REJ-REPLANIFICATION-NON-PRETE``), avec ce qui manque. Une ``planifiee`` dont le créneau daté
est CONFIRMÉ ne se replanifie pas : le créneau n'est jamais déplacé (l'outil refuse avant toute écriture).
"""

from __future__ import annotations

from typing import Any

from . import etats, horodatage, preparation, verdicts

__all__ = [
    "STATUTS_REPLANIFIABLES",
    "historique_reports",
    "plan_de_secours",
    "verifier",
]

# Une reportee a quitté son créneau (à remettre dans le cycle) ; une planifiee perturbée y est encore mais sa
# préparation ne tient plus (créneau perdu, équipe ou matériel manquant).
STATUTS_REPLANIFIABLES = ("reportee", "planifiee")


def _refus(code: str, detail: str, statut: str = "") -> dict[str, Any]:
    return verdicts.construire_verdict(code, statut=statut, detail=detail)


def verifier(registre_cible, intervention_id, lire_position, lire_equipes=None, lire_meteo=None,
             lire_creneau_confirme=None):
    """``(dossier, None)`` ou ``(None, verdict)`` : la replanification est-elle possible, et que manque-t-il.

    ``lire_creneau_confirme(registre, intervention_id)`` : lecture du créneau daté CONFIRMÉ de l'intervention
    (``calendrier_civil.creneau_confirme``), ou ``None``. Un créneau confirmé ne se déplace jamais : la replanification
    est refusée (``REJ-REPLANIFICATION-REFUS``) avant toute écriture. Sans ce lecteur, le contrôle n'est pas fait
    (compatibilité des appels qui ne replanifient pas une ``planifiee`` datée).

    ``dossier`` : ``intervention_id``, ``statut`` courant, ``preparation`` (verdict complet), ``historique``
    (les reports passés), ``prochaine_etape`` (``repasser_planifiee`` pour une ``reportee`` prête,
    ``reproposer_cedule`` pour une ``planifiee`` prête). Refus : intervention inconnue ou statut non
    replanifiable (``REJ-REPLANIFICATION-REFUS``) ; créneau confirmé (``REJ-REPLANIFICATION-REFUS``) ; préparation non
    « prête » (``REJ-REPLANIFICATION-NON-PRETE``, avec ``a_fournir``). Rien n'est écrit, rien n'est promis."""
    statut = etats.statut_courant(registre_cible, intervention_id)
    if statut is None:
        return None, _refus("REJ-REPLANIFICATION-REFUS", f"intervention {intervention_id!r} inconnue")
    if statut not in STATUTS_REPLANIFIABLES:
        return None, _refus(
            "REJ-REPLANIFICATION-REFUS",
            f"replanification sans objet : l'intervention est {statut} "
            f"(attendu : {', '.join(STATUTS_REPLANIFIABLES)})",
            statut=statut,
        )
    if lire_creneau_confirme is not None:
        creneau = lire_creneau_confirme(registre_cible, intervention_id)
        if creneau is not None:
            return None, _refus(
                "REJ-REPLANIFICATION-REFUS",
                f"créneau déjà confirmé du {creneau['debut']} au {creneau['fin']} : un créneau confirmé n'est "
                "jamais déplacé ; aucune replanification n'est écrite (signaler un report d'abord si le créneau "
                "ne tient plus)",
                statut=statut,
            )
    verdict_preparation, refus = preparation.evaluer(
        registre_cible, intervention_id, lire_position, lire_equipes, lire_meteo)
    if refus is not None:
        return None, _refus(
            "REJ-REPLANIFICATION-NON-PRETE",
            f"préparation illisible : {refus.get('detail', refus.get('code'))}",
            statut=statut,
        )
    if not verdict_preparation["pret"]:
        return None, _refus(
            "REJ-REPLANIFICATION-NON-PRETE",
            "préparation non « prête » : "
            + "; ".join(
                f"{item['volet']} ({item['statut']}) : {item['manque']}"
                for item in verdict_preparation["a_fournir"]
            )
            + " (m4_verifier_preparation dit ce qui manque)",
            statut=statut,
        )
    return {
        "intervention_id": intervention_id,
        "statut": statut,
        "preparation": verdict_preparation,
        "historique": historique_reports(registre_cible, intervention_id),
        "prochaine_etape": "repasser_planifiee" if statut == "reportee" else "reproposer_cedule",
    }, None


def plan_de_secours(dossier_ou_statut, raison: str = ""):
    """Le plan de secours quand la replanification ne peut pas aboutir : garder le report, attendre, revalider.

    ``dossier_ou_statut`` : le dossier rendu par ``verifier``, ou un statut seul (sans dossier vérifié, le secours
    reste « attendre »). Ne propose jamais une date, une équipe ni un créneau : seulement l'étape à refaire et
    pourquoi. Pur : aucune écriture."""
    dossier = dossier_ou_statut if isinstance(dossier_ou_statut, dict) else {}
    statut = dossier.get("statut", dossier_ou_statut if isinstance(dossier_ou_statut, str) else "?")
    historique = dossier.get("historique", []) if isinstance(dossier, dict) else []
    dernier_motif = historique[-1]["motif"] if historique else None
    if dernier_motif is not None:
        conseil = (
            f"garder le report (motif {dernier_motif}) et attendre sa levée, "
            "puis revalider la préparation avant toute proposition"
        )
    elif statut == "planifiee":
        conseil = "garder la planification et revalider la préparation avant toute nouvelle proposition"
    else:
        conseil = "garder l'état courant et revalider la préparation avant toute proposition"
    if raison:
        conseil += f" : {raison}"
    return {
        "statut": statut,
        "secours": "attendre",
        "conseil": conseil,
        "reports_passes": len(historique),
        "a_fournir": list(dossier.get("preparation", {}).get("a_fournir", [])),
    }


def historique_reports(registre_cible, intervention_id):
    """Les reports passés d'une intervention : ``[{motif, horodatage, origine_heure}]``, du plus ancien au récent.

    Relit les transitions ``reportee`` du registre (motif fermé, heure gardée, origine serveur/appelant). Aucun nom,
    aucune position, aucun texte libre. L'ordre est celui de l'HEURE (pas celui de l'append) : un report antidaté par
    la console, un agent ou une reprise ne devient donc pas le « dernier » motif du plan de secours. Intervention
    inconnue : liste vide, jamais une erreur."""
    passe = []
    for maillon in registre_cible.lire():
        if (maillon.get("type_entree") == etats.TYPE_TRANSITION
                and maillon.get("intervention_id") == intervention_id
                and maillon.get("statut") == "reportee"):
            try:
                heure = horodatage.instant(maillon.get("horodatage", ""))
            except ValueError:
                continue
            passe.append((heure, {
                "motif": maillon.get("motif"),
                "horodatage": maillon.get("horodatage"),
                "origine_heure": horodatage.origine(maillon),
            }))
    passe.sort(key=lambda entree: entree[0])
    return [entree for _heure, entree in passe]
