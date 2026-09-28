"""Catalogue des verdicts M4 et utilitaires de validation."""

CODES_M4_LIST = [
    # Groupe 1 — verdicts ratifiés par le PRD M4 (CA-M4-01 à CA-M4-21)
    "REJ-READINESS-NON-FRANCHIE",
    "REJ-FRONTIERE-VIOLEE",
    "REJ-TRANSITION-ILLEGALE",
    "REJ-FENETRE-INVALIDE",
    "REJ-HORODATAGE-ANTERIEUR",
    "REJ-PUNCH-HORS-HEURES",
    "REJ-PUNCH-SANS-INTERVENTION",
    # Groupe 2 — invariants transversaux de validation structurelle
    "REJ-CONTRAT-INVALIDE",
    "REJ-CHAMP-MANQUANT",
    "REJ-CHAMP-VIDE",
    "REJ-ENUM-INVALIDE",
    "REJ-HORODATAGE-INVALIDE",
    # Groupe 2 bis — T1.2-f : faits CLIENT (Loi 25) hors d'un appel d'appareil
    "REJ-CHAMPS-CLIENT-HORS-APPAREIL",
    # Groupe 3 — succès
    "OK",
]

CODES_M4 = set(CODES_M4_LIST)


class CodeVerdictInconnu(Exception):
    """Le code verdict fourni n'appartient pas au catalogue CODES_M4."""


def est_verdict(code):
    """Retourne True si `code` est un verdict du catalogue M4."""
    return code in CODES_M4


def construire_verdict(code, statut="", detail=""):
    """Construit un dictionnaire verdict si `code` est catalogue.

    Lève CodeVerdictInconnu sinon.
    """
    if not est_verdict(code):
        raise CodeVerdictInconnu(f"Code verdict invalide : {code!r}")
    return {"code": code, "statut": statut, "detail": detail}


__all__ = [
    "CODES_M4_LIST",
    "CODES_M4",
    "CodeVerdictInconnu",
    "est_verdict",
    "construire_verdict",
]
