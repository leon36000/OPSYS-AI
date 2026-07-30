"""
Machine à états de l'intervention pour M4 – S004.

Ce module implémente la table des transitions RATIFIÉE du PRD (M4-S004).
Les conditions sémantiques des chemins (pointage cohérent, fix GPS, écart détecté,
validation humaine) sont vérifiées par les modules appelants.
Cette machine garantit uniquement la fermeture de l’énuméré et de la table,
pas les faits de terrain.
"""

import copy
from . import cedule
from . import contrats
from . import horodatage
from . import verdicts
from . import encodage
# registre n’est pas importé en tant que module car on n’en utilise que les instances passées.

# ---------------------------------------------------------------------------
# Constantes épinglées
# ---------------------------------------------------------------------------
ETATS = (
    "planifiee",
    "en_route",
    "sur_site",
    "en_revue",
    "reportee",
    "terminee",
    "annulee",
)
ETATS_TERMINAUX = ("terminee", "annulee")
MOTIFS_REPORT = ("client_absent", "meteo", "decision_admin")
TRANSITIONS_AUTORISEES = (
    ("planifiee", "en_route"),
    ("planifiee", "reportee"),
    ("planifiee", "annulee"),
    ("en_route", "sur_site"),
    ("en_route", "reportee"),
    ("en_route", "annulee"),
    ("sur_site", "en_revue"),
    ("sur_site", "terminee"),
    ("en_revue", "terminee"),
    ("en_revue", "annulee"),
    ("en_revue", "sur_site"),
    ("reportee", "planifiee"),
    ("reportee", "annulee"),
)

TYPE_INSCRIPTION = "intervention_inscrite"
TYPE_TRANSITION = "transition_statut"

__all__ = [
    "ETATS",
    "ETATS_TERMINAUX",
    "MOTIFS_REPORT",
    "TRANSITIONS_AUTORISEES",
    "TYPE_INSCRIPTION",
    "TYPE_TRANSITION",
    "statut_courant",
    "inscrire_intervention",
    "transitionner",
]

# ---------------------------------------------------------------------------
# Fonctions publiques
# ---------------------------------------------------------------------------

def statut_courant(registre_cible, intervention_id):
    """
    Calcule le statut actuel d’une intervention en rejouant le registre.

    Args:
        registre_cible: instance de Registre.
        intervention_id: identifiant de l’intervention.

    Returns:
        Le dernier statut rencontré, ou None si l’intervention est inexistante.
    """
    dernier_statut = None
    for maillon in registre_cible.lire():
        if maillon["type_entree"] not in (TYPE_INSCRIPTION, TYPE_TRANSITION):
            continue
        if maillon.get("intervention_id") != intervention_id:
            continue
        dernier_statut = maillon["statut"]
    return dernier_statut


def inscrire_intervention(contrat, marqueur, registre_cible, horodatage_arg, sel):
    """
    Enregistre une nouvelle intervention (transition vide → planifiee).

    Args:
        contrat: dict validé par contrats.valider_entree.
        marqueur: dict de readiness.
        registre_cible: instance de Registre.
        horodatage_arg: horodatage chaîne (RFC 3339 avec fuseau).
        sel: sel de tokenisation de la ville, fourni par l’appelant (obligatoire).

    Returns:
        (accusé, None) en cas de succès, ou (None, verdict) en cas d’échec.
    """
    # 1. Validation du contrat + marqueur
    ok, verdict = contrats.valider_entree(contrat, marqueur)
    if not ok:
        return None, verdict  # verdict déjà construit

    # 1 bis. Le sel de tokenisation est OBLIGATOIRE : une empreinte nue de nom de
    # ville est attaquable par dictionnaire (quelques milliers de villes).
    if not isinstance(sel, str) or sel == "":
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="sel de tokenisation absent"
        )

    # 2. Validation de l’horodatage
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")

    # 3. Génération de l’identifiant d’intervention
    intervention_id = encodage.empreinte(
        "intervention", contrat["lead_id"], horodatage_arg
    )

    # 4. Vérification de non‑réinscription
    if statut_courant(registre_cible, intervention_id) is not None:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail=(
                "intervention déjà inscrite : l'inscription est la transition "
                "vide->planifiee, fermée depuis un état existant"
            ),
        )

    # 5. Construction du maillon d’inscription
    # INTERDIT ABSOLU : ne jamais copier contrat["contact"] (données personnelles)
    maillon = {
        "type_entree": TYPE_INSCRIPTION,
        "intervention_id": intervention_id,
        "lead_id": copy.deepcopy(contrat["lead_id"]),
        "conversation_id": copy.deepcopy(contrat["conversation_id"]),
        "type_travaux": copy.deepcopy(contrat["type_travaux"]),
        # Architecture §2 : l'entité Intervention porte la ville TOKENISÉE.
        # Le registre est immuable : une ville en clair y serait irrattrapable.
        "ville_tokenisee": cedule.tokeniser_ville(sel, contrat["ville"]),
        "urgence_declaree": copy.deepcopy(contrat["urgence_declaree"]),
        "statut": "planifiee",
        "horodatage": horodatage_arg,
        "empreinte_contrat": encodage.empreinte(contrat),
        "empreinte_marqueur": encodage.empreinte(marqueur),
    }

    # 6. Écriture dans le registre, puis relecture PAR ligne_id (hash, pas un index)
    ligne_id = registre_cible.ajouter(maillon)
    maillon_relu = None
    for m in registre_cible.lire():
        if m.get("ligne_id") == ligne_id:
            maillon_relu = m
            break
    if maillon_relu is None:
        raise RuntimeError(
            "Incohérence interne : l’entrée ajoutée est introuvable dans le registre."
        )

    # 7. Fabrication de l’accusé
    accuse = {
        "intervention_id": intervention_id,
        "ligne_id": ligne_id,
        "statut": "planifiee",
        "empreinte_maillon": encodage.empreinte(maillon_relu),
        "tete_chaine": registre_cible.tete(),
        "horodatage": horodatage_arg,
    }
    return accuse, None


def transitionner(
    intervention_id, statut_cible, registre_cible, horodatage_arg, motif=None
):
    """
    Effectue une transition d’état pour une intervention existante.

    Args:
        intervention_id: identifiant de l’intervention.
        statut_cible: état visé (doit appartenir à ETATS).
        registre_cible: instance de Registre.
        horodatage_arg: horodatage chaîne (RFC 3339 avec fuseau).
        motif: obligatoire pour un report, interdit sinon.

    Returns:
        (accusé, None) en cas de succès, ou (None, verdict) en cas d’échec.
    """
    # 1. Horodatage
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")

    # 2. Existence de l’intervention
    courant = statut_courant(registre_cible, intervention_id)
    if courant is None:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE", detail="intervention inexistante"
        )

    # 3. validité de la cible dans l’énuméré
    if statut_cible not in ETATS:
        return None, verdicts.construire_verdict(
            "REJ-ENUM-INVALIDE",
            statut=courant,
            detail=f"statut_cible invalide : {statut_cible}",
        )

    # 4. État terminal interdit comme départ
    if courant in ETATS_TERMINAUX:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail=f"transition impossible depuis un état terminal ({courant})",
        )

    # 5. Vérification dans la table des transitions autorisées
    if (courant, statut_cible) not in TRANSITIONS_AUTORISEES:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail=f"transition non autorisée : {courant} -> {statut_cible}",
        )

    # 6. Contrôle du motif
    if statut_cible == "reportee":
        if motif not in MOTIFS_REPORT:
            return None, verdicts.construire_verdict(
                "REJ-ENUM-INVALIDE",
                statut=courant,
                detail=f"motif de report invalide ou manquant : {motif}",
            )
    else:
        if motif is not None:
            return None, verdicts.construire_verdict(
                "REJ-ENUM-INVALIDE",
                statut=courant,
                detail="motif réservé au report",
            )

    # 7. Construction du maillon de transition
    maillon = {
        "type_entree": TYPE_TRANSITION,
        "intervention_id": intervention_id,
        "statut": statut_cible,
        "statut_precedent": courant,
        "horodatage": horodatage_arg,
    }
    if statut_cible == "reportee":
        maillon["motif"] = motif

    # 8. Écriture, puis relecture PAR ligne_id (hash, pas un index)
    ligne_id = registre_cible.ajouter(maillon)
    maillon_relu = None
    for m in registre_cible.lire():
        if m.get("ligne_id") == ligne_id:
            maillon_relu = m
            break
    if maillon_relu is None:
        raise RuntimeError(
            "Incohérence interne : l’entrée ajoutée est introuvable dans le registre."
        )

    # 9. Accusé
    accuse = {
        "intervention_id": intervention_id,
        "ligne_id": ligne_id,
        "statut": statut_cible,
        "statut_precedent": courant,
        "empreinte_maillon": encodage.empreinte(maillon_relu),
        "tete_chaine": registre_cible.tete(),
        "horodatage": horodatage_arg,
    }
    return accuse, None
