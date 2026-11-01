"""Catalogue FERMÉ des refus typés de la mesure marketing de M7 (`REJ-MESURE-*`).

Même patron que `verdicts_calcul.py` de M5 et `verdicts_commercial.py` de M2 : un verdict est `{code, statut,
detail}` ; un code hors catalogue est une faute de programmation (`CodeVerdictInconnu`), jamais un refus à code
inventé en cours de route. Le détail dit quoi corriger ; il ne recopie jamais une valeur personnelle.
"""

from __future__ import annotations

from typing import Any

CODES_MESURE_LIST = [
    # -- UTM
    "REJ-MESURE-UTM-ENTREE-INVALIDE",  # URL ou valeur absente, trop longue, avec caractère de contrôle ou hors bornes
    "REJ-MESURE-UTM-NON-NORMALISABLE",  # valeur que la convention ne sait pas ramener à un énuméré
    # -- conversions hors ligne
    "REJ-MESURE-CONVERSION-INVALIDE",  # champ absent, mal typé ou hors énuméré
    "REJ-MESURE-CONVERSION-CHAMP-INCONNU",  # champ hors de la liste fermée (minimisation, Loi 25)
    "REJ-MESURE-CONVERSION-COORDONNEE",  # un identifiant qui ressemble à un courriel ou à un téléphone
    "REJ-MESURE-CONVERSION-VALEUR",  # valeur en CAD mal formée (texte décimal >= 0, 2 décimales au plus)
    "REJ-MESURE-CONVERSION-FUTURE",  # conversion datée d'après l'instant de l'import
    "REJ-MESURE-CONVERSION-CONFLIT",  # même conversion, même révision, contenu différent
    "REJ-MESURE-CONVERSION-REVISION-PERIMEE",  # la révision existe déjà
    "REJ-MESURE-CONVERSION-REVISION-SAUTEE",  # la révision suivante est attendue
    "REJ-MESURE-CONVERSION-REVISION-INITIALE",  # une nouvelle conversion commence à la révision 1
    "REJ-MESURE-CONVERSION-MOTIF",  # une révision exige un motif de l'énuméré
    "REJ-MESURE-LOT-TROP-GROS",  # plus de 200 conversions dans un lot
    "REJ-MESURE-JOURNAL-ALTERE",  # la chaîne de hachage d'un registre ne correspond plus
    # -- conception statistique
    "REJ-MESURE-ARGUMENT-INVALIDE",  # entrées absentes, mal typées ou champs inconnus
    "REJ-MESURE-TAUX-INVALIDE",  # proportion hors de ]0 ; 1[
    "REJ-MESURE-ALPHA-INVALIDE",  # seuil alpha hors bornes
    "REJ-MESURE-PUISSANCE-INVALIDE",  # puissance visée hors bornes
    "REJ-MESURE-EFFET-INVALIDE",  # effet nul, hors bornes ou rendant le test irréaliste
    "REJ-MESURE-HISTORIQUE-INSUFFISANT",  # moins de huit semaines d'historique
    "REJ-MESURE-SERIE-DEGENEREE",  # historique constant ou moyenne nulle : la variance ne dit rien
    "REJ-MESURE-GRAINE-INVALIDE",  # graine hors de [0 ; 2^64[
    "REJ-MESURE-REGIONS-INVALIDES",  # régions mal formées, en double ou sans mesure de base
    "REJ-MESURE-ECHANTILLON-INVALIDE",  # comptes k/n impossibles
    "REJ-MESURE-PERIODE-INVALIDE",  # dates de plan ou de données invalides
    "REJ-MESURE-MOTEUR-INCONNU",  # moteur ou version inconnus
    "REJ-MESURE-RECU-INVALIDE",  # reçu retouché, compact ou d'un moteur inconnu
    # -- préenregistrement
    "REJ-MESURE-PLAN-INVALIDE",  # plan mal formé
    "REJ-MESURE-PLAN-EXISTANT",  # même plan_id, contenu différent
    "REJ-MESURE-PLAN-INCONNU",  # plan_id absent du registre
    # -- attribution
    "REJ-MESURE-ATTRIBUTION-INVALIDE",  # période ou entrées de l'attribution invalides
]
CODES_MESURE = frozenset(CODES_MESURE_LIST)


class CodeVerdictInconnu(ValueError):
    """Code hors du catalogue de la mesure marketing."""


def est_verdict(code: object) -> bool:
    return code in CODES_MESURE


def construire_verdict(code: str, statut: str = "", detail: str = "") -> dict[str, str]:
    if not est_verdict(code):
        raise CodeVerdictInconnu(f"Code verdict de mesure invalide : {code!r}")
    return {"code": code, "statut": statut, "detail": detail}


def refus_outil(verdict: dict[str, Any], chemin: str = "$") -> dict[str, Any]:
    """Un verdict mis à la forme des refus d'outil de M7 : `{accepte: False, refus: [{code, chemin, detail}]}`."""
    return {"accepte": False, "refus": [{"code": verdict["code"], "chemin": chemin, "detail": verdict["detail"]}]}


__all__ = [
    "CODES_MESURE",
    "CODES_MESURE_LIST",
    "CodeVerdictInconnu",
    "construire_verdict",
    "est_verdict",
    "refus_outil",
]
