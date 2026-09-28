"""WCT reçus par M5 via `m4.travaux_termines` (PLAN T1.2-d, suite : facture brouillon).

Symétrique de `devis_recus.py` : le devis accepté (`m3.devis_accepte`) peut arriver AVANT ou
APRÈS la complétion des travaux chez M4. Ce module garde ce que M5 a reçu du WCT (wct_id,
intervention_id, devis_id — peut être `None`, une intervention peut être inscrite sans devis,
voir `outils._recevoir_travaux_termines` — et horodatage_completion, la seule date que M5 utilise
pour la facture, faute d'horloge propre, DA-M5-06) dans un registre durable DÉDIÉ, DISTINCT de
celui des factures et de celui des devis reçus (`devis_recus.py`).

Idempotent par wct_id : le WCT est immuable une fois écrit côté M4 (CA-M4-11, patron déjà
documenté par M6 `wct_recus.py`) — une redélivrance pour le MÊME wct_id porte toujours la même
charge, donc un second enregistrement est un NO-OP silencieux, jamais une erreur ni un doublon.

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["construire", "pour_wct_id", "pour_devis_id"]


def construire(wct_id: Any, intervention_id: Any, devis_id: Any, horodatage_completion: Any) -> dict[str, Any]:
    """Le maillon WCT reçu — construction pure, sans écriture (l'appelant, `outils.py`, vérifie
    d'abord `pour_wct_id` et n'ajoute que si absent : l'idempotence vit là, pas ici)."""
    return {
        "wct_id": wct_id,
        "intervention_id": intervention_id,
        "devis_id": devis_id,
        "horodatage_completion": horodatage_completion,
    }


def pour_wct_id(wct_id: Any, maillons_existants: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Le WCT reçu pour ce wct_id, ou None si M5 ne l'a jamais reçu."""
    for maillon in maillons_existants:
        if maillon.get("wct_id") == wct_id:
            return maillon
    return None


def pour_devis_id(devis_id: Any, maillons_existants: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Le WCT reçu dont le devis_id correspond, ou None (devis_id absent, ou jamais vu — y compris
    quand `devis_id` vaut `None` : une intervention sans devis ne peut jamais correspondre à une
    recherche par devis_id, `None` n'est pas une clé de jointure valide). Un devis_id n'a
    normalement qu'un seul WCT ; s'il en existait plusieurs, le PREMIER (le plus ancien, ordre
    d'écriture du registre) fait foi — jamais un mélange."""
    if devis_id is None:
        return None
    for maillon in maillons_existants:
        if maillon.get("devis_id") == devis_id:
            return maillon
    return None
