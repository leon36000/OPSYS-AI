"""Catalogue des identifiants de verdicts stables du module M2."""

__all__ = [
    "CODES_M2_LIST",
    "CODES_M2",
    "CodeVerdictInconnu",
    "est_verdict",
    "construire_verdict",
]


class CodeVerdictInconnu(Exception):
    """
    Levée par construire_verdict lorsque le code demandé ne figure pas dans
    le catalogue M2. Hérite d'Exception pour rester attrapable par les tests
    existants qui font pytest.raises(Exception).
    """


# Identifiants stables du catalogue M2 (épinglés par des tests existants :
# contenu et ordre inchangés)
CODES_M2_LIST = [
    # Groupe 1 — catalogue d'origine (M2-S001), ordre épinglé par les tests
    "REJ-FRONTIERE-VIOLEE",
    "REJ-TRANSITION-ILLEGALE",
    "REJ-OWNER-ABSENT",
    "REJ-ACTION-ABSENTE",
    "REJ-DEVIS-ABSENT",
    "REJ-MOTIF-ABSENT",
    "REJ-ADAPTATEUR-INDISPONIBLE",
    "OK",
    # Groupe 2 — repris du catalogue voisin, invariant transversal
    "REJ-CONVERSATION-CLOSE",
    "REJ-CONTRAT-INVALIDE",
    "REJ-CHAMP-MANQUANT",
    "REJ-CHAMP-VIDE",
    "REJ-ENUM-INVALIDE",
    # Groupe 3 — addition M2, addendum architecture
    "REJ-LEAD-DEJA-INGERE",
    # Groupe 4 — émis par les modules du présent arbre
    "REJ-FIXTURE-NON-FICTIVE",
    "REJ-HORODATAGE-INVALIDE",
]
CODES_M2 = set(CODES_M2_LIST)


def est_verdict(code):
    """Retourne True si le code fait partie du catalogue M2."""
    return code in CODES_M2


def construire_verdict(code, statut="", detail=""):
    """
    Construit un verdict dictionnaire si le code est reconnu.
    Lève CodeVerdictInconnu dans le cas contraire.
    """
    if not est_verdict(code):
        raise CodeVerdictInconnu(f"Code verdict invalide : {code!r}")
    return {"code": code, "statut": statut, "detail": detail}
