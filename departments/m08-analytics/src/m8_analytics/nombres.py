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
# Ordre de grandeur lisible : de 1e-15 à 1e15 en valeur absolue (un montant de M5 plafonne à ~1e12). Au-delà, un nombre
# fait lever `texte_decimal` (28 chiffres), `1e999999999` fait déborder le contexte et `1e-999999999` s'écrirait en un
# milliard de caractères : il n'est pas « lisible », la mesure est non calculable et le dit.
_ADJUSTED_MAX = 15


def decimal_lu(valeur: Any) -> Decimal | None:
    """Décimal fini lu d'un nombre ou d'un texte décimal, d'au plus 1e15 en valeur absolue et d'au moins 1e-15 s'il
    n'est pas nul ; ``None`` sinon (un booléen n'est pas un nombre). Jamais une valeur par défaut. Un zéro à exposant
    démesuré (``0E+999999``) est rendu comme le zéro tout court."""
    if valeur is None or isinstance(valeur, bool):
        return None
    try:
        lu = Decimal(str(valeur).strip())
    except (InvalidOperation, ValueError):  # ValueError : un entier de plus de 4 300 chiffres refuse `str`
        return None
    if not lu.is_finite():
        return None
    if lu.is_zero():
        return lu if abs(lu.as_tuple().exponent) <= _ADJUSTED_MAX else Decimal(0)
    return lu if -_ADJUSTED_MAX <= lu.adjusted() <= _ADJUSTED_MAX else None


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
