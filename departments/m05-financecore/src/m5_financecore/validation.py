from __future__ import annotations

from decimal import Decimal

from . import contrats


class CodeVerdictInconnu(Exception):
    pass


class MouvementInvalide(ValueError):
    """Rejet nommé d'un mouvement avant son écriture dans le registre."""

    def __init__(self, verdict):
        self.verdict = verdict
        super().__init__(verdict["code"])


CODES_M5_LIST = [
    "REJ-MOUVEMENT-STRUCTURE-INVALIDE",
    "REJ-MOUVEMENT-MONTANT-INVALIDE",
    "REJ-MOUVEMENT-TYPE-INCONNU",
    "REJ-MOUVEMENT-CLASSE-RETENTION-INCONNUE",
    "REJ-MOUVEMENT-CHAMP-TEXTE-INVALIDE",
    "REJ-MOUVEMENT-SIGNE-INCOHERENT",
    "REJ-TAUX-INCONNU",
    "REJ-PALIER-INVALIDE",
    "REJ-DEMANDE-DEJA-CREEE",
    "REJ-DEMANDE-INTROUVABLE",
    "REJ-TRANSITION-ILLEGALE",
    "REJ-APPROBATEUR-ABSENT",
    "REJ-PREUVE-ABSENTE",
    "REJ-PREUVE-STRUCTURE-INVALIDE",
]
CODES_M5 = set(CODES_M5_LIST)

_CHAMPS_TEXTE_MOUVEMENT = ("horodatage", "source")

# Signe imposé par type_mouvement (bug NEW-PROD : un DECAISSEMENT positif gonflait le
# solde au lieu de le diminuer). PROVISION est une réservation, donc positive elle
# aussi. AJUSTEMENT (correction d'un mouvement antérieur, dans un sens ou l'autre) et
# AUTRE (échappatoire D-032, nature non classifiable) n'ont pas de signe imposé.
_TYPES_SIGNE_STRICTEMENT_POSITIF = frozenset({"ENCAISSEMENT", "PROVISION"})
_TYPES_SIGNE_STRICTEMENT_NEGATIF = frozenset({"DECAISSEMENT"})


def est_verdict(code):
    return code in CODES_M5


def construire_verdict(code, detail=""):
    if not est_verdict(code):
        raise CodeVerdictInconnu(f"Code verdict invalide : {code!r}")
    return {"code": code, "detail": detail}


def _est_chaine_non_vide(valeur):
    return isinstance(valeur, str) and valeur != ""


def valider_mouvement(mouvement):
    if not isinstance(mouvement, dict):
        return False, construire_verdict("REJ-MOUVEMENT-STRUCTURE-INVALIDE")
    if set(mouvement.keys()) != contrats.CHAMPS_MOUVEMENT_FINANCIER:
        return False, construire_verdict("REJ-MOUVEMENT-STRUCTURE-INVALIDE")

    montant = mouvement["montant"]
    if not isinstance(montant, Decimal):
        return False, construire_verdict("REJ-MOUVEMENT-MONTANT-INVALIDE")

    if not montant.is_finite():
        return False, construire_verdict("REJ-MOUVEMENT-MONTANT-INVALIDE")

    for champ in _CHAMPS_TEXTE_MOUVEMENT:
        if not _est_chaine_non_vide(mouvement[champ]):
            return False, construire_verdict(
                "REJ-MOUVEMENT-CHAMP-TEXTE-INVALIDE",
                detail=f"champ {champ!r} : chaîne non vide exigée",
            )

    if mouvement["type_mouvement"] not in contrats.TYPE_MOUVEMENT:
        return False, construire_verdict("REJ-MOUVEMENT-TYPE-INCONNU")

    type_mouvement = mouvement["type_mouvement"]
    if type_mouvement in _TYPES_SIGNE_STRICTEMENT_POSITIF and montant <= 0:
        return False, construire_verdict(
            "REJ-MOUVEMENT-SIGNE-INCOHERENT",
            detail=f"{type_mouvement} exige un montant strictement positif",
        )
    if type_mouvement in _TYPES_SIGNE_STRICTEMENT_NEGATIF and montant >= 0:
        return False, construire_verdict(
            "REJ-MOUVEMENT-SIGNE-INCOHERENT",
            detail=f"{type_mouvement} exige un montant strictement négatif",
        )

    if mouvement["classe_retention"] not in contrats.CLASSE_RETENTION:
        return False, construire_verdict("REJ-MOUVEMENT-CLASSE-RETENTION-INCONNUE")

    return True, None
