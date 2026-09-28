"""Signaux de variance de chantier reçus par M5 via `m6.variance_chantier` (PLAN T1.3-c, point 4).

DISTINCT du registre des factures : M5 ne bloque JAMAIS l'envoi d'une facture sur ce signal (M6
« signale seulement », `m6_material_control/variance_chantier.py`) — il l'affiche à côté d'une
facture BROUILLON dans `file_proprietaire` (`outils.attentes`), à titre d'information pour le
propriétaire, jamais comme un verrou.

Contrairement à `devis_recus.py`/`wct_recus.py` (un fait immuable, écrit une seule fois), une
variance PEUT être republiée pour le MÊME `wct_id` sous un `statut_variance` différent (le
catalogue, `opsys.evenements.catalogue.m6.variance_chantier`, le documente explicitement :
`declaration_absente` -> `evaluee` quand la déclaration de matériaux arrive après la complétion).
Ce module garde donc TOUJOURS le DERNIER signal connu par `wct_id` (`pour_wct_id` : dernier
maillon qui correspond, jamais seulement le premier) — la redélivrance du MÊME `evenement_id` est
déjà rendue idempotente par le bus lui-même (`UNIQUE(evenement_id, consommateur)`,
`evenements_recus`, ADR-0009 §3) ; ce module n'a donc rien de plus à garder pour ce cas-là.

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["construire", "pour_wct_id"]


def construire(
    wct_id: Any, chantier_id: Any, statut_variance: Any, signal_critique: Any, horodatage_completion: Any
) -> dict[str, Any]:
    """Le maillon de signal reçu — construction pure, sans écriture (l'appelant, `outils.py`,
    ajoute inconditionnellement : une variance peut légitimement changer de statut, voir plus
    haut, donc il n'y a pas de garde d'idempotence « déjà connu » à faire ici)."""
    return {
        "wct_id": wct_id,
        "chantier_id": chantier_id,
        "statut_variance": statut_variance,
        "signal_critique": signal_critique,
        "horodatage_completion": horodatage_completion,
    }


def pour_wct_id(wct_id: Any, maillons_existants: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Le DERNIER signal connu pour ce wct_id, ou None si M5 n'a jamais reçu de variance pour lui."""
    dernier: dict[str, Any] | None = None
    for maillon in maillons_existants:
        if maillon.get("wct_id") == wct_id:
            dernier = dict(maillon)
    return dernier
