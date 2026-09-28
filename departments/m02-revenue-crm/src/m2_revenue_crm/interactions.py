"""Interactions commerciales post-qualification (S005).

Chaque interaction est enregistrée une fois le lead qualifié et actif.
Fonctions : enregistrer (avec contrôle d'état) et lister.
"""

from . import horodatage as _horodatage
from .verdicts import construire_verdict
from .statuts import statut_courant, STATUTS_TERMINAUX

TYPE_ENTREE = "interaction"  # Identifiant canonique du type d'écriture


def enregistrer(lead_id, auteur, resume, registre_cible, horodatage):
    """Enregistre une interaction humaine pour un lead actif.

    Contrôles dans l'ordre :
    1. horodatage valide
    2. auteur et resume non vides après strip
    3. lead existant
    4. statut non terminal (converti ou perdu)
    Succès : écrit un maillon et retourne un accusé.
    Rejet : retourne un verdict, aucun maillon écrit.

    Retourne un tuple (accusé, verdict) dont un seul membre est non nul.

    Paramètres :
    lead_id : identifiant du lead
    auteur : chaîne identifiant l'auteur de l'interaction
    resume : résumé textuel de l'interaction
    registre_cible : instance de Registre (append-only)
    horodatage : chaîne ISO-8601 avec timezone

    Retourne :
    (dict, None) en succès, (None, dict) en rejet
    """
    # 1. Validation de l'horodatage
    try:
        horodatage_valide = _horodatage.valider_horodatage(horodatage)
    except ValueError as e:
        return (None, construire_verdict("REJ-HORODATAGE-INVALIDE", detail=str(e)))

    # 2. Champs obligatoires non vides
    auteur = auteur.strip() if isinstance(auteur, str) else ""
    resume = resume.strip() if isinstance(resume, str) else ""
    if not auteur or not resume:
        champ = "auteur" if not auteur else "resume"
        return (None, construire_verdict("REJ-CHAMP-VIDE", detail=f"{champ} vide"))

    # 3. Existence du lead
    statut = statut_courant(registre_cible, lead_id)
    if statut is None:
        return (None, construire_verdict("REJ-TRANSITION-ILLEGALE",
                                         detail=f"lead {lead_id} inexistant"))

    # 4. Statut terminal interdit
    if statut in STATUTS_TERMINAUX:
        return (None, construire_verdict("REJ-CONVERSATION-CLOSE",
                                         detail=f"lead {lead_id} déjà clos (statut={statut})"))

    # 5. Écriture du maillon (unique .ajouter du fichier)
    entree = {
        "type_entree": TYPE_ENTREE,
        "horodatage": horodatage_valide,
        "lead_id": lead_id,
        "auteur": auteur,
        "resume": resume,
    }
    # Correctif d'audit : ligne_id doit être l'identifiant réel du maillon (le
    # hash retourné par .ajouter), jamais la taille du registre après écriture
    # (un simple compteur, qui n'identifie rien de façon vérifiable).
    ligne_id = registre_cible.ajouter(entree)

    # 6. Accusé de réception
    tete = registre_cible.tete()
    accuse = {
        "lead_id": lead_id,
        "ligne_id": ligne_id,
        "tete_chaine": tete,
        "horodatage": horodatage_valide,
    }
    return (accuse, None)


def lister(registre_cible, lead_id):
    """Liste toutes les interactions d'un lead, dans l'ordre d'enregistrement.

    Les maillons retournés sont des copies profondes (fournies par le registre),
    aucune référence partagée.

    Paramètres :
    registre_cible : registre append-only
    lead_id : identifiant du lead

    Retourne :
    liste de dict (chaque maillon de type interaction)
    """
    interactions = []
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") == TYPE_ENTREE and maillon.get("lead_id") == lead_id:
            interactions.append(maillon)  # déjà copie profonde
    return interactions
