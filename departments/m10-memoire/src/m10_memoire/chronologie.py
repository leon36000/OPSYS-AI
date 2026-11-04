"""Clés de tri exactes pour les horodatages ISO 8601 des registres M10."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

_DATE_HEURE = re.compile(
    r"^(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{8}|[0-9]{4}-W[0-9]{2}-[0-9]|"
    r"[0-9]{4}-W[0-9]{2}|[0-9]{4}W[0-9]{3}|[0-9]{4}W[0-9]{2}|"
    r"[0-9]{4}-[0-9]{3}|[0-9]{7})[\s\S]"
    r"(?P<heure>[0-9]{2}(?::?[0-9]{2})?(?::?[0-9]{2})?)"
    r"(?:[.,](?P<f>[0-9]+))?"
    r"(?P<zone>Z|(?P<signe>[+-])(?P<oh>[0-9]{2})(?::?(?P<om>[0-9]{2}))?"
    r"(?::?(?P<os>[0-9]{2})(?:[.,](?P<of>[0-9]+))?)?)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _FractionDecimale:
    """Fraction [0,1) stockée sans zéros finaux et comparée sans conversion numérique."""

    chiffres: str

    def __lt__(self, autre: object) -> bool:
        if not isinstance(autre, _FractionDecimale):
            return NotImplemented
        if len(self.chiffres) < len(autre.chiffres) and autre.chiffres.startswith(self.chiffres):
            return True
        if len(self.chiffres) > len(autre.chiffres) and self.chiffres.startswith(autre.chiffres):
            return False
        # Sans préfixe strict, le premier chiffre différent suffit. Les zéros finaux supprimés
        # rendent le cas de préfixe exact ci-dessus équivalent à l'extension par des zéros.
        return self.chiffres < autre.chiffres


def _normaliser_fraction(chiffres: str) -> _FractionDecimale:
    return _FractionDecimale(chiffres.rstrip("0"))


def _soustraire_chiffres(gauche: str, droite: str) -> str:
    """Soustraction décimale linéaire par blocs de 9 chiffres, sans grand entier."""
    blocs = []
    retenue = 0
    for fin in range(len(gauche), 0, -9):
        debut = max(0, fin - 9)
        largeur = fin - debut
        valeur = int(gauche[debut:fin]) - int(droite[debut:fin]) - retenue
        if valeur < 0:
            valeur += 10**largeur
            retenue = 1
        else:
            retenue = 0
        blocs.append(f"{valeur:0{largeur}d}")
    return "".join(reversed(blocs))


def _additionner_chiffres(gauche: str, droite: str) -> tuple[int, str]:
    """Addition de chaînes décimales de même longueur : rend (retenue, reste) en O(n)."""
    blocs = []
    retenue = 0
    for fin in range(len(gauche), 0, -9):
        debut = max(0, fin - 9)
        largeur = fin - debut
        valeur = int(gauche[debut:fin]) + int(droite[debut:fin]) + retenue
        base = 10**largeur
        retenue, valeur = divmod(valeur, base)
        blocs.append(f"{valeur:0{largeur}d}")
    return retenue, "".join(reversed(blocs))


def _complement_fraction(chiffres: str) -> str:
    """Retourne 1 - chiffres/10**len(chiffres), sans construire 10**n comme entier."""
    neuf = "9" * len(chiffres)
    difference = _soustraire_chiffres(neuf, chiffres)
    resultat = list(difference)
    retenue = 1
    for position in range(len(resultat) - 1, -1, -1):
        chiffre = ord(resultat[position]) - ord("0") + retenue
        resultat[position] = chr(ord("0") + chiffre % 10)
        retenue = chiffre // 10
    return "".join(resultat)


def cle_instant(horodatage: str) -> tuple[int, _FractionDecimale]:
    """Retourne (secondes UTC entières, fraction exacte), sans flottant ni perte de chiffres.

    ``datetime.fromisoformat`` reste l'autorité pour valider les formes que M10 accepte. Il ne
    conserve toutefois que six décimales du temps et de l'offset : on extrait les deux fractions
    textuelles pour comparer sans perte.
    """
    instant = datetime.fromisoformat(horodatage)
    decalage_parse = instant.utcoffset()
    if decalage_parse is None:
        raise ValueError("fuseau absent")

    correspondance = _DATE_HEURE.fullmatch(horodatage)
    if correspondance is None:
        # Forme ISO acceptée par Python mais non canonique dans les événements M10 : garder le
        # comportement de datetime, sans prétendre récupérer une précision qui n'est pas lisible.
        fraction_locale = f"{instant.microsecond:06d}"
    else:
        fraction_locale = (correspondance.group("f") or "").rstrip("0")

    secondes_locales = (
        instant.date().toordinal() * 86400 + instant.hour * 3600 + instant.minute * 60 + instant.second
    )
    if correspondance is None:
        # Secours pour une forme admise par `fromisoformat` que le parseur textuel ne connaît pas.
        # Les formes ISO calendaires, compactes et semaine sont toutes prises ci-dessus; ce chemin
        # garde le comportement temporel historique pour une éventuelle forme future.
        signe_offset = -1 if decalage_parse < timedelta(0) else 1
        decalage_abs = abs(decalage_parse)
        secondes_offset_total = decalage_abs.days * 86400 + decalage_abs.seconds
        fraction_offset = f"{decalage_abs.microseconds:06d}".rstrip("0")
    else:
        signe_offset = -1 if correspondance.group("signe") == "-" else 1
        heures_offset = int(correspondance.group("oh") or 0)
        minutes_offset = int(correspondance.group("om") or 0)
        secondes_offset = int(correspondance.group("os") or 0)
        fraction_offset = (correspondance.group("of") or "").rstrip("0")
        secondes_offset_total = heures_offset * 3600 + minutes_offset * 60 + secondes_offset
    largeur = max(len(fraction_locale), len(fraction_offset), 6)
    locale_alignee = fraction_locale.ljust(largeur, "0")
    offset_aligne = fraction_offset.ljust(largeur, "0")
    secondes_utc = secondes_locales - signe_offset * secondes_offset_total
    if signe_offset > 0:
        if locale_alignee < offset_aligne:
            secondes_utc -= 1
            fraction_utc = _complement_fraction(_soustraire_chiffres(offset_aligne, locale_alignee))
        else:
            fraction_utc = _soustraire_chiffres(locale_alignee, offset_aligne)
    else:
        retenue, fraction_utc = _additionner_chiffres(locale_alignee, offset_aligne)
        secondes_utc += retenue
    return secondes_utc, _normaliser_fraction(fraction_utc)
