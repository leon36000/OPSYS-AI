"""Le rapprochement « bon de commande, réception, facture » que M5 constate, dit à M6 (interconnexion M5 -> M6).

Module PUR (aucun import `opsys`, aucune horloge). M5 est le propriétaire de la facture fournisseur et du verdict
(`CONCORDANT`, `ECART`, `SANS_FACTURE`, `INCOMPLET`) : M6, propriétaire de la commande et de la réception, le REÇOIT, le
range et ne le recalcule jamais. M5 ne publie qu'un identifiant de facture, un identifiant de PO, un verdict, des
montants
avant taxes et des codes de réserve : ni nom de fournisseur, ni numéro de facture, ni prix unitaire.

Ce que M6 en fait : une attente « À voir » de l'admin quand le dernier état d'une facture est `ECART` ou `INCOMPLET`
(ce qu'il a réceptionné n'est pas facturé tel quel, ou le rapprochement ne se calcule pas). L'attente ne propose AUCUNE
action de M6 sur la facture (la facture est à M5) : elle renvoie vers la lecture des comptes à payer de M5. Un état
`CONCORDANT` ou `SANS_FACTURE` n'en crée aucune.

Le dernier état d'une facture est celui de la plus grande `date_reference`, puis du dernier reçu (M5 publie un événement
par état : l'ordre de livraison n'est pas garanti).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

REGISTRE = "rapprochements_facture_recus"
TYPE_ENTREE = "rapprochement_facture_recu"
_CLES_UNICITE = (
    "facture_fournisseur_id",
    "po_id",
    "verdict",
    "sens",
    "facture_avant_taxes",
    "recu_avant_taxes",
    "ecart_avant_taxes",
    "reserves",
    "date_reference",
)


def fait(charge: Mapping[str, Any]) -> dict[str, Any]:
    return {"type_entree": TYPE_ENTREE, **{cle: charge[cle] for cle in _CLES_UNICITE}}


def meme_etat(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return all(a.get(cle) == b.get(cle) for cle in _CLES_UNICITE)


def derniers_etats(maillons: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """`{facture_fournisseur_id: dernier état}`."""
    derniers: dict[str, tuple[tuple[str, int], Mapping[str, Any]]] = {}
    for rang, m in enumerate(maillons):
        if m.get("type_entree") != TYPE_ENTREE:
            continue
        cle = (m["date_reference"], rang)
        actuel = derniers.get(m["facture_fournisseur_id"])
        if actuel is None or cle >= actuel[0]:
            derniers[m["facture_fournisseur_id"]] = (cle, m)
    return {facture: m for facture, (_, m) in derniers.items()}


def attentes(maillons: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Une attente par facture dont le dernier état est un écart ou un rapprochement incomplet."""
    res = []
    for facture, m in sorted(derniers_etats(maillons).items()):
        if m["verdict"] not in ("ECART", "INCOMPLET"):  # les seuls états à signaler à l'admin
            continue
        res.append(
            {
                "type": "rapprochement_po_a_voir",
                "id": facture,
                "niveau": "N3",
                "depuis": m["date_reference"],
                "action_proposee": "m5_lister_comptes_a_payer",
                "resume": (
                    f"M5 constate un rapprochement {m['verdict']} pour le PO {m['po_id']} : ce qui a été réceptionné "
                    "n'est pas facturé tel quel. La facture est à M5 ; M6 ne la modifie pas."
                ),
            }
        )
    return res
