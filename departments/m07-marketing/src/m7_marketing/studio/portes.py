"""Les portes par lesquelles un actif du studio devient utilisable : le sas social et le site.

Les sas existants (`sas_social`, `site`) ne savent pas lire le registre du studio ; ils reçoivent un RÉSOLVEUR
(`sha256 -> InfoActif | None`) et appliquent ces règles pures. Elles ferment trois failles :
  1. un média déclaré « composition déterministe » dont le SHA-256 n'est pas un visuel du studio, ou qui n'est pas
     approuvé par une personne (N3), ou dont les faits (format, taille, dimensions, part d'IA, allure réaliste) ne sont
     pas ceux du registre : refusé ;
  2. un fond brut, un logo non approuvé ou un visuel quelconque du studio présenté sous une AUTRE origine (« photo de
     chantier », « banque licenciée ») pour contourner la composition ou la divulgation d'IA : refusé ;
  3. un registre dont la chaîne ne tient plus : tout est refusé (on ne peut plus savoir ce qui est approuvé).
Un média qui n'est PAS du studio (SHA-256 inconnu) et qui n'affirme pas l'être passe ces règles ; ses autres contrôles
(modération, format, divulgation) sont ceux du sas. Limite : une image du studio réencodée (autre SHA-256) n'est pas
reconnue ; la provenance est celle de l'octet exact.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from typing import Any

KIND_FOND = "fond"
KIND_VISUEL = "visuel"
KIND_LOGO = "logo"

REJ_SOCIAL_ACTIF_INCONNU = "REJ-SOCIAL-MEDIA-ACTIF-INCONNU"
REJ_SOCIAL_ACTIF_NON_APPROUVE = "REJ-SOCIAL-MEDIA-ACTIF-NON-APPROUVE"
REJ_SOCIAL_ACTIF_INCOHERENT = "REJ-SOCIAL-MEDIA-ACTIF-INCOHERENT"
REJ_SOCIAL_ACTIF_ORIGINE = "REJ-SOCIAL-MEDIA-ACTIF-ORIGINE-INCOHERENTE"
REJ_SOCIAL_IA = "REJ-SOCIAL-MEDIA-IA-INCOHERENTE"
REJ_SOCIAL_REGISTRE = "REJ-SOCIAL-ACTIFS-REGISTRE-ALTERE"
REJ_SITE_NON_APPROUVE = "REJ-SITE-IMAGE-STUDIO-NON-APPROUVE"
REJ_SITE_FOND_BRUT = "REJ-SITE-IMAGE-STUDIO-FOND-BRUT"
REJ_SITE_REGISTRE = "REJ-SITE-IMAGE-STUDIO-REGISTRE-ALTERE"
ORIGINE_COMPOSEE = "composition_deterministe"


@dataclasses.dataclass(frozen=True)
class InfoActif:
    actif_id: str
    kind: str
    etat: str
    format: str  # format de l'artefact désigné par le SHA-256 (png, svg, pdf, apng)
    octets: int
    largeur: int | None
    hauteur: int | None
    ia_generee: bool
    realiste: bool | None
    fictif: bool
    approuve: bool


Resolveur = Callable[[str], InfoActif | None]


def _refus(code: str, chemin: str, detail: str) -> dict[str, str]:
    return {"code": code, "chemin": chemin, "detail": detail}


def registre_integre(resolveur: Resolveur) -> bool:
    return bool(getattr(resolveur, "integre", True))


def controler_media_sas(media: Mapping[str, Any], chemin: str, resolveur: Resolveur) -> list[dict[str, str]]:
    """Refus (vide si le média passe) d'un média du sas — `media` : champs de `sas_social.modele.Media`."""
    if not registre_integre(resolveur):
        return [
            _refus(
                REJ_SOCIAL_REGISTRE,
                chemin,
                "le registre des actifs du studio est altéré : aucun média ne peut être vérifié",
            )
        ]
    info = resolveur(media["sha256"])
    composee = media["origine"] == ORIGINE_COMPOSEE
    if info is None:
        if composee:
            return [
                _refus(
                    REJ_SOCIAL_ACTIF_INCONNU,
                    f"{chemin}.sha256",
                    "ce média se déclare « composition déterministe » mais n'est pas un visuel du studio : "
                    "composer, contrôler et faire approuver le visuel par le studio créatif",
                )
            ]
        return []
    refus: list[dict[str, str]] = []
    if not composee:
        refus.append(
            _refus(
                REJ_SOCIAL_ACTIF_ORIGINE,
                f"{chemin}.origine",
                f"ce média EST un actif du studio ({info.actif_id}, {info.etat}) : il se déclare "
                f"« {ORIGINE_COMPOSEE} », jamais « {media['origine']} » (une image générée ne se présente pas "
                "comme une "
                "photo ou une banque d'images)",
            )
        )
        return refus
    if info.kind != KIND_VISUEL:
        return [
            _refus(
                REJ_SOCIAL_ACTIF_NON_APPROUVE,
                f"{chemin}.sha256",
                f"{info.actif_id} est un {info.kind} ({info.etat}), pas un visuel composé : un fond ou un "
                "logo seul ne se publie jamais",
            )
        ]
    if not info.approuve:
        refus.append(
            _refus(
                REJ_SOCIAL_ACTIF_NON_APPROUVE,
                f"{chemin}.sha256",
                f"le visuel {info.actif_id} est « {info.etat} » : seule l'approbation d'une personne (N3) "
                "le rend utilisable",
            )
        )
    faits = {
        "format": (media["format"], info.format),
        "octets": (media["octets"], info.octets),
        "largeur": (media["largeur"], info.largeur),
        "hauteur": (media["hauteur"], info.hauteur),
    }
    ecarts = {k: v for k, v in faits.items() if v[1] is not None and v[0] != v[1]}
    if ecarts:
        refus.append(
            _refus(
                REJ_SOCIAL_ACTIF_INCOHERENT,
                chemin,
                "faits différents du registre du studio : "
                + ", ".join(f"{k} déclaré {a!r} / registre {b!r}" for k, (a, b) in ecarts.items()),
            )
        )
    if media["ia_generee"] != info.ia_generee:
        refus.append(
            _refus(
                REJ_SOCIAL_IA,
                f"{chemin}.ia_generee",
                f"le registre du studio dit ia_generee={info.ia_generee} : la part d'IA ne se déclare pas",
            )
        )
    if info.ia_generee and info.realiste is not None and media["realiste"] != info.realiste:
        refus.append(
            _refus(
                REJ_SOCIAL_IA,
                f"{chemin}.realiste",
                f"l'approbation humaine a consigné realiste={info.realiste} : la divulgation d'un média "
                "synthétique réaliste découle de cette décision",
            )
        )
    return refus


def controler_image_site(nom: str, sha256: str, resolveur: Resolveur) -> list[dict[str, str]]:
    """Refus d'une image de site (`images/<nom>.png|svg`) : un actif du studio doit être approuvé ; un fond brut
    jamais."""
    if not registre_integre(resolveur):
        return [_refus(REJ_SITE_REGISTRE, f"$.images.{nom}", "registre des actifs du studio altéré")]
    info = resolveur(sha256)
    if info is None:
        return []
    if info.kind == KIND_FOND:
        return [
            _refus(
                REJ_SITE_FOND_BRUT,
                f"$.images.{nom}",
                f"{info.actif_id} est un fond généré non composé : il ne se publie jamais tel quel",
            )
        ]
    if not info.approuve:
        return [
            _refus(
                REJ_SITE_NON_APPROUVE,
                f"$.images.{nom}",
                f"l'actif {info.actif_id} du studio est « {info.etat} » : seule l'approbation d'une personne "
                "(N3) le rend publiable",
            )
        ]
    return []
