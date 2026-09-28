import copy
from . import horodatage as _horodatage
from . import registre
from . import verdicts
from . import encodage

# Cycle de vie couvert par M2 (DEFINITION-PRODUIT §7 M2, « Cycle de vie couvert ») : lead →
# qualification → dossier client → estimation → soumission → relance → acceptation → cédule →
# chantier → facture → paiement → avis → référence et affaires répétées → mémoire client.
# "converti" porte l'« acceptation » (soumission acceptée : §6 « Flux principal », « soumission
# acceptée → M4 planifie, route, exécute »). PLAN T1.1-a ajoute les cinq statuts suivants de
# cette même liste, un mot exact chacun : cedule, chantier, facture, paiement, avis. "référence
# et affaires répétées" et "mémoire client" ne sont PAS ajoutés ici : ce sont des segments/
# relations en continu (M2.11, encore ABSENT — docs/departements/M2-audit.md §1.3), pas des
# étapes discrètes d'un pipeline fermé — hors du périmètre de cette correction.
STATUTS = (
    "nouveau", "qualifie", "converti", "perdu",
    "cedule", "chantier", "facture", "paiement", "avis",
)

# Seul "perdu" est un dossier vraiment clos. "converti" N'EST PLUS terminal : PLAN T1.1-a
# corrige le constat selon lequel M2 refusait par construction l'activité « chantier terminé »
# (§6, cascade « travaux terminés », ligne M2 : « Marque le chantier terminé, écrit l'activité,
# définit la prochaine action ») alors que la définition prévoit une suite au cycle de vie après
# l'acceptation (§7 M2, ligne ci-dessus). La définition ne prévoit aucun statut de « dossier
# clôturé en fin de cycle » pour M2 (seul M4 « clôture des chantiers », §2 tableau des
# départements) : aucun n'est inventé ici, donc "avis" (la dernière étape discrète nommée) reste
# lui aussi ouvert aux interactions — la relance et le suivi (référence, affaires répétées)
# continuent au-delà.
STATUTS_TERMINAUX = ("perdu",)

TRANSITIONS_AUTORISEES = (
    ("nouveau", "qualifie"),
    ("qualifie", "converti"),
    ("qualifie", "perdu"),
    ("nouveau", "perdu"),
    # Suite du cycle de vie après l'acceptation (§7 M2), chaînée dans l'ordre exact de la
    # définition — voir le commentaire de STATUTS. "chantier" → "facture" est la transition
    # portée par l'outil m2_marquer_chantier_termine (PLAN T1.1-a, outils.py).
    ("converti", "cedule"),
    ("cedule", "chantier"),
    ("chantier", "facture"),
    ("facture", "paiement"),
    ("paiement", "avis"),
)
TYPE_ENTREE = "transition_statut"


def _prochaine_action_invalide(prochaine_action):
    """Valide la forme de prochaine_action : dict avec description non vide et échéance
    ISO-8601 avec fuseau. Retourne None si valide, sinon un détail (chaîne vide si la forme est
    absente/incorrecte, message précis si seule l'échéance est invalide — la distinction rend le
    digest d'erreurs actionnable). Factorisé pour être partagé par les deux chemins qui exigent
    une prochaine_action : ("nouveau","qualifie") et ("chantier","facture")."""
    forme_correcte = (
        isinstance(prochaine_action, dict)
        and "description" in prochaine_action
        and "echeance" in prochaine_action
    )
    if not forme_correcte:
        return ""
    desc = prochaine_action.get("description")
    if not isinstance(desc, str) or desc.strip() == "":
        return ""
    try:
        _horodatage.valider_horodatage(prochaine_action.get("echeance"))
    except ValueError:
        return "Échéance de la prochaine action invalide."
    return None

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
        # prochaine_action : dict avec description non vide et échéance valide. Échéance
        # invalide = prochaine_action INCOMPLÈTE (condition du chemin), pas un défaut de
        # l'horodatage de la transition : REJ-HORODATAGE-INVALIDE est réservé à l'étape 1.
        detail = _prochaine_action_invalide(prochaine_action)
        if detail is not None:
            return (None, verdicts.construire_verdict("REJ-ACTION-ABSENTE", statut=courant, detail=detail))
    elif transition == ("qualifie", "converti"):
        # reference_devis_m3 non vide
        if not isinstance(reference_devis_m3, str) or reference_devis_m3.strip() == "":
            return (None, verdicts.construire_verdict("REJ-DEVIS-ABSENT", statut=courant))
    elif transition == ("chantier", "facture"):
        # PLAN T1.1-a : l'outil m2_marquer_chantier_termine emprunte ce chemin. Règle dure
        # § 7 M2 « jamais... laisser un lead sans prochaine action » — vérifiée ici, à la
        # source, pour tenir quel que soit l'outil appelant (défense en profondeur).
        detail = _prochaine_action_invalide(prochaine_action)
        if detail is not None:
            return (None, verdicts.construire_verdict("REJ-ACTION-ABSENTE", statut=courant, detail=detail))
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
    elif transition == ("chantier", "facture"):
        maillon["prochaine_action"] = copy.deepcopy(prochaine_action)
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
