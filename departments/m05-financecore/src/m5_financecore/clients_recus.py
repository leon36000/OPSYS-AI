"""Clients associés reçus par M5 via `m2.client_associe` (PLAN T2.2, Client 360 de M2).

Avant ce correctif, `_essayer_facture_brouillon` facturait avec `client_id = lead_id`, faute de
Client 360 côté M2 (documenté en commentaire à l'endroit même de l'appel). M2 publie maintenant
`m2.client_associe` à l'ingestion de chaque lead — bien AVANT qu'un devis (M3) ou une complétion
(M4) puisse exister pour ce même lead, puisqu'un lead doit d'abord être qualifié, converti, cédulé
et exécuté. Ce module garde ce lien (lead_id -> client_id) dans un registre durable DÉDIÉ, DISTINCT
des autres (`devis_recus.py`, `wct_recus.py`, `variance_recus.py`) — même discipline que ceux-ci.

Idempotent par lead_id : le lien est immuable une fois publié (`clients.lier_lead` côté M2 est
lui-même idempotent par lead_id — le contact d'un lead ne change jamais après ingestion) — une
redélivrance porte toujours la même charge, donc un second enregistrement est un NO-OP silencieux,
jamais une erreur ni un doublon.

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["construire", "pour_lead_id"]


def construire(lead_id: Any, client_id: Any, horodatage_association: Any) -> dict[str, Any]:
    """Le maillon client associé reçu — construction pure, sans écriture (l'appelant, `outils.py`,
    vérifie d'abord `pour_lead_id` et n'ajoute que si absent : l'idempotence vit là, pas ici)."""
    return {
        "lead_id": lead_id,
        "client_id": client_id,
        "horodatage_association": horodatage_association,
    }


def pour_lead_id(lead_id: Any, maillons_existants: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Le client associé reçu pour ce lead_id, ou None si M5 ne l'a jamais reçu (le devis/WCT
    facture alors avec le repli documenté par `_essayer_facture_brouillon`, jamais un blocage)."""
    for maillon in maillons_existants:
        if maillon.get("lead_id") == lead_id:
            return maillon
    return None
