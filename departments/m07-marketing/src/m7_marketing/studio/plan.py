"""Le plan de composition : ce que le gabarit pose, avec ses coordonnées en pixels.

Un plan est la SEULE source de ce qui est dessiné : le SVG, le PNG et le PDF sont trois rendus du même plan
(`rendus.py`). Il contient des rectangles, un logo vectoriel optionnel et des lignes de texte ; chaque ligne porte
l'identifiant de l'élément logique dont elle fait partie (`titre.fr`, `critique.telephone`, `mention.0`…), sa langue
et, pour une donnée critique, son type. Le contrôle qualité s'appuie sur ces identifiants pour comparer ce qu'il lit
dans la sortie à ce que le brief a demandé.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any

Couleur = tuple[int, int, int]
Boite = tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclasses.dataclass(frozen=True)
class Rect:
    id: str
    x: float
    y: float
    w: float
    h: float
    couleur: Couleur
    opacite: float
    role: str  # panneau | filet


@dataclasses.dataclass(frozen=True)
class Ligne:
    """Une ligne de texte posée. `id` désigne l'élément logique (plusieurs lignes peuvent le composer)."""

    id: str
    n: int
    texte: str
    x: float
    baseline: float
    taille_px: float
    couleur: Couleur
    police_id: str
    role: str
    langue: str | None
    critique: str | None
    largeur_px: float
    boite: Boite


@dataclasses.dataclass(frozen=True)
class LogoPose:
    id: str
    chemins: tuple[str, ...]
    vb_w: float
    vb_h: float
    x: float
    y: float
    w: float
    h: float
    couleur: Couleur


@dataclasses.dataclass(frozen=True)
class Plan:
    gabarit: str
    format: str
    largeur_px: int
    hauteur_px: int
    ppp: int
    impression: bool
    fond_perdu_px: int
    rognage: Boite
    surete: Boite
    fond: dict[str, Any]
    elements: tuple[Rect | LogoPose | Ligne, ...]
    polices: tuple[str, ...]
    taille_min_px: float
    zones_reservees: tuple[Boite, ...] = ()

    @property
    def lignes(self) -> tuple[Ligne, ...]:
        return tuple(e for e in self.elements if isinstance(e, Ligne))

    @property
    def rects(self) -> tuple[Rect, ...]:
        return tuple(e for e in self.elements if isinstance(e, Rect))

    @property
    def logo(self) -> LogoPose | None:
        return next((e for e in self.elements if isinstance(e, LogoPose)), None)

    def elements_logiques(self) -> dict[str, list[Ligne]]:
        regroupes: dict[str, list[Ligne]] = {}
        for ligne in self.lignes:
            regroupes.setdefault(ligne.id, []).append(ligne)
        return {i: sorted(v, key=lambda x: x.n) for i, v in regroupes.items()}


def en_dict(plan: Plan) -> dict[str, Any]:
    def convertir(valeur: Any) -> Any:
        if dataclasses.is_dataclass(valeur) and not isinstance(valeur, type):
            donnees = {c.name: convertir(getattr(valeur, c.name)) for c in dataclasses.fields(valeur)}
            donnees["_type"] = type(valeur).__name__
            return donnees
        if isinstance(valeur, (tuple, list)):
            return [convertir(v) for v in valeur]
        if isinstance(valeur, dict):
            return {k: convertir(v) for k, v in valeur.items()}
        if isinstance(valeur, float):
            return round(valeur, 3)
        return valeur

    return convertir(plan)


def empreinte(plan: Plan) -> str:
    texte = json.dumps(en_dict(plan), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(("opsys-studio-plan/v1\n" + texte).encode("utf-8")).hexdigest()
