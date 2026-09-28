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
    # Groupe 5 — PLAN T1.4-e2 : dépôt de fichiers adressé par contenu (m4_deposer_fichier).
    "REJ-FICHIER-PARAMETRES-INVALIDES",
    "REJ-FICHIER-TROP-VOLUMINEUX",
    "REJ-FICHIER-INCOHERENT",
    "REJ-FICHIER-EMPREINTE-DISCORDANTE",
    "REJ-FICHIER-TYPE-NON-PERMIS",
    # Groupe 5 bis — PLAN T1.4-e2 : m4_completer_intervention vérifie chaque référence de fichier.
    "REJ-PREUVE-FICHIER-INTROUVABLE",
    # Groupe 6 — PLAN T1.4-k : contrôle d'accès par intervention et par personne authentifiée.
    "REJ-IDENTITE-APPAREIL-INVALIDE",         # l'identité du jeton n'est pas confirmée par la base.
    "REJ-INTERVENTION-NON-ASSIGNEE",          # un employé agit sur l'intervention d'un autre.
    "REJ-IDENTITE-FOURNIE-DIFFERENTE",         # technicien_id ou accede_par != personne authentifiée.
    # Groupe 7 — PLAN T4.1-a : localisation des chantiers (localisation.py, R15 §3 et §4)
    "REJ-COORDONNEES-A-CONFIRMER",   # « coordonnées manquantes : à confirmer » : jamais une position inventée.
    "REJ-INDEX-RQA-ABSENT",          # l'index local du RQA n'est pas importé : dit quoi faire, pas « introuvable ».
    "REJ-LOCALISATION-DETRUITE",     # clé du chantier détruite : la position n'est plus lisible (voulu).
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
