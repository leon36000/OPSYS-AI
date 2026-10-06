"""Lanceur OCR local opt-in. Aucun parser sur l'hôte, stockage ou action M5."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from . import fusion_pdf
from .ocr_candidat import ContexteOCR, OCRContratErreur, decoder_candidat
from .ocr_profil import MODELE_SHA256, PDFIUM_SHA256, OCRProfilErreur, valider_bundle
from .ocr_worker import CONFIGURATION_SHA256

_WORKER = Path(__file__).with_name("ocr_worker.py")
_REFUS = frozenset({
    "OCR_STRUCTURE_REFUSEE", "OCR_PROFIL_INDISPONIBLE", "OCR_RUNTIME_INDISPONIBLE",
    "OCR_SOURCE_INVALIDE", "OCR_RESULTAT_INVALIDE", "OCR_LIMITES_INDISPONIBLES",
})


class OCRRuntimeErreur(ValueError):
    """Code fermé, sans contenu reconnu ni chemin du serveur."""

    def __init__(self, code: str):
        self.code = code
        super().__init__("préparation OCR refusée ou indisponible")


def contexte_ocr(source: bytes, *, lot_id: str, revision_source: int) -> ContexteOCR:
    if (type(source) is not bytes or not 1 <= len(source) <= fusion_pdf.SOURCE_MAX
            or not source.startswith(b"%PDF-") or not source.rstrip(b" \r\n\t").endswith(b"%%EOF")):
        raise OCRRuntimeErreur("OCR_SOURCE_INVALIDE")
    try:
        return ContexteOCR(
            lot_id=lot_id, revision_source=revision_source, source_sha256=hashlib.sha256(source).hexdigest(),
            configuration_sha256=CONFIGURATION_SHA256, rasteriseur="pypdfium2-5.13.0",
            moteur="tesseract-5.5.0", leptonica="leptonica-1.84.1",
            pdfium_sha256=PDFIUM_SHA256, modele_sha256=MODELE_SHA256,
        )
    except OCRContratErreur:
        raise OCRRuntimeErreur("OCR_CONTEXTE_INVALIDE") from None


def _commande_ocr(bundle: Path) -> list[str]:
    try:
        fichiers = valider_bundle(bundle)
        commande = fusion_pdf._commande_isolee()
        commande[commande.index(str(fusion_pdf._CHEMIN_WORKER.resolve()))] = str(_WORKER.resolve(strict=True))
        montages = []
        for nom in ("wheel.whl", "tessdata/fra.traineddata", *sorted(fichiers)):
            montages.extend(["--ro-bind", str(bundle / nom), "/bundle/" + nom])
        for source, cible in (
            (fusion_pdf._CHEMIN_WORKER, "/policy.py"),
            (Path(__file__).with_name("ocr_profil.py"), "/profile.py"),
            (Path(__file__).with_name("ocr_pdf_structure.py"), "/structure.py"),
            (Path(__file__).with_name("ocr_candidat.py"), "/contract.py"),
        ):
            montages.extend(["--ro-bind", str(source.resolve(strict=True)), cible])
        position = commande.index("--proc")
        commande[position:position] = montages
        return commande
    except OCRProfilErreur:
        raise OCRRuntimeErreur("OCR_PROFIL_INDISPONIBLE") from None
    except (OSError, ValueError, fusion_pdf.FusionPDFErreur):
        raise OCRRuntimeErreur("OCR_ISOLATION_INDISPONIBLE") from None


def extraire_candidat(source: bytes, *, lot_id: str, revision_source: int, bundle: Path) -> dict[str, Any]:
    contexte = contexte_ocr(source, lot_id=lot_id, revision_source=revision_source)
    commande = _commande_ocr(bundle) + [lot_id, str(revision_source), contexte.source_sha256]
    try:
        brut = fusion_pdf._executer_borne(commande, source)
    except fusion_pdf.FusionPDFErreur:
        raise OCRRuntimeErreur("OCR_ISOLATION_INDISPONIBLE") from None
    try:
        if type(brut) is not bytes or not 1 <= len(brut) <= 262_144:
            raise OCRRuntimeErreur("OCR_RESULTAT_INVALIDE")
        valeur = fusion_pdf._objet_json(brut)
        if (isinstance(valeur, dict) and set(valeur) == {"ok", "code"} and valeur["ok"] is False
                and isinstance(valeur["code"], str) and valeur["code"] in _REFUS):
            raise OCRRuntimeErreur(valeur["code"])
        return decoder_candidat(brut, contexte=contexte)
    except (OCRContratErreur, fusion_pdf.FusionPDFErreur):
        raise OCRRuntimeErreur("OCR_RESULTAT_INVALIDE") from None
