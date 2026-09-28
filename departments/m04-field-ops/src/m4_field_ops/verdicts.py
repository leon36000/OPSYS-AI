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
    # Groupe 4 — PLAN T4.2 (POLITIQUE-geolocalisation.md) : consentement, rétention et destruction
    "REJ-CONSENTEMENT-INVALIDE",       # §4 : enregistrement de consentement mal formé.
    "REJ-RETENTION-DONNEE-MANQUANTE",  # §5 : fin de contrat inconnue, fail-closed, aucune purge.
    "REJ-RETENTION-NON-ECHUE",         # §5 : échéance (12 mois) pas encore atteinte.
    "REJ-POSITION-INTROUVABLE",        # §7 : aucun fix GPS chiffré à cette ligne du registre.
    "REJ-POSITION-DETRUITE",           # §5 : clé détruite par une purge antérieure (succès de la
                                        # destruction, pas une anomalie).
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
