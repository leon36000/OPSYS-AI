__all__ = ["CODES_M2_LIST", "est_verdict", "construire_verdict"]

# Identifiants stables du catalogue M2 (ceux utilisés par les tests)
CODES_M2_LIST = [
    "REJ-FRONTIERE-VIOLEE",
    "REJ-TRANSITION-ILLEGALE",
    "REJ-OWNER-ABSENT",
    "REJ-ACTION-ABSENTE",
    "REJ-DEVIS-ABSENT",
    "REJ-MOTIF-ABSENT",
    "REJ-ADAPTATEUR-INDISPONIBLE",
    "OK",
]
CODES_M2 = set(CODES_M2_LIST)


def est_verdict(code):
    """Retourne True si le code fait partie du catalogue M2."""
    return code in CODES_M2


def construire_verdict(code, statut="", detail=""):
    """
    Construit un verdict dictionnaire si le code est reconnu.
    Lève une exception dans le cas contraire.
    """
    if not est_verdict(code):
        raise Exception(f"Code verdict invalide : {code!r}")
    return {"code": code, "statut": statut, "detail": detail}
