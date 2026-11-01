"""Ce que M5 constate pour M8 et que M8 ne peut pas lire lui-même : la dépense publicitaire COMPTABILISÉE (D1) et les
factures clients ÉMISES (D3), décisions de `docs/architecture/M8-ENTREPOT-SOURCES.md`.

Module pur (même règle que `operations_periodes.py`) : aucun import d'`opsys`, aucune horloge, aucun accès réseau,
aucune
écriture. Il reçoit l'état déjà lu du grand livre et les factures déjà lues, et rend la charge d'un événement du
catalogue (schéma fermé, minimisé). Que des nombres et des montants en CAD (texte décimal) : aucun fournisseur, aucun
client, aucun libellé, aucune pièce, aucun nom de campagne.

DÉPENSE PUBLICITAIRE COMPTABILISÉE. M5 range un brouillon de charge pour chaque relevé HORS_TAXES de M7
(`charges_marketing_recues.py`, pièce déclarée `m7:<relevé>:r<révision>`) ; une personne le valide (N4). Ce que le
grand livre
a COMPTABILISÉ est donc le solde net (débits moins crédits) sur le compte de la catégorie « marketing » des écritures
DÉFINITIVES dont la pièce est un relevé de M7 : l'écriture d'origine et sa contre-passation (qui reprend la même pièce)
s'annulent. Un brouillon n'est jamais comptabilisé : il est compté à part (`brouillons_en_attente`). La période est
celle de
la DATE D'EFFET de l'écriture (la fin du relevé). Aucun autre compte, aucune autre dépense de marketing que celles de
M7 : l'écart que M8 en tire est un écart de DÉFINITION entre deux départements, pas une erreur.

FACTURE ÉMISE. Une facture est émise quand une personne l'a ENVOYÉE (N4) ; ENVOYEE, PAYEE et ANNULEE (après envoi) sont
publiées, jamais BROUILLON ni une facture ANNULEE qui n'a jamais été envoyée. Sans client, sans chantier, sans devis,
sans ligne.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import encodage

__all__ = [
    "charge_depense_publicitaire",
    "charge_facture_emise",
    "depense_publicitaire_comptabilisee",
    "version_depense",
]

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_PREFIXE_PIECE_M7 = "m7:"
_JOURS_MAX = 366
_STATUTS_EMIS = ("ENVOYEE", "PAYEE", "ANNULEE")


def _txt(valeur: Decimal) -> str:
    return format(valeur.quantize(_CENT, rounding=ROUND_HALF_UP), "f")


def _jour(texte: Any) -> date | None:
    if not isinstance(texte, str) or len(texte) != 10:
        return None
    try:
        return date.fromisoformat(texte)
    except ValueError:
        return None


def _vient_d_un_releve(ecriture: Mapping[str, Any]) -> bool:
    piece = ecriture.get("piece")
    reference = piece.get("reference") if isinstance(piece, Mapping) else None
    return isinstance(reference, str) and reference.startswith(_PREFIXE_PIECE_M7)


def _net_sur_compte(ecriture: Mapping[str, Any], compte: str) -> Decimal:
    return sum(
        (
            Decimal(ligne["debit"]) - Decimal(ligne["credit"])
            for ligne in ecriture["lignes"]
            if ligne["compte"] == compte
        ),
        _ZERO,
    )


def depense_publicitaire_comptabilisee(
    etat_gl: Mapping[str, Any], compte_charge: str, debut: Any, fin: Any
) -> tuple[dict[str, Any] | None, str | None]:
    """`({comptabilise, ecritures_definitives, brouillons_en_attente, brouillons_en_attente_cad}, None)` pour les
    écritures
    de relevés de M7 dont la date d'effet est dans `[debut, fin]` ; `(None, raison)` si la période est illisible,
    inversée ou
    de plus de 366 jours. Les montants sont des `Decimal` au cent."""
    d, f = _jour(debut), _jour(fin)
    if d is None or f is None:
        return None, "debut et fin : dates AAAA-MM-JJ exigées"
    if f < d or (f - d).days >= _JOURS_MAX:
        return None, f"période inversée ou de plus de {_JOURS_MAX} jours"
    net = _ZERO
    definitives = 0
    brouillons = 0
    net_brouillons = _ZERO
    for ident in etat_gl["ordre"]:
        ecriture = etat_gl["ecritures"][ident]
        jour_effet = _jour(ecriture.get("date_effet"))
        if jour_effet is None or not d <= jour_effet <= f or not _vient_d_un_releve(ecriture):
            continue
        if not any(ligne["compte"] == compte_charge for ligne in ecriture["lignes"]):
            continue  # une écriture de relevé qui ne touche pas le compte de charge marketing n'est ni comptée ni
            # sommée
        if ecriture["statut"] == "DEFINITIVE":
            definitives += 1
            net += _net_sur_compte(ecriture, compte_charge)
        elif ecriture["statut"] == "BROUILLON":
            brouillons += 1
            net_brouillons += _net_sur_compte(ecriture, compte_charge)
    return {
        "comptabilise": net,
        "ecritures_definitives": definitives,
        "brouillons_en_attente": brouillons,
        "brouillons_en_attente_cad": net_brouillons,
    }, None


def charge_depense_publicitaire(
    mesure: Mapping[str, Any], *, debut: str, fin: str, date_reference: str, sequence: int, version_donnees: str
) -> dict[str, Any]:
    """La charge de `m5.depense_publicitaire_constatee` (schéma fermé du catalogue du socle)."""
    return {
        "evenement_id": f"m5-depense-pub-{sequence}-{debut}-{fin}-{version_donnees}",
        "sequence": sequence,
        "date_reference": date_reference,
        "periode_debut": debut,
        "periode_fin": fin,
        "version_donnees": version_donnees,
        "devise": "CAD",
        "base_taxes": "HORS_TAXES",
        "comptabilise_cad": _txt(mesure["comptabilise"]),
        "ecritures_definitives": mesure["ecritures_definitives"],
        "brouillons_en_attente": mesure["brouillons_en_attente"],
        "brouillons_en_attente_cad": _txt(mesure["brouillons_en_attente_cad"]),
    }


def version_depense(mesure: Mapping[str, Any], debut: str, fin: str) -> str:
    """Les 16 premiers caractères de l'empreinte du calcul : la même période et les mêmes écritures, la même version."""
    return encodage.empreinte(
        "m5.depense_publicitaire.v1",
        debut,
        fin,
        _txt(mesure["comptabilise"]),
        mesure["ecritures_definitives"],
        mesure["brouillons_en_attente"],
        _txt(mesure["brouillons_en_attente_cad"]),
    )[:16]


def charge_facture_emise(etat: Mapping[str, Any]) -> dict[str, Any] | None:
    """La charge de `m5.facture_emise_constatee` d'après l'état courant d'une facture, ou `None` si elle n'est pas
    émise (BROUILLON, ou ANNULEE sans jour d'envoi : elle n'a jamais été envoyée). Les montants viennent de M5 tels
    quels."""
    statut = etat.get("statut")
    jour = _jour(str(etat.get("date_envoi"))[:10]) if etat.get("date_envoi") else None
    facture_id = etat.get("facture_id")
    if statut not in _STATUTS_EMIS or jour is None or not isinstance(facture_id, str) or not facture_id:
        return None
    try:
        avant = Decimal(str(etat["montant_avant_taxes"]))
        taxes = Decimal(str(etat["total_taxes"]))
        apres = Decimal(str(etat["montant_apres_taxes"]))
    except (KeyError, ArithmeticError, ValueError):
        return None
    return {
        "evenement_id": f"m5-facture-emise-{facture_id}-{statut}",
        "facture_id": facture_id,
        "statut": statut,
        "emise_le": jour.isoformat(),
        "devise": "CAD",
        "montant_avant_taxes_cad": _txt(avant),
        "total_taxes_cad": _txt(taxes),
        "montant_apres_taxes_cad": _txt(apres),
    }
