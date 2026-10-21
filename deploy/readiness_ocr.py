"""Sonde OCR opérateur explicite; aucune donnée métier ou écriture n'est lue."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from opsys.console.ocr_configuration import chemin_bundle
from opsys.ocr_runtime import contexte_ocr, extraire_candidat

_FIXTURE = Path(__file__).with_name("fixtures") / "ocr-image-fictive.pdf"
_FIXTURE_SHA256 = "a8487a4255aac8d40d5f88d635045a14a4f80a1b535757a53f610fdca3348d22"
_FIXTURE_BYTES = 12_194
_FIXTURE_LOT_ID = "12345678-1234-4234-8234-123456789abc"
_TOKENS_ATTENDUS = ("FACTURE", "FICTIVE", "TEST")
_DIMENSIONS_ATTENDUES = (1275, 1651)


def _lire_fixture() -> bytes:
    descriptor = os.open(
        _FIXTURE, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != _FIXTURE_BYTES:
            raise ValueError("fixture invalide")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            source = stream.read(_FIXTURE_BYTES + 1)
        if len(source) != _FIXTURE_BYTES or hashlib.sha256(source).hexdigest() != _FIXTURE_SHA256:
            raise ValueError("fixture invalide")
        return source
    finally:
        os.close(descriptor)


def _candidat_attendu(candidat: Any, source: bytes) -> bool:
    if not isinstance(candidat, dict) or set(candidat) != {
        "schema_version", "genre", "statut", "lot_id", "source_sha256", "revision_source",
        "configuration_sha256", "profil", "page",
    }:
        return False
    page = candidat.get("page")
    if not isinstance(page, dict) or set(page) != {"numero", "largeur_px", "hauteur_px", "tokens"}:
        return False
    contexte = contexte_ocr(source, lot_id=_FIXTURE_LOT_ID, revision_source=1)
    profil_attendu = {
        "rasteriseur": contexte.rasteriseur,
        "moteur": contexte.moteur,
        "leptonica": contexte.leptonica,
        "pdfium_sha256": contexte.pdfium_sha256,
        "modele_sha256": contexte.modele_sha256,
        "langue": "fra",
    }
    tokens = page.get("tokens")
    if not isinstance(tokens, list) or any(not isinstance(token, dict) for token in tokens):
        return False
    mots = tuple(token.get("texte") for token in tokens)
    return (
        type(candidat.get("schema_version")) is int and candidat["schema_version"] == 1
        and candidat.get("genre") == "m5.ocr_scan_candidat"
        and candidat.get("statut") == "CANDIDAT_A_REVOIR"
        and candidat.get("lot_id") == _FIXTURE_LOT_ID
        and candidat.get("source_sha256") == hashlib.sha256(source).hexdigest()
        and type(candidat.get("revision_source")) is int and candidat["revision_source"] == 1
        and candidat.get("configuration_sha256") == contexte.configuration_sha256
        and candidat.get("profil") == profil_attendu
        and type(page.get("numero")) is int and page["numero"] == 1
        and type(page.get("largeur_px")) is int and page["largeur_px"] == _DIMENSIONS_ATTENDUES[0]
        and type(page.get("hauteur_px")) is int and page["hauteur_px"] == _DIMENSIONS_ATTENDUES[1]
        and mots == _TOKENS_ATTENDUS
    )


def _usage() -> int:
    print("usage: readiness_ocr.py --ocr-only", file=sys.stderr)
    return 2


def _indisponible() -> int:
    print("not ready OCR: profil, dépendance ou isolation indisponible", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    """Retourne 0 prêt, 3 opt-in absent, 1 refus fermé ou 2 invocation invalide."""
    arguments = sys.argv[1:] if argv is None else argv
    if not isinstance(arguments, Sequence) or isinstance(arguments, (str, bytes)) or list(arguments) != ["--ocr-only"]:
        return _usage()
    try:
        choix = chemin_bundle(os.environ if environ is None else environ)
    except (OSError, ValueError):
        return _indisponible()
    if choix is None:
        print("not ready OCR: non activé (configuration opérateur absente)", file=sys.stderr)
        return 3
    try:
        source = _lire_fixture()
        candidat = extraire_candidat(
            source, lot_id=_FIXTURE_LOT_ID, revision_source=1, bundle=choix,
        )
        if not _candidat_attendu(candidat, source):
            return _indisponible()
    except Exception:  # noqa: BLE001 - frontière CLI: toute panne reste un refus générique.
        return _indisponible()
    print("ready OCR: fixture image-only confinée et profil vérifiés")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
