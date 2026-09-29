"""Charge de l'événement `m6.reception_enregistree` (M6.16 « pont finance vers M5 », PLAN T4.15).

Module PUR (AGENTS.md, ADR-0009) : aucun import `opsys`, aucune horloge, aucun aléa, aucun réseau. C'est
`outils.py` (l'adaptateur, seul) qui publie ; ce module ne fait que CONSTRUIRE la charge et refuser ce qui
ne peut pas devenir un fait publiable.

CE QUE M6 DIT À M5, ET CE QU'IL NE DIT PAS. M6 est la source de vérité du bon de commande et de la
réception : il dit ce qui a été commandé, ce qui est arrivé cette fois-là, à quel prix unitaire le PO l'avait
prévu et à quel prix la réception l'a résolu. M5 est la source de vérité de l'argent : c'est LUI qui multiplie,
arrondit et ajoute les taxes (P13, `docs/produit/DEFINITION-PRODUIT.md` §5). Cette charge ne porte donc aucun
montant calculé : seulement des quantités et des prix unitaires, en TEXTE décimal (`Decimal(str(x))`, jamais
`Decimal(x)` sur un float, jamais un nombre JSON). Les registres de M6 gardent leurs quantités et leurs prix en
`float` (contrat gelé) : la conversion en texte est la frontière, et elle est exacte (`format(..., "f")`, jamais
la notation scientifique que `str(1e-07)` produirait).

UNITÉ DES PRIX (GATE NATHAN, PLAN T4.15). Le livre de prix ne déclare pas l'unité d'un prix unitaire, et le PO ne
déclare pas celle d'une quantité. Ce module ne convertit RIEN et n'invente aucune unité : les deux valeurs sont
recopiées telles quelles, et le schéma du catalogue le dit.

FAIL-CLOSED. Une quantité reçue négative, non finie ou non numérique n'est pas une livraison : elle est refusée
AVANT toute écriture au stock (`verifier_reception`, appelé par `outils.receptionner_commande` avant
`materiel.enregistrer_reception`). Un prix illisible devient `null` (inconnu), jamais un nombre inventé. Un
écart de prix est évalué seulement si le seuil ET les deux prix sont connus, sinon `null`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from . import verdicts

__all__ = [
    "TYPE_EVENEMENT",
    "construire_charge",
    "evenement_id",
    "texte_decimal",
    "verifier_reception",
]

# Type du catalogue du socle (`src/opsys/evenements/catalogue/m6.reception_enregistree.json`) : M6 en est le
# seul producteur. Le nom seulement : la publication (`opsys.evenements`) reste dans `outils.py`.
TYPE_EVENEMENT = "m6.reception_enregistree"

_VERDICTS_PUBLIABLES = frozenset({"CONFORME", "RECEPTION_INFERIEURE", "RECEPTION_SUPERIEURE", "RECEPTION_MIXTE"})
_STATUTS_PO_PUBLIABLES = frozenset({"received", "partially_received"})
_RFC_3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"
)
_HASH_HEX = re.compile(r"^[0-9a-f]{64}$")
_LONGUEUR_EMPREINTE_ID = 16
# Longueur maximale d'un texte décimal de la charge (`maxLength` du schéma du catalogue) : M5 multiplie deux de ces
# textes en précision étendue, jamais tronquée. Un nombre plus long (1e-300 s'écrit sur 300 caractères) n'est pas
# une livraison.
_LONGUEUR_TEXTE_MAX = 40


def texte_decimal(valeur: Any) -> str | None:
    """Représentation décimale EXACTE, en notation positionnelle, d'un nombre fini de M6 ; `None` sinon.

    `Decimal(str(x))` (jamais `Decimal(x)`, qui importerait l'imprécision binaire du float) puis
    `format(..., "f")` : `str(1e-07)` vaut `'1e-07'`, que le schéma du catalogue refuse et qu'aucun consommateur
    ne devrait avoir à interpréter. Un bool, un texte, `None`, un nombre non fini ou dont l'écriture dépasse
    `_LONGUEUR_TEXTE_MAX`
    caractères rendent `None`."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    if isinstance(valeur, float) and not math.isfinite(valeur):
        return None
    try:
        decimal = Decimal(str(valeur))
    except InvalidOperation:
        return None
    if decimal.is_zero():
        decimal = abs(decimal)  # -0.0 s'écrirait « -0.0 » : un zéro n'a pas de signe
    texte = format(decimal, "f")
    return texte if len(texte) <= _LONGUEUR_TEXTE_MAX else None


def _texte_prix(valeur: Any) -> str | None:
    """Un prix unitaire lisible ET strictement positif, en texte décimal ; `None` sinon. Un prix nul ou négatif
    (un catalogue fourni à l'appel n'est validé nulle part) n'est jamais publié comme un prix : c'est un prix
    inconnu."""
    texte = texte_decimal(valeur)
    return texte if texte is not None and valeur > 0 else None


def _quantite_valide(valeur: Any) -> bool:
    return texte_decimal(valeur) is not None and valeur >= 0


def verifier_reception(reception_po: Any) -> dict[str, Any] | None:
    """`None` si cette réception peut devenir un fait publiable, sinon le verdict du premier défaut.

    À appeler AVANT d'écrire quoi que ce soit au stock, pour une réception rattachée à un PO persisté : un
    défaut découvert après l'écriture forcerait à défaire un stock déjà écrit. Tolérant sur la FORME
    (`reception_po` qui n'est pas un objet, `lignes_recues` qui n'est pas une liste, une ligne sans
    `quantite_recue`) : ces défauts-là appartiennent à `validation.valider_reception_po`, qui les refuse avec
    son propre code juste après. Ici ne sont jugées que les VALEURS, quand elles sont là :
    - `horodatage` : RFC 3339 avec fuseau (M5 en fait la date de sa piste d'audit et n'a pas d'horloge) ;
    - `quantite_recue` de chaque ligne : nombre fini, jamais négatif (zéro : ligne pas encore livrée)."""
    if not isinstance(reception_po, Mapping):
        return None
    horodatage = reception_po.get("horodatage")
    if "horodatage" in reception_po and (not isinstance(horodatage, str) or _RFC_3339.fullmatch(horodatage) is None):
        return verdicts.construire_verdict(
            "REJ-RECEPTION-HORODATAGE-INVALIDE",
            detail="horodatage de la réception : RFC 3339 avec fuseau requis (ex. 2026-09-29T09:15:00-04:00)",
        )
    lignes = reception_po.get("lignes_recues")
    if not isinstance(lignes, list):
        return None
    for index, ligne in enumerate(lignes):
        if isinstance(ligne, Mapping) and "quantite_recue" in ligne and not _quantite_valide(ligne["quantite_recue"]):
            return verdicts.construire_verdict(
                "REJ-RECEPTION-QUANTITE-INVALIDE",
                detail=(
                    f"ligne {index} : quantite_recue doit être un nombre fini, zéro ou plus, de {_LONGUEUR_TEXTE_MAX} "
                    "caractères au plus (un retour au fournisseur n'est pas une réception)"
                ),
            )
    return None


def evenement_id(po_id: str, hash_maillon: str) -> str:
    """Identifiant DÉTERMINISTE de l'événement d'une réception : le PO et les 16 premiers caractères de
    l'empreinte de son dernier mouvement de stock. Deux livraisons d'un même PO ont deux empreintes (le registre
    est hash-chaîné : chaque mouvement porte le précédent) ; rejouer la même réception donne le même identifiant."""
    return f"m6-reception-{po_id}-{hash_maillon[:_LONGUEUR_EMPREINTE_ID]}"


def _ecart_prix_critique(
    materiau_id: str,
    seuil: float | None,
    prix_prevu: Any,
    prix_reception: Any,
    materiaux_en_ecart: frozenset[str],
) -> bool | None:
    """`None` sans seuil ou sans l'un des deux prix (même silence que `bons_commande.detecter_ecarts_prix`,
    qui ne compare jamais un prix connu à `None` ni ne divise par un prix prévu nul)."""
    if seuil is None or _texte_prix(prix_prevu) is None or _texte_prix(prix_reception) is None:
        return None
    return materiau_id in materiaux_en_ecart


def _ligne(
    ligne_accuse: Mapping[str, Any],
    ligne_po: Mapping[str, Any],
    seuil: float | None,
    materiaux_en_ecart: frozenset[str],
) -> dict[str, Any]:
    materiau_id = ligne_accuse["materiau_id"]
    prix_prevu = ligne_po.get("prix_unitaire_prevu")
    prix_reception = ligne_accuse.get("cout_unitaire_resolu")
    return {
        "materiau_id": materiau_id,
        "quantite_demandee": texte_decimal(ligne_accuse["quantite_demandee"]),
        "quantite_recue": texte_decimal(ligne_accuse["quantite_recue"]),
        "prix_unitaire_prevu": _texte_prix(prix_prevu),
        "devise_prevue": ligne_po.get("devise_prevue") if _texte_prix(prix_prevu) is not None else None,
        "verdict_prix_po": ligne_po["verdict_prix"],
        "prix_unitaire_reception": _texte_prix(prix_reception),
        "verdict_prix_reception": ligne_accuse["verdict_resolution_prix"],
        "ecart_prix_critique": _ecart_prix_critique(materiau_id, seuil, prix_prevu, prix_reception, materiaux_en_ecart),
    }


def construire_charge(
    po: Mapping[str, Any],
    accuse_reception: Mapping[str, Any],
    reception_po: Mapping[str, Any],
    seuil_ecart_prix: float | None,
    signaux_ecart_prix: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(charge, None)` : la charge de `m6.reception_enregistree` pour une réception DÉJÀ écrite ; ou
    `(None, verdict)` quand elle ne peut pas être publiée.

    Pas de charge, et pas de verdict d'erreur, pour une réception qui n'a rien reçu (`INDETERMINE`, aucune
    ligne appariée) : rien n'est écrit au stock, rien n'est dû, et l'appelant ne publie rien. Ce cas rend
    `(None, None)`.

    Un refus (`(None, verdict)`) trahit une incohérence interne (un PO ou un accusé de réception qui ne se
    correspondent pas), jamais un cas d'usage : l'appelant LÈVE, ce qui annule la réception entière plutôt que de
    la laisser sans son événement. Les entrées ont déjà été jugées par `verifier_reception` et par
    `validation.valider_reception_po`."""
    lignes_accuse = accuse_reception.get("lignes") or []
    verdict_reception = accuse_reception.get("verdict_reception")
    if not lignes_accuse or verdict_reception == "INDETERMINE":
        return None, None
    if verdict_reception not in _VERDICTS_PUBLIABLES:
        return None, verdicts.construire_verdict(
            "REJ-RECEPTION-EVENEMENT-INCOHERENT", detail=f"verdict_reception inconnu : {verdict_reception!r}"
        )
    if po.get("statut") not in _STATUTS_PO_PUBLIABLES:
        return None, verdicts.construire_verdict(
            "REJ-RECEPTION-EVENEMENT-INCOHERENT",
            detail=f"PO {po.get('po_id')!r} au statut {po.get('statut')!r} après une réception écrite",
        )
    hash_maillon = accuse_reception.get("hash_maillon")
    if not isinstance(hash_maillon, str) or _HASH_HEX.fullmatch(hash_maillon) is None:
        return None, verdicts.construire_verdict(
            "REJ-RECEPTION-EVENEMENT-INCOHERENT", detail="hash_maillon du dernier mouvement de stock illisible"
        )

    lignes_po = {ligne["materiau_id"]: ligne for ligne in po["lignes"]}
    manquantes = [ligne["materiau_id"] for ligne in lignes_accuse if ligne["materiau_id"] not in lignes_po]
    if manquantes:
        return None, verdicts.construire_verdict(
            "REJ-RECEPTION-EVENEMENT-INCOHERENT",
            detail=f"matériaux reçus absents du PO {po['po_id']!r} : {sorted(manquantes)}",
        )
    illisibles = [
        ligne["materiau_id"] for ligne in lignes_accuse
        if texte_decimal(ligne["quantite_demandee"]) is None or texte_decimal(ligne["quantite_recue"]) is None
    ]
    if illisibles:
        return None, verdicts.construire_verdict(
            "REJ-RECEPTION-EVENEMENT-INCOHERENT",
            detail=(
                f"quantité illisible en texte décimal (fini, {_LONGUEUR_TEXTE_MAX} caractères au plus) : "
                f"{sorted(illisibles)}"
            ),
        )
    materiaux_en_ecart = frozenset(signal["materiau_id"] for signal in signaux_ecart_prix)
    charge = {
        "evenement_id": evenement_id(po["po_id"], hash_maillon),
        "po_id": po["po_id"],
        "fournisseur_id": po["fournisseur_id"],
        "chantier_id": po["chantier_id"],
        "horodatage_reception": reception_po["horodatage"],
        "verdict_reception": verdict_reception,
        "statut_po": po["statut"],
        "hash_maillon": hash_maillon,
        "seuil_ecart_prix_pourcentage": seuil_ecart_prix,
        "lignes": [
            _ligne(ligne, lignes_po[ligne["materiau_id"]], seuil_ecart_prix, materiaux_en_ecart)
            for ligne in lignes_accuse
        ],
    }
    return charge, None
