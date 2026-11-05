"""Arithmétique décimale exacte et bornée pour les quantités M6."""

from __future__ import annotations

import math
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_DIGITS = 4096
MAX_EXPONENT = 4096


class DecimalIndeterminable(ValueError):
    """Le calcul exact dépasse les limites techniques; aucun résultat arrondi n'est substitué."""

    def __init__(self) -> None:
        super().__init__("REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE")


def somme_decimaux_exactement(termes: Iterable[tuple[Any, int]]) -> Decimal | None:
    """Somme exacte en flux, ou `None` si un coefficient/exposant dépasse les bornes techniques.

    La mémoire dépend des chiffres/exposants du total courant, jamais du nombre de termes. Aux limites
    numériques, un dépassement intermédiaire peut refuser une séquence dont une annulation
    ultérieure aurait ramené le total sous la borne : le refus peut donc dépendre de l'ordre. Chaque
    résultat rendu reste exact; aucun total arrondi n'est substitué au refus.
    """
    try:
        iterator = iter(termes)
    except TypeError:
        return None

    accumulateur = AccumulateurDecimalExact()
    for terme in iterator:
        try:
            valeur, signe = terme
        except (TypeError, ValueError):
            return None
        if not accumulateur.ajouter(valeur, signe):
            return None
    return accumulateur.resultat()


class AccumulateurDecimalExact:
    """Accumulateur exact en flux, sans plafond de termes et borné par chiffres/exposants."""

    __slots__ = ("_exposant", "_initialise", "_invalide", "_total")

    def __init__(self) -> None:
        self._total = 0
        self._exposant = 0
        self._initialise = False
        self._invalide = False

    def ajouter(self, valeur: Any, signe: int) -> bool:
        if self._invalide or type(signe) is not int or signe not in {-1, 1}:
            self._invalide = True
            return False
        try:
            decimal = valeur if isinstance(valeur, Decimal) else Decimal(str(valeur))
        except (InvalidOperation, TypeError, ValueError):
            self._invalide = True
            return False
        if not decimal.is_finite():
            self._invalide = True
            return False
        signe_decimal, chiffres, exposant = decimal.as_tuple()
        if decimal.is_zero():
            return True
        if abs(exposant) > MAX_EXPONENT or len(chiffres) > MAX_DIGITS:
            self._invalide = True
            return False
        try:
            coefficient = int("".join(str(chiffre) for chiffre in chiffres)) if chiffres else 0
        except ValueError:
            self._invalide = True
            return False
        if signe_decimal:
            coefficient = -coefficient
        coefficient *= signe

        if not self._initialise or self._total == 0:
            nouveau_total, nouvel_exposant = coefficient, exposant
        elif exposant < self._exposant:
            decalage = self._exposant - exposant
            chiffres_total = _nombre_chiffres_int(self._total)
            if chiffres_total is None or chiffres_total + decalage > MAX_DIGITS:
                self._invalide = True
                return False
            nouveau_total = self._total * 10**decalage + coefficient
            nouvel_exposant = exposant
        else:
            decalage = exposant - self._exposant
            if len(chiffres) + decalage > MAX_DIGITS:
                self._invalide = True
                return False
            nouveau_total = self._total + coefficient * 10**decalage
            nouvel_exposant = self._exposant

        chiffres_resultat = _nombre_chiffres_int(nouveau_total)
        if chiffres_resultat is None or chiffres_resultat > MAX_DIGITS:
            self._invalide = True
            return False
        if nouveau_total == 0:
            self._total, self._exposant, self._initialise = 0, nouvel_exposant, True
        else:
            self._total, self._exposant, self._initialise = nouveau_total, nouvel_exposant, True
        return True

    def resultat(self) -> Decimal | None:
        if self._invalide:
            return None
        if not self._initialise:
            return Decimal(0)
        try:
            texte_total = str(abs(self._total))
        except ValueError:
            return None
        chiffres_total = tuple(ord(chiffre) - ord("0") for chiffre in texte_total)
        return Decimal((int(self._total < 0), chiffres_total, self._exposant))


def _nombre_chiffres_int(valeur: int) -> int | None:
    try:
        return len(str(abs(valeur)))
    except ValueError:
        return None


def somme_ou_refus(termes: Iterable[tuple[Any, int]]) -> Decimal:
    resultat = somme_decimaux_exactement(termes)
    if resultat is None:
        raise DecimalIndeterminable
    return resultat


def ajouter_exactement(gauche: Any, droite: Any) -> Decimal:
    return somme_ou_refus(((gauche, 1), (droite, 1)))


def soustraire_exactement(gauche: Any, droite: Any) -> Decimal:
    return somme_ou_refus(((gauche, 1), (droite, -1)))


def multiplier_exactement(gauche: Any, droite: Any) -> Decimal:
    """Produit décimal exact sans le contexte de précision ambiant."""
    try:
        gauche_decimal = gauche if isinstance(gauche, Decimal) else Decimal(str(gauche))
        droite_decimal = droite if isinstance(droite, Decimal) else Decimal(str(droite))
    except (InvalidOperation, TypeError, ValueError):
        raise DecimalIndeterminable from None
    if not gauche_decimal.is_finite() or not droite_decimal.is_finite():
        raise DecimalIndeterminable
    signe_g, chiffres_g, exposant_g = gauche_decimal.as_tuple()
    signe_d, chiffres_d, exposant_d = droite_decimal.as_tuple()
    exposant = exposant_g + exposant_d
    if abs(exposant) > MAX_EXPONENT or len(chiffres_g) + len(chiffres_d) > MAX_DIGITS:
        raise DecimalIndeterminable
    try:
        coeff_g = int("".join(str(chiffre) for chiffre in chiffres_g)) if chiffres_g else 0
        coeff_d = int("".join(str(chiffre) for chiffre in chiffres_d)) if chiffres_d else 0
        coefficient = coeff_g * coeff_d
        texte_coefficient = str(coefficient)
    except ValueError:
        raise DecimalIndeterminable from None
    if len(texte_coefficient) > MAX_DIGITS:
        raise DecimalIndeterminable
    signe = int(bool(signe_g) ^ bool(signe_d))
    chiffres = tuple(ord(chiffre) - ord("0") for chiffre in texte_coefficient)
    return Decimal((signe, chiffres, exposant))


def texte_decimal_exact(valeur: Any) -> str | None:
    """Texte décimal sans `normalize()` contextuel, ou `None` si le texte dépasse la borne."""
    try:
        decimal = valeur if isinstance(valeur, Decimal) else Decimal(str(valeur))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not decimal.is_finite():
        return None
    if decimal.is_zero():
        return "0"
    signe, chiffres, exposant = decimal.as_tuple()
    texte = "".join(str(chiffre) for chiffre in chiffres)
    if abs(exposant) > MAX_EXPONENT or len(texte) + max(0, exposant) > MAX_DIGITS:
        return None
    if exposant >= 0:
        rendu = texte + "0" * exposant
    else:
        point = len(texte) + exposant
        rendu = "0." + "0" * -point + texte if point <= 0 else texte[:point] + "." + texte[point:]
        rendu = rendu.rstrip("0").rstrip(".")
    if len(rendu) > MAX_DIGITS:
        return None
    return f"-{rendu}" if signe else rendu


def texte_ou_refus(valeur: Any) -> str:
    resultat = texte_decimal_exact(valeur)
    if resultat is None:
        raise DecimalIndeterminable
    return resultat


def float_projection_exacte_ou_refus(valeur: Any) -> float:
    """Projette vers le float historique seulement si son texte JSON préserve le décimal.

    Un float peut représenter une quantité usuelle comme `0.1` avec un arrondi binaire interne,
    tout en sérialisant `0.1`. En revanche `9007199254740993` se sérialise `9007199254740992.0` :
    cette perte change la quantité métier et doit donc refuser, comme tout dépassement/non-fini.
    """
    try:
        decimal = valeur if isinstance(valeur, Decimal) else Decimal(str(valeur))
        if not decimal.is_finite():
            raise DecimalIndeterminable
        projection = float(decimal)
        if not math.isfinite(projection) or Decimal(str(projection)) != decimal:
            raise DecimalIndeterminable
        return projection
    except DecimalIndeterminable:
        raise
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        raise DecimalIndeterminable from None
