"""Attentes C5/C6 (M6.7, M6.17) : alerte prix BL + achats terrain, lecture seule.

Lecture seule : aucun outil d'écriture n'est appelé ici, jamais de paiement ni d'envoi.
L'employé ne voit aucun montant d'autrui : ces attentes sont admin (console « À voir »).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["attentes_achats_terrain", "attentes_prix_bl"]


def attentes_prix_bl(signaux: Any) -> list[dict[str, Any]]:
    """Une attente `ecart_prix_bl_a_verifier` par signal BL (source `BON_LIVRAISON`), admin N3."""
    sortie = []
    for signal in signaux or []:
        if not isinstance(signal, Mapping):
            continue
        sortie.append({
            "type": "ecart_prix_bl_a_verifier",
            "id": f"ecart_prix_bl:{signal.get('materiau_id')}",
            "resume": (
                f"Prix du bon de livraison contre prix prévu : {signal.get('materiau_id')} "
                f"({signal.get('prix_bl')} contre {signal.get('prix_prevu')}, "
                f"source {signal.get('source_prix')})."
            ),
            "niveau": "N3",
            "action_proposee": "Vérifier la facture du fournisseur, puis rapprocher avec M5.",
        })
    return sortie


def attentes_achats_terrain(decisions: Any) -> list[dict[str, Any]]:
    """Une attente `achat_terrain_a_approuver` par achat en attente admin, N3, sans montant vers l'employé."""
    sortie = []
    for entree in decisions or []:
        if not isinstance(entree, Mapping):
            continue
        decision = entree.get("decision") if isinstance(entree.get("decision"), Mapping) else entree
        if decision.get("statut") != "en_attente_approbation":
            continue
        sortie.append({
            "type": "achat_terrain_a_approuver",
            "id": f"achat_terrain:{entree.get('recu', decision.get('plafond', 'sans-plafond'))}",
            "resume": f"Achat sur place à approuver ({decision.get('motif')}).",
            "niveau": "N3",
            "action_proposee": "L'admin adopte un plafond puis approuve ou refuse cet achat.",
        })
    return sortie
