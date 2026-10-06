"""Validation en lecture seule du bundle OCR installé et optionnel."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

WHEEL_SHA256 = "81df25c1ab4c13ff773102d3cbea1967511d079123b067fc077bd0c4d57d91d8"
PDFIUM_SHA256 = "224f8ece41f7e35891f11c10073b7b7062d7a18e9ef870586162a85c46130f7d"
MODELE_SHA256 = "ced037562e8c80c13122dece28dd477d399af80911a28791a66a63ac1e3445ca"

_MESSAGE = "profil OCR indisponible"
_WHEEL_MAX = 4 * 1024 * 1024
_MODELE_MAX = 2 * 1024 * 1024
_MEMBRE_MAX = 8 * 1024 * 1024
_TOTAL_DECOMPRESSE_MAX = 12 * 1024 * 1024
_WHEEL_ENTREES_MAX = 256
_ARBRE_ENTREES_MAX = 256
_ARBRE_PROFONDEUR_MAX = 16
_PACKAGES = ("pypdfium2", "pypdfium2_raw", "pypdfium2_cfg")
_MODELE = "tessdata/fra.traineddata"
_RECORD_PATH = re.compile(r"[A-Za-z0-9_.+-]+\.dist-info/RECORD\Z")
_TAILLE_DECIMALE = re.compile(r"(?:0|[1-9][0-9]{0,9})\Z")


class OCRProfilErreur(ValueError):
    """Erreur générique, sans chemin local ni détail de bundle."""

    def __init__(self):
        self.code = "OCR_PROFIL_INDISPONIBLE"
        super().__init__(_MESSAGE)


def _refuser() -> None:
    raise OCRProfilErreur() from None


def _stat(path: Path, *, directory: bool | None = None) -> os.stat_result:
    try:
        result = path.lstat()
    except (OSError, ValueError, RuntimeError):
        _refuser()
    if stat.S_ISLNK(result.st_mode):
        _refuser()
    if directory is True and not stat.S_ISDIR(result.st_mode):
        _refuser()
    if directory is False and not stat.S_ISREG(result.st_mode):
        _refuser()
    return result


def _proprietaire_et_permissions(path: Path, result: os.stat_result, *, parent: bool = False) -> None:
    uid = os.geteuid()
    if result.st_uid not in (0, uid):
        _refuser()
    ecriture_groupe_autres = result.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    if not ecriture_groupe_autres:
        return
    if parent and result.st_uid == 0 and result.st_mode & stat.S_ISVTX:
        return
    _refuser()


def _verifier_chaine(path: Path) -> None:
    if (not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts
            or (len(path.parts) < 3 and path != Path("/bundle"))):
        _refuser()
    if path == Path("/"):
        _refuser()
    # Les composants de la chaîne et tout le bundle sont examinés par lstat :
    # aucune redirection symbolique ne peut élargir le périmètre monté ensuite.
    parents = list(reversed(path.parents))
    for parent in parents:
        result = _stat(parent, directory=True)
        _proprietaire_et_permissions(parent, result, parent=True)
    result = _stat(path, directory=True)
    _proprietaire_et_permissions(path, result)


def _lire_fichier(path: Path, maximum: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as flux:
            meta = os.fstat(flux.fileno())
            if not stat.S_ISREG(meta.st_mode) or not 0 < meta.st_size <= maximum:
                _refuser()
            _proprietaire_et_permissions(path, meta)
            data = flux.read(maximum + 1)
    except OCRProfilErreur:
        raise
    except (OSError, ValueError, RuntimeError):
        _refuser()
    if len(data) != meta.st_size or len(data) > maximum:
        _refuser()
    return data


def _entrees_reelles(root: Path) -> dict[str, os.stat_result]:
    result: dict[str, os.stat_result] = {}
    try:
        pending = [root]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    relative = path.relative_to(root).as_posix()
                    if len(result) >= _ARBRE_ENTREES_MAX or len(PurePosixPath(relative).parts) > _ARBRE_PROFONDEUR_MAX:
                        _refuser()
                    meta = _stat(path)
                    _proprietaire_et_permissions(path, meta)
                    if stat.S_ISDIR(meta.st_mode):
                        result[relative] = meta
                        pending.append(path)
                    elif stat.S_ISREG(meta.st_mode):
                        result[relative] = meta
                    else:
                        _refuser()
    except OCRProfilErreur:
        raise
    except (OSError, ValueError, RuntimeError):
        _refuser()
    return result


def _nom_wheel(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name:
        _refuser()
    posix = PurePosixPath(name)
    if posix.is_absolute() or ".." in posix.parts or "." in posix.parts or posix.as_posix() != name:
        _refuser()
    return name


def _record_digest(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256="):
        _refuser()
    encoded = value[7:]
    if not encoded or not re.fullmatch(r"[A-Za-z0-9_-]{43}", encoded):
        _refuser()
    try:
        digest = base64.b64decode(encoded + "=", altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error):
        _refuser()
    if len(digest) != 32:
        _refuser()
    return digest.hex()


def _wheel_packages(wheel_bytes: bytes) -> dict[str, tuple[bytes, str]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(wheel_bytes), "r")
    except (OSError, ValueError, zipfile.BadZipFile):
        _refuser()
    with archive:
        infos = archive.infolist()
        names = [_nom_wheel(item.filename) for item in infos]
        if (not infos or len(infos) > _WHEEL_ENTREES_MAX or len(set(names)) != len(names)
                or any(item.is_dir() or item.flag_bits & 1
                       or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                       or stat.S_IFMT(item.external_attr >> 16) not in (0, stat.S_IFREG)
                       for item in infos)):
            _refuser()
        if sum(item.file_size for item in infos) > _TOTAL_DECOMPRESSE_MAX:
            _refuser()
        if any(item.file_size > _MEMBRE_MAX for item in infos):
            _refuser()
        records = [name for name in names if _RECORD_PATH.fullmatch(name)]
        if len(records) != 1:
            _refuser()
        record_name = records[0]
        try:
            raw_record = archive.read(record_name)
            rows = list(csv.reader(io.StringIO(raw_record.decode("utf-8", "strict"), newline="")))
        except (OSError, ValueError, UnicodeDecodeError, csv.Error, zipfile.BadZipFile, RuntimeError):
            _refuser()
        record: dict[str, tuple[str, str]] = {}
        for row in rows:
            if len(row) != 3:
                _refuser()
            name = _nom_wheel(row[0])
            if name in record:
                _refuser()
            record[name] = (row[1], row[2])
        if set(record) != set(names):
            _refuser()
        if record.get(record_name) != ("", ""):
            _refuser()
        packages: dict[str, tuple[bytes, str]] = {}
        for item, name in zip(infos, names, strict=True):
            if name == record_name:
                continue
            digest_record, size_record = record[name]
            if not _TAILLE_DECIMALE.fullmatch(size_record):
                _refuser()
            if int(size_record) != item.file_size or not digest_record:
                _refuser()
            expected_sha = _record_digest(digest_record)
            try:
                content = archive.read(item)
            except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
                _refuser()
            actual_sha = hashlib.sha256(content).hexdigest()
            if len(content) != item.file_size or actual_sha != expected_sha:
                _refuser()
            package = next((root for root in _PACKAGES if name.startswith(root + "/")), None)
            if package is not None:
                packages[name] = (content, actual_sha)
        expected_prefixes = {root for name in packages for root in _PACKAGES if name.startswith(root + "/")}
        if expected_prefixes != set(_PACKAGES):
            _refuser()
    return packages


def valider_bundle(bundle: Path) -> dict[str, str]:
    """Valide un bundle déjà installé, sans extraction, import ni modification.

    Retourne uniquement les membres extraits sous `rasterizer/` et leurs SHA-256.
    Le worker doit refaire les vérifications à l'intérieur de sa sandbox.
    """
    try:
        _verifier_chaine(bundle)
        root_entries = _entrees_reelles(bundle)
        root_directories = {
            path for path, meta in root_entries.items()
            if "/" not in path and stat.S_ISDIR(meta.st_mode)
        }
        root_files = {
            path for path, meta in root_entries.items()
            if "/" not in path and stat.S_ISREG(meta.st_mode)
        }
        if root_directories != {"rasterizer", "tessdata"} or root_files != {"wheel.whl"}:
            _refuser()
        raster_root = bundle / "rasterizer"
        tessdata_root = bundle / "tessdata"
        raster_entries = _entrees_reelles(raster_root)
        tess_entries = _entrees_reelles(tessdata_root)
        if set(tess_entries) != {"fra.traineddata"}:
            _refuser()
        wheel_bytes = _lire_fichier(bundle / "wheel.whl", _WHEEL_MAX)
        if hashlib.sha256(wheel_bytes).hexdigest() != WHEEL_SHA256:
            _refuser()
        model = _lire_fichier(tessdata_root / "fra.traineddata", _MODELE_MAX)
        if hashlib.sha256(model).hexdigest() != MODELE_SHA256:
            _refuser()
        packages = _wheel_packages(wheel_bytes)
        expected_files = {name for name in packages}
        actual_files = {name for name, meta in raster_entries.items() if stat.S_ISREG(meta.st_mode)}
        actual_directories = {name for name, meta in raster_entries.items() if stat.S_ISDIR(meta.st_mode)}
        expected_directories: set[str] = set()
        for name in expected_files:
            parts = PurePosixPath(name).parts[:-1]
            for count in range(1, len(parts) + 1):
                expected_directories.add(PurePosixPath(*parts[:count]).as_posix())
        if actual_files != expected_files or actual_directories != expected_directories:
            _refuser()
        required = {
            "pypdfium2/__init__.py", "pypdfium2/version.json", "pypdfium2_raw/__init__.py",
            "pypdfium2_raw/version.json", "pypdfium2_raw/libpdfium.so", "pypdfium2_cfg/__init__.py",
        }
        if not required.issubset(expected_files):
            _refuser()
        if packages["pypdfium2_raw/libpdfium.so"][1] != PDFIUM_SHA256:
            _refuser()
        output: dict[str, str] = {}
        for name in sorted(expected_files):
            content, digest = packages[name]
            installed = _lire_fichier(raster_root / name, _MEMBRE_MAX)
            if installed != content or hashlib.sha256(installed).hexdigest() != digest:
                _refuser()
            output["rasterizer/" + name] = digest
        return output
    except OCRProfilErreur:
        raise
    except Exception:
        _refuser()
    raise AssertionError("inatteignable")
