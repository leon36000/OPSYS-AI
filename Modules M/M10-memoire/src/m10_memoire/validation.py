from . import contrats

REJ_EVENEMENT_STRUCTURE_INVALIDE = "REJ-EVENEMENT-STRUCTURE-INVALIDE"
REJ_EVENEMENT_CHAMP_TEXTE_INVALIDE = "REJ-EVENEMENT-CHAMP-TEXTE-INVALIDE"
REJ_DECISION_STRUCTURE_INVALIDE = "REJ-DECISION-STRUCTURE-INVALIDE"
REJ_DECISION_RAISON_ABSENTE = "REJ-DECISION-RAISON-ABSENTE"
REJ_DECISION_STATUT_INCONNU = "REJ-DECISION-STATUT-INCONNU"


def construire_verdict(code, detail=None):
    return {"code": code, "detail": detail}


def valider_evenement(evenement):
    if not isinstance(evenement, dict):
        return False, REJ_EVENEMENT_STRUCTURE_INVALIDE

    if set(evenement.keys()) != contrats.CHAMPS_EVENEMENT_MEMOIRE:
        return False, REJ_EVENEMENT_STRUCTURE_INVALIDE

    for valeur in evenement.values():
        if not isinstance(valeur, str) or not valeur:
            return False, REJ_EVENEMENT_CHAMP_TEXTE_INVALIDE

    return True, None


def valider_decision(decision):
    if not isinstance(decision, dict):
        return False, REJ_DECISION_STRUCTURE_INVALIDE

    if set(decision.keys()) != contrats.CHAMPS_DECISION:
        return False, REJ_DECISION_STRUCTURE_INVALIDE

    if not isinstance(decision["raison"], str) or not decision["raison"]:
        return False, REJ_DECISION_RAISON_ABSENTE

    if decision["statut"] not in contrats.STATUT_DECISION:
        return False, REJ_DECISION_STATUT_INCONNU

    return True, None
