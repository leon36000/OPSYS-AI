from __future__ import annotations

from . import contrats


class CodeVerdictInconnu(Exception):
    pass


CODES_M5_LIST = [
    "REJ-MOUVEMENT-STRUCTURE-INVALIDE",
    "REJ-MOUVEMENT-MONTANT-INVALIDE",
    "REJ-MOUVEMENT-TYPE-INCONNU",
    "REJ-MOUVEMENT-CLASSE-RETENTION-INCONNUE",
]
CODES_M5 = set(CODES_M5_LIST)


def est_verdict(code):
    return code in CODES_M5


def construire_verdict(code, detail=""):
    if not est_verdict(code):
        raise CodeVerdictInconnu(f"Code verdict invalide : {code!r}")
    return {"code": code, "detail": detail}


def valider_mouvement(mouvement):
    if not isinstance(mouvement, dict):
        return False, construire_verdict("REJ-MOUVEMENT-STRUCTURE-INVALIDE")
    if set(mouvement.keys()) != contrats.CHAMPS_MOUVEMENT_FINANCIER:
        return False, construire_verdict("REJ-MOUVEMENT-STRUCTURE-INVALIDE")

    montant = mouvement["montant"]
    if isinstance(montant, bool) or not isinstance(montant, (int, float)):
        return False, construire_verdict("REJ-MOUVEMENT-MONTANT-INVALIDE")

    if mouvement["type_mouvement"] not in contrats.TYPE_MOUVEMENT:
        return False, construire_verdict("REJ-MOUVEMENT-TYPE-INCONNU")

    if mouvement["classe_retention"] not in contrats.CLASSE_RETENTION:
        return False, construire_verdict("REJ-MOUVEMENT-CLASSE-RETENTION-INCONNUE")

    return True, None
