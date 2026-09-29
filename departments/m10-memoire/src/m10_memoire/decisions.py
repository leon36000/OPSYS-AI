from . import confidentialite, validation

_TYPE_ENTREE_DECISION = "decision_enregistree"


def _dernier_maillon(registre_cible, decision_id):
    dernier = None
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") != _TYPE_ENTREE_DECISION:
            continue
        if maillon.get("decision_id") != decision_id:
            continue
        dernier = maillon
    return dernier


def statut_courant(registre_cible, decision_id):
    maillon = _dernier_maillon(registre_cible, decision_id)
    return maillon["statut"] if maillon is not None else None


def decisions_par_statut(registre_cible, statut):
    """Le dernier maillon de CHAQUE ``decision_id`` dont le statut COURANT (pas seulement passé)
    vaut ``statut`` — une décision validée puis remplacée n'apparaît plus ici (PLAN T3.3, couche
    « règles de l'entreprise » de ``paquets.py``)."""
    derniers: dict[str, dict] = {}
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") != _TYPE_ENTREE_DECISION:
            continue
        decision_id = maillon.get("decision_id")
        if decision_id is not None:
            derniers[decision_id] = maillon  # dernier maillon lu (append-only) = le plus récent
    return [maillon for maillon in derniers.values() if maillon.get("statut") == statut]


def enregistrer_decision(decision, registre_cible, horodatage, niveau_confidentialite=None):
    """``niveau_confidentialite`` (PLAN T3.3-suite-b) : clé SŒUR additive du contrat gelé de la décision
    (les quatre champs ne changent pas). Absent, le maillon est écrit exactement comme avant et se lit
    ``INTERNAL`` ; présent, il doit être l'un des sept niveaux (``confidentialite.py``), sinon refus nommé."""
    valide, code = validation.valider_decision(decision)
    if not valide:
        return None, code
    if niveau_confidentialite is not None and not confidentialite.niveau_connu(niveau_confidentialite):
        return None, confidentialite.REJ_CONFIDENTIALITE_NIVEAU_INCONNU

    entree = {
        "decision_id": decision["decision_id"],
        "raison": decision["raison"],
        "statut": decision["statut"],
        "options_ecartees": decision["options_ecartees"],
        "type_entree": _TYPE_ENTREE_DECISION,
        "horodatage": horodatage,
    }
    if niveau_confidentialite is not None:
        entree["confidentialite"] = niveau_confidentialite
    ligne_id = registre_cible.ajouter(entree)

    for maillon in registre_cible.lire():
        if maillon.get("ligne_id") == ligne_id:
            return maillon, None

    raise RuntimeError("Maillon ajouté introuvable.")
