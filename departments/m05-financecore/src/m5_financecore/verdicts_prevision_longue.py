"""Catalogue FERMÉ des refus de la prévision longue M5 (M5-PREV-2).

Pourquoi un catalogue à part : `validation.py` est épinglé par empreinte pour la paie et partagé par tous les modules
M5 ; un chantier parallèle (trésorerie 13 semaines) le touche en même temps. Même précédent que `verdicts_rapports.py` :
les
codes de ce chantier vivent ici, sont fermés (un code absent lève, il n'est jamais rendu par accident) et ne changent
pas les codes existants.

Module pur : aucune entrée-sortie, aucune horloge, aucun import `opsys`.
"""

from __future__ import annotations

from typing import Any

__all__ = ["CODES", "CodeVerdictInconnu", "construire_verdict"]


class CodeVerdictInconnu(ValueError):
    """Un code hors catalogue : erreur du code, jamais une donnée d'appelant."""


CODES = frozenset({
    "REJ-PREVISION-LONGUE-A-DECLARER",
    "REJ-PREVISION-LONGUE-CONFIGURATION-INVALIDE",
    "REJ-PREVISION-LONGUE-HORIZON-INVALIDE",
    "REJ-PREVISION-LONGUE-DATE-INVALIDE",
    "REJ-PREVISION-LONGUE-SOLDE-INVALIDE",
    "REJ-PREVISION-LONGUE-MOIS-HISTORIQUE-INVALIDE",
    "REJ-PREVISION-LONGUE-SCENARIOS-A-DECLARER",
    "REJ-PREVISION-LONGUE-SCENARIO-INVALIDE",
    "REJ-PREVISION-LONGUE-SCENARIO-DOUBLE",
    "REJ-PREVISION-LONGUE-SCENARIO-INCONNU",
    "REJ-PREVISION-LONGUE-CROISSANCE-INVALIDE",
    "REJ-PREVISION-LONGUE-SAISONNALITE-A-DECLARER",
    "REJ-PREVISION-LONGUE-SAISONNALITE-INVALIDE",
    "REJ-PREVISION-LONGUE-DELAI-INVALIDE",
    "REJ-PREVISION-LONGUE-HISTORIQUE-INVALIDE",
    "REJ-PREVISION-LONGUE-HISTORIQUE-INCOMPLET",
    "REJ-PREVISION-LONGUE-BUDGET-INVALIDE",
    "REJ-PREVISION-LONGUE-BUDGET-DOUBLE",
    "REJ-PREVISION-LONGUE-BUDGET-HORS-PLAN",
    "REJ-PREVISION-LONGUE-CARNET-INVALIDE",
    "REJ-PREVISION-LONGUE-CARNET-DOUBLE",
    "REJ-PREVISION-LONGUE-CARNET-DATE-INVALIDE",
    "REJ-PREVISION-LONGUE-CHAINE-INVALIDE",
    "REJ-PREVISION-LONGUE-PLAN-INVALIDE",
    "REJ-PREVISION-LONGUE-STOCKAGE-NON-DURABLE",
    "REJ-PREVISION-LONGUE-ECHEANCIER-INVALIDE",
    "REJ-PREVISION-LONGUE-LIMITE-INVALIDE",
    "REJ-PREVISION-LONGUE-TRANSPORT-INVALIDE",
    "REJ-PREVISION-LONGUE-REPONSE-TROP-GROSSE",
    "REJ-PREVISION-LONGUE-RECU-INVALIDE",
    "REJ-PREVISION-LONGUE-REJEU-DIFFERENT",
})


def construire_verdict(code: str, detail: str = "") -> dict[str, Any]:
    """Le verdict nommé `{code, detail}`. Un code hors catalogue lève : un refus ne s'invente pas."""
    if code not in CODES:
        raise CodeVerdictInconnu(f"code de refus inconnu de la prévision longue : {code!r}")
    return {"code": code, "detail": detail}
