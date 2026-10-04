"""Validation pure du candidat OCR financier, sans interprétation comptable."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

_MESSAGE_JSON = "résultat OCR refusé"
_MESSAGE_TSV = "TSV OCR refusé"
_MAX_JSON = 262_144
_MAX_TSV = 524_288
_MAX_LIGNES_TSV = 4_096
_MAX_DIMENSION = 4_096
_MAX_PIXELS = 4_000_000
_MAX_TOKENS = 2_048
_MAX_TEXTE_TOKEN = 512
_MAX_TEXTE_TOTAL = 65_536
_MAX_ENTIER = 2_147_483_647
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_VERSION = re.compile(r"[a-z][a-z0-9]*-[0-9]+\.[0-9]+\.[0-9]+\Z")
_ENTIER = re.compile(r"[0-9]{1,10}\Z")
_SCORE = re.compile(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)\Z")
_ENTETE_TSV = (
    "level", "page_num", "block_num", "par_num", "line_num", "word_num",
    "left", "top", "width", "height", "conf", "text",
)
_CHAMPS_RACINE = {
    "schema_version", "genre", "statut", "lot_id", "source_sha256", "revision_source",
    "configuration_sha256", "profil", "page",
}
_CHAMPS_PROFIL = {"rasteriseur", "moteur", "leptonica", "pdfium_sha256", "modele_sha256", "langue"}
_CHAMPS_PAGE = {"numero", "largeur_px", "hauteur_px", "tokens"}
_CHAMPS_TOKEN = {"texte", "x0", "y0", "x1", "y1", "confiance_brute"}


class OCRContratErreur(ValueError):
    """Erreur bornée du protocole OCR, sans donnée du document dans le message."""

    def __init__(self, code: str, message: str = _MESSAGE_JSON):
        self.code = code
        self.message = message
        super().__init__(message)


def _erreur_json() -> OCRContratErreur:
    return OCRContratErreur("OCR_RESULTAT_INVALIDE", _MESSAGE_JSON)


def _erreur_tsv() -> OCRContratErreur:
    return OCRContratErreur("OCR_TSV_INVALIDE", _MESSAGE_TSV)


def _mapping_exact(value: Any, champs: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == champs


def _entier(value: Any, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _hash_valide(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _version_valide(value: Any, famille: str) -> bool:
    return (
        isinstance(value, str) and len(value) <= 64 and value.startswith(famille + "-")
        and _VERSION.fullmatch(value) is not None
    )


def _texte_valide(value: Any, *, taille_max: int) -> tuple[bool, int]:
    if not isinstance(value, str) or not value or not value.strip():
        return False, 0
    try:
        taille = len(value.encode("utf-8", "strict"))
    except UnicodeEncodeError:
        return False, 0
    if taille > taille_max:
        return False, taille
    for caractere in value:
        code = ord(caractere)
        if code < 0x20 or 0x7F <= code <= 0x9F or 0xD800 <= code <= 0xDFFF or code == 0xFFFD:
            return False, taille
    return True, taille


def _doublons_refuses(paires: list[tuple[str, Any]]) -> dict[str, Any]:
    resultat: dict[str, Any] = {}
    for cle, valeur in paires:
        if cle in resultat:
            raise _erreur_json()
        resultat[cle] = valeur
    return resultat


def _constante_json_refusee(_: str) -> None:
    raise _erreur_json()


def _profil_contexte(contexte: ContexteOCR) -> dict[str, str]:
    return {
        "rasteriseur": contexte.rasteriseur,
        "moteur": contexte.moteur,
        "leptonica": contexte.leptonica,
        "pdfium_sha256": contexte.pdfium_sha256,
        "modele_sha256": contexte.modele_sha256,
        "langue": "fra",
    }


@dataclass(frozen=True, slots=True)
class ContexteOCR:
    """Identités attendues, fournies par l'orchestrateur et jamais par le PDF."""

    lot_id: str
    source_sha256: str
    revision_source: int
    configuration_sha256: str
    rasteriseur: str
    moteur: str
    leptonica: str
    pdfium_sha256: str
    modele_sha256: str

    def __post_init__(self) -> None:
        valide = (
            isinstance(self.lot_id, str) and _UUID.fullmatch(self.lot_id) is not None
            and _hash_valide(self.source_sha256)
            and _entier(self.revision_source, 1, _MAX_ENTIER)
            and _hash_valide(self.configuration_sha256)
            and _version_valide(self.rasteriseur, "pypdfium2")
            and _version_valide(self.moteur, "tesseract")
            and _version_valide(self.leptonica, "leptonica")
            and _hash_valide(self.pdfium_sha256)
            and _hash_valide(self.modele_sha256)
        )
        if not valide:
            raise OCRContratErreur("OCR_CONTEXTE_INVALIDE", "contexte OCR invalide")


def _valider_candidat(candidat: Any, contexte: ContexteOCR) -> bool:
    if not _mapping_exact(candidat, _CHAMPS_RACINE):
        return False
    if (
        type(candidat["schema_version"]) is not int or candidat["schema_version"] != 1
        or candidat["genre"] != "m5.ocr_scan_candidat"
        or candidat["statut"] != "CANDIDAT_A_REVOIR"
        or candidat["lot_id"] != contexte.lot_id
        or candidat["source_sha256"] != contexte.source_sha256
        or type(candidat["revision_source"]) is not int
        or candidat["revision_source"] != contexte.revision_source
        or candidat["configuration_sha256"] != contexte.configuration_sha256
    ):
        return False

    profil = candidat["profil"]
    if not _mapping_exact(profil, _CHAMPS_PROFIL) or profil != _profil_contexte(contexte):
        return False

    page = candidat["page"]
    if not _mapping_exact(page, _CHAMPS_PAGE):
        return False
    largeur, hauteur = page["largeur_px"], page["hauteur_px"]
    if (
        page["numero"] != 1 or type(page["numero"]) is not int
        or not _entier(largeur, 1, _MAX_DIMENSION)
        or not _entier(hauteur, 1, _MAX_DIMENSION)
        or largeur * hauteur > _MAX_PIXELS
    ):
        return False

    tokens = page["tokens"]
    if not isinstance(tokens, list) or not 1 <= len(tokens) <= _MAX_TOKENS:
        return False
    total_octets = 0
    for token in tokens:
        if not _mapping_exact(token, _CHAMPS_TOKEN):
            return False
        texte_ok, taille = _texte_valide(token["texte"], taille_max=_MAX_TEXTE_TOKEN)
        total_octets += taille
        if not texte_ok or total_octets > _MAX_TEXTE_TOTAL:
            return False
        x0, y0, x1, y1 = (token[cle] for cle in ("x0", "y0", "x1", "y1"))
        if (
            not _entier(x0, 0, largeur - 1) or not _entier(y0, 0, hauteur - 1)
            or not _entier(x1, 1, largeur) or not _entier(y1, 1, hauteur)
            or x1 <= x0 or y1 <= y0
        ):
            return False
        score = token["confiance_brute"]
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            return False
        if isinstance(score, int):
            if not 0 <= score <= 100:
                return False
        elif not math.isfinite(score) or not 0 <= score <= 100:
            return False
    return True


def decoder_candidat(sortie: bytes, *, contexte: ContexteOCR) -> dict[str, Any]:
    """Décode un JSON fermé, le lie au contexte attendu et renvoie son objet validé."""
    if not isinstance(sortie, bytes) or len(sortie) > _MAX_JSON or sortie.startswith(b"\xef\xbb\xbf"):
        raise _erreur_json()
    try:
        texte = sortie.decode("utf-8", "strict")
        candidat = json.loads(
            texte, object_pairs_hook=_doublons_refuses, parse_constant=_constante_json_refusee,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, OCRContratErreur, ValueError, TypeError, RecursionError):
        raise _erreur_json() from None
    if not isinstance(contexte, ContexteOCR) or not _valider_candidat(candidat, contexte):
        raise _erreur_json()
    return candidat


def _entier_tsv(valeur: str) -> int:
    if not _ENTIER.fullmatch(valeur):
        raise _erreur_tsv()
    nombre = int(valeur)
    if nombre > _MAX_ENTIER:
        raise _erreur_tsv()
    return nombre


def _score_tsv(valeur: str) -> float:
    if not _SCORE.fullmatch(valeur):
        raise _erreur_tsv()
    score = float(valeur)
    if not math.isfinite(score) or not 0 <= score <= 100:
        raise _erreur_tsv()
    return score


def candidat_depuis_tsv(
    tsv: bytes, *, contexte: ContexteOCR, largeur_px: int, hauteur_px: int,
) -> dict[str, Any]:
    """Convertit le TSV hiérarchique Tesseract en candidat brut, sans corriger le texte."""
    if (
        not isinstance(tsv, bytes) or len(tsv) > _MAX_TSV or tsv.startswith(b"\xef\xbb\xbf")
        or not isinstance(contexte, ContexteOCR)
        or not _entier(largeur_px, 1, _MAX_DIMENSION)
        or not _entier(hauteur_px, 1, _MAX_DIMENSION)
        or largeur_px * hauteur_px > _MAX_PIXELS
    ):
        raise _erreur_tsv()
    try:
        contenu = tsv.decode("utf-8", "strict")
    except UnicodeDecodeError:
        raise _erreur_tsv() from None
    lignes = contenu.split("\n")
    if lignes and lignes[-1] == "":
        lignes.pop()
    if not lignes or tuple(lignes[0].removesuffix("\r").split("\t")) != _ENTETE_TSV:
        raise _erreur_tsv()
    lignes_donnees = lignes[1:]
    if not 1 <= len(lignes_donnees) <= _MAX_LIGNES_TSV:
        raise _erreur_tsv()

    page_vue = False
    identifiants: dict[int, set[tuple[int, ...]]] = {niveau: set() for niveau in range(1, 6)}
    tokens: list[dict[str, Any]] = []
    for index, ligne in enumerate(lignes_donnees):
        if ligne.endswith("\r"):
            ligne = ligne[:-1]
        cellules = ligne.split("\t")
        if len(cellules) != 12:
            raise _erreur_tsv()
        valeurs = [_entier_tsv(cellules[i]) for i in range(10)]
        niveau, numero_page, bloc, paragraphe, ligne_id, mot, gauche, haut, largeur, hauteur = valeurs
        if niveau not in range(1, 6) or numero_page != 1:
            raise _erreur_tsv()
        conf, texte = cellules[10], cellules[11]
        if (
            largeur <= 0 or hauteur <= 0 or gauche + largeur > largeur_px or haut + hauteur > hauteur_px
            or (niveau > 1 and (largeur > largeur_px or hauteur > hauteur_px))
        ):
            raise _erreur_tsv()

        if niveau == 1:
            if (
                index != 0 or page_vue or (bloc, paragraphe, ligne_id, mot) != (0, 0, 0, 0)
                or (gauche, haut, largeur, hauteur) != (0, 0, largeur_px, hauteur_px)
                or conf != "-1" or texte != ""
            ):
                raise _erreur_tsv()
            page_vue = True
            identifiants[1].add((1,))
            continue

        if not page_vue:
            raise _erreur_tsv()
        if niveau < 5 and (conf != "-1" or texte != ""):
            raise _erreur_tsv()
        if niveau == 2:
            cle = (numero_page, bloc)
            parent_ok = bloc > 0 and (numero_page,) in identifiants[1] and (paragraphe, ligne_id, mot) == (0, 0, 0)
        elif niveau == 3:
            cle = (numero_page, bloc, paragraphe)
            parent_ok = (
                bloc > 0 and paragraphe > 0 and (numero_page, bloc) in identifiants[2]
                and (ligne_id, mot) == (0, 0)
            )
        elif niveau == 4:
            cle = (numero_page, bloc, paragraphe, ligne_id)
            parent_ok = (
                bloc > 0 and paragraphe > 0 and ligne_id > 0
                and (numero_page, bloc, paragraphe) in identifiants[3] and mot == 0
            )
        else:
            cle = (numero_page, bloc, paragraphe, ligne_id, mot)
            parent_ok = (
                bloc > 0 and paragraphe > 0 and ligne_id > 0 and mot > 0
                and (numero_page, bloc, paragraphe, ligne_id) in identifiants[4]
            )
        if not parent_ok or cle in identifiants[niveau]:
            raise _erreur_tsv()
        identifiants[niveau].add(cle)

        if niveau == 5:
            if not _SCORE.fullmatch(conf):
                raise _erreur_tsv()
            score = _score_tsv(conf)
            valide, _ = _texte_valide(texte, taille_max=_MAX_TEXTE_TOKEN)
            if not valide:
                raise _erreur_tsv()
            tokens.append({
                "texte": texte, "x0": gauche, "y0": haut,
                "x1": gauche + largeur, "y1": haut + hauteur,
                "confiance_brute": score,
            })

    if not page_vue or not tokens or len(tokens) > _MAX_TOKENS:
        raise _erreur_tsv()
    candidat = {
        "schema_version": 1,
        "genre": "m5.ocr_scan_candidat",
        "statut": "CANDIDAT_A_REVOIR",
        "lot_id": contexte.lot_id,
        "source_sha256": contexte.source_sha256,
        "revision_source": contexte.revision_source,
        "configuration_sha256": contexte.configuration_sha256,
        "profil": _profil_contexte(contexte),
        "page": {"numero": 1, "largeur_px": largeur_px, "hauteur_px": hauteur_px, "tokens": tokens},
    }
    try:
        return decoder_candidat(
            json.dumps(candidat, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"),
            contexte=contexte,
        )
    except (TypeError, ValueError, OCRContratErreur):
        raise _erreur_tsv() from None
