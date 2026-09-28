"""WCT reçus par M6 via `m4.travaux_termines` — correctif PLAN T1.2-b (le trou du flux réel).

Le trou : dans le flux réel (R12 §4, §9.7), l'employé appuie sur « Terminer » PUIS remplit le
formulaire des matériaux (`materials_submit` dépend de la complétion) ; le devis M3 peut lui
aussi arriver après la complétion (T1.2-d, ailleurs). Le répartiteur livre `m4.travaux_termines`
à M6 presque toujours AVANT que la déclaration ou le prévu existent : le consommateur publiait
`declaration_absente`/`prevu_absent` puis n'était plus jamais rappelé quand la pièce manquante
arrivait — l'intervention restait `completed_pending_review` pour toujours.

Ce module garde ce que M6 a reçu du WCT (wct_id, intervention_id, devis_id,
horodatage_completion — exactement ce qu'il faut pour réévaluer et republier plus tard, rien de
plus) dans un registre durable DÉDIÉ, DISTINCT du registre de mouvements de stock et de celui des
besoins prévus : ni une quantité qui bouge, ni un besoin estimé. `m6_declarer_materiaux_utilises`
et `m6_enregistrer_besoins_prevus` le retrouvent (par wct_id, par devis_id) pour savoir QUEL WCT
réévaluer quand leur propre écriture vient de combler ce qui manquait — voir
`outils.py::_evaluer_et_publier_variance`, la fonction UNIQUE partagée par les trois
déclencheurs.

Idempotent par wct_id : contrairement à `besoins_prevus.py` (deux `devis_id` distincts pour un
même chantier sont légitimes), une redélivrance de `m4.travaux_termines` pour le MÊME wct_id
porte TOUJOURS la même charge (le WCT est immuable une fois écrit côté M4, CA-M4-11) — un second
enregistrement est donc un NO-OP silencieux qui rend le maillon déjà présent, jamais une erreur.
En pratique ni le bus (idempotent par `evenement_id`, un seul reçu par WCT côté M6) ni ce module
ne devraient jamais voir une vraie redélivrance ; l'idempotence ici est une défense supplémentaire
pour un appel direct au consommateur (tests, concurrence), pas la seule ligne de défense.

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["construire", "pour_wct_id", "pour_devis_id"]


def construire(wct_id: Any, intervention_id: Any, devis_id: Any, horodatage_completion: Any) -> dict[str, Any]:
    """Le maillon WCT reçu — construction pure, sans écriture (l'appelant, `outils.py`,
    vérifie d'abord `pour_wct_id` et n'ajoute que si absent : l'idempotence vit là, pas ici)."""
    return {
        "wct_id": wct_id,
        "intervention_id": intervention_id,
        "devis_id": devis_id,
        "horodatage_completion": horodatage_completion,
    }


def pour_wct_id(wct_id: Any, maillons_existants: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Le WCT reçu pour ce wct_id, ou None si M6 ne l'a jamais reçu."""
    for maillon in maillons_existants:
        if maillon.get("wct_id") == wct_id:
            return maillon
    return None


def pour_devis_id(devis_id: Any, maillons_existants: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Le WCT reçu dont le devis_id correspond, ou None (devis_id absent ou jamais vu dans un
    WCT reçu). Un devis_id n'a normalement qu'un seul WCT ; s'il en existait plusieurs, le
    PREMIER (le plus ancien, ordre d'écriture du registre) fait foi — jamais un mélange."""
    if devis_id is None:
        return None
    for maillon in maillons_existants:
        if maillon.get("devis_id") == devis_id:
            return maillon
    return None
