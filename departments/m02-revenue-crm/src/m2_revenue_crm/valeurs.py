"""Valeur déclarée d'une opportunité (M2.4 rentabilité, M2.15 valeur pondérée) : un chiffre que le VENDEUR déclare,
jamais un prix de M3 ni un montant comptable.

M2 n'est pas la source de vérité financière (SOUL.md : « Stocker un prix, un montant ou une date de chantier… rejeté à
l'ingestion »). Pour pondérer un pipeline, il faut pourtant un ordre de grandeur par opportunité : le vendeur le
DÉCLARE, en dollars canadiens au cent près, dans un registre dédié, chaîné et append-only (`valeurs_pipeline`). Cette
valeur est une ESTIMATION COMMERCIALE : elle n'engage rien, ne remplace pas la soumission de M3 et n'est jamais
présentée comme un prix. Sans valeur déclarée, tout calcul qui en a besoin est « non calculable, manque la valeur
déclarée » : aucun montant n'est inventé ni moyenné à la place. À valider auprès d'un comptable (CPA) / professionnel
qualifié avant tout usage comptable.

Module PUR : aucune entrée-sortie.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from . import horodatage as _horodatage
from .verdicts_commercial import construire_verdict

__all__ = ["MONTANT_MAX_CENTS", "REGISTRE", "TYPE_ENTREE", "construire", "courantes", "lire_bandes", "texte_montant"]

TYPE_ENTREE = "valeur_pipeline"
REGISTRE = "valeurs_pipeline"
MONTANT_MAX_CENTS = 10**11  # 1 milliard de dollars : au-delà, une faute de frappe
_RE_MONTANT = re.compile(r"^[0-9]{1,12}(\.[0-9]{1,2})?$")


def _refus(code: str, detail: str) -> tuple[None, dict[str, str]]:
    return None, construire_verdict(code, detail=detail)


def en_cents(montant: Any) -> tuple[int | None, dict[str, str] | None]:
    """Un montant en texte décimal (« 12500 », « 12500.50 ») -> cents entiers. Un nombre, un signe, une virgule, un
    espace ou plus de deux décimales sont refusés : aucun flottant n'entre."""
    if type(montant) is not str or _RE_MONTANT.fullmatch(montant) is None:
        return _refus("REJ-PREV-VALEUR-INVALIDE", "montant : texte décimal positif au cent près (« 12500.00 »)")
    try:
        cents = int((Decimal(montant) * 100).to_integral_exact())
    except InvalidOperation:
        return _refus("REJ-PREV-VALEUR-INVALIDE", "montant illisible")
    if not 0 < cents <= MONTANT_MAX_CENTS:
        return _refus("REJ-PREV-VALEUR-INVALIDE", "montant : supérieur à zéro et au plus un milliard")
    return cents, None


def texte_montant(cents: int) -> str:
    """Cents entiers -> « 12500.50 »."""
    return f"{cents // 100}.{cents % 100:02d}"


def construire(
    lead_id: str,
    montant: Any,
    *,
    declare_par: str,
    voie: str,
    horodatage: str,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """L'entrée du registre pour une valeur déclarée, ou un refus. La plus récente fait foi ; l'historique reste."""
    cents, verdict = en_cents(montant)
    if verdict is not None:
        return None, verdict
    try:
        _horodatage.valider_horodatage(horodatage)
    except ValueError:
        return _refus("REJ-PREV-VALEUR-INVALIDE", "horodatage : ISO-8601 avec fuseau attendu")
    return {
        "type_entree": TYPE_ENTREE,
        "lead_id": lead_id,
        "montant_cents": cents,
        "devise": "CAD",
        "nature": "estimation_commerciale_declaree",
        "declare_par": declare_par,
        "voie": voie,
        "horodatage": horodatage,
    }, None


def courantes(maillons: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """`{lead_id: montant en cents}` : la dernière déclaration de chaque lead."""
    sortie: dict[str, int] = {}
    for maillon in maillons:
        if maillon.get("type_entree") == TYPE_ENTREE and type(maillon.get("montant_cents")) is int:
            sortie[maillon["lead_id"]] = maillon["montant_cents"]
    return sortie


def lire_bandes(brut: Any) -> list[int] | None:
    """Les trois bandes croissantes de `configuration.scoring.bandes_valeur_cents`, ou `None` (absentes ou invalides :
    le
    facteur « valeur » est alors non évalué, jamais calculé avec des bandes devinées)."""
    if isinstance(brut, Mapping):
        brut = brut.get("bandes_valeur_cents")
    if (
        isinstance(brut, list)
        and len(brut) == 3
        and all(type(v) is int and v > 0 for v in brut)
        and brut[0] < brut[1] < brut[2]
    ):
        return list(brut)
    return None
