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

__all__ = ["construire", "pour_wct_id", "signal_retenu_pour_wct_id"]


def construire(
    wct_id: Any,
    chantier_id: Any,
    statut_variance: Any,
    signal_critique: Any,
    horodatage_completion: Any,
    lignes: Any = None,
) -> dict[str, Any]:
    """Le maillon de signal reçu — construction pure, sans écriture (l'appelant, `outils.py`,
    ajoute inconditionnellement : une variance peut légitimement changer de statut, voir plus
    haut, donc il n'y a pas de garde d'idempotence « déjà connu » à faire ici).

    `lignes` (PLAN T1.5-d) : le détail par matériau de `m6.variance_chantier` (`quantite_reelle` en texte
    décimal), recopié tel que M6 l'a publié : la SEULE source des matériaux réellement utilisés pour le
    coût réel (`cout_reel.py`). `None` tant que le statut n'est pas `evaluee`, et pour un maillon écrit
    avant ce changement (le coût réel dit alors « détail absent » au lieu d'en deviner un)."""
    return {
        "wct_id": wct_id,
        "chantier_id": chantier_id,
        "statut_variance": statut_variance,
        "signal_critique": signal_critique,
        "horodatage_completion": horodatage_completion,
        "lignes": lignes,
    }


def pour_wct_id(wct_id: Any, maillons_existants: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Le DERNIER signal connu pour ce wct_id, ou None si M5 n'a jamais reçu de variance pour lui."""
    dernier: dict[str, Any] | None = None
    for maillon in maillons_existants:
        if maillon.get("wct_id") == wct_id:
            dernier = dict(maillon)
    return dernier


def signal_retenu_pour_wct_id(wct_id: Any, maillons_existants: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Le signal sur lequel un calcul de coût peut s'appuyer : le DERNIER `evaluee` reçu pour ce wct_id,
    à défaut le dernier signal connu, ou None.

    Pourquoi pas `pour_wct_id` : `evaluee` est TERMINAL chez M6 (plus rien n'est republié après). Or le
    répartiteur peut livrer un signal plus ancien APRÈS un plus récent (réessai d'un événement d'abord en
    échec) : `pour_wct_id` rendrait alors `declaration_absente` alors que l'évaluation existe. Un coût réel
    ne doit pas dépendre de cet ordre de livraison."""
    dernier: dict[str, Any] | None = None
    dernier_evalue: dict[str, Any] | None = None
    for maillon in maillons_existants:
        if maillon.get("wct_id") != wct_id:
            continue
        dernier = dict(maillon)
        if maillon.get("statut_variance") == "evaluee":
            dernier_evalue = dict(maillon)
    return dernier_evalue if dernier_evalue is not None else dernier
