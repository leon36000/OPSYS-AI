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

Le dernier état d'une facture est celui de la plus grande `date_reference`, puis de la PUBLICATION la plus récente
(`publie_le`, l'instant où M5 l'a publié, donné par le bus) : M5 publie un événement par état et l'ordre de LIVRAISON
n'est pas garanti (un réessai après panne fait arriver l'état ancien après le récent ; sans cela, un écart du même
jour serait masqué par un état concordant périmé). Un fait rangé avant ce champ n'en a pas : il passe avant les autres
du même jour, puis l'ordre d'arrivée départage.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Any

REGISTRE = "rapprochements_facture_recus"
TYPE_ENTREE = "rapprochement_facture_recu"
TYPE_ATTENTE_A_FACTURER = "po_a_facturer"
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


def fait(charge: Mapping[str, Any], publie_le: str | None = None) -> dict[str, Any]:
    """Le fait rangé ; `publie_le` (instant de publication fourni par le bus) n'entre pas dans la clé de contenu."""
    rangee = {"type_entree": TYPE_ENTREE, **{cle: charge[cle] for cle in _CLES_UNICITE}}
    if publie_le is not None:
        rangee["publie_le"] = publie_le
    return rangee


def meme_etat(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return all(a.get(cle) == b.get(cle) for cle in _CLES_UNICITE)


_PLUS_ANCIEN = dt.datetime.min.replace(tzinfo=dt.UTC)


def _lisible(m: Any) -> bool:
    """Un maillon COMPLET et lisible : les clés de contenu existent, et les deux clés de tri ont un type sûr.

    Le registre est append-only, mais la base reste éditable hors outil (administrateur de base, migration, ancien
    format) : une ligne incomplète est ignorée, jamais une exception qui rend toute la file d'attentes inutilisable.
    """
    if not isinstance(m, Mapping) or m.get("type_entree") != TYPE_ENTREE:
        return False
    if not all(cle in m for cle in _CLES_UNICITE):
        return False
    return (
        isinstance(m.get("facture_fournisseur_id"), str) and bool(m["facture_fournisseur_id"])
        and isinstance(m.get("date_reference"), str) and bool(m["date_reference"])
    )


def compter_ignores(maillons: Iterable[Mapping[str, Any]]) -> int:
    """Combien de maillons de CE registre sont incomplets/illisibles (donc ignorés par les lectures ci-dessous).

    Les entrées d'un autre type ne sont pas des maillons de ce registre : elles ne sont pas comptées.
    """
    return sum(
        1 for m in maillons
        if isinstance(m, Mapping) and m.get("type_entree") == TYPE_ENTREE and not _lisible(m)
    )


def _publie(m: Mapping[str, Any]) -> dt.datetime:
    try:
        instant = dt.datetime.fromisoformat(m["publie_le"])
    except (KeyError, TypeError, ValueError):
        return _PLUS_ANCIEN
    return instant if instant.tzinfo is not None else _PLUS_ANCIEN


def derniers_etats(maillons: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """`{facture_fournisseur_id: dernier état}` (date de référence, puis publication, puis ordre d'arrivée).

    Un maillon incomplet est ignoré (voir `compter_ignores`) : il ne peut ni servir d'état ni faire lever la lecture.
    """
    derniers: dict[str, tuple[tuple[str, dt.datetime, int], Mapping[str, Any]]] = {}
    for rang, m in enumerate(maillons):
        if not _lisible(m):
            continue
        cle = (m["date_reference"], _publie(m), rang)
        actuel = derniers.get(m["facture_fournisseur_id"])
        if actuel is None or cle >= actuel[0]:
            derniers[m["facture_fournisseur_id"]] = (cle, m)
    return {facture: m for facture, (_, m) in derniers.items()}


def propositions_facturation(
    maillons: Iterable[Mapping[str, Any]], pos: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """C4 : un rapprochement M5 CONCORDANT sur un PO REÇU propose `invoiced` à une personne (N3).

    M6 ne facture pas seul : le PO reste `received` jusqu'à ce qu'un humain applique
    `m6_changer_statut_po` avec un motif. Un PO partiel, déjà facturé/fermé/contesté, inconnu, ou un verdict autre
    que CONCORDANT ne propose rien. Une seule proposition par PO, même si plusieurs factures concordantes le visent.
    Lecture seule, aucun montant dans le texte (l'attente est une décision, pas une pièce comptable)."""
    par_po = {po.get("po_id"): po for po in pos if isinstance(po, Mapping)}
    propositions, vus = [], set()
    for facture, etat in sorted(derniers_etats(maillons).items()):
        if etat.get("verdict") != "CONCORDANT":
            continue
        po_id = etat.get("po_id")
        po = par_po.get(po_id)
        if po is None or po.get("statut") != "received" or po_id in vus:
            continue
        vus.add(po_id)
        propositions.append({
            "type": TYPE_ATTENTE_A_FACTURER,
            "id": po_id,
            "resume": (
                f"Rapprochement M5 concordant pour le PO {po_id} (facture {facture}) : le PO est reçu. "
                "Le passer à « facturé » (invoiced) ? M6 ne facture pas seul."
            ),
            "niveau": "N3",
            "depuis": etat.get("date_reference", ""),
            "action_proposee": "m6_changer_statut_po (statut_cible=invoiced), avec un motif",
        })
    return propositions


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
