"""Chemins vectoriels d'un logo : sous-ensemble SVG absolu `M L H V C Q Z`, borné, converti pour le raster et le PDF.

Un logo du studio est une liste de chemins dans une boîte `vb_w × vb_h`. Le sous-ensemble est volontairement étroit :
un logo issu d'un vectoriseur externe (vtracer, potrace) est normalisé vers ce format AVANT d'entrer au studio
(commandes absolues, aucune transformation, aucun style). Le SVG émis ne contient ni script, ni image, ni police.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import math
import re

from .toile import Polygone

REJ_CHEMIN = "REJ-STUDIO-LOGO-CHEMIN-INVALIDE"
CHEMIN_OCTETS_MAX = 40_000
COMMANDES_MAX = 4000
VALEUR_MAX = 100_000.0
_JETON = re.compile(r"\s*([MLHVCQZ])|\s*,?\s*(-?(?:\d+\.?\d*|\.\d+))")
_ARITE = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Q": 4, "Z": 0}


class CheminInvalide(ValueError):
    def __init__(self, detail: str) -> None:
        super().__init__(f"{REJ_CHEMIN} : {detail}")
        self.code, self.detail = REJ_CHEMIN, detail


def analyser(d: str) -> list[tuple[str, tuple[float, ...]]]:
    """Les commandes absolues du chemin : `[("M", (x, y)), ("L", (x, y)), …, ("Z", ())]`."""
    if not isinstance(d, str) or not d.strip() or len(d) > CHEMIN_OCTETS_MAX:
        raise CheminInvalide("chemin vide ou trop long")
    position, commandes, courante, valeurs = 0, [], None, []
    n = len(d)
    while position < n:
        trouve = _JETON.match(d, position)
        if trouve is None:
            if d[position:].strip() == "":
                break
            raise CheminInvalide(f"caractère non admis près de la position {position} (sous-ensemble M L H V C Q Z)")
        position = trouve.end()
        if trouve.group(1):
            if courante is not None:
                _clore(commandes, courante, valeurs)
            courante, valeurs = trouve.group(1), []
        else:
            if courante is None:
                raise CheminInvalide("nombre avant toute commande")
            valeur = float(trouve.group(2))
            if not math.isfinite(valeur) or abs(valeur) > VALEUR_MAX:
                raise CheminInvalide("coordonnée hors bornes")
            valeurs.append(valeur)
        if len(commandes) > COMMANDES_MAX:
            raise CheminInvalide("trop de commandes")
    if courante is not None:
        _clore(commandes, courante, valeurs)
    if not commandes or commandes[0][0] != "M":
        raise CheminInvalide("le chemin doit commencer par M")
    return commandes


def _clore(commandes: list, commande: str, valeurs: list[float]) -> None:
    arite = _ARITE[commande]
    if arite == 0:
        if valeurs:
            raise CheminInvalide("Z ne prend aucun nombre")
        commandes.append(("Z", ()))
        return
    if not valeurs or len(valeurs) % arite:
        raise CheminInvalide(f"{commande} attend des multiples de {arite} nombres")
    for i in range(0, len(valeurs), arite):
        # Après un M, les paires suivantes sont des L implicites (règle SVG).
        nom = "L" if (commande == "M" and i > 0) else commande
        commandes.append((nom, tuple(valeurs[i : i + arite])))


def polygones(d: str, echelle_x: float, echelle_y: float, origine_x: float, origine_y: float) -> list[Polygone]:
    """Sous-chemins aplatis en pixels (courbes subdivisées), pour le remplissage par enroulement non nul."""
    sortie: list[Polygone] = []
    courant: Polygone = []
    x = y = debut_x = debut_y = 0.0
    for nom, v in analyser(d):
        if nom == "M":
            if len(courant) >= 3:
                sortie.append(courant)
            x, y = v
            debut_x, debut_y = x, y
            courant = [(origine_x + x * echelle_x, origine_y + y * echelle_y)]
        elif nom == "L":
            x, y = v
            courant.append((origine_x + x * echelle_x, origine_y + y * echelle_y))
        elif nom == "H":
            x = v[0]
            courant.append((origine_x + x * echelle_x, origine_y + y * echelle_y))
        elif nom == "V":
            y = v[0]
            courant.append((origine_x + x * echelle_x, origine_y + y * echelle_y))
        elif nom == "Q":
            cx, cy, ex, ey = v
            for i in range(1, 13):
                t, u = i / 12, 1 - i / 12
                px = u * u * x + 2 * u * t * cx + t * t * ex
                py = u * u * y + 2 * u * t * cy + t * t * ey
                courant.append((origine_x + px * echelle_x, origine_y + py * echelle_y))
            x, y = ex, ey
        elif nom == "C":
            c1x, c1y, c2x, c2y, ex, ey = v
            for i in range(1, 17):
                t, u = i / 16, 1 - i / 16
                px = u**3 * x + 3 * u * u * t * c1x + 3 * u * t * t * c2x + t**3 * ex
                py = u**3 * y + 3 * u * u * t * c1y + 3 * u * t * t * c2y + t**3 * ey
                courant.append((origine_x + px * echelle_x, origine_y + py * echelle_y))
            x, y = ex, ey
        elif nom == "Z":
            x, y = debut_x, debut_y
    if len(courant) >= 3:
        sortie.append(courant)
    return sortie


def operateurs_pdf(
    d: str,
    echelle_x: float,
    echelle_y: float,
    origine_x: float,
    origine_y: float,
    hauteur_page_px: float,
    pt_par_px: float,
) -> str:
    """Opérateurs de chemin PDF (m l c h) pour `d` posé à (origine, échelle) en pixels de plan."""

    def pt(px: float, py: float) -> str:
        x_pt = (origine_x + px * echelle_x) * pt_par_px
        y_pt = (hauteur_page_px - (origine_y + py * echelle_y)) * pt_par_px
        return f"{_n(x_pt)} {_n(y_pt)}"

    ops: list[str] = []
    x = y = debut_x = debut_y = 0.0
    for nom, v in analyser(d):
        if nom == "M":
            x, y = v
            debut_x, debut_y = x, y
            ops.append(f"{pt(x, y)} m")
        elif nom == "L":
            x, y = v
            ops.append(f"{pt(x, y)} l")
        elif nom == "H":
            x = v[0]
            ops.append(f"{pt(x, y)} l")
        elif nom == "V":
            y = v[0]
            ops.append(f"{pt(x, y)} l")
        elif nom == "Q":
            cx, cy, ex, ey = v
            ops.append(
                f"{pt(x + 2 / 3 * (cx - x), y + 2 / 3 * (cy - y))} "
                f"{pt(ex + 2 / 3 * (cx - ex), ey + 2 / 3 * (cy - ey))} {pt(ex, ey)} c"
            )
            x, y = ex, ey
        elif nom == "C":
            ops.append(f"{pt(v[0], v[1])} {pt(v[2], v[3])} {pt(v[4], v[5])} c")
            x, y = v[4], v[5]
        elif nom == "Z":
            ops.append("h")
            x, y = debut_x, debut_y
    return "\n".join(ops)


def _n(valeur: float) -> str:
    texte = f"{valeur:.3f}".rstrip("0").rstrip(".")
    return "0" if texte in ("-0", "") else texte
