"""Génération de FONDS : ports `GenerateurImage` / `GenerateurVideo`, doubles déterministes, invite sans texte.

Un générateur ne produit qu'un fond : jamais un texte, un logo ou une mention (décision r2 n°3). L'invite est construite
par le code à partir de champs STRUCTURÉS du brief (sujet, ambiance, rendu, palette) et d'un cadre fixe qui demande
explicitement « aucun texte, aucun logo, aucune signature » ; l'invite négative répète l'interdit. Le brief a déjà
refusé
toute description qui nomme un logo, un texte ou une marque (`brief.MOTS_INTERDITS_FOND`).

Aucun adaptateur de modèle réel n'est livré : `ADAPTATEURS_DE_PRODUCTION` est vide. Un adaptateur (Diffusers local, API
Recraft, Nexora) est une classe de ce module qui implémente le port, déclare sa NATURE (`reel`) et se branche par
identifiant de fournisseur du registre (`executeur.py`). Les doubles déclarent la nature `double`.

Deux doubles : `GenerateurImageDouble` (PNG synthétique, dégradé et bandes dérivés de la graine et de l'invite) et
`GenerateurVideoDouble` (PNG animé, APNG, d'images synthétiques). Même demande, mêmes octets : la graine est rejouable.

Module pur : aucune entrée-sortie, aucun réseau.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import struct
import zlib
from collections.abc import Mapping
from typing import Any, Protocol

from . import png
from .brief import Brief

NATURE_REEL = "reel"
NATURE_DOUBLE = "double"
CADRE_POSITIF = (
    "background image for marketing material, large uncluttered areas reserved for overlaid text, "
    "no text, no letters, no numbers, no logo, no watermark, no signature"
)
INVITE_NEGATIVE = (
    "text, letters, numbers, words, typography, logo, watermark, signature, caption, brand name, trademark, "
    "readable signage, license plate, identifiable face"
)
DIMENSION_FOND_MAX = 4096
REJ_GENERATION = "REJ-STUDIO-GENERATION"
REJ_SORTIE = "REJ-STUDIO-GENERATION-SORTIE"
REJ_ADAPTATEUR_ABSENT = "REJ-STUDIO-ADAPTATEUR-ABSENT"
REJ_GENERATEUR_DE_TEST = "REJ-STUDIO-GENERATEUR-DE-TEST"
REJ_VIDEO_NON_COMPOSABLE = "REJ-STUDIO-VIDEO-NON-COMPOSABLE"


class ErreurGeneration(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code, self.detail = code, detail


@dataclasses.dataclass(frozen=True)
class DemandeGeneration:
    job_id: str
    brief_id: str
    brief_empreinte: str
    genre: str  # image | video
    invite: str
    invite_negative: str
    largeur: int
    hauteur: int
    graine: int
    duree_s: int | None = None
    images_par_seconde: int | None = None
    parametres: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def vers_dict(self) -> dict[str, Any]:
        return {**dataclasses.asdict(self), "parametres": dict(self.parametres)}

    def empreinte(self) -> str:
        texte = json.dumps(self.vers_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(("opsys-studio-demande/v1\n" + texte).encode("utf-8")).hexdigest()


@dataclasses.dataclass(frozen=True)
class SortieGeneration:
    octets: bytes
    format: str
    largeur: int
    hauteur: int
    modele: str
    version_modele: str
    poids_ref: str | None
    graine: int
    invite_effective: str
    nature: str
    parametres: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    duree_s: int | None = None


class GenerateurImage(Protocol):
    nature: str

    def generer(self, demande: DemandeGeneration) -> SortieGeneration:
        """Un fond (PNG) pour la demande. Ne produit jamais de texte ni de logo ; aucun secret n'est journalisé."""


class GenerateurVideo(Protocol):
    nature: str

    def generer(self, demande: DemandeGeneration) -> SortieGeneration:
        """Un clip de fond. L'habillage (titre, mentions, sous-titres) relève d'un montage déterministe distinct."""


def construire_invite(brief: Brief) -> tuple[str, str]:
    """`(invite, invite négative)` d'un brief au fond généré : champs structurés + cadre fixe, rien d'autre."""
    if not brief.genere:
        raise ErreurGeneration(REJ_GENERATION, "ce brief n'a pas de fond généré")
    fond = brief.fond
    morceaux = [CADRE_POSITIF, f"subject: {fond['sujet']}"]
    if fond.get("ambiance"):
        morceaux.append(f"mood: {fond['ambiance']}")
    morceaux.append(
        "photographic" if fond.get("rendu", "photographique") == "photographique" else "flat illustration style"
    )
    morceaux.append("color palette: " + ", ".join(brief.marque["couleurs"]))
    return "; ".join(morceaux), INVITE_NEGATIVE


def dimensions_du_fond(largeur_px: int, hauteur_px: int) -> tuple[int, int]:
    """Taille demandée au modèle : celle de la composition, bornée (la résolution d'impression est contrôlée après)."""
    echelle = min(1.0, DIMENSION_FOND_MAX / max(largeur_px, hauteur_px))
    return max(64, round(largeur_px * echelle)), max(64, round(hauteur_px * echelle))


def graine_par_defaut(brief_empreinte: str, job_id: str) -> int:
    """Graine déterministe quand le brief n'en fixe pas : journalisée, donc rejouable."""
    return int(hashlib.sha256(f"{brief_empreinte}\n{job_id}".encode()).hexdigest()[:8], 16)


# -- doubles ---------------------------------------------------------------------------------------------------
def _octets_synthetiques(largeur: int, hauteur: int, graine: int, invite: str, phase: int = 0) -> bytes:
    """Dégradé vertical + bandes + damier, dérivés de la graine et de l'invite : un fond de test, jamais une image
    réelle.
    Chaque rangée est construite par répétition de blocs d'octets (aucun calcul par pixel : rapide en Python pur)."""
    h = hashlib.sha256(f"{graine}\n{invite}".encode()).digest()
    a = (h[0], h[1], h[2])
    b = (h[3], h[4], h[5])
    pas = 24 + h[6] % 48
    lignes = []
    for y in range(hauteur):
        t = y / max(1, hauteur - 1)
        centre = [a[k] + (b[k] - a[k]) * t for k in range(3)]
        clair = bytes(max(0, min(255, round(v + 28))) for v in centre)
        sombre = bytes(max(0, min(255, round(v - 28))) for v in centre)
        premier, second = (clair, sombre) if ((y // pas) + phase) % 2 == 0 else (sombre, clair)
        motif = (premier * pas + second * pas) * (largeur // (2 * pas) + 2)
        lignes.append(motif[: 3 * largeur])
    return b"".join(lignes)


class GenerateurImageDouble:
    """Double déterministe : PNG synthétique. NATURE `double` : un visuel qui l'utilise est un visuel de TEST."""

    nature = NATURE_DOUBLE
    MODELE = "double-deterministe"
    VERSION = "1"

    def generer(self, demande: DemandeGeneration) -> SortieGeneration:
        if demande.genre != "image":
            raise ErreurGeneration(REJ_GENERATION, "ce double ne génère que des images")
        if not (16 <= demande.largeur <= DIMENSION_FOND_MAX and 16 <= demande.hauteur <= DIMENSION_FOND_MAX):
            raise ErreurGeneration(REJ_GENERATION, "dimensions demandées hors bornes")
        image = png.ImageRVB(
            demande.largeur,
            demande.hauteur,
            _octets_synthetiques(demande.largeur, demande.hauteur, demande.graine, demande.invite),
        )
        return SortieGeneration(
            png.encoder(image),
            "png",
            demande.largeur,
            demande.hauteur,
            self.MODELE,
            self.VERSION,
            None,
            demande.graine,
            demande.invite,
            self.nature,
            {"synthetique": True},
        )


def _bloc(type_bloc: bytes, donnees: bytes) -> bytes:
    return struct.pack(">I", len(donnees)) + type_bloc + donnees + struct.pack(">I", zlib.crc32(type_bloc + donnees))


def apng(images: list[png.ImageRVB], images_par_seconde: int) -> bytes:
    """PNG animé (APNG) : le « clip » synthétique du double vidéo. Les images ont toutes la même taille."""
    premiere = images[0]
    sortie = [
        png.SIGNATURE,
        _bloc(b"IHDR", struct.pack(">IIBBBBB", premiere.largeur, premiere.hauteur, 8, 2, 0, 0, 0)),
        _bloc(b"acTL", struct.pack(">II", len(images), 0)),
    ]
    sequence = 0
    ligne = 3 * premiere.largeur
    for rang, image in enumerate(images):
        brut = b"".join(b"\x00" + image.pixels[y * ligne : (y + 1) * ligne] for y in range(image.hauteur))
        sortie.append(
            _bloc(
                b"fcTL",
                struct.pack(">IIIIIHHBB", sequence, image.largeur, image.hauteur, 0, 0, 1, images_par_seconde, 0, 0),
            )
        )
        sequence += 1
        compresse = zlib.compress(brut, 9)
        if rang == 0:
            sortie.append(_bloc(b"IDAT", compresse))
        else:
            sortie.append(_bloc(b"fdAT", struct.pack(">I", sequence) + compresse))
            sequence += 1
    sortie.append(_bloc(b"IEND", b""))
    return b"".join(sortie)


class GenerateurVideoDouble:
    """Double vidéo : un APNG de quelques images synthétiques (jamais une vraie vidéo). NATURE `double`."""

    nature = NATURE_DOUBLE
    MODELE = "double-video-deterministe"
    VERSION = "1"

    def generer(self, demande: DemandeGeneration) -> SortieGeneration:
        if demande.genre != "video" or not demande.duree_s or not demande.images_par_seconde:
            raise ErreurGeneration(REJ_GENERATION, "durée et cadence exigées pour une vidéo")
        if not (16 <= demande.largeur <= 512 and 16 <= demande.hauteur <= 512):
            raise ErreurGeneration(REJ_GENERATION, "le double vidéo ne produit que de petites images (512 px au plus)")
        nombre = min(demande.duree_s * demande.images_par_seconde, 12)
        images = [
            png.ImageRVB(
                demande.largeur,
                demande.hauteur,
                _octets_synthetiques(demande.largeur, demande.hauteur, demande.graine, demande.invite, i),
            )
            for i in range(nombre)
        ]
        return SortieGeneration(
            apng(images, demande.images_par_seconde),
            "apng",
            demande.largeur,
            demande.hauteur,
            self.MODELE,
            self.VERSION,
            None,
            demande.graine,
            demande.invite,
            self.nature,
            {"images": nombre, "synthetique": True},
            demande.duree_s,
        )


# Adaptateurs de modèles réels, par identifiant de fournisseur du registre. VIDE : aucun adaptateur réel n'est livré
# dans
# cette tranche ; un fournisseur sélectionné sans adaptateur est un refus typé (`REJ-STUDIO-ADAPTATEUR-ABSENT`).
ADAPTATEURS_DE_PRODUCTION: dict[str, GenerateurImage | GenerateurVideo] = {}


def verifier_sortie(sortie: SortieGeneration, demande: DemandeGeneration) -> None:
    """La sortie d'un adaptateur est une donnée externe : forme, format, dimensions et graine sont revérifiées."""
    if not isinstance(sortie, SortieGeneration) or not isinstance(sortie.octets, bytes) or not sortie.octets:
        raise ErreurGeneration(REJ_SORTIE, "sortie du générateur absente ou mal formée")
    if sortie.graine != demande.graine:
        raise ErreurGeneration(REJ_SORTIE, "le générateur n'a pas rendu la graine demandée (rejeu impossible)")
    if sortie.nature not in (NATURE_REEL, NATURE_DOUBLE):
        raise ErreurGeneration(REJ_SORTIE, "nature du générateur inconnue")
    if not sortie.modele or not sortie.version_modele:
        raise ErreurGeneration(REJ_SORTIE, "le générateur doit déclarer son modèle et sa version")
    if demande.genre == "image":
        if sortie.format != "png":
            raise ErreurGeneration(REJ_SORTIE, "fond d'image attendu en PNG (pas de JPEG pour l'impression)")
        try:
            largeur, hauteur = png.dimensions(sortie.octets)
            png.decoder(sortie.octets)
        except png.PngInvalide as exc:
            raise ErreurGeneration(REJ_SORTIE, f"PNG illisible : {exc.detail}") from None
        if (largeur, hauteur) != (sortie.largeur, sortie.hauteur):
            raise ErreurGeneration(REJ_SORTIE, "dimensions annoncées différentes de celles du PNG")
    elif sortie.format not in ("apng", "mp4"):
        raise ErreurGeneration(REJ_SORTIE, "format vidéo attendu : mp4 ou apng")
