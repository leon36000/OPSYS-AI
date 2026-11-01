"""Factures de fournisseurs reçues par courriel (pont M1 -> M5, M6.16 / M1.6) : une ATTENTE, jamais une écriture
comptable.

M1 trie les courriels (`m1.courriel_aiguille`) et aiguille vers M5 ceux de classe `facture_fournisseur`. M5 en tire
une ligne de suivi append-only : « une facture est arrivée par courriel, à saisir par une personne ». La ligne porte la
provenance (message, règles, confiance, empreinte de l'expéditeur), les références de PO que M5 reconnaît parmi
celles citées, et un drapeau « à vérifier » si le tri a exigé une relecture ou si l'authentification est incomplète
(usurpation possible : une fausse facture est le cas classique).

Aucun montant n'est lu du courriel, aucune facture n'est créée, aucun paiement n'est préparé : la saisie reste humaine
(`m5_saisir_facture_fournisseur`), le paiement N5 (Nathan et un CPA). À valider auprès d'un comptable (CPA) /
professionnel qualifié pour toute écriture ou tout paiement qui en découle.

Module pur : aucun import `opsys`, aucune horloge.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

TYPE_FACTURE_COURRIEL = "facture_fournisseur_courriel_recue"


def identifiant(signal_id: str) -> str:
    return "fc-" + hashlib.sha256(("m5-facture-courriel|" + signal_id).encode()).hexdigest()[:16]


def po_reconnus(charge: Mapping[str, Any], maillons_comptes_a_payer: Iterable[Mapping[str, Any]]) -> list[str]:
    """Les PO cités dans le courriel que les comptes à payer de M5 connaissent déjà (réception de M6), sans casse."""
    cites = {str(r).casefold() for r in (*charge.get("references_po", ()), *charge.get("jetons_reference", ()))}
    connus = {m["po_id"] for m in maillons_comptes_a_payer if isinstance(m.get("po_id"), str)}
    return sorted(p for p in connus if p.casefold() in cites)


def maillon(charge: Mapping[str, Any], po: list[str]) -> dict[str, Any]:
    a_verifier = bool(charge["revue_humaine"]) or not charge["authentification_complete"]
    return {
        "type_entree": TYPE_FACTURE_COURRIEL,
        "horodatage": charge["recu_le"],
        "facture_courriel_id": identifiant(charge["signal_id"]),
        "signal_id": charge["signal_id"],
        "compte_id": charge["compte_id"],
        "nb_pieces": charge["nb_pieces"],
        "po_reconnus": po,
        "a_verifier": a_verifier,
        "raisons_a_verifier": sorted(
            {*charge["motifs_revue"], *([] if charge["authentification_complete"] else ["authentification_incomplete"])}
        ),
        "statut": "a_saisir",
        "provenance": {
            "source": "m1.courriel_aiguille",
            "confiance": charge["confiance"],
            "version_regles": charge["version_regles"],
            "regles": list(charge["regles"])[:40],
            "expediteur_empreinte": charge["expediteur_empreinte"],
        },
    }


def attente(m: Mapping[str, Any]) -> dict[str, Any]:
    morceaux = [
        f"{m['nb_pieces']} pièce(s) jointe(s)",
        f"PO reconnu : {', '.join(m['po_reconnus'])}" if m["po_reconnus"] else "aucun PO reconnu",
    ]
    if m["a_verifier"]:
        morceaux.append("À VÉRIFIER : expéditeur non authentifié ou relecture exigée (fausse facture possible)")
    return {
        "type": "facture_fournisseur_courriel_a_saisir",
        "id": m["facture_courriel_id"],
        "resume": "Facture de fournisseur reçue par courriel : " + " ; ".join(morceaux) + ".",
        "niveau": "N3",
        "depuis": m["horodatage"],
        "action_proposee": "saisir (m5_saisir_facture_fournisseur)",
    }
