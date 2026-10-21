"""Arithmétique décimale partagée par les mesures de M8 (PLAN T1.5-d, T4.19) : lire un nombre, l'écrire en
texte, lire un seuil.

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge. ``mesures_chantier.py`` (un chantier terminé)
et ``entonnoir.py`` (le trajet commercial) s'en servent : une seule règle d'arrondi et une seule lecture d'un
seuil, jamais deux copies qui divergeraient.

Decimal partout, texte à la sortie : un montant ou un pourcentage n'est jamais un ``float``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

SENS_AU_DESSUS = "au_dessus"
SENS_AU_DESSOUS = "au_dessous"

_CENTIEME = Decimal("0.01")


def decimal_lu(valeur: Any) -> Decimal | None:
    """Décimal fini lu d'un nombre ou d'un texte décimal ; ``None`` sinon (un booléen n'est pas un
    nombre). Jamais une valeur par défaut."""
    if valeur is None or isinstance(valeur, bool):
        return None
    try:
        lu = Decimal(str(valeur).strip())
    except InvalidOperation:
        return None
    return lu if lu.is_finite() else None


def texte_decimal(valeur: Decimal) -> str:
    """Texte décimal à deux décimales (ROUND_HALF_UP), sans « -0.00 »."""
    arrondi = valeur.quantize(_CENTIEME, rounding=ROUND_HALF_UP)
    if arrondi == 0:
        arrondi = arrondi.copy_abs()
    return format(arrondi, "f")


def seuil_valide(brut: Any) -> dict[str, Any] | None:
    """Le seuil ``{sens, valeur}`` lu de la configuration, ou ``None`` s'il n'est pas exactement de cette forme :
    un sens connu (``au_dessus`` ou ``au_dessous``) et une valeur numérique finie (un booléen ou un texte n'en
    est pas une). Une clé de plus est une faute de frappe à dire, jamais à ignorer."""
    if not isinstance(brut, dict) or set(brut) != {"sens", "valeur"}:
        return None
    if brut["sens"] not in (SENS_AU_DESSUS, SENS_AU_DESSOUS):
        return None
    valeur = brut["valeur"]
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    lue = decimal_lu(valeur)
    return None if lue is None else {"sens": brut["sens"], "valeur": lue}
