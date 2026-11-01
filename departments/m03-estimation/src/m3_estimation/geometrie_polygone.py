"""Aire et périmètre d'un polygone, par le moteur déterministe de M3, avec reçu (M3.7, estimation géospatiale).

Aucun calcul de tête, aucun flottant : tout est en ``Fraction`` (tests d'intersection exacts) et ``Decimal`` à 60
chiffres (projection et formule du lacet). Même entrée, même reçu, sur toute plateforme.

DEUX SYSTÈMES D'ENTRÉE.

``plan_metrique``  sommets ``[x, y]`` en mètres dans un plan déjà projeté (par exemple des coordonnées MTM d'un plan
    d'arpentage). L'aire est celle de la GRILLE ; si le plan déclare un facteur d'échelle de grille
    (``facteur_echelle_grille``, texte décimal), l'aire au sol est l'aire de grille divisée par son carré. Sans
    facteur déclaré, il n'est PAS supposé égal à 1 : le reçu le dit.
``geographique``   sommets ``[latitude, longitude]`` en degrés décimaux (NAD83(CSRS) ou WGS84 : la différence de
  datum, de l'ordre du mètre sur les coordonnées, n'est pas modélisée). Projection locale documentée ci-dessous.

PROJECTION LOCALE (``tangent-local-grs80-v1``). Autour du point de référence (moyenne des latitudes et des longitudes
des sommets), sur l'ellipsoïde GRS 80 (a = 6 378 137 m, f = 1/298,257222101 ; NAD83(CSRS)) :

    N0 = a / sqrt(1 - e² sin²φ0)                      rayon de courbure du premier vertical
    M0 = a (1 - e²) / (1 - e² sin²φ0)^(3/2)           rayon de courbure méridien
    x = (λ - λ0) · N0 · cos φ0 ,   y = (φ - φ0) · M0   (angles en radians)

puis formule du lacet (Gauss) : A = |Σ (x_i y_{i+1} - x_{i+1} y_i)| / 2 ; le périmètre est la somme des distances
planes. C'est une approximation du PREMIER ORDRE : l'écart à l'aire géodésique croît avec l'étendue du polygone. Le
moteur REFUSE donc un polygone dont l'étendue dépasse ``ETENDUE_MAX_M`` (2 000 m) et le dit dans le reçu. Écart mesuré
contre une formule fermée de l'aire d'une cellule de graticule sur l'ellipsoïde : voir
``tests/test_geometrie_polygone.py`` (un parcelle de ~200 m : de l'ordre de 10⁻⁶ en relatif). NON vérifié contre PROJ
ni contre la projection MTM officielle (aucun accès réseau ni bibliothèque de référence ici).

INCERTITUDE. Si la source déclare une incertitude de position ``sigma`` (mètres), le reçu donne une borne d'ordre un
  de l'aire :
périmètre × sigma. Sinon, ``incertitude_aire_m2`` vaut ``null`` : jamais zéro.

Un polygone doit être SIMPLE (aucune auto-intersection, aucune pointe), (donc d'aire non nulle), de 3 à 500 sommets
distincts ; en coordonnées géographiques, tous les sommets doivent tomber dans le rectangle de vraisemblance du Québec
(garde grossière contre une inversion latitude/longitude, jamais un contrôle de frontière).

Module pur : aucune horloge, aucun aléa, aucun réseau, aucun import ``opsys``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from fractions import Fraction
from typing import Any

from . import journal_site, verdicts

__all__ = [
    "ETENDUE_MAX_M",
    "MOTEUR",
    "VERSION_MOTEUR",
    "calculer",
    "rejouer",
    "verifier_recu",
]

MOTEUR = "m3.geometrie.polygone"
VERSION_MOTEUR = "1.0.0"
PROJECTION = "tangent-local-grs80-v1"
ETENDUE_MAX_M = 2000
_SOMMETS_MIN, _SOMMETS_MAX = 3, 500
_PRECISION = 60
_PI = Decimal("3.14159265358979323846264338327950288419716939937510582097494")
_A = Decimal(6378137)
_F = Decimal(1) / Decimal("298.257222101")
_QUANTUM = Decimal("0.01")
# Rectangle de vraisemblance du Québec (mêmes bornes que localisation.py de M4) : refuse une inversion lat/lon.
_LAT_MIN, _LAT_MAX = Fraction(445, 10), Fraction(63)
_LON_MIN, _LON_MAX = Fraction(-80), Fraction(-57)
_DECIMAL = re.compile(r"^-?\d{1,9}(\.\d{1,9})?$")
_POSITIF = re.compile(r"^\d{1,9}(\.\d{1,9})?$")
_SYSTEMES = frozenset({"geographique", "plan_metrique"})


def _refus(code: str, detail: str) -> dict[str, Any]:
    return verdicts.construire_verdict(code, detail)


class _Invalide(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


# ------------------------------------------------------------------------------------------- trigonométrie exacte
def _sin_cos(x: Decimal) -> tuple[Decimal, Decimal]:
    """sin et cos par série de Taylor, ``x`` en radians avec |x| < 2 (latitudes du Québec : < 1,11 rad). Arrêt quand le
    terme passe sous 10⁻⁵⁵ ; l'erreur est donc très inférieure à 10⁻⁵⁰."""
    seuil = Decimal(10) ** -55
    sinus, terme, n = Decimal(0), x, 1
    while abs(terme) > seuil:
        sinus += terme
        terme = -terme * x * x / ((n + 1) * (n + 2))
        n += 2
    cosinus, terme, n = Decimal(0), Decimal(1), 0
    while abs(terme) > seuil:
        cosinus += terme
        terme = -terme * x * x / ((n + 1) * (n + 2))
        n += 2
    return sinus, cosinus


def _radians(degres: Decimal) -> Decimal:
    return degres * _PI / Decimal(180)


# ------------------------------------------------------------------------------------------- validation
def _frac(texte: Any, nom: str) -> Fraction:
    if not isinstance(texte, str) or not _DECIMAL.fullmatch(texte):
        raise _Invalide("REJ-GEO-ENTREE-INVALIDE", f"{nom} : texte décimal attendu (jamais un flottant)")
    return Fraction(texte)


def _orient(a: tuple[Fraction, Fraction], b: tuple[Fraction, Fraction], c: tuple[Fraction, Fraction]) -> Fraction:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _signe(v: Fraction) -> int:
    return (v > 0) - (v < 0)


def _sur_segment(a: tuple[Fraction, Fraction], b: tuple[Fraction, Fraction], c: tuple[Fraction, Fraction]) -> bool:
    return min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])


def _se_coupent(p1, p2, p3, p4) -> bool:
    d1, d2 = _signe(_orient(p3, p4, p1)), _signe(_orient(p3, p4, p2))
    d3, d4 = _signe(_orient(p1, p2, p3)), _signe(_orient(p1, p2, p4))
    if d1 != d2 and d3 != d4:
        return True
    return (
        (d1 == 0 and _sur_segment(p3, p4, p1))
        or (d2 == 0 and _sur_segment(p3, p4, p2))
        or (d3 == 0 and _sur_segment(p1, p2, p3))
        or (d4 == 0 and _sur_segment(p1, p2, p4))
    )


def _sommets(brut: Any, systeme: str) -> list[tuple[Fraction, Fraction]]:
    if not isinstance(brut, Sequence) or isinstance(brut, (str, bytes)):
        raise _Invalide("REJ-GEO-POLYGONE-INVALIDE", "sommets : liste de paires attendue")
    points = []
    for position, paire in enumerate(brut):
        if not isinstance(paire, Sequence) or isinstance(paire, (str, bytes)) or len(paire) != 2:
            raise _Invalide("REJ-GEO-POLYGONE-INVALIDE", f"sommets[{position}] : paire de textes décimaux attendue")
        points.append((_frac(paire[0], f"sommets[{position}][0]"), _frac(paire[1], f"sommets[{position}][1]")))
    if len(points) >= 2 and points[0] == points[-1]:
        points.pop()  # anneau fermé explicitement : le dernier sommet répète le premier
    if not _SOMMETS_MIN <= len(points) <= _SOMMETS_MAX:
        raise _Invalide("REJ-GEO-POLYGONE-INVALIDE", f"polygone : de {_SOMMETS_MIN} à {_SOMMETS_MAX} sommets distincts")
    for a, b in zip(points, points[1:] + points[:1], strict=True):
        if a == b:
            raise _Invalide("REJ-GEO-POLYGONE-INVALIDE", "deux sommets consécutifs identiques")
    if len(set(points)) != len(points):
        raise _Invalide("REJ-GEO-AUTO-INTERSECTION", "un sommet est répété : le polygone n'est pas simple")
    if systeme == "geographique":
        for position, (lat, lon) in enumerate(points):
            if not (_LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX):
                raise _Invalide(
                    "REJ-GEO-HORS-QUEBEC",
                    f"sommets[{position}] hors du rectangle de vraisemblance du Québec "
                    "(latitude, longitude inversées ?)",
                )
    n = len(points)
    # Un anneau simple dont aucun sommet ne fait demi-tour n'a jamais une aire nulle : des sommets alignés sont donc
    # refusés ici comme « pointe » (le contour revient sur lui-même).
    for i in range(n):
        a, b, c = points[i], points[(i + 1) % n], points[(i + 2) % n]
        if _orient(a, b, c) == 0 and (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) < 0:
            raise _Invalide("REJ-GEO-AUTO-INTERSECTION", "pointe : le contour revient sur lui-même")
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue  # segments adjacents : partagent un sommet
            if _se_coupent(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n]):
                raise _Invalide("REJ-GEO-AUTO-INTERSECTION", "le contour se coupe lui-même")
    return points


def _texte(valeur: Decimal) -> str:
    return format(valeur.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def _dec(f: Fraction) -> Decimal:
    return Decimal(f.numerator) / Decimal(f.denominator)


def _norm(valeur: Decimal) -> str:
    """Texte décimal sans exposant (``format(…, "f")``) : relisible par la validation d'entrée au rejeu."""
    return format(valeur.normalize(), "f")


# ------------------------------------------------------------------------------------------- calcul
def _lacet_et_perimetre(xy: list[tuple[Decimal, Decimal]]) -> tuple[Decimal, Decimal]:
    n = len(xy)
    somme = sum((xy[i][0] * xy[(i + 1) % n][1] - xy[(i + 1) % n][0] * xy[i][1] for i in range(n)), Decimal(0))
    perimetre = sum(
        (((xy[(i + 1) % n][0] - xy[i][0]) ** 2 + (xy[(i + 1) % n][1] - xy[i][1]) ** 2).sqrt() for i in range(n)),
        Decimal(0),
    )
    return abs(somme) / 2, perimetre


def _projeter(points: list[tuple[Fraction, Fraction]]) -> list[tuple[Decimal, Decimal]]:
    n = len(points)
    lat0 = sum((_dec(p[0]) for p in points), Decimal(0)) / n
    lon0 = sum((_dec(p[1]) for p in points), Decimal(0)) / n
    phi0 = _radians(lat0)
    s, c = _sin_cos(phi0)
    e2 = 2 * _F - _F * _F
    w = 1 - e2 * s * s
    n0 = _A / w.sqrt()
    m0 = _A * (1 - e2) / (w * w.sqrt())
    kx, ky = n0 * c, m0
    return [(_radians(_dec(p[1]) - lon0) * kx, _radians(_dec(p[0]) - lat0) * ky) for p in points]


def calculer(entrees: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """``(recu, None)`` ou ``(None, verdict)``.

    ``entrees`` : ``systeme`` (``geographique`` ou ``plan_metrique``), ``sommets`` (paires de textes décimaux) et,
    facultatifs, ``incertitude_position_m`` (texte décimal positif) et, pour ``plan_metrique``,
    ``facteur_echelle_grille`` (texte décimal
    positif)."""
    try:
        if (
            not isinstance(entrees, Mapping)
            or set(entrees) - {"systeme", "sommets", "incertitude_position_m", "facteur_echelle_grille"}
            or not {"systeme", "sommets"} <= set(entrees)
        ):
            raise _Invalide("REJ-GEO-ENTREE-INVALIDE", "entrées : systeme et sommets requis, aucun autre champ inconnu")
        systeme = entrees["systeme"]
        if systeme not in _SYSTEMES:
            raise _Invalide("REJ-GEO-ENTREE-INVALIDE", "systeme : geographique ou plan_metrique")
        sigma = None
        if entrees.get("incertitude_position_m") is not None:
            texte = entrees["incertitude_position_m"]
            if not isinstance(texte, str) or not _POSITIF.fullmatch(texte) or Fraction(texte) == 0:
                raise _Invalide("REJ-GEO-ENTREE-INVALIDE", "incertitude_position_m : texte décimal positif attendu")
            sigma = Decimal(texte)
        facteur = None
        if entrees.get("facteur_echelle_grille") is not None:
            if systeme != "plan_metrique":
                raise _Invalide("REJ-GEO-ENTREE-INVALIDE", "facteur_echelle_grille : plan_metrique seulement")
            texte = entrees["facteur_echelle_grille"]
            if not isinstance(texte, str) or not _POSITIF.fullmatch(texte) or Fraction(texte) == 0:
                raise _Invalide("REJ-GEO-ENTREE-INVALIDE", "facteur_echelle_grille : texte décimal positif attendu")
            facteur = Decimal(texte)
        points = _sommets(entrees["sommets"], systeme)
        with localcontext() as ctx:
            ctx.prec = _PRECISION
            xy = _projeter(points) if systeme == "geographique" else [(_dec(p[0]), _dec(p[1])) for p in points]
            xs, ys = [p[0] for p in xy], [p[1] for p in xy]
            etendue = max(max(xs) - min(xs), max(ys) - min(ys))
            if etendue > ETENDUE_MAX_M:
                raise _Invalide(
                    "REJ-GEO-ETENDUE-EXCESSIVE",
                    f"étendue supérieure à {ETENDUE_MAX_M} m : l'approximation locale n'est plus admise",
                )
            aire, perimetre = _lacet_et_perimetre(xy)
            avertissements = []
            if systeme == "geographique":
                aire_sol, perimetre_sol, facteur_applique = aire, perimetre, None
                avertissements.append(
                    "projection locale du premier ordre, non vérifiée contre PROJ ni la projection MTM officielle"
                )
                avertissements.append("différence de datum NAD83(CSRS)/WGS84 non modélisée")
            elif facteur is not None:
                aire_sol, perimetre_sol, facteur_applique = (
                    aire / (facteur * facteur),
                    perimetre / facteur,
                    _texte(facteur),
                )
            else:
                aire_sol, perimetre_sol, facteur_applique = aire, perimetre, None
                avertissements.append(
                    "aire de grille : aucun facteur d'échelle de grille déclaré, non supposé égal à 1"
                )
            incertitude = None if sigma is None else perimetre_sol * sigma
            if sigma is None:
                avertissements.append(
                    "incertitude de position non déclarée : incertitude d'aire inconnue (jamais zéro)"
                )
            entrees_normalisees = {
                "systeme": systeme,
                "sommets": [[_norm(_dec(p[0])), _norm(_dec(p[1]))] for p in points],
                "incertitude_position_m": None if sigma is None else _norm(sigma),
                "facteur_echelle_grille": None if facteur is None else _norm(facteur),
            }
            resultat = {
                "aire_m2": _texte(aire_sol),
                "perimetre_m": _texte(perimetre_sol),
                "sommets": len(points),
                "etendue_m": _texte(etendue),
                "incertitude_aire_m2": None if incertitude is None else _texte(incertitude),
                "facteur_echelle_grille_applique": facteur_applique,
            }
    except _Invalide as exc:
        return None, _refus(exc.code, exc.detail)
    except (InvalidOperation, ArithmeticError):  # pragma: no cover - garde de dernier recours
        return None, _refus("REJ-GEO-ENTREE-INVALIDE", "calcul impossible sur ces entrées")
    corps = {
        "type": "RECU_CALCUL",
        "format": "recu-geometrie.v1",
        "moteur": MOTEUR,
        "version_moteur": VERSION_MOTEUR,
        "methode": "formule du lacet (Gauss) en Decimal à 60 chiffres, intersections exactes en Fraction",
        "precision": {"chiffres_significatifs": _PRECISION, "arrondi_sortie": "0,01 (demi-pair)"},
        "parametres": {
            "projection": PROJECTION if systeme == "geographique" else None,
            "ellipsoide": "GRS80 a=6378137 f=1/298.257222101" if systeme == "geographique" else None,
            "etendue_max_m": ETENDUE_MAX_M,
        },
        "empreinte_entrees": journal_site.empreinte_canonique("recu-geometrie.v1", "entrees", entrees_normalisees),
        "resultat": resultat,
        "avertissements": avertissements,
        "mention": "Mesure géométrique issue de coordonnées fournies ; pas un arpentage ni un avis professionnel.",
    }
    return {**corps, "entrees": entrees_normalisees, "empreinte": journal_site.empreinte_canonique(corps)}, None


def verifier_recu(recu: Any) -> tuple[bool, str]:
    """``(True, "")`` si les empreintes du reçu correspondent à son contenu (aucune retouche) ; ne rejoue pas le
    calcul."""
    if not isinstance(recu, Mapping) or recu.get("format") != "recu-geometrie.v1":
        return False, "format de reçu inconnu"
    try:
        corps = {k: v for k, v in recu.items() if k not in ("entrees", "empreinte")}
        if "entrees" in recu and journal_site.empreinte_canonique(
            "recu-geometrie.v1", "entrees", recu["entrees"]
        ) != recu.get("empreinte_entrees"):
            return False, "empreinte_entrees ne correspond pas aux entrées"
        if journal_site.empreinte_canonique(corps) != recu.get("empreinte"):
            return False, "empreinte ne correspond pas au contenu du reçu"
    except (TypeError, ValueError):
        return False, "reçu mal formé"
    return True, ""


def rejouer(recu: Mapping[str, Any]) -> tuple[bool, str]:
    """Refait le calcul depuis les entrées du reçu et compare les empreintes : ``(True, "")`` si identiques."""
    ok, raison = verifier_recu(recu)
    if not ok:
        return False, raison
    if "entrees" not in recu:
        return False, "reçu compact : entrées absentes"
    nouveau, verdict = calculer(recu["entrees"])
    if verdict is not None or nouveau is None:
        return False, "les entrées du reçu ne passent plus la validation"
    return (nouveau["empreinte"] == recu["empreinte"]), "" if nouveau["empreinte"] == recu[
        "empreinte"
    ] else "résultat différent"
