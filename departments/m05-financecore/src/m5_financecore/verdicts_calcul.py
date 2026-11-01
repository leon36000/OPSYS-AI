"""Catalogue fermé des refus du moteur de calcul (tranche 1, `docs/moteur-calcul.md`), à part de
`validation.CODES_M5_LIST`.

Même raison que `verdicts_grand_livre.py` : `validation.py` fait partie du code de paie épinglé par empreinte
(`contracts/admission_paie_preparatoire.v1.json`) ; y ajouter des codes ferait tomber le diagnostic d'admission de la
paie. Même forme de verdict (`{code, detail}`), même fermeture : un code hors catalogue lève. Module pur.

Un refus n'est jamais un résultat dégradé : une entrée invalide (taux hors bornes, flux vides, fréquence inconnue,
borne de calcul dépassée) ne produit AUCUN chiffre. Un TRI multiple ou indéfini, lui, n'est pas un refus : c'est un
statut du résultat (`maths_financieres.tri`), dit tel quel, sans nombre inventé.
"""

from __future__ import annotations

__all__ = ["CODES_CALCUL", "construire_verdict"]

CODES_CALCUL = [
    "REJ-CALC-MONTANT-INVALIDE",  # montant non texte décimal, non fini, signe interdit, hors bornes, trop de décimales
    "REJ-CALC-TAUX-HORS-BORNES",  # taux non texte décimal ou hors de l'intervalle déclaré du paramètre
    "REJ-CALC-FLUX-VIDES",  # liste de flux vide (ou trop courte pour le calcul demandé)
    "REJ-CALC-FLUX-INVALIDES",  # flux mal formés, trop nombreux, ou tous nuls
    "REJ-CALC-FREQUENCE-INCONNUE",  # fréquence de paiement hors de la liste fermée
    "REJ-CALC-CONVENTION-INCONNUE",  # convention de taux hors de la liste fermée
    "REJ-CALC-DUREE-INVALIDE",  # nombre de périodes, d'années ou de semaines hors bornes
    "REJ-CALC-BORNE-DEPASSEE",  # budget de calcul dépassé (tirages, tirages x flux, hypothèses, scénarios)
    "REJ-CALC-DISTRIBUTION-INVALIDE",  # distribution inconnue ou paramètres incohérents (min > mode, écart-type ≤ 0...)
    "REJ-CALC-GRAINE-INVALIDE",  # graine absente ou hors de [0, 2^63 - 1] : jamais une graine tirée de l'horloge
    "REJ-CALC-MARGE-NON-POSITIVE",  # point mort : prix unitaire ≤ coût variable unitaire, aucun point mort n'existe
    "REJ-CALC-HYPOTHESE-INVALIDE",  # sensibilité : hypothèse inconnue, bas/haut illisibles ou hors bornes
    "REJ-CALC-SCENARIO-INVALIDE",  # scénario mal nommé, en double, ou qui change une hypothèse inconnue
    "REJ-CALC-PREVISION-NON-CALCULABLE",  # Monte-Carlo : la prévision existante n'a aucune semaine calculable
    "REJ-CALC-OBJET-HORS-PERIMETRE",  # garde NC 31-103 : placement en titres, portefeuille, crypto... jamais calculé
    "REJ-CALC-RECU-INVALIDE",  # reçu mal formé, empreinte qui ne correspond pas à son contenu
    "REJ-CALC-MOTEUR-INCONNU",  # reçu d'un moteur ou d'une version que ce code ne sait pas rejouer
    "REJ-CALC-COUTS-REQUIS",  # Monte-Carlo : la vue sans droit aux coûts ne voit aucun montant
    "REJ-CALC-PAGE-INVALIDE",  # depart ou limite d'une page hors bornes
    "REJ-CALC-AMORTISSEMENT-IMPOSSIBLE",  # le versement arrondi ne couvre pas l'intérêt de la première période
]
_CODES = frozenset(CODES_CALCUL)


class CodeCalculInconnu(ValueError):
    pass


def construire_verdict(code: str, detail: str = "") -> dict[str, str]:
    if code not in _CODES:
        raise CodeCalculInconnu(f"code de refus du moteur de calcul inconnu : {code!r}")
    return {"code": code, "detail": detail}
