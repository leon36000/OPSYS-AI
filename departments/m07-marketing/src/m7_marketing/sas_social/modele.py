"""Le modèle d'une publication sociale : ce que la direction approuve, et son empreinte.

Une publication dit : sur quel RÉSEAU et quel COMPTE, quel TEXTE (et titre), quels MÉDIAS (chacun avec son origine, sa
modération et sa part d'IA), QUAND (instant UTC), avec quelle DIVULGATION d'IA, de quel TYPE (organique ou annonce
payante, avec son budget en cents) et quelles OPTIONS propres au réseau. Son EMPREINTE (SHA-256 d'un JSON canonique)
est ce que la direction approuve : le moindre changement après l'approbation donne une autre empreinte et plus rien ne
part. La clé d'idempotence n'en fait pas partie (elle identifie la publication, pas son contenu).

Fail-closed : un champ inconnu, un type faux ou une valeur hors liste est un refus `{code, chemin, detail}`, jamais une
valeur corrigée en silence.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .reseaux import IMAGE, RESEAUX, VIDEO

ORGANIQUE = "organique"
ANNONCE_PAYANTE = "annonce_payante"
TYPES_PUBLICATION = (ORGANIQUE, ANNONCE_PAYANTE)

ORIGINE_PHOTO = "photo_chantier"
ORIGINE_COMPOSEE = "composition_deterministe"
ORIGINE_BANQUE = "banque_licenciee"
ORIGINE_GENERE_NON_COMPOSE = "genere_non_compose"
ORIGINES = (ORIGINE_PHOTO, ORIGINE_COMPOSEE, ORIGINE_BANQUE, ORIGINE_GENERE_NON_COMPOSE)
MODERATIONS = ("verifiee", "revue_requise", "non_verifiee")
CONTROLES_OCR = ("conforme", "non_requis", "non_fait")

REJ_CHAMP = "REJ-SOCIAL-CHAMP"
REJ_CHAMP_INCONNU = "REJ-SOCIAL-CHAMP-INCONNU"
REJ_VALEUR = "REJ-SOCIAL-VALEUR"
REJ_INSTANT = "REJ-SOCIAL-INSTANT"

_REFERENCE = re.compile(r"[a-z0-9][a-z0-9._-]{0,80}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMPTE = re.compile(r"[a-z0-9][a-z0-9._-]{1,63}")
_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_FORMAT = re.compile(r"[a-z0-9]{2,6}")

CHAMPS_PUBLICATION = (
    "reseau",
    "compte",
    "texte",
    "titre",
    "medias",
    "planifie_le",
    "divulgation",
    "type_publication",
    "budget",
    "options",
)
CHAMPS_MEDIA = (
    "reference",
    "type_media",
    "format",
    "sha256",
    "octets",
    "largeur",
    "hauteur",
    "duree_s",
    "alt",
    "origine",
    "ia_generee",
    "realiste",
    "moderation",
    "controle_ocr",
)
CHAMPS_DIVULGATION = ("texte_ia", "media_synthetique_realiste", "contenu_commercial")
CHAMPS_BUDGET = ("montant_cents", "plafond_quotidien_cents", "duree_jours")


@dataclasses.dataclass(frozen=True)
class Media:
    reference: str
    type_media: str
    format: str
    sha256: str
    octets: int
    largeur: int
    hauteur: int
    duree_s: int | None
    alt: str
    origine: str
    ia_generee: bool
    realiste: bool
    moderation: str
    controle_ocr: str


@dataclasses.dataclass(frozen=True)
class Divulgation:
    texte_ia: bool
    media_synthetique_realiste: bool
    contenu_commercial: bool


@dataclasses.dataclass(frozen=True)
class Budget:
    montant_cents: int
    plafond_quotidien_cents: int
    duree_jours: int


@dataclasses.dataclass(frozen=True)
class Publication:
    reseau: str
    compte: str
    texte: str
    titre: str | None
    medias: tuple[Media, ...]
    planifie_le: str
    divulgation: Divulgation
    type_publication: str
    budget: Budget | None
    options: Mapping[str, Any]


def instant(texte: str) -> datetime:
    """`AAAA-MM-JJTHH:MM:SSZ` -> datetime UTC. `ValueError` si le texte n'a pas exactement cette forme."""
    if not isinstance(texte, str) or not _INSTANT.fullmatch(texte):
        raise ValueError("instant UTC AAAA-MM-JJTHH:MM:SSZ attendu")
    return datetime.strptime(texte, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def en_instant(valeur: datetime) -> str:
    return valeur.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _refus(code: str, chemin: str, detail: str) -> dict[str, str]:
    return {"code": code, "chemin": chemin, "detail": detail}


def _entier(valeur: Any) -> bool:
    return type(valeur) is int


def _objet_strict(donnees: Any, champs: tuple[str, ...], chemin: str, refus: list[dict[str, str]]) -> bool:
    """Vrai si `donnees` est un objet aux champs EXACTS de `champs` ; sinon ajoute les refus et rend faux."""
    avant = len(refus)
    if not isinstance(donnees, Mapping):
        refus.append(_refus(REJ_CHAMP, chemin, "objet attendu"))
        return False
    for nom in sorted(set(donnees) - set(champs)):
        refus.append(_refus(REJ_CHAMP_INCONNU, f"{chemin}.{nom}", "champ inconnu"))
    for nom in champs:
        if nom not in donnees:
            refus.append(_refus(REJ_CHAMP, f"{chemin}.{nom}", "champ requis absent"))
    return len(refus) == avant


def _media(donnees: Any, chemin: str, refus: list[dict[str, str]]) -> Media | None:
    avant = len(refus)
    if not _objet_strict(donnees, CHAMPS_MEDIA, chemin, refus):
        return None

    def texte(nom: str, motif: re.Pattern[str]) -> None:
        if not isinstance(donnees[nom], str) or not motif.fullmatch(donnees[nom]):
            refus.append(_refus(REJ_VALEUR, f"{chemin}.{nom}", "forme invalide"))

    texte("reference", _REFERENCE)
    texte("sha256", _SHA256)
    texte("format", _FORMAT)
    for nom, permis in (
        ("type_media", (IMAGE, VIDEO)),
        ("origine", ORIGINES),
        ("moderation", MODERATIONS),
        ("controle_ocr", CONTROLES_OCR),
    ):
        if donnees[nom] not in permis:
            refus.append(_refus(REJ_VALEUR, f"{chemin}.{nom}", f"une de {list(permis)} attendue"))
    for nom in ("octets", "largeur", "hauteur"):
        if not _entier(donnees[nom]) or donnees[nom] <= 0:
            refus.append(_refus(REJ_VALEUR, f"{chemin}.{nom}", "entier positif attendu"))
    if donnees["duree_s"] is not None and (not _entier(donnees["duree_s"]) or donnees["duree_s"] <= 0):
        refus.append(_refus(REJ_VALEUR, f"{chemin}.duree_s", "entier positif ou null attendu"))
    if donnees["type_media"] == VIDEO and donnees["duree_s"] is None:
        refus.append(_refus(REJ_VALEUR, f"{chemin}.duree_s", "durée exigée pour une vidéo"))
    if donnees["type_media"] == IMAGE and donnees["duree_s"] is not None:
        refus.append(_refus(REJ_VALEUR, f"{chemin}.duree_s", "durée interdite pour une image"))
    if not isinstance(donnees["alt"], str) or len(donnees["alt"]) > 300:
        refus.append(_refus(REJ_VALEUR, f"{chemin}.alt", "texte de 300 caractères au plus"))
    elif donnees["type_media"] == IMAGE and not donnees["alt"].strip():
        refus.append(_refus(REJ_VALEUR, f"{chemin}.alt", "texte alternatif exigé pour une image (accessibilité)"))
    for nom in ("ia_generee", "realiste"):
        if type(donnees[nom]) is not bool:
            refus.append(_refus(REJ_VALEUR, f"{chemin}.{nom}", "booléen attendu"))
    if len(refus) > avant:
        return None
    return Media(**{nom: donnees[nom] for nom in CHAMPS_MEDIA})


def depuis_dict(donnees: Any) -> tuple[Publication | None, list[dict[str, str]]]:
    """(publication, refus). Un seul des deux est utile : jamais de publication partielle."""
    refus: list[dict[str, str]] = []
    if not _objet_strict(donnees, CHAMPS_PUBLICATION, "$", refus):
        return None, refus
    if donnees["reseau"] not in RESEAUX:
        refus.append(_refus(REJ_VALEUR, "$.reseau", f"un de {list(RESEAUX)} attendu"))
    if not isinstance(donnees["compte"], str) or not _COMPTE.fullmatch(donnees["compte"]):
        refus.append(_refus(REJ_VALEUR, "$.compte", "identifiant de compte invalide"))
    if not isinstance(donnees["texte"], str):
        refus.append(_refus(REJ_VALEUR, "$.texte", "texte attendu"))
    if donnees["titre"] is not None and not isinstance(donnees["titre"], str):
        refus.append(_refus(REJ_VALEUR, "$.titre", "texte ou null attendu"))
    try:
        instant(donnees["planifie_le"])
    except ValueError as exc:
        refus.append(_refus(REJ_INSTANT, "$.planifie_le", str(exc)))
    if donnees["type_publication"] not in TYPES_PUBLICATION:
        refus.append(_refus(REJ_VALEUR, "$.type_publication", f"un de {list(TYPES_PUBLICATION)} attendu"))
    if not isinstance(donnees["options"], Mapping):
        refus.append(_refus(REJ_VALEUR, "$.options", "objet attendu"))
    medias: list[Media] = []
    if not isinstance(donnees["medias"], (list, tuple)):
        refus.append(_refus(REJ_VALEUR, "$.medias", "liste attendue"))
    else:
        for rang, brut in enumerate(donnees["medias"]):
            media = _media(brut, f"$.medias[{rang}]", refus)
            if media is not None:
                medias.append(media)
    divulgation = None
    if _objet_strict(donnees["divulgation"], CHAMPS_DIVULGATION, "$.divulgation", refus):
        if not all(type(donnees["divulgation"][n]) is bool for n in CHAMPS_DIVULGATION):
            refus.append(_refus(REJ_VALEUR, "$.divulgation", "trois booléens attendus"))
        else:
            divulgation = Divulgation(**{n: donnees["divulgation"][n] for n in CHAMPS_DIVULGATION})
    budget = None
    brut_budget = donnees["budget"]
    if brut_budget is not None and _objet_strict(brut_budget, CHAMPS_BUDGET, "$.budget", refus):
        if not all(_entier(brut_budget[n]) and brut_budget[n] > 0 for n in CHAMPS_BUDGET):
            refus.append(_refus(REJ_VALEUR, "$.budget", "entiers positifs attendus (cents CAD, jours)"))
        else:
            budget = Budget(**{n: brut_budget[n] for n in CHAMPS_BUDGET})
    if refus:
        return None, refus
    return Publication(
        reseau=donnees["reseau"],
        compte=donnees["compte"],
        texte=donnees["texte"],
        titre=donnees["titre"],
        medias=tuple(medias),
        planifie_le=donnees["planifie_le"],
        divulgation=divulgation,
        type_publication=donnees["type_publication"],
        budget=budget,
        options=dict(donnees["options"]),
    ), []


def en_dict(publication: Publication) -> dict[str, Any]:
    """Forme JSON native (stockable au journal, rejouable dans `depuis_dict`)."""
    brut = dataclasses.asdict(publication)
    brut["medias"] = [dataclasses.asdict(m) for m in publication.medias]
    brut["options"] = dict(publication.options)
    return brut


def empreinte(publication: Publication) -> str:
    texte = json.dumps(en_dict(publication), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(("opsys-social/v1\n" + texte).encode("utf-8")).hexdigest()


def media_synthetique_realiste(publication: Publication) -> bool:
    """Calculé des médias, jamais cru sur parole : au moins un média généré par IA et d'allure réaliste."""
    return any(m.ia_generee and m.realiste for m in publication.medias)
