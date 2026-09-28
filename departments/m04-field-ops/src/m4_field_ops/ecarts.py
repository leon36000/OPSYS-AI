"""
Module écarts : gestion des demandes d'écart métier et de l'arbitrage.
Fournit les opérations de création, listage, volumétrie et résolution des
demandes de revue.  Respecte le cahier M4-S007.
"""

import copy

from . import encodage
from . import etats
from . import horodatage
from . import outbox
from . import pointage
from . import verdicts

# ------------------------------------------------------------------ constantes
TYPES_DEMANDE = ("ecart_metier", "anomalie_pointage")
"""Deux concepts fermés : écart sur faits déclarés / anomalie de cohérence terrain.
Ces deux types ne confluent jamais."""

TYPE_RESOLUTION = "resolution_revue"
"""Type d'entrée registre pour la résolution d'une demande de revue."""

DECISIONS = ("validee", "rejetee")
"""Décisions possibles pour la résolution."""

STATUTS_ARBITRAGE = ("en_attente", "validee", "rejetee")
"""Statuts possibles du champ statut_arbitrage."""

CLES_VERSION = ("duree_minutes", "perimetre", "materiaux")
"""Clés obligatoires pour une version métier (prevue / declaree)."""


# ------------------------------------------------------------------ helpers
def _valider_version(version, etiquette="version"):
    """Valide une version selon le contrat métier.

    Args:
        version: dict à valider.
        etiquette: nom pour les messages d'erreur.

    Returns:
        None si OK.

    Raises:
        ValueError: avec le code verdict approprié.
    """
    if not isinstance(version, dict):
        raise ValueError("REJ-CONTRAT-INVALIDE")
    if set(version.keys()) != set(CLES_VERSION):
        raise ValueError("REJ-CONTRAT-INVALIDE")

    duree = version["duree_minutes"]
    if not isinstance(duree, int) or isinstance(duree, bool) or duree < 0:
        raise ValueError("REJ-CONTRAT-INVALIDE")

    perimetre = version["perimetre"]
    if not isinstance(perimetre, str):
        raise ValueError("REJ-CONTRAT-INVALIDE")
    if perimetre == "":
        raise ValueError("REJ-CHAMP-VIDE")

    materiaux = version["materiaux"]
    if not isinstance(materiaux, list):
        raise ValueError("REJ-CONTRAT-INVALIDE")
    for m in materiaux:
        if not isinstance(m, str) or m == "":
            raise ValueError("REJ-CONTRAT-INVALIDE")


# ------------------------------------------------------------------ API publique
def creer_demande_ecart(
    intervention_id, version_prevue, version_declaree, horodatage_arg, registre_cible
):
    """Crée une demande d'écart métier et l'inscrit au registre.

    Ordre strict des contrôles :
    1. horodatage valide
    2. validation des deux versions (clés, types, non-vide)
    3. rejet si versions identiques (pas d'écart)
    4. récupération du statut courant de l'intervention
    5. rejet si intervention inexistante
    6. rejet si statut terminal
    7. génération d'un demande_id et rejet si déjà ouverte
    8. transition vers "en_revue" si autorisée
    9. écriture du maillon (copies profondes)
    10. accusé avec l’état final

    Returns:
        (accusé, None) en cas de succès,
        (None, verdict) en cas d’échec.
    """
    # 1. Horodatage
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return (None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE"))

    # 2. Validation des versions
    try:
        _valider_version(version_prevue, "version_prevue")
        _valider_version(version_declaree, "version_declaree")
    except ValueError as exc:
        code = exc.args[0]
        return (
            None,
            verdicts.construire_verdict(code, detail="version invalide"),
        )

    # 3. Versions identiques
    if version_prevue == version_declaree:
        return (
            None,
            verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail="aucun écart : versions identiques",
            ),
        )

    # 4. Statut courant
    statut = etats.statut_courant(registre_cible, intervention_id)

    # 5. Intervention inexistante
    if statut is None:
        return (
            None,
            verdicts.construire_verdict(
                "REJ-TRANSITION-ILLEGALE",
                detail="intervention inexistante",
            ),
        )

    # 6. Terminal
    if statut in etats.ETATS_TERMINAUX:
        return (
            None,
            verdicts.construire_verdict(
                "REJ-TRANSITION-ILLEGALE",
                detail="intervention dans un état terminal",
            ),
        )

    # 7. Demande déjà ouverte ?
    demande_id = encodage.empreinte("demande_revue", intervention_id, horodatage_arg)
    for entre in registre_cible.lire():
        if (
            entre.get("type_entree") == pointage.TYPE_DEMANDE_REVUE
            and entre.get("demande_id") == demande_id
        ):
            return (
                None,
                verdicts.construire_verdict(
                    "REJ-CONTRAT-INVALIDE",
                    detail="demande déjà ouverte",
                ),
            )

    # 8. Transition éventuelle vers en_revue
    if (statut, "en_revue") in etats.TRANSITIONS_AUTORISEES:
        acc_trans, ver_trans = etats.transitionner(
            intervention_id, "en_revue", registre_cible, horodatage_arg
        )
        if acc_trans is None:
            # DÉFENSIF et structurellement inatteignable : la condition ci-dessus
            # interroge la MÊME table que la machine à états, donc elle ne peut
            # pas refuser ici (mesuré : la mutation ne mord pas). Conservé pour
            # ne pas propager un échec en silence si les deux sources divergeaient.
            return (None, ver_trans)

    # 9. Écriture du maillon
    maillon = {
        "type_entree": pointage.TYPE_DEMANDE_REVUE,
        "intervention_id": intervention_id,
        "horodatage": horodatage_arg,
        "type_demande": "ecart_metier",
        "demande_id": demande_id,
        # Copies profondes DÉFENSIVES : redondantes aujourd'hui avec la copie que
        # le registre effectue à l'ajout (mesuré : les retirer ne casse aucun
        # test). Conservées pour ne pas faire dépendre ce module d'un détail
        # d'implémentation du registre — redondance DÉCLARÉE, pas oubliée.
        "version_prevue": copy.deepcopy(version_prevue),
        "version_declaree": copy.deepcopy(version_declaree),
        "statut_arbitrage": "en_attente",
    }
    ligne_id = registre_cible.ajouter(maillon)

    # 10. Accusé
    statut_final = etats.statut_courant(registre_cible, intervention_id)
    accuse = {
        "demande_id": demande_id,
        "intervention_id": intervention_id,
        "ligne_id": ligne_id,
        "type_demande": "ecart_metier",
        "statut_arbitrage": "en_attente",
        "statut": statut_final,
        "tete_chaine": registre_cible.tete(),
    }
    return (accuse, None)


def lister_pending_review(registre_cible, type_demande=None):
    """Liste les demandes de revue en attente (sans résolution).

    Args:
        registre_cible: instance du registre à interroger.
        type_demande: None pour toutes, ou un type parmi TYPES_DEMANDE.

    Returns:
        Liste (éventuellement vide) des maillons, copies profondes.

    Raises:
        ValueError: si type_demande est fourni et non reconnu.
    """
    if type_demande is not None and type_demande not in TYPES_DEMANDE:
        raise ValueError("type_demande inconnu")

    # identifiants des demandes ayant une résolution
    ids_resolus = set()
    for entree in registre_cible.lire():
        if entree.get("type_entree") == TYPE_RESOLUTION:
            ids_resolus.add(entree.get("demande_id"))

    result = []
    for entree in registre_cible.lire():
        if entree.get("type_entree") == pointage.TYPE_DEMANDE_REVUE:
            if entree.get("demande_id") in ids_resolus:
                continue
            if type_demande is None or entree.get("type_demande") == type_demande:
                # Copie DÉFENSIVE, redondante avec celle que lire() effectue
                # déjà (mesuré) : conservée pour que le contrat « le résultat
                # n'est pas une vue mutable du registre » tienne ici même.
                result.append(copy.deepcopy(entree))
    return result


def volumetrie_pending_review(registre_cible):
    """Comptage des demandes en attente par type.

    Returns:
        dict: {"total": int, "ecart_metier": int, "anomalie_pointage": int}
    """
    pending = lister_pending_review(registre_cible)
    total = len(pending)
    ecart = sum(1 for d in pending if d.get("type_demande") == "ecart_metier")
    anomalie = sum(1 for d in pending if d.get("type_demande") == "anomalie_pointage")
    return {"total": total, "ecart_metier": ecart, "anomalie_pointage": anomalie}


def resoudre_demande(
    demande_id, decision, horodatage_arg, registre_cible, motif=None
):
    """Résout une demande de revue en définitive (validee/rejetee).

    Ordre des contrôles :
    1. décision valide
    2. horodatage valide
    3. demande introuvable → REJ-CONTRAT-INVALIDE
    4. déjà une résolution → REJ-CONTRAT-INVALIDE
    5. motif si fourni doit être une str non vide
    6. transition d'état (terminee/annulee)
    7. écriture du maillon de résolution (nouvelle entrée)
    8. accusé

    Returns:
        (accusé, None) ou (None, verdict).
    """
    # 1. décision
    if decision not in DECISIONS:
        return (None, verdicts.construire_verdict("REJ-ENUM-INVALIDE"))

    # 2. horodatage
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return (None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE"))

    # 3. demande introuvable + 4. déjà résolue
    # On parcourt une fois pour trouver la demande et vérifier la résolution
    # Balayage COMPLET, sans arrêt anticipé : la demande est écrite AVANT sa
    # résolution, donc s'arrêter sur la demande rendrait le contrôle de double
    # résolution inopérant (mesuré).
    maillon_demande = None
    deja_resolue = False
    for entree in registre_cible.lire():
        if entree.get("demande_id") != demande_id:
            continue
        if entree.get("type_entree") == pointage.TYPE_DEMANDE_REVUE:
            maillon_demande = entree
        elif entree.get("type_entree") == TYPE_RESOLUTION:
            deja_resolue = True

    if deja_resolue:
        return (
            None,
            verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail="demande déjà résolue",
            ),
        )
    if maillon_demande is None:
        return (
            None,
            verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail="demande introuvable",
            ),
        )

    intervention_id = maillon_demande["intervention_id"]

    # 5. motif
    if motif is not None:
        if not isinstance(motif, str) or motif == "":
            return (
                None,
                verdicts.construire_verdict(
                    "REJ-CONTRAT-INVALIDE",
                    detail="motif invalide",
                ),
            )

    # 6. suite d'état
    # Un écart métier VALIDÉ mène à la complétion, qui doit émettre le WCT dans
    # le même maillon (CA-M4-10 + CA-M4-11) : ce chemin passe donc par l'outbox,
    # seul écrivain autorisé vers une issue de complétion. Une ANOMALIE DE
    # POINTAGE validée, elle, ne dit pas « le travail est fini » : elle dit
    # « l'administrateur a résolu l'incohérence, le technicien ÉTAIT bien
    # là » — la table PRD (§4) prévoit précisément en_revue -> sur_site pour
    # cette reprise (amendement #145). Router les deux types vers l'outbox
    # faisait échouer la reprise : une arrivée en anomalie n'a par construction
    # ni départ, donc aucune durée calculable (« durée réelle indéterminable »),
    # et en_revue -> sur_site restait inatteignable faute d'appelant. Une
    # décision REJETÉE, quel que soit le type, annule l'intervention : la
    # machine à états reste l'autorité de ce chemin.
    if decision == "validee":
        if maillon_demande.get("type_demande") == pointage.TYPE_REVUE_ANOMALIE:
            acc_trans, ver_trans = etats.transitionner(
                intervention_id, "sur_site", registre_cible, horodatage_arg
            )
        else:
            # ecart_detecte=True EXPLICITE (T1.1-b#2, jamais déduit PAR
            # L'OUTBOX) : c'est ce module-ci, qui vient de valider une demande
            # d'écart métier, qui le décide — un écart métier confirmé EST par
            # définition un écart détecté, donc l'issue est
            # completed_pending_review, jamais completed_verified.
            acc_trans, ver_trans = outbox.completer_intervention(
                intervention_id, horodatage_arg, registre_cible,
                ecart_detecte=True, revue_id=demande_id,
            )
    else:
        acc_trans, ver_trans = etats.transitionner(
            intervention_id, "annulee", registre_cible, horodatage_arg
        )
    if acc_trans is None:
        return (None, ver_trans)

    # 7. écriture résolution
    resolution_id = encodage.empreinte(
        "resolution_revue", demande_id, horodatage_arg
    )
    maillon_resolution = {
        "type_entree": TYPE_RESOLUTION,
        "intervention_id": intervention_id,
        "horodatage": horodatage_arg,
        "demande_id": demande_id,
        "decision": decision,
        "statut_arbitrage": decision,
        "resolution_id": resolution_id,
    }
    if motif is not None:
        maillon_resolution["motif"] = motif

    ligne_id = registre_cible.ajouter(maillon_resolution)

    # 8. accusé
    statut_final = etats.statut_courant(registre_cible, intervention_id)
    accuse = {
        "resolution_id": resolution_id,
        "demande_id": demande_id,
        "intervention_id": intervention_id,
        "ligne_id": ligne_id,
        "decision": decision,
        "statut": statut_final,
        "tete_chaine": registre_cible.tete(),
    }
    return (accuse, None)


__all__ = [
    "TYPES_DEMANDE",
    "TYPE_RESOLUTION",
    "DECISIONS",
    "STATUTS_ARBITRAGE",
    "CLES_VERSION",
    "creer_demande_ecart",
    "lister_pending_review",
    "volumetrie_pending_review",
    "resoudre_demande",
]
