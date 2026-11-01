"""Toile raster en Python pur : rectangles, image de fond (couvrir), remplissage de contours, texte.

Le texte est rendu à partir des CONTOURS de la police (`polices.TTF`) : remplissage par balayage, règle du
enroulement non nul, sous-échantillonnage vertical 4× et couverture horizontale exacte. Chaque glyphe est posé à une
abscisse entière (positionnement arrondi) : le rendu est déterministe au pixel près et ne dépend d'aucune bibliothèque
graphique. La qualité n'est pas celle d'un moteur typographique (pas de crénage, pas d'indices) ; elle suffit à une
épreuve lisible et à un contrôle de lecture. Le PDF d'impression, lui, garde les courbes.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .png import ImageRVB
from .polices import TTF, Police

Couleur = tuple[int, int, int]
Polygone = list[tuple[float, float]]
SOUS_ECHANTILLONS = 4
PIXELS_TOILE_MAX = 40_000_000


def couleur_hex(texte: str) -> Couleur:
    if not isinstance(texte, str) or len(texte) != 7 or texte[0] != "#":
        raise ValueError("couleur #RRGGBB attendue")
    try:
        return int(texte[1:3], 16), int(texte[3:5], 16), int(texte[5:7], 16)
    except ValueError:
        raise ValueError("couleur #RRGGBB attendue") from None


def hex_couleur(couleur: Couleur) -> str:
    return "#{:02X}{:02X}{:02X}".format(*couleur)


def luminance(couleur: Couleur) -> float:
    """Luminance relative WCAG 2.x (sRGB)."""

    def canal(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = couleur
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def rapport_contraste(a: Couleur, b: Couleur) -> float:
    la, lb = luminance(a), luminance(b)
    clair, sombre = max(la, lb), min(la, lb)
    return (clair + 0.05) / (sombre + 0.05)


def aplatir(contour: tuple, echelle: float, origine_x: float, origine_y: float) -> Polygone:
    """Contour TrueType (unités de police, y vers le haut) -> polygone en pixels (y vers le bas)."""
    depart, segments = contour
    x0, y0 = depart
    points: Polygone = [(origine_x + x0 * echelle, origine_y - y0 * echelle)]
    for segment in segments:
        if segment[0] == "L":
            points.append((origine_x + segment[1] * echelle, origine_y - segment[2] * echelle))
            x0, y0 = segment[1], segment[2]
        else:
            cx, cy, x1, y1 = segment[1:]
            ecart = max(abs(x0 - 2 * cx + x1), abs(y0 - 2 * cy + y1)) * echelle
            n = max(2, min(24, 1 + int(math.sqrt(ecart / 0.15))))
            for i in range(1, n + 1):
                t = i / n
                u = 1 - t
                x = u * u * x0 + 2 * u * t * cx + t * t * x1
                y = u * u * y0 + 2 * u * t * cy + t * t * y1
                points.append((origine_x + x * echelle, origine_y - y * echelle))
            x0, y0 = x1, y1
    return points


def couverture(polygones: Sequence[Polygone]) -> tuple[int, int, int, int, list[float]] | None:
    """Couverture [0, 1] de l'union (enroulement non nul) : `(x0, y0, largeur, hauteur, valeurs)`."""
    aretes = []
    xs, ys = [], []
    for poly in polygones:
        n = len(poly)
        for i in range(n):
            (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
            xs.append(ax)
            ys.append(ay)
            if ay < by:
                aretes.append((ax, ay, bx, by, 1))
            elif by < ay:
                aretes.append((bx, by, ax, ay, -1))
    if not aretes:
        return None
    x0, x1 = math.floor(min(xs)), math.ceil(max(xs))
    y0, y1 = math.floor(min(ys)), math.ceil(max(ys))
    largeur, hauteur = max(1, x1 - x0), max(1, y1 - y0)
    if largeur * hauteur > PIXELS_TOILE_MAX:
        raise ValueError("zone de remplissage trop grande")
    valeurs = [0.0] * (largeur * hauteur)
    poids = 1.0 / SOUS_ECHANTILLONS
    for ligne in range(hauteur):
        for k in range(SOUS_ECHANTILLONS):
            sy = y0 + ligne + (k + 0.5) / SOUS_ECHANTILLONS
            croisements = []
            for ax, ay, bx, by, sens in aretes:
                if ay <= sy < by:
                    croisements.append((ax + (sy - ay) * (bx - ax) / (by - ay), sens))
            if not croisements:
                continue
            croisements.sort()
            enroulement = 0
            debut = 0.0
            for x, sens in croisements:
                if enroulement == 0:
                    debut = x
                enroulement += sens
                if enroulement == 0:
                    _ajouter_intervalle(valeurs, ligne, largeur, debut - x0, x - x0, poids)
    return x0, y0, largeur, hauteur, valeurs


def _ajouter_intervalle(valeurs: list[float], ligne: int, largeur: int, a: float, b: float, poids: float) -> None:
    a, b = max(a, 0.0), min(b, float(largeur))
    if b <= a:
        return
    base = ligne * largeur
    ia, ib = int(a), int(b)
    if ia == ib:
        valeurs[base + ia] += (b - a) * poids
        return
    valeurs[base + ia] += (ia + 1 - a) * poids
    for i in range(ia + 1, ib):
        valeurs[base + i] += poids
    if ib < largeur:
        valeurs[base + ib] += (b - ib) * poids


class Toile:
    def __init__(self, largeur: int, hauteur: int, fond: Couleur = (255, 255, 255)) -> None:
        if not (largeur >= 1 and hauteur >= 1 and largeur * hauteur <= PIXELS_TOILE_MAX):
            raise ValueError("dimensions de toile hors bornes")
        self.largeur, self.hauteur = largeur, hauteur
        self.pixels = bytearray(bytes(fond) * (largeur * hauteur))

    def vers_image(self) -> ImageRVB:
        return ImageRVB(self.largeur, self.hauteur, bytes(self.pixels))

    def rectangle(self, x0: float, y0: float, x1: float, y1: float, couleur: Couleur, opacite: float = 1.0) -> None:
        a, b = max(0, round(x0)), max(0, round(y0))
        c, d = min(self.largeur, round(x1)), min(self.hauteur, round(y1))
        if c <= a or d <= b:
            return
        r, g, bl = couleur
        for y in range(b, d):
            debut = 3 * (y * self.largeur + a)
            if opacite >= 1.0:
                self.pixels[debut : debut + 3 * (c - a)] = bytes((r, g, bl)) * (c - a)
                continue
            for i in range(debut, debut + 3 * (c - a), 3):
                self.pixels[i] = round(self.pixels[i] * (1 - opacite) + r * opacite)
                self.pixels[i + 1] = round(self.pixels[i + 1] * (1 - opacite) + g * opacite)
                self.pixels[i + 2] = round(self.pixels[i + 2] * (1 - opacite) + bl * opacite)

    def image_couvrir(self, image: ImageRVB, x0: float, y0: float, x1: float, y1: float) -> None:
        """Remplit le rectangle avec `image` mise à l'échelle pour le COUVRIR (rognage centré), voisin le plus
        proche."""
        a, b = round(x0), round(y0)
        c, d = round(x1), round(y1)
        largeur_dest, hauteur_dest = c - a, d - b
        if largeur_dest <= 0 or hauteur_dest <= 0:
            return
        echelle = max(largeur_dest / image.largeur, hauteur_dest / image.hauteur)
        decalage_x = (image.largeur * echelle - largeur_dest) / 2
        decalage_y = (image.hauteur * echelle - hauteur_dest) / 2
        colonnes = [min(image.largeur - 1, int((i + 0.5 + decalage_x) / echelle)) for i in range(largeur_dest)]
        for j in range(hauteur_dest):
            y = b + j
            if not 0 <= y < self.hauteur:
                continue
            sy = min(image.hauteur - 1, int((j + 0.5 + decalage_y) / echelle))
            source = image.pixels[3 * sy * image.largeur : 3 * (sy + 1) * image.largeur]
            ligne = bytearray()
            for sx in colonnes:
                ligne += source[3 * sx : 3 * sx + 3]
            debut_x = max(0, a)
            fin_x = min(self.largeur, c)
            if fin_x <= debut_x:
                continue
            morceau = ligne[3 * (debut_x - a) : 3 * (fin_x - a)]
            base = 3 * (y * self.largeur + debut_x)
            self.pixels[base : base + len(morceau)] = morceau

    def remplir(self, polygones: Sequence[Polygone], couleur: Couleur, opacite: float = 1.0) -> None:
        resultat = couverture(polygones)
        if resultat is None:
            return
        x0, y0, largeur, hauteur, valeurs = resultat
        r, g, b = couleur
        for j in range(hauteur):
            y = y0 + j
            if not 0 <= y < self.hauteur:
                continue
            for i in range(largeur):
                c = valeurs[j * largeur + i]
                x = x0 + i
                if c <= 0.0 or not 0 <= x < self.largeur:
                    continue
                c = min(1.0, c) * opacite
                p = 3 * (y * self.largeur + x)
                self.pixels[p] = round(self.pixels[p] * (1 - c) + r * c)
                self.pixels[p + 1] = round(self.pixels[p + 1] * (1 - c) + g * c)
                self.pixels[p + 2] = round(self.pixels[p + 2] * (1 - c) + b * c)

    def texte(self, police: Police, texte: str, x: float, baseline: float, taille_px: float, couleur: Couleur) -> None:
        for polygones in polygones_texte(police.ttf, texte, x, baseline, taille_px):
            self.remplir(polygones, couleur)


def polygones_texte(ttf: TTF, texte: str, x: float, baseline: float, taille_px: float) -> list[list[Polygone]]:
    """Un jeu de polygones par glyphe, chaque glyphe posé à une abscisse entière."""
    echelle = taille_px / ttf.unites_par_em
    pen = x
    sortie = []
    for caractere in texte:
        if caractere != " ":
            contours = ttf.contours(caractere)
            origine = float(round(pen))
            polys = [aplatir(c, echelle, origine, float(round(baseline))) for c in contours]
            if polys:
                sortie.append(polys)
        else:
            ttf.avance(caractere)
        pen += ttf.avance(caractere) * echelle
    return sortie
