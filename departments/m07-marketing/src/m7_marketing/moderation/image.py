"""Représentation minimale d'image et floutage déterministe (PLAN T4.3, M7-audit.md §3.5).

Aucune dépendance externe : `numpy`/`Pillow`/`opencv-python` ne sont pas installables dans ce
bac à sable (vérifié — voir `detection.py`). Une « image » est ici une grille de pixels RGB déjà
décodée en mémoire, ce qui suffit à la partie déterministe (pixellisation d'une zone détectée)
qui ne dépend d'aucun format de fichier. Le décodage d'une vraie photo (JPEG/PNG -> pixels) et
l'appel au vrai détecteur restent à brancher avec la brique retenue (OpenCV, voir
`docs/research/INGREDIENTS.md`) une fois installable dans l'environnement cible.

Module pur : aucun import `opsys`.
"""

from __future__ import annotations

import dataclasses

Pixel = tuple[int, int, int]


class DimensionInvalide(ValueError):
    """Dimensions d'image ou de boîte incohérentes, ou boîte hors image."""


@dataclasses.dataclass(frozen=True)
class ImageSynthetique:
    """Grille de pixels RGB, rangée par rangée (row-major). `pixels` a exactement
    `largeur * hauteur` éléments — vérifié à la construction, jamais silencieusement tronqué."""

    largeur: int
    hauteur: int
    pixels: tuple[Pixel, ...]

    def __post_init__(self) -> None:
        if self.largeur <= 0 or self.hauteur <= 0:
            raise DimensionInvalide(f"dimensions d'image invalides : {self.largeur}x{self.hauteur}")
        attendu = self.largeur * self.hauteur
        if len(self.pixels) != attendu:
            raise DimensionInvalide(
                f"{len(self.pixels)} pixel(s) fourni(s), {attendu} attendu(s) pour "
                f"{self.largeur}x{self.hauteur}"
            )


@dataclasses.dataclass(frozen=True)
class Boite:
    """Zone rectangulaire en coordonnées pixel (origine en haut-gauche), issue d'une détection."""

    x: int
    y: int
    largeur: int
    hauteur: int

    def __post_init__(self) -> None:
        if self.largeur <= 0 or self.hauteur <= 0:
            raise DimensionInvalide(f"boîte de dimensions invalides : {self.largeur}x{self.hauteur}")


def _bornes_recouvrement(boite: Boite, image: ImageSynthetique) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) exclusifs, coupés aux bords de `image` ; `None` si `boite` ne recouvre
    `image` sur aucun pixel."""
    x0 = max(0, boite.x)
    y0 = max(0, boite.y)
    x1 = min(image.largeur, boite.x + boite.largeur)
    y1 = min(image.hauteur, boite.y + boite.hauteur)
    if x0 >= x1 or y0 >= y1:
        return None
    return x0, y0, x1, y1


def flouter_zone(image: ImageSynthetique, boite: Boite, taille_bloc: int = 8) -> ImageSynthetique:
    """Pixellise `image` sur `boite` par moyenne de blocs `taille_bloc` x `taille_bloc`.

    Fonction pure et déterministe : mêmes entrées -> mêmes pixels de sortie, jamais de flou
    aléatoire ni d'appel réseau. Retourne une NOUVELLE image ; `image` n'est jamais mutée, donc
    un appelant qui veut comparer avant/après garde les deux références.

    Lève `DimensionInvalide` si `taille_bloc` n'est pas positif, ou si `boite` ne recouvre `image`
    sur aucun pixel : un floutage qui ne floute rien n'est pas un floutage silencieux, c'est un
    échec nommé (M7-audit.md §3.5, « refus fail-closed ... si le floutage échoue »).
    """
    if taille_bloc <= 0:
        raise DimensionInvalide(f"taille_bloc doit être positive : {taille_bloc}")
    bornes = _bornes_recouvrement(boite, image)
    if bornes is None:
        raise DimensionInvalide(
            f"boîte {boite} hors de l'image {image.largeur}x{image.hauteur} : floutage impossible"
        )
    x0, y0, x1, y1 = bornes
    pixels = list(image.pixels)

    def index(x: int, y: int) -> int:
        return y * image.largeur + x

    for by in range(y0, y1, taille_bloc):
        by1 = min(by + taille_bloc, y1)
        for bx in range(x0, x1, taille_bloc):
            bx1 = min(bx + taille_bloc, x1)
            somme_r = somme_g = somme_b = 0
            compte = 0
            for y in range(by, by1):
                for x in range(bx, bx1):
                    r, g, b = pixels[index(x, y)]
                    somme_r += r
                    somme_g += g
                    somme_b += b
                    compte += 1
            moyenne = (somme_r // compte, somme_g // compte, somme_b // compte)
            for y in range(by, by1):
                for x in range(bx, bx1):
                    pixels[index(x, y)] = moyenne

    return ImageSynthetique(largeur=image.largeur, hauteur=image.hauteur, pixels=tuple(pixels))
