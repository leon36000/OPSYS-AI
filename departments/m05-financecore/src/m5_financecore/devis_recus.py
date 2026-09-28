"""Devis acceptés reçus par M5 via `m3.devis_accepte` (PLAN T1.2-d, suite : facture brouillon).

Dans le flux réel, la complétion des travaux (`m4.travaux_termines`) peut arriver AVANT ou APRÈS
l'acceptation du devis chez M3 — le répartiteur (ADR-0009 §3) livre les deux événements dans
l'ordre où ils ont été publiés, jamais dans un ordre garanti entre deux TYPES différents. Ce
module garde ce que M5 a reçu du devis (devis_id, lead_id, chantier_id, lignes, prix_total,
horodatage_acceptation — exactement ce qu'il faut à `outils._essayer_facture_brouillon` pour
créer la facture, rien de plus, même discipline que M6 `wct_recus.py`) dans un registre durable
DÉDIÉ, DISTINCT de celui des factures et de celui des WCT reçus (`wct_recus.py`) : ni une facture,
ni une intervention terminée.

Idempotent par devis_id : un devis accepté est immuable une fois publié (M3 ne republie
`m3.devis_accepte` qu'une fois par devis, à l'acceptation — voir le catalogue) — une redélivrance
porte toujours la même charge, donc un second enregistrement est un NO-OP silencieux qui garde le
premier, jamais une erreur ni un doublon. En pratique ni le bus (idempotent par `evenement_id`, un
seul reçu par devis côté M5) ni ce module ne devraient jamais voir une vraie redélivrance ;
l'idempotence ici est une défense supplémentaire (appel direct, tests, concurrence), pas la seule
ligne de défense.

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["construire", "pour_devis_id"]


def construire(
    devis_id: Any,
    lead_id: Any,
    chantier_id: Any,
    lignes: Any,
    prix_total: Any,
    horodatage_acceptation: Any,
) -> dict[str, Any]:
    """Le maillon devis reçu — construction pure, sans écriture (l'appelant, `outils.py`, vérifie
    d'abord `pour_devis_id` et n'ajoute que si absent : l'idempotence vit là, pas ici)."""
    return {
        "devis_id": devis_id,
        "lead_id": lead_id,
        "chantier_id": chantier_id,
        "lignes": lignes,
        "prix_total": prix_total,
        "horodatage_acceptation": horodatage_acceptation,
    }


def pour_devis_id(devis_id: Any, maillons_existants: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Le devis reçu pour ce devis_id, ou None si M5 ne l'a jamais reçu."""
    for maillon in maillons_existants:
        if maillon.get("devis_id") == devis_id:
            return maillon
    return None
