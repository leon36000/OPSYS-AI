"""Logos : vectorisation (port + double), SVG sûr, déclinaisons, contrôle structurel, avertissement juridique.

R5 §3 : pipeline logo recommandé = concepts raster -> vectorisation (vtracer, MIT) -> nettoyage (svgo, MIT) -> police
OFL
convertie en chemins -> déclinaisons -> contrôles (lisibilité à 16 px, zone de protection) -> recherche d'antériorité de
marque -> validation humaine avec note de contribution. Ce module couvre le port `Vectoriseur`, un double
déterministe, la
validation du vectoriel, les déclinaisons (monochrome, négatif) et un rapport de contrôle SIGNÉ (même forme que celui
des
visuels : `actifs.enregistrer_controle` l'accepte). Il NE FAIT PAS : l'appel de vtracer ou de svgo (aucun des deux n'est
installé ; adaptateurs à écrire derrière le port, qui normalisent leur sortie vers le sous-ensemble `vecteur.py`), la
conversion d'une police en chemins, la recherche d'antériorité, ni aucune promesse de protection juridique.

AVERTISSEMENT (rendu dans CHAQUE sortie) : un logo généré ou vectorisé automatiquement n'a aucune protection juridique
garantie ; la voie est la marque de commerce, à valider par un agent de marques ou un avocat.

Module pur : aucune entrée-sortie, aucun réseau.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from collections.abc import Sequence
from typing import Any, Protocol

from . import controle, png, vecteur
from .actifs import AVERTISSEMENT_LOGO, empreinte_actif_logo
from .toile import Toile

CHEMINS_MAX = 200
VB_MAX = 10_000.0
REJ_LOGO = "REJ-STUDIO-LOGO"
REJ_LOGO_COMPLEXE = "REJ-STUDIO-LOGO-TROP-COMPLEXE"
SCHEMA_RAPPORT_LOGO = controle.SCHEMA_RAPPORT


@dataclasses.dataclass(frozen=True)
class LogoVectoriel:
    chemins: tuple[str, ...]
    vb_w: float
    vb_h: float

    def __post_init__(self) -> None:
        if not (0 < self.vb_w <= VB_MAX and 0 < self.vb_h <= VB_MAX):
            raise vecteur.CheminInvalide("boîte de vue hors bornes")
        if not 1 <= len(self.chemins) <= CHEMINS_MAX:
            raise vecteur.CheminInvalide(f"1 à {CHEMINS_MAX} chemins attendus ({len(self.chemins)} reçus)")
        for chemin in self.chemins:
            vecteur.analyser(chemin)

    def empreinte(self) -> str:
        return empreinte_actif_logo(list(self.chemins), self.vb_w, self.vb_h)


class Vectoriseur(Protocol):
    nom: str
    version: str
    nature: str

    def vectoriser(self, raster: png.ImageRVB, seuil: int) -> LogoVectoriel:
        """Raster -> chemins absolus du sous-ensemble `vecteur.py`. Aucun style, aucune image incorporée."""


class VectoriseurDouble:
    """Double déterministe : binarise (luminance < seuil = forme) et trace des rectangles par plages horizontales
    fusionnées
    verticalement. Ce n'est PAS vtracer : aucune courbe, aucun lissage ; il prouve le port et la chaîne, pas la
    qualité."""

    nom = "vectoriseur-double"
    version = "1"
    nature = "double"

    def vectoriser(self, raster: png.ImageRVB, seuil: int = 128) -> LogoVectoriel:
        L, H = raster.largeur, raster.hauteur
        if L * H > 400_000:
            raise vecteur.CheminInvalide("raster trop grand pour le double (400 000 pixels au plus)")
        encre = [
            [
                (
                    raster.pixels[3 * (y * L + x)] * 299
                    + raster.pixels[3 * (y * L + x) + 1] * 587
                    + raster.pixels[3 * (y * L + x) + 2] * 114
                )
                // 1000
                < seuil
                for x in range(L)
            ]
            for y in range(H)
        ]
        ouverts: dict[tuple[int, int], int] = {}
        rectangles: list[tuple[int, int, int, int]] = []
        for y in range(H + 1):
            plages = set()
            if y < H:
                x = 0
                while x < L:
                    if encre[y][x]:
                        debut = x
                        while x < L and encre[y][x]:
                            x += 1
                        plages.add((debut, x))
                    else:
                        x += 1
            for plage in list(ouverts):
                if plage not in plages:
                    rectangles.append((plage[0], ouverts.pop(plage), plage[1], y))
            for plage in plages:
                ouverts.setdefault(plage, y)
        if not rectangles:
            raise vecteur.CheminInvalide("aucune forme détectée au seuil demandé")
        if len(rectangles) > CHEMINS_MAX:
            raise vecteur.CheminInvalide(
                f"{len(rectangles)} formes : trop complexe pour le double ({CHEMINS_MAX} au plus)"
            )
        chemins = tuple(f"M {x0} {y0} H {x1} V {y1} H {x0} Z" for x0, y0, x1, y1 in rectangles)
        return LogoVectoriel(chemins, float(L), float(H))


def svg_du_logo(logo: LogoVectoriel, couleur: str = "#000000", fond: str | None = None) -> bytes:
    """SVG autonome : chemins remplis, aucun script, aucune image, aucune police, l'avertissement en `<desc>`."""
    if len(couleur) != 7 or couleur[0] != "#" or (fond is not None and (len(fond) != 7 or fond[0] != "#")):
        raise ValueError("couleur #RRGGBB attendue")
    arriere = f'<rect width="{logo.vb_w:g}" height="{logo.vb_h:g}" fill="{fond}"/>' if fond else ""
    chemins = "".join(f'<path d="{c}"/>' for c in logo.chemins)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {logo.vb_w:g} '
        f'{logo.vb_h:g}" width="{logo.vb_w:g}" height="{logo.vb_h:g}" role="img"><title>Concept de logo</title>'
        f'<desc>{AVERTISSEMENT_LOGO}</desc>{arriere}<g fill="{couleur}">{chemins}</g></svg>\n'
    ).encode()


def declinaisons(logo: LogoVectoriel) -> dict[str, bytes]:
    """Versions livrées avec le concept : monochrome (noir 100 %), négatif (blanc sur noir). Horizontale, empilée et
    monogramme exigent un travail de conception humain : non produites ici."""
    return {"monochrome": svg_du_logo(logo, "#000000"), "negatif": svg_du_logo(logo, "#FFFFFF", "#000000")}


def _couverture(logo: LogoVectoriel, hauteur_px: int) -> float:
    largeur = max(1, round(hauteur_px * logo.vb_w / logo.vb_h))
    toile = Toile(largeur, hauteur_px, (255, 255, 255))
    polys = [
        p for c in logo.chemins for p in vecteur.polygones(c, largeur / logo.vb_w, hauteur_px / logo.vb_h, 0.0, 0.0)
    ]
    toile.remplir(polys, (0, 0, 0))
    encre = sum(1 - toile.pixels[3 * i] / 255 for i in range(largeur * hauteur_px))
    return encre / (largeur * hauteur_px)


def rapport_controle(
    logo: LogoVectoriel, svg: bytes, *, maintenant: dt.datetime, source: str, outil: dict[str, Any]
) -> dict[str, Any]:
    """Rapport signé de contrôle STRUCTUREL du logo (même forme que celui des visuels). Il ne juge ni l'originalité ni
    la
    protection : seulement la forme (chemins valides et bornés, lisible à 16 px, ni vide ni plein)."""
    constats: list[dict[str, Any]] = []

    def ajouter(code: str, ok: bool, detail: str, mesure: Any = None) -> None:
        constats.append({"code": code, "critique": True, "ok": ok, "detail": detail, "mesure": mesure})

    ajouter(
        "QC-LOGO-CHEMINS",
        len(logo.chemins) <= CHEMINS_MAX,
        f"{len(logo.chemins)} chemin(s) valides du sous-ensemble M L H V C Q Z (au plus {CHEMINS_MAX})",
        {"chemins": len(logo.chemins)},
    )
    ajouter(
        "QC-LOGO-SANS-RASTER",
        b"<image" not in svg and b"<script" not in svg and b"href" not in svg,
        "aucun raster incorporé, aucun script, aucune référence externe",
    )
    couverture = _couverture(logo, 16)
    ajouter(
        "QC-LOGO-LISIBLE-16PX",
        0.04 <= couverture <= 0.96,
        f"couverture de l'encre à 16 px : {couverture:.0%} (ni disparu ni empâté)",
        {"couverture": round(couverture, 3)},
    )
    ajouter(
        "QC-LOGO-AVERTISSEMENT",
        AVERTISSEMENT_LOGO.encode() in svg,
        "l'avertissement de non-protection juridique accompagne le logo",
    )
    donnees = {
        "schema": SCHEMA_RAPPORT_LOGO,
        "constats": constats,
        "conforme": all(c["ok"] for c in constats),
        "lecteurs": [],
        "artefacts": {"svg": {"sha256": hashlib.sha256(svg).hexdigest(), "octets": len(svg)}},
        "composition_empreinte": logo.empreinte(),
        "plan_empreinte": logo.empreinte(),
        "brief_empreinte": None,
        "ia_generee": False,
        "fictif": None,
        "source": source,
        "outil": outil,
        "controle_le": maintenant.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limites": [
            AVERTISSEMENT_LOGO,
            "Aucune recherche d'antériorité de marque (OPIC, USPTO, WIPO) n'est faite ici.",
            "Les déclinaisons horizontale, empilée et monogramme ne sont pas produites.",
        ],
    }
    donnees["empreinte"] = controle.empreinte_rapport(donnees)
    return json.loads(json.dumps(donnees))


def logo_depuis_chemins(chemins: Sequence[str], vb_w: float, vb_h: float) -> LogoVectoriel:
    """Logo écrit à la main ou par un agent (R5 : « un LLM généraliste qui écrit du SVG »), validé contre le
    sous-ensemble."""
    return LogoVectoriel(tuple(chemins), float(vb_w), float(vb_h))
