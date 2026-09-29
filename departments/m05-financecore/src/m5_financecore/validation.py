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
    # M5.2 (facturation.py) : facture brouillon, verrous d'envoi/paiement, âge des créances.
    "REJ-FACTURE-FACTURE-ID-VIDE",
    "REJ-FACTURE-CHANTIER-ID-VIDE",
    "REJ-FACTURE-DEVIS-ID-VIDE",
    "REJ-FACTURE-CLIENT-ID-VIDE",
    "REJ-FACTURE-LIGNES-VIDES",
    "REJ-FACTURE-LIGNE-INVALIDE",
    "REJ-FACTURE-MONTANT-INCOHERENT",
    "REJ-FACTURE-DEVIS-DEJA-FACTURE",
    "REJ-FACTURE-INTROUVABLE",
    "REJ-FACTURE-TRANSITION-ILLEGALE",
    "REJ-FACTURE-APPROBATEUR-ABSENT",
    "REJ-CREANCES-AUJOURDHUI-INVALIDE",
    "REJ-CREANCES-DATE-ENVOI-ABSENTE",
    "REJ-CREANCES-DATE-ENVOI-INVALIDE",
    # M5.3 (PLAN T1.3-c) : paiement d'une facture (N5, socle) — montant réellement déposé comparé
    # par le code au montant dû, jamais accepté sans contrôle.
    "REJ-FACTURE-PAIEMENT-MONTANT-INVALIDE",
    "REJ-FACTURE-PAIEMENT-PARTIEL",
    "REJ-FACTURE-PAIEMENT-ECART",
    # PLAN T1.4-k2 (acces.py) : la vue financière d'un appel d'appareil vient de l'identité
    # AUTHENTIFIÉE, jamais des arguments. Mêmes noms que M3, M4 et M6 pour que l'app les traite pareil.
    "REJ-IDENTITE-APPAREIL-INVALIDE",
    "REJ-IDENTITE-FOURNIE-DIFFERENTE",
    "REJ-ROLE-ELARGI",
    "REJ-AUTORISE-COUTS-REQUIS",
    # PLAN T1.5-d (cout_reel.py, M5.9) : coût réel et rentabilité d'un chantier. Ce sont des verdicts
    # qui DISENT QUOI DEMANDER (jamais une valeur de remplacement) : chacun est un manque, porté par la
    # liste `manque` d'un coût partiel, ou un refus de l'outil de lecture.
    "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER",
    "REJ-COUT-TEMPS-POINTE-ABSENT",
    "REJ-COUT-PLUSIEURS-WCT",
    "REJ-COUT-MATERIAUX-REELS-ABSENTS",
    "REJ-COUT-PRIX-NON-DISPONIBLE",
    "REJ-COUT-PRIX-AMBIGU",
    "REJ-COUT-LIGNE-INDETERMINEE",
    "REJ-RENTABILITE-FACTURE-ABSENTE",
    "REJ-RENTABILITE-MARGE-PREVUE-ABSENTE",
    "REJ-RENTABILITE-CHANTIER-INCONNU",
    "REJ-RENTABILITE-LIMITE-INVALIDE",
    # PLAN T1.5-d (facturation.comptes_a_recevoir) : une facture ENVOYEE dont le montant dû est illisible
    # n'entre jamais au total à recevoir avec un montant inventé.
    "REJ-CREANCES-MONTANT-ILLISIBLE",
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
