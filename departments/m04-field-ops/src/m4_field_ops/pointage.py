"""Pointage horodaté et géolocalisé (M4-S006).

Fonctions :
    distance_km(lat1, lon1, lat2, lon2) -> float
    enregistrer_pointage(...) -> (accusé, None) ou (None, verdict)

Constantes :
    ACTIONS, TYPE_POINTAGE, TYPE_DEMANDE_REVUE, TYPE_REVUE_ANOMALIE,
    CAUSES_NEUTRES
"""

import math
from datetime import datetime

from . import horodatage, verdicts, encodage, cedule, etats

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
ACTIONS = ("arrivee", "depart")
TYPE_POINTAGE = "pointage"
TYPE_DEMANDE_REVUE = "demande_revue"
TYPE_REVUE_ANOMALIE = "anomalie_pointage"

# Formulations neutres (CA-M4-20) : aucune notion de faute, frauder, culpabilité.
CAUSES_NEUTRES = (
    "fix_gps_hors_perimetre_declare",
    "referentiel_ville_a_verifier",
    "conditions_de_captation_a_confirmer",
)

# ---------------------------------------------------------------------------
# Fonctions publiques
# ---------------------------------------------------------------------------
def distance_km(lat1, lon1, lat2, lon2):
    """Distance orthodromique (haversine) en km entre deux points géographiques.
    Rayon terrestre = 6371.0 km.
    """
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def enregistrer_pointage(
    intervention_id,
    technicien_id,
    action,
    horodatage_arg,
    fix_gps,
    attestation,
    assignation,
    fenetre_travail,
    referentiel_villes,
    ville,
    sel,
    registre_cible,
):
    """Enregistre un pointage horodaté et géolocalisé.

    Retourne (accusé, None) en cas de succès, ou (None, verdict) si rejet.
    L'ordre des contrôles est figé, le premier échec provoque le rejet
    immédiat et rien n'est écrit au registre.

    Les données de localisation ne sont jamais conservées dans les verdicts
    de rejet (Loi 25 / CA-M4-19).
    """
    # -- 1. action valide
    if action not in ACTIONS:
        return (None, verdicts.construire_verdict("REJ-ENUM-INVALIDE",
                                                   detail=f"action={action}"))

    # -- 2. horodatage valide (fuseau obligatoire)
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return (None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE",
                                                   detail=f"horodatage invalide: {horodatage_arg}"))

    dt_pointage = datetime.fromisoformat(horodatage_arg)

    # -- 3. fenêtre de travail valide AVANT tout examen du pointage
    if not isinstance(fenetre_travail, dict) or set(fenetre_travail.keys()) != {"debut", "fin"}:
        return (None, verdicts.construire_verdict("REJ-FENETRE-INVALIDE",
                                                   detail="clés fenêtre invalides"))
    debut = fenetre_travail["debut"]
    fin = fenetre_travail["fin"]
    try:
        horodatage.valider_horodatage(debut)
        horodatage.valider_horodatage(fin)
    except ValueError:
        return (None, verdicts.construire_verdict("REJ-FENETRE-INVALIDE",
                                                   detail="bornes fenêtre sans fuseau ou format invalide"))
    dt_debut = datetime.fromisoformat(debut)
    dt_fin = datetime.fromisoformat(fin)
    if dt_debut >= dt_fin:
        return (None, verdicts.construire_verdict("REJ-FENETRE-INVALIDE",
                                                   detail="début >= fin"))

    # -- 4. Hors fenêtre -> rejet immédiat, AUCUNE donnée géographique conservée
    if dt_pointage < dt_debut or dt_pointage > dt_fin:
        detail = f"Pointage {horodatage_arg} hors fenêtre [{debut}, {fin}]"
        return (None, verdicts.construire_verdict("REJ-PUNCH-HORS-HEURES",
                                                   detail=detail))

    # -- 5. Assignation valide + correspondance technicien / intervention (CA-M4-12)
    if not isinstance(assignation, dict) or set(assignation.keys()) != {"intervention_id", "technicien_id"}:
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="assignation invalide"))
    if (assignation["intervention_id"] != intervention_id
            or assignation["technicien_id"] != technicien_id):
        return (None, verdicts.construire_verdict("REJ-PUNCH-SANS-INTERVENTION",
                                                   detail="assignation ne correspond pas"))

    # -- 5 bis. Vérification CONTRE LA CÉDULE réelle (pas seulement la
    # cohérence interne de la déclaration de l'appelant, ci-dessus). La
    # cédule effective est le champ technicien_id persisté par etats.py sur
    # LE maillon de transition planifiee -> en_route (seul point d'écriture
    # de l'assignation, validé à ce moment-là) : on y relit qui a réellement
    # été envoyé sur cette intervention, et on refuse tout pointage d'un
    # autre technicien, même si sa propre déclaration est auto-cohérente.
    technicien_assigne = None
    for m in registre_cible.lire():
        if (m.get("type_entree") == etats.TYPE_TRANSITION
                and m.get("intervention_id") == intervention_id
                and m.get("statut") == "en_route"):
            technicien_assigne = m.get("technicien_id")
    if technicien_assigne != technicien_id:
        return (None, verdicts.construire_verdict(
            "REJ-PUNCH-SANS-INTERVENTION",
            detail="assignation non confirmée par la cédule (registre)"))

    # -- 6. Statut courant compatible avec l'action
    statut_courant = etats.statut_courant(registre_cible, intervention_id)
    if action == "arrivee":
        attendu = "en_route"
    else:  # depart
        attendu = "sur_site"
    if statut_courant != attendu:
        detail = f"statut courant={statut_courant}, attendu={attendu} pour action={action}"
        return (None, verdicts.construire_verdict("REJ-PUNCH-SANS-INTERVENTION",
                                                   detail=detail))

    # -- 7. Horodatage antérieur au dernier pointage (CA-M4-07)
    derniers_pointages = [
        m for m in registre_cible.lire()
        if m.get("type_entree") == TYPE_POINTAGE
        and m.get("intervention_id") == intervention_id
    ]
    if derniers_pointages:
        dernier = derniers_pointages[-1]   # le plus récent par ordre d'écriture
        dt_dernier = datetime.fromisoformat(dernier["horodatage"])
        if dt_pointage < dt_dernier:
            return (None, verdicts.construire_verdict("REJ-HORODATAGE-ANTERIEUR",
                                                       detail=f"{horodatage_arg} < {dernier['horodatage']}"))

    # -- 8. Attestation valide (fictive obligatoire)
    if not isinstance(attestation, dict) or set(attestation.keys()) != {"fictif", "appareil_id"}:
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="attestation invalide"))
    if attestation.get("fictif") is not True:
        return (None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="attestation réelle non supportée en mode ombre"))
    appareil = attestation.get("appareil_id")
    if not isinstance(appareil, str) or appareil == "":
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="appareil_id manquant ou vide"))

    # -- 9. fix_gps valide
    if not isinstance(fix_gps, dict) or set(fix_gps.keys()) != {"latitude", "longitude"}:
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="fix_gps mal formé"))
    lat = fix_gps["latitude"]
    lon = fix_gps["longitude"]
    # valeur numérique mais pas bool
    if isinstance(lat, bool) or not isinstance(lat, (int, float)):
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="latitude non numérique"))
    if isinstance(lon, bool) or not isinstance(lon, (int, float)):
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="longitude non numérique"))
    if not (-90 <= lat <= 90):
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="latitude hors [-90, 90]"))
    if not (-180 <= lon <= 180):
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="longitude hors [-180, 180]"))

    # -- 10. ville, sel, référentiel valide
    if not isinstance(ville, str) or ville == "":
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="ville absente"))
    if not isinstance(sel, str) or sel == "":
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="sel absent"))
    token_ville = cedule.tokeniser_ville(sel, ville)
    if not isinstance(referentiel_villes, dict):
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="référentiel_villes absent"))
    if token_ville not in referentiel_villes:
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="périmètre inconnu"))
    ref = referentiel_villes[token_ville]
    if not isinstance(ref, dict) or set(ref.keys()) != {"latitude", "longitude", "rayon_km"}:
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="entrée référentiel invalide"))
    # Objection de revue (r1, Grok-4.5) : sans ce contrôle, un référentiel mal typé
    # lève TypeError dans distance_km au lieu de produire un verdict — fail-closed
    # rompu sur le chemin le plus sensible (la cohérence géographique).
    for cle_ref in ("latitude", "longitude"):
        valeur_ref = ref[cle_ref]
        if isinstance(valeur_ref, bool) or not isinstance(valeur_ref, (int, float)):
            return (None, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail=f"référentiel : {cle_ref} non numérique"))
    if not (-90 <= ref["latitude"] <= 90):
        return (None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="référentiel : latitude hors [-90, 90]"))
    if not (-180 <= ref["longitude"] <= 180):
        return (None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="référentiel : longitude hors [-180, 180]"))

    rayon = ref["rayon_km"]
    if isinstance(rayon, bool) or not isinstance(rayon, (int, float)):
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="rayon_km non numérique"))
    if rayon <= 0:
        return (None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                   detail="rayon_km <= 0"))

    # --- Tous les contrôles passés : le pointage a effectivement eu lieu ---

    # 11. Cohérence GPS
    dist = distance_km(lat, lon, ref["latitude"], ref["longitude"])
    coherent = dist <= rayon

    # 12. Écriture du maillon de pointage (toujours, cohérent ou non)
    #     La ville en clair reste à l'extérieur du registre (minimisation).
    maillon_pointage = {
        "type_entree": TYPE_POINTAGE,
        "intervention_id": intervention_id,
        "technicien_id": technicien_id,
        "action": action,
        "horodatage": horodatage_arg,
        "latitude": lat,
        "longitude": lon,
        "appareil_id": appareil,
        "fictif": True,
        "ville_tokenisee": token_ville,
        "gps_coherent": coherent,
    }
    ligne_id = registre_cible.ajouter(maillon_pointage)

    # 13. Suite d'état selon la table ratifiée
    transition_verdict = None
    if action == "arrivee" and coherent:
        # Le PRD conditionne en_route -> sur_site à un fix GPS COHÉRENT.
        cible = "sur_site"
    elif not coherent:
        # CA-M4-08 : toute incohérence GPS route l'intervention en revue.
        # L'entrée en_route -> en_revue vient de l'amendement de cadrage #145 :
        # sans elle, une anomalie à l'ARRIVÉE n'avait aucune issue légale.
        cible = "en_revue"
    else:
        # Départ cohérent : aucune transition — la complétion et le WCT
        # appartiennent à la story suivante.
        cible = None
    if cible is not None:
        acc, v = etats.transitionner(
            intervention_id, cible, registre_cible, horodatage_arg,
        )
        if acc is None:  # théoriquement impossible, mais on propage sans masquer
            return (None, v)

    # 14. Demande de revue si non cohérent
    demande_id = None
    if not coherent:
        demande_id = encodage.empreinte("demande_revue", intervention_id, horodatage_arg)
        maillon_demande = {
            "type_entree": TYPE_DEMANDE_REVUE,
            "intervention_id": intervention_id,
            "horodatage": horodatage_arg,
            "type_demande": TYPE_REVUE_ANOMALIE,
            "pointage_ligne_id": ligne_id,
            "causes_possibles": list(CAUSES_NEUTRES),
            "statut_arbitrage": "en_attente",
            "demande_id": demande_id,
        }
        registre_cible.ajouter(maillon_demande)

    # 15. Construction de l'accusé
    statut_final = etats.statut_courant(registre_cible, intervention_id)
    tete_chaine = registre_cible.tete()

    accuse = {
        "intervention_id": intervention_id,
        "technicien_id": technicien_id,
        "action": action,
        "horodatage": horodatage_arg,
        "ligne_id": ligne_id,
        "gps_coherent": coherent,
        "statut": statut_final,
        "demande_id": demande_id,
        "tete_chaine": tete_chaine,
    }
    return (accuse, None)


__all__ = [
    "ACTIONS",
    "TYPE_POINTAGE",
    "TYPE_DEMANDE_REVUE",
    "TYPE_REVUE_ANOMALIE",
    "CAUSES_NEUTRES",
    "distance_km",
    "enregistrer_pointage",
]
