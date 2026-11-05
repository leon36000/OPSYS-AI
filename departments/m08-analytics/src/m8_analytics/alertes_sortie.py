"""Garde de taille pour les alertes M8 relues comme éléments indivisibles par M9.

Le gabarit est celui de ``m9_lire_alertes_m8`` (un élément, sans pagination) ; il est mesuré avec
le même ``json.dumps(..., ensure_ascii=False)`` que le lecteur. Pas d'import inter-département.
"""

from __future__ import annotations

import json
from typing import Any

BUDGET_LECTURE_M9 = 5900  # LIMITE_SORTIE_DEFAUT 6000 moins la réserve d'enveloppe de 100 caractères
_SOURCE = "m8.alerte_proposee (registre m09-strategic-intelligence/alertes_m8)"
_ORDRE = "horodatage_reference décroissant (le plus récent d'abord), puis evenement_id croissant"


def page_unique(charge: dict[str, Any]) -> dict[str, Any]:
    """Enveloppe exacte rendue par `lecture_alertes.lire_alertes_m8([charge], budget>=taille)`."""
    return {
        "type": "ALERTES_M8", "source": _SOURCE, "ordre": _ORDRE, "total": 1, "depart": 0,
        "affichees": 1, "reste": 0, "prochain_depart": None, "message": None, "alertes": [charge],
    }


def taille_page_unique(charge: dict[str, Any], budget: int = BUDGET_LECTURE_M9) -> int:
    """Longueur JSON exacte si elle tient, sinon ``budget + 1`` dès le premier dépassement.

    La borne comprend les échappements JSON (guillemets, antislashs et caractères de contrôle), pas
    seulement les longueurs des champs. Pour refuser une page trop grande, parcourir le reste serait
    inutile et coûteux ; ``budget + 1`` suffit à la décision.
    """
    encodeur = json.JSONEncoder(ensure_ascii=False)
    taille = 0
    for fragment in encodeur.iterencode(page_unique(charge)):
        taille += len(fragment)
        if taille > budget:
            return budget + 1
    return taille


def exiger_page_lisible(charge: dict[str, Any], budget: int = BUDGET_LECTURE_M9) -> int:
    """Refuse une publication que M9 ne pourrait pas rendre en une page, sans recopier le contenu."""
    taille = taille_page_unique(charge, budget)
    if taille > budget:
        raise ValueError(
            f"REJ-M8-ALERTE-BORNE-SORTIE:{charge.get('evenement_id', 'inconnu')}: "
            f"une alerte indivisible dépasse le budget public de {budget} caractères"
        )
    return taille
