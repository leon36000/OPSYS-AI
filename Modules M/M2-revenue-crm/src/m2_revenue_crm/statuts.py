import copy
from . import horodatage as _horodatage
from . import registre
from . import verdicts
from . import encodage

STATUTS = ("nouveau", "qualifie", "converti", "perdu")
STATUTS_TERMINAUX = ("converti", "perdu")
TRANSITIONS_AUTORISEES = (
    ("nouveau", "qualifie"),
    ("qualifie", "converti"),
    ("qualifie", "perdu"),
    ("nouveau", "perdu"),
)
TYPE_ENTREE = "transition_statut"

def statut_courant(registre_cible, lead_id):
    """Retourne le statut courant du lead, None s'il n'a jamais été ingéré."""
    statut = None
    for maillon in registre_cible.lire():
        if maillon.get("lead_id") == lead_id and maillon.get("type_entree") in ("lead_ingere", "transition_statut"):
            statut = maillon.get("statut")
    return statut

def transitionner(lead_id, statut_cible, registre_cible, horodatage,
                  owner=None, prochaine_action=None,
                  reference_devis_m3=None, motif=None):
    """Enregistre une transition de statut pour un lead existant.
    Retourne un couple (accusé, None) en cas de succès, (None, verdict) sinon.
    """
    # 1. Validation de l'horodatage de l'appelant
    try:
        horodatage_valide = _horodatage.valider_horodatage(horodatage)
    except ValueError:
        return (None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE",
                                                   detail="Horodatage global invalide."))

    # 2. Existence du lead (statut courant)
    courant = statut_courant(registre_cible, lead_id)
    if courant is None:
        # Aucun chemin légal depuis l'inexistence
        return (None, verdicts.construire_verdict("REJ-TRANSITION-ILLEGALE",
                                                   detail="Lead inexistant."))

    # 3. Statut cible dans l'énumération fermée
    if statut_cible not in STATUTS:
        return (None, verdicts.construire_verdict("REJ-ENUM-INVALIDE",
                                                   statut=courant,
                                                   detail=f"Statut cible '{statut_cible}' invalide."))

    # 4. Statut terminal -> conversation close (prioritaire sur la table pour figer les leads clos)
    if courant in STATUTS_TERMINAUX:
        return (None, verdicts.construire_verdict("REJ-CONVERSATION-CLOSE",
                                                   statut=courant,
                                                   detail="Lead clos, aucune transition permise."))

    # 5. Couple (courant, cible) dans la table des transitions autorisées
    transition = (courant, statut_cible)
    if transition not in TRANSITIONS_AUTORISEES:
        return (None, verdicts.construire_verdict("REJ-TRANSITION-ILLEGALE",
                                                   statut=courant,
                                                   detail=f"Transition {courant} -> {statut_cible} non autorisée."))

    # 6. Vérification des conditions spécifiques au chemin
    if transition == ("nouveau", "qualifie"):
        # owner non vide
        if not isinstance(owner, str) or owner.strip() == "":
            return (None, verdicts.construire_verdict("REJ-OWNER-ABSENT", statut=courant))
        # prochaine_action : dict avec description non vide et échéance valide
        if not isinstance(prochaine_action, dict) or "description" not in prochaine_action or "echeance" not in prochaine_action:
            return (None, verdicts.construire_verdict("REJ-ACTION-ABSENTE", statut=courant))
        desc = prochaine_action.get("description")
        if not isinstance(desc, str) or desc.strip() == "":
            return (None, verdicts.construire_verdict("REJ-ACTION-ABSENTE", statut=courant))
        echeance = prochaine_action.get("echeance")
        try:
            _horodatage.valider_horodatage(echeance)
        except ValueError:
            # Échéance invalide = prochaine_action INCOMPLÈTE (condition du chemin),
            # pas un défaut de l'horodatage de la transition : REJ-HORODATAGE-INVALIDE est
            # réservé à l'étape 1. La distinction rend le digest d'erreurs actionnable.
            return (None, verdicts.construire_verdict("REJ-ACTION-ABSENTE",
                                                       statut=courant,
                                                       detail="Échéance de la prochaine action invalide."))
    elif transition == ("qualifie", "converti"):
        # reference_devis_m3 non vide
        if not isinstance(reference_devis_m3, str) or reference_devis_m3.strip() == "":
            return (None, verdicts.construire_verdict("REJ-DEVIS-ABSENT", statut=courant))
    elif statut_cible == "perdu":
        # motif non vide pour tout chemin vers perdu
        if not isinstance(motif, str) or motif.strip() == "":
            return (None, verdicts.construire_verdict("REJ-MOTIF-ABSENT", statut=courant))

    # 7. Construction du maillon avec copie profonde des valeurs mutables
    maillon = {
        "type_entree": TYPE_ENTREE,
        "horodatage": horodatage_valide,
        "lead_id": lead_id,
        "statut": statut_cible,
        "statut_precedent": courant,
    }
    if transition == ("nouveau", "qualifie"):
        maillon["owner"] = copy.deepcopy(owner)
        maillon["prochaine_action"] = copy.deepcopy(prochaine_action)
    elif transition == ("qualifie", "converti"):
        maillon["reference_devis_m3"] = copy.deepcopy(reference_devis_m3)
    elif statut_cible == "perdu":
        maillon["motif"] = copy.deepcopy(motif)

    # Écriture unique dans le registre
    ligne_id = registre_cible.ajouter(maillon)

    # 8. Lecture du maillon fraîchement écrit pour l'accusé
    maillon_relu = None
    for m in registre_cible.lire():
        if m.get("ligne_id") == ligne_id:
            maillon_relu = m
            break
    if maillon_relu is None:
        # Cohérence interne du registre
        raise RuntimeError("Maillon ajouté introuvable.")
    empreinte = encodage.empreinte(maillon_relu)
    tete = registre_cible.tete()

    accuse = {
        "lead_id": lead_id,
        "ligne_id": ligne_id,
        "statut": statut_cible,
        "statut_precedent": courant,
        "empreinte_maillon": empreinte,
        "tete_chaine": tete,
        "horodatage": horodatage_valide,
    }
    return (accuse, None)
