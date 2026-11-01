"""Composition d'un visuel : brief + fond + police -> plan -> trois artefacts (SVG, PNG, PDF d'impression).

Le fond est le SEUL ingrédient qui peut venir d'un modèle ; il entre ici comme des octets PNG déjà enregistrés au
journal de provenance. Un brief au fond « genere » refuse de se composer sans fond et sans provenance (aucun fond
anonyme), et un brief au fond « uni » ou « degrade » refuse un fond fourni (aucune image glissée dans un visuel présenté
comme sans IA). Le marquage « généré par IA » est calculé du brief et de la provenance, jamais fourni par l'appelant.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from . import gabarits, png, rendus
from . import plan as p
from .brief import Brief
from .polices import RegistrePolices

SCHEMA_MARQUAGE = "opsys.studio.marquage/v1"
REJ_FOND_SANS_PROVENANCE = "REJ-STUDIO-FOND-SANS-PROVENANCE"
REJ_FOND_NON_DEMANDE = "REJ-STUDIO-FOND-NON-DEMANDE"
REJ_FOND_IMAGE = "REJ-STUDIO-FOND-IMAGE"
AVERTISSEMENT_IA = "Fond généré par IA ; texte, logo et mentions posés par un gabarit déterministe."


class CompositionRefusee(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code, self.detail = code, detail


@dataclasses.dataclass(frozen=True)
class Composition:
    brief: Brief
    plan: p.Plan
    artefacts: Mapping[str, bytes]
    fond_png: bytes | None
    marquage: Mapping[str, Any]
    police_id: str
    police_sha256: str = ""

    def empreintes(self) -> dict[str, dict[str, Any]]:
        return {fmt: {"sha256": hashlib.sha256(o).hexdigest(), "octets": len(o)} for fmt, o in self.artefacts.items()}

    @property
    def ia_generee(self) -> bool:
        return bool(self.marquage["ia_generee"])

    def empreinte(self) -> str:
        corps = {
            "brief": self.brief.empreinte(),
            "plan": p.empreinte(self.plan),
            "artefacts": self.empreintes(),
            "marquage": dict(self.marquage),
            "police": self.police_id,
            "police_sha256": self.police_sha256,
        }
        texte = json.dumps(corps, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(("opsys-studio-composition/v1\n" + texte).encode("utf-8")).hexdigest()


def construire_marquage(
    brief: Brief, plan_empreinte: str, fond_png: bytes | None, provenance: Mapping[str, Any] | None
) -> dict[str, Any]:
    ia = brief.genere
    marquage: dict[str, Any] = {
        "schema": SCHEMA_MARQUAGE,
        "genere_par": "OPSYS-AI studio créatif (M7)",
        "ia_generee": ia,
        "brief_empreinte": brief.empreinte(),
        "plan_empreinte": plan_empreinte,
        "fond_sha256": hashlib.sha256(fond_png).hexdigest() if fond_png is not None else None,
        "provenance": provenance["chaine"] if provenance else None,
        "modele": provenance.get("modele") if provenance else None,
        "version_modele": provenance.get("version_modele") if provenance else None,
        "graine": provenance.get("graine") if provenance else None,
    }
    if ia:
        marquage["avertissement"] = AVERTISSEMENT_IA
    return marquage


def composer_visuel(
    brief: Brief,
    polices: RegistrePolices,
    police_id: str,
    *,
    fond_png: bytes | None = None,
    provenance: Mapping[str, Any] | None = None,
    logo: Mapping[str, Any] | None = None,
    ppp: int | None = None,
) -> Composition:
    couleurs = brief.marque["couleurs"]
    secondaire = couleurs[1] if len(couleurs) > 1 else "#FFFFFF"
    if brief.genere:
        if fond_png is None or provenance is None or not provenance.get("chaine"):
            raise CompositionRefusee(
                REJ_FOND_SANS_PROVENANCE, "un fond généré exige l'image ET son enregistrement de provenance"
            )
        try:
            image = png.decoder(fond_png)
        except png.PngInvalide as exc:
            raise CompositionRefusee(REJ_FOND_IMAGE, exc.detail) from None
        fond = {
            "mode": "genere",
            "actif_sha256": hashlib.sha256(fond_png).hexdigest(),
            "largeur_px": image.largeur,
            "hauteur_px": image.hauteur,
            "couleur": couleurs[0],
        }
    else:
        if fond_png is not None or provenance is not None:
            raise CompositionRefusee(
                REJ_FOND_NON_DEMANDE, "ce brief n'a pas de fond généré : aucune image ni provenance n'est acceptée"
            )
        fond = {"mode": brief.fond["mode"], "couleur": secondaire}
        if brief.fond["mode"] == "degrade":
            fond["couleur2"] = couleurs[0]
    plan = gabarits.composer(brief, polices, police_id, ppp=ppp, fond=fond, logo=logo)
    marquage = construire_marquage(brief, p.empreinte(plan), fond_png, provenance)
    artefacts = {
        "svg": rendus.rendre_svg(plan, fond_png, polices, marquage),
        "png": rendus.rendre_png(plan, fond_png, polices, marquage),
    }
    if plan.impression:
        artefacts["pdf"] = rendus.rendre_pdf(plan, fond_png, polices, marquage)
    return Composition(brief, plan, artefacts, fond_png, marquage, police_id, polices.obtenir(police_id).sha256)
