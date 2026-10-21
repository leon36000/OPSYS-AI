from . import contrats


def valider_rapport_strategique(rapport):
    if not isinstance(rapport, dict):
        return False, "REJ-RAPPORT-STRUCTURE-INVALIDE"

    manquantes = contrats.CHAMPS_RAPPORT_STRATEGIQUE - set(rapport.keys())
    if manquantes:
        return False, "REJ-RAPPORT-CLE-MANQUANTE"

    en_trop = set(rapport.keys()) - contrats.CHAMPS_RAPPORT_STRATEGIQUE
    if en_trop:
        return False, "REJ-RAPPORT-CLE-EN-TROP"

    return True, None
