"""Dépôt sûr d'un fichier d'onboarding : lecture par NOM seul, types en liste fermée, archive ZIP gardée.

Module pur hors de `lire_depose` (qui ouvre un fichier) : aucune base, aucun réseau, aucun parseur de contenu. Il ne
décide que de la FORME : quel fichier, de quel type (signature ET extension), dans quelles bornes. Le contenu n'est
jamais interprété ici.

- Le client (ou l'opérateur) dépose ses fichiers dans `<OPSYS_HOME>/imports/onboarding/`. Un outil ne reçoit qu'un
  NOM : pas de chemin, pas de `..`, pas de lien symbolique (le dossier lui-même ne peut pas en être un, le fichier est
  ouvert avec `O_NOFOLLOW`), un fichier ordinaire d'au plus `SOURCE_MAX` octets.
- Types acceptés (liste FERMÉE, `TYPES`) : PDF, PNG, JPEG, texte, CSV, classeur `.xlsx` ; plus l'archive `.zip` au
  premier niveau seulement. L'extension ET la signature doivent concorder (`REJ-ING-TYPE-INCOHERENT` sinon) : un
  `.pdf` qui n'est pas un PDF n'entre pas.
- Archive : refus de TOUTE l'archive au premier signe d'attaque (traversée de chemin, lien symbolique, nom répété,
  trop de membres, taille décompressée totale ou ratio de compression hors bornes, taille déclarée mensongère) ; refus
  d'un MEMBRE seulement pour ce qui ne menace pas les autres (type non accepté, membre chiffré, archive imbriquée,
  membre trop gros). Les membres refusés restent des documents du lot, sans contenu, avec leur code.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

from .. import stockage
from .codes import IngestionErreur, construire_verdict

SOURCE_MAX = 32 * 1024 * 1024
MEMBRE_MAX = 8 * 1024 * 1024
MEMBRES_MAX = 500
TOTAL_DECOMPRESSE_MAX = 128 * 1024 * 1024
RATIO_MAX = 100
RATIO_SEUIL_OCTETS = 64 * 1024
NOM_MEMBRE_MAX = 255

TYPES: tuple[str, ...] = ("pdf", "png", "jpeg", "txt", "csv", "xlsx")
_EXTENSIONS = {
    ".pdf": "pdf", ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".txt": "txt", ".csv": "csv", ".xlsx": "xlsx",
}
_NOM_FICHIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,119}\.(?:zip|pdf|png|jpe?g|txt|csv|xlsx)", re.IGNORECASE)
_IGNORES = ("__MACOSX/",)
_NOMS_IGNORES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})


@dataclasses.dataclass(frozen=True)
class Membre:
    """Un document candidat : son nom (dans l'archive, ou le nom déposé), ses octets s'il est accepté, son type
    détecté, et le refus qui l'écarte (`None` s'il est accepté)."""

    nom: str
    octets: bytes | None
    taille: int
    sha256: str
    type_detecte: str | None
    refus: dict | None


def dossier_depot() -> Path:
    """Le seul dossier d'où l'ingestion lit : `<OPSYS_HOME>/imports/onboarding/`."""
    return stockage.dossier_opsys() / "imports" / "onboarding"


def valider_nom(nom: object) -> str:
    if not isinstance(nom, str) or _NOM_FICHIER.fullmatch(nom) is None or ".." in nom:
        raise IngestionErreur(
            "REJ-ING-NOM-INVALIDE",
            "nom de fichier seul attendu (lettres, chiffres, . _ - espace ; .zip .pdf .png .jpg .txt .csv .xlsx), "
            "déposé dans <OPSYS_HOME>/imports/onboarding/ ; jamais un chemin",
            422,
        )
    return nom


def lire_depose(nom: object, *, dossier: Path | None = None) -> bytes:
    """Les octets d'un fichier déposé, par son NOM seul. Refus typés, sans jamais suivre un lien."""
    nom = valider_nom(nom)
    racine = dossier if dossier is not None else dossier_depot()
    try:
        etat_dossier = os.lstat(racine)
    except OSError:
        raise IngestionErreur("REJ-ING-DOSSIER-INVALIDE", "dossier de dépôt absent : créer "
                              "<OPSYS_HOME>/imports/onboarding/ et y déposer les fichiers", 404) from None
    if not stat.S_ISDIR(etat_dossier.st_mode):
        raise IngestionErreur("REJ-ING-DOSSIER-INVALIDE", "le dossier de dépôt est un lien ou n'est pas un dossier",
                              422)
    try:
        descripteur = os.open(racine / nom, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        raise IngestionErreur("REJ-ING-FICHIER-ABSENT", f"fichier {nom!r} absent du dossier de dépôt, ou lien "
                              "symbolique", 404) from None
    try:
        etat_fichier = os.fstat(descripteur)
        if not stat.S_ISREG(etat_fichier.st_mode):
            raise IngestionErreur("REJ-ING-FICHIER-ABSENT", f"{nom!r} n'est pas un fichier ordinaire", 422)
        if etat_fichier.st_size > SOURCE_MAX:
            raise IngestionErreur("REJ-ING-FICHIER-TROP-GROS", f"{nom!r} dépasse {SOURCE_MAX} octets", 413)
        with os.fdopen(os.dup(descripteur), "rb") as flux:
            octets = flux.read(SOURCE_MAX + 1)
    finally:
        os.close(descripteur)
    if len(octets) > SOURCE_MAX:
        raise IngestionErreur("REJ-ING-FICHIER-TROP-GROS", f"{nom!r} dépasse {SOURCE_MAX} octets", 413)
    if not octets:
        raise IngestionErreur("REJ-ING-FICHIER-VIDE", f"{nom!r} est vide", 422)
    return octets


def _signature(octets: bytes) -> str | None:
    """Le type que disent les premiers octets ; `None` pour du texte possible (txt, csv), jugé à part."""
    if octets.startswith(b"%PDF-"):
        return "pdf"
    if octets.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if octets.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if octets.startswith(b"PK\x03\x04") or octets.startswith(b"PK\x05\x06"):
        return "zip"
    return None


def _est_xlsx(octets: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(octets)) as archive:
            noms = set(archive.namelist())
    except (zipfile.BadZipFile, ValueError, RuntimeError, OSError):
        return False
    return "[Content_Types].xml" in noms and "xl/workbook.xml" in noms


def _est_texte(octets: bytes) -> bool:
    """Du texte décodable (UTF-8 avec ou sans BOM, UTF-16 avec BOM, Windows-1252), sans caractère nul."""
    if octets.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            texte = octets.decode("utf-16")
        except UnicodeDecodeError:
            return False
        return "\x00" not in texte
    if b"\x00" in octets:
        return False
    for codec in ("utf-8-sig", "cp1252"):
        try:
            octets.decode(codec)
            return True
        except UnicodeDecodeError:
            continue
    return False


def detecter_type(nom: str, octets: bytes) -> tuple[str | None, dict | None]:
    """`(type, None)` si l'extension est de la liste fermée et que la signature la confirme ; `(None, refus)` sinon."""
    extension = PurePosixPath(nom).suffix.lower()
    attendu = _EXTENSIONS.get(extension)
    if attendu is None:
        return None, construire_verdict("REJ-ING-TYPE-NON-ACCEPTE", f"extension {extension or '(aucune)'!r} hors de "
                                        "la liste fermée : .pdf .png .jpg .jpeg .txt .csv .xlsx")
    signature = _signature(octets)
    if attendu in ("pdf", "png", "jpeg"):
        concorde = signature == attendu
    elif attendu == "xlsx":
        concorde = signature == "zip" and _est_xlsx(octets)
    else:
        concorde = signature is None and _est_texte(octets)
    if not concorde:
        return None, construire_verdict("REJ-ING-TYPE-INCOHERENT", f"le contenu ne correspond pas à l'extension "
                                        f"{extension!r} (signature : {signature or 'texte ou inconnue'})")
    return attendu, None


def _membre(nom: str, octets: bytes) -> Membre:
    empreinte = hashlib.sha256(octets).hexdigest()
    if len(octets) > MEMBRE_MAX:
        return Membre(nom, None, len(octets), empreinte, None,
                      construire_verdict("REJ-ING-FICHIER-TROP-GROS", f"document de plus de {MEMBRE_MAX} octets"))
    if not octets:
        return Membre(nom, None, 0, empreinte, None, construire_verdict("REJ-ING-FICHIER-VIDE", "document vide"))
    type_detecte, refus = detecter_type(nom, octets)
    if refus is not None:
        return Membre(nom, None, len(octets), empreinte, None, refus)
    return Membre(nom, octets, len(octets), empreinte, type_detecte, None)


def _nom_sur(nom: str) -> str:
    """Le nom d'un membre, refusé (pour TOUTE l'archive) s'il sort de l'archive ou s'il est ambigu."""
    if (not nom or not nom.isprintable() or "\\" in nom or nom.startswith("/") or re.match(r"[A-Za-z]:", nom)
            or len(nom) > NOM_MEMBRE_MAX):
        raise IngestionErreur("REJ-ING-ZIP-TRAVERSEE", "un membre de l'archive a un nom absolu, non imprimable ou "
                              "hors bornes : archive refusée en entier", 422)
    parties = nom.rstrip("/").split("/")
    if any(partie in ("", ".", "..") for partie in parties):
        raise IngestionErreur("REJ-ING-ZIP-TRAVERSEE", "un membre de l'archive sort de son dossier (`..`, `.` ou "
                              "chemin vide) : archive refusée en entier", 422)
    return nom


def _est_lien(info: zipfile.ZipInfo) -> bool:
    return info.create_system == 3 and stat.S_ISLNK(info.external_attr >> 16)


def deplier(nom: str, octets: bytes) -> tuple[list[Membre], dict]:
    """Les documents d'un dépôt et le résumé de la lecture : un seul membre pour un fichier simple ; les membres d'une
    archive `.zip` sinon (un seul niveau). Lève `IngestionErreur` pour un dépôt refusé en entier."""
    extension = PurePosixPath(nom).suffix.lower()
    if extension != ".zip":
        return [_membre(nom, octets)], {"type_source": "fichier", "ignores": 0}
    if _signature(octets) != "zip":
        raise IngestionErreur("REJ-ING-TYPE-INCOHERENT", "le fichier .zip n'est pas une archive ZIP", 422)
    try:
        archive = zipfile.ZipFile(io.BytesIO(octets))
        infos = archive.infolist()
    except (zipfile.BadZipFile, ValueError, RuntimeError, OSError):
        raise IngestionErreur("REJ-ING-ZIP-ILLISIBLE", "archive ZIP illisible ou corrompue", 422) from None
    with archive:
        fichiers = [info for info in infos if not info.is_dir()]
        if len(fichiers) > MEMBRES_MAX:
            raise IngestionErreur("REJ-ING-ZIP-BOMBE", f"plus de {MEMBRES_MAX} membres dans l'archive", 422)
        vus: set[str] = set()
        total = 0
        for info in infos:
            _nom_sur(info.filename)
            if _est_lien(info):
                raise IngestionErreur("REJ-ING-ZIP-LIEN", "l'archive contient un lien symbolique : archive refusée",
                                      422)
            if info.is_dir():
                continue
            cle = info.filename.casefold()
            if cle in vus:
                raise IngestionErreur("REJ-ING-ZIP-NOM-REPETE", "deux membres portent le même nom (casse ignorée) : "
                                      "archive refusée", 422)
            vus.add(cle)
            total += info.file_size
            if total > TOTAL_DECOMPRESSE_MAX:
                raise IngestionErreur("REJ-ING-ZIP-BOMBE", f"plus de {TOTAL_DECOMPRESSE_MAX} octets une fois "
                                      "décompressée", 422)
            if (info.file_size > RATIO_SEUIL_OCTETS
                    and info.file_size > RATIO_MAX * max(info.compress_size, 1)):
                raise IngestionErreur("REJ-ING-ZIP-BOMBE", f"un membre se décompresse plus de {RATIO_MAX} fois sa "
                                      "taille compressée", 422)
        membres: list[Membre] = []
        ignores = 0
        for info in fichiers:
            nom_membre = info.filename
            base = PurePosixPath(nom_membre).name.casefold()
            if nom_membre.startswith(_IGNORES) or base in _NOMS_IGNORES:
                ignores += 1
                continue
            if info.flag_bits & 0x1:
                membres.append(Membre(nom_membre, None, info.file_size, "0" * 64, None,
                                      construire_verdict("REJ-ING-ZIP-CHIFFRE", "membre chiffré : déposer le fichier "
                                                         "en clair")))
                continue
            if info.file_size > MEMBRE_MAX:
                membres.append(Membre(nom_membre, None, info.file_size, "0" * 64, None, construire_verdict(
                    "REJ-ING-FICHIER-TROP-GROS", f"document de plus de {MEMBRE_MAX} octets")))
                continue
            try:
                with archive.open(info) as flux:
                    contenu = flux.read(MEMBRE_MAX + 1)
            except (zipfile.BadZipFile, ValueError, RuntimeError, OSError, EOFError):
                raise IngestionErreur("REJ-ING-ZIP-ILLISIBLE", "un membre de l'archive est illisible", 422) from None
            if len(contenu) != info.file_size:
                raise IngestionErreur("REJ-ING-ZIP-BOMBE", "un membre ne fait pas la taille qu'il déclare : archive "
                                      "refusée", 422)
            if PurePosixPath(nom_membre).suffix.lower() == ".zip" or (
                    _signature(contenu) == "zip" and not _est_xlsx(contenu)):
                membres.append(Membre(nom_membre, None, len(contenu), hashlib.sha256(contenu).hexdigest(), None,
                                      construire_verdict("REJ-ING-ZIP-IMBRIQUE", "archive dans l'archive : déposer "
                                                         "son contenu directement")))
                continue
            membres.append(_membre(nom_membre, contenu))
    return membres, {"type_source": "zip", "ignores": ignores}


__all__ = [
    "MEMBRES_MAX", "MEMBRE_MAX", "Membre", "SOURCE_MAX", "TOTAL_DECOMPRESSE_MAX", "TYPES", "deplier", "detecter_type",
    "dossier_depot", "lire_depose", "valider_nom",
]
