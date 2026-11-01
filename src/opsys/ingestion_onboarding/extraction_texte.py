"""Étape « texte » : le texte (ou le tableau) d'un document, en RÉUTILISANT les extracteurs existants du dépôt.

- PDF né numérique : le worker natif isolé de `opsys.fusion_pdf` (pypdf dans bubblewrap, sans réseau, bornes kernel) ;
  le processus principal ne parse jamais le PDF.
- PDF scanné (page image, refus natif `PDF_IMAGE_OU_MIXTE` ou `PDF_SANS_TEXTE`) : l'OCR local de `opsys.ocr_runtime`
  (Tesseract dans bubblewrap) SI le bundle OCR est configuré (`OPSYS_OCR_BUNDLE`, même réglage que la console) ;
  sinon `REJ-ING-OCR-INDISPONIBLE`, jamais un autre moteur à sa place.
- Image PNG/JPEG : `REJ-ING-IMAGE-NON-TRAITEE` (l'OCR local ne prend que des PDF ; aucun VLM d'image n'est raccordé
  dans cette tranche).
- Texte : UTF-8 (avec ou sans BOM), UTF-16 avec BOM, Windows-1252.
- CSV et `.xlsx` : le lecteur de tableaux de l'import QuickBooks de M5 (`import_quickbooks._sources`, bibliothèque
  standard seulement : séparateurs , ; tabulation, encodages ci-dessus, première feuille du classeur).

Une panne d'isolation ou un délai dépassé est REPRENABLE (la tâche réessaie plus tard, puis file morte) ; un refus du
contenu est DÉFINITIF (le document reste au lot, non traité, avec son code).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .codes import EchecEtape

ExtracteurPDF = Callable[[bytes], dict[str, Any]]
ExtracteurOCR = Callable[[bytes, str], dict[str, Any]]

_PDF_VERS_OCR = frozenset({"PDF_IMAGE_OU_MIXTE", "PDF_SANS_TEXTE"})
_OCR_TEMPORAIRES = frozenset({"OCR_ISOLATION_INDISPONIBLE", "OCR_LIMITES_INDISPONIBLES", "OCR_RUNTIME_INDISPONIBLE"})


def extracteur_pdf_isole(octets: bytes) -> dict[str, Any]:
    """Le worker natif du pilote PDF, tel quel : `{"ok": True, "resultat": …}` ou `{"ok": False, "code": …}`."""
    from .. import fusion_pdf

    try:
        return fusion_pdf._extraire_isole(octets)
    except fusion_pdf.FusionPDFErreur as exc:
        raise EchecEtape("REJ-ING-ISOLATION-INDISPONIBLE", f"extracteur PDF isolé indisponible ({exc.code}) : "
                         "Linux, bubblewrap et l'extra ingestion-pdf sont requis", reprenable=True) from None


def extracteur_ocr_local(octets: bytes, document_id: str) -> dict[str, Any]:
    """L'OCR local isolé (`ocr_runtime.extraire_candidat`) si le bundle est configuré ; le candidat validé sinon un
    refus typé."""
    from .. import ocr_runtime
    from ..console.ocr_configuration import chemin_bundle

    try:
        bundle = chemin_bundle(os.environ)
    except ValueError:
        bundle = None
    if bundle is None:
        raise EchecEtape("REJ-ING-OCR-INDISPONIBLE", "PDF scanné : l'OCR local n'est pas configuré "
                         "(OPSYS_OCR_BUNDLE) ; aucun autre moteur n'est utilisé à sa place")
    try:
        return ocr_runtime.extraire_candidat(octets, lot_id=str(uuid.UUID(hex=document_id)), revision_source=1,
                                             bundle=Path(bundle))
    except ocr_runtime.OCRRuntimeErreur as exc:
        if exc.code in _OCR_TEMPORAIRES:
            raise EchecEtape("REJ-ING-ISOLATION-INDISPONIBLE", f"OCR isolé indisponible ({exc.code})",
                             reprenable=True) from None
        raise EchecEtape("REJ-ING-OCR-REFUSE", f"OCR refusé ({exc.code})") from None


def _decoder_texte(octets: bytes) -> str:
    essais = ("utf-16",) if octets.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "cp1252")
    for codec in essais:
        try:
            texte = octets.decode(codec)
        except UnicodeDecodeError:
            continue
        if "\x00" not in texte:
            return texte.replace("\r\n", "\n").replace("\r", "\n")
    raise EchecEtape("REJ-ING-TEXTE-ILLISIBLE", "ni UTF-8, ni UTF-16 avec BOM, ni Windows-1252")


def _texte_ocr(candidat: dict[str, Any]) -> list[dict[str, Any]]:
    pages = []
    for page in candidat.get("pages", []):
        pages.append({"numero": page["numero"], "texte": " ".join(t["texte"] for t in page["tokens"])})
    return pages


def extraire(type_detecte: str, octets: bytes, *, document_id: str, extracteur_pdf: ExtracteurPDF | None = None,
             extracteur_ocr: ExtracteurOCR | None = None) -> dict[str, Any]:
    """Le résultat de l'étape, sérialisable en JSON : `{"genre": "texte", "source", "pages": [{numero, texte}]}` ou
    `{"genre": "tableau", "format", "encodage", "candidats": [{separateur, lignes}]}`. Lève `EchecEtape`."""
    if type_detecte == "txt":
        return {"genre": "texte", "source": "texte", "pages": [{"numero": 1, "texte": _decoder_texte(octets)}]}
    if type_detecte == "pdf":
        reponse = (extracteur_pdf or extracteur_pdf_isole)(octets)
        if reponse.get("ok") is True:
            pages = [{"numero": p["numero"], "texte": "\n".join(f["texte"] for f in p["fragments"])}
                     for p in reponse["resultat"]["pages"]]
            return {"genre": "texte", "source": "pdf_natif", "pages": pages}
        code = reponse.get("code")
        if code in _PDF_VERS_OCR:
            candidat = (extracteur_ocr or extracteur_ocr_local)(octets, document_id)
            return {"genre": "texte", "source": "ocr", "pages": _texte_ocr(candidat)}
        from .. import fusion_pdf

        if code in fusion_pdf._TEMPORAIRES:
            raise EchecEtape("REJ-ING-ISOLATION-INDISPONIBLE", f"extracteur PDF : {code}", reprenable=True)
        raise EchecEtape("REJ-ING-PDF-REFUSE", f"PDF refusé par le parseur natif ({code})")
    if type_detecte in ("png", "jpeg"):
        raise EchecEtape("REJ-ING-IMAGE-NON-TRAITEE", "image : l'OCR local ne lit que des PDF et aucun VLM d'image "
                         "n'est raccordé dans cette tranche ; déposer la facture en PDF")
    if type_detecte in ("csv", "xlsx"):
        from m5_financecore import import_quickbooks

        candidats, lecture, refus = import_quickbooks._sources(octets)
        if refus is not None:
            raise EchecEtape("REJ-ING-TABLEAU-ILLISIBLE", f"tableau illisible ({refus['code']})")
        return {"genre": "tableau", "format": lecture["format"], "encodage": lecture.get("encodage"),
                "candidats": [{"separateur": separateur, "lignes": lignes} for separateur, lignes in candidats]}
    raise EchecEtape("REJ-ING-TYPE-NON-ACCEPTE", f"type {type_detecte!r} hors de la liste fermée")


__all__ = ["ExtracteurOCR", "ExtracteurPDF", "extracteur_ocr_local", "extracteur_pdf_isole", "extraire"]
