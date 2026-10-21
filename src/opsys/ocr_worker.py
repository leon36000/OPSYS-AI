"""Worker autonome OCR. Lancer uniquement par ocr_runtime dans bubblewrap."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import logging
import math
import os
import selectors
import subprocess
import sys
import warnings
from contextlib import closing
from importlib.metadata import distribution, version
from pathlib import Path
from time import monotonic

TESSERACT_SHA256 = "74b76a5b994adcc18be362bf64ed5118082b2401d5d9a35242e92fc4c62e2b4b"
CONFIGURATION = (
    "ocr-scan-2;linux-x86_64-bwrap;pypdf=6.19.0;pillow=13.0.0;"
    "wheel=81df25c1ab4c13ff773102d3cbea1967511d079123b067fc077bd0c4d57d91d8;"
    "pdfium=224f8ece41f7e35891f11c10073b7b7062d7a18e9ef870586162a85c46130f7d;"
    "fra=ced037562e8c80c13122dece28dd477d399af80911a28791a66a63ac1e3445ca;"
    "tesseract=5.5.0;leptonica=1.84.1;binary=" + TESSERACT_SHA256 + ";"
    "source=1048576;pages=1;dpi=150;axis=4096;pixels=4000000;png=524288;"
    "tsv=262144;json=262144;stderr=8192;as=536870912;cpu=10;wall=15;child-wall=8;"
    "lang=fra;psm=6;tesseract-dpi=150;threads=1;tessedit_create_tsv=1;structure=1"
)
CONFIGURATION_SHA256 = hashlib.sha256(CONFIGURATION.encode()).hexdigest()
SOURCE_MAX = 1_048_576
PNG_MAX = 524_288
TSV_MAX = 262_144


class RefusOCR(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__("OCR refusé")


class Avertissements(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.detecte = False

    def emit(self, record):
        self.detecte = True


def _charger(nom: str, chemin: str):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    if spec is None or spec.loader is None:
        raise RefusOCR("OCR_RUNTIME_INDISPONIBLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


def _pomper(commande: list[str], entree: bytes, plafond: int) -> bytes:
    """Lit stdout/stderr pendant l'écriture, sans deadlock des pipes."""
    fin = monotonic() + 8.0
    enfant = subprocess.Popen(
        commande, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False, close_fds=True,
        env={"OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1", "LANG": "C.UTF-8"},
    )
    curseur = 0
    sortie, erreurs = bytearray(), bytearray()
    selecteur = None
    try:
        selecteur = selectors.DefaultSelector()
        for canal, evenements, nature in (
            (enfant.stdin, selectors.EVENT_WRITE, "entree"),
            (enfant.stdout, selectors.EVENT_READ, "sortie"),
            (enfant.stderr, selectors.EVENT_READ, "erreurs"),
        ):
            os.set_blocking(canal.fileno(), False)
            selecteur.register(canal, evenements, nature)
        while selecteur.get_map():
            reste = fin - monotonic()
            if reste <= 0:
                raise RefusOCR("OCR_RUNTIME_INDISPONIBLE")
            for cle, _ in selecteur.select(min(reste, 0.1)):
                if cle.data == "entree":
                    try:
                        curseur += os.write(cle.fd, entree[curseur:curseur + 65_536])
                    except BrokenPipeError:
                        curseur = len(entree)
                    except BlockingIOError:
                        continue
                    if curseur == len(entree):
                        selecteur.unregister(cle.fileobj)
                        cle.fileobj.close()
                else:
                    try:
                        donnees = os.read(cle.fd, 16_384)
                    except BlockingIOError:
                        continue
                    if not donnees:
                        selecteur.unregister(cle.fileobj)
                        cle.fileobj.close()
                        continue
                    tampon = sortie if cle.data == "sortie" else erreurs
                    if len(tampon) + len(donnees) > (plafond if cle.data == "sortie" else 8_192):
                        raise RefusOCR("OCR_RESULTAT_INVALIDE")
                    tampon.extend(donnees)
        try:
            retour = enfant.wait(timeout=max(0.001, fin - monotonic()))
        except subprocess.TimeoutExpired:
            raise RefusOCR("OCR_RUNTIME_INDISPONIBLE") from None
        if retour != 0:
            raise RefusOCR("OCR_RUNTIME_INDISPONIBLE")
        if erreurs:
            raise RefusOCR("OCR_RESULTAT_INVALIDE")
        return bytes(sortie)
    finally:
        if selecteur is not None:
            selecteur.close()
        if enfant.poll() is None:
            enfant.kill()
        enfant.wait()
        for canal in (enfant.stdin, enfant.stdout, enfant.stderr):
            canal.close()


def _dependances(profil):
    if (sys.platform != "linux" or os.uname().machine != "x86_64"
            or version("pypdf") != "6.19.0" or version("Pillow") != "13.0.0"):
        raise RefusOCR("OCR_RUNTIME_INDISPONIBLE")
    binary = Path("/usr/bin/tesseract")
    with binary.open("rb") as fichier:
        brut = fichier.read(1_048_577)
    if len(brut) > 1_048_576 or hashlib.sha256(brut).hexdigest() != TESSERACT_SHA256:
        raise RefusOCR("OCR_RUNTIME_INDISPONIBLE")
    if not _pomper([str(binary), "--version"], b"", 8_192).startswith(
        b"tesseract 5.5.0\n leptonica-1.84.1\n"
    ):
        raise RefusOCR("OCR_RUNTIME_INDISPONIBLE")
    bundle = Path("/bundle")
    profil.valider_bundle(bundle)
    sys.path.insert(0, str(bundle / "rasterizer"))
    import pypdfium2
    import pypdfium2_cfg
    import pypdfium2_raw
    from pypdfium2_raw import bindings

    for module in (pypdfium2, pypdfium2_cfg, pypdfium2_raw):
        if Path(module.__file__).resolve() != bundle / "rasterizer" / module.__name__ / "__init__.py":
            raise RefusOCR("OCR_RUNTIME_INDISPONIBLE")
    if Path(bindings._libs["pdfium"]._name).resolve() != bundle / "rasterizer/pypdfium2_raw/libpdfium.so":
        raise RefusOCR("OCR_RUNTIME_INDISPONIBLE")
    return pypdfium2


def _parser():
    paquet = distribution("pypdf")
    if paquet.version != "6.19.0":
        raise RefusOCR("OCR_RUNTIME_INDISPONIBLE")
    import pypdf

    reader = sys.modules.get("pypdf._reader")
    if (pypdf.__version__ != "6.19.0"
            or Path(pypdf.__file__).resolve() != Path(paquet.locate_file("pypdf/__init__.py")).resolve()
            or pypdf.PdfReader.__module__ != "pypdf._reader" or reader is None
            or Path(reader.__file__).resolve() != Path(paquet.locate_file("pypdf/_reader.py")).resolve()):
        raise RefusOCR("OCR_RUNTIME_INDISPONIBLE")
    return pypdf


def _raster(source: bytes, verdict, pdfium) -> bytes:
    with closing(pdfium.PdfDocument(source)) as document:
        if len(document) != 1:
            raise RefusOCR("OCR_STRUCTURE_REFUSEE")
        with closing(document[0]) as page:
            dimensions = page.get_size()
            if any(not math.isfinite(n) for n in dimensions) or any(
                abs(a - b) > 0.000001 for a, b in zip(dimensions, (verdict.largeur_pt, verdict.hauteur_pt), strict=True)
            ):
                raise RefusOCR("OCR_STRUCTURE_REFUSEE")
            with closing(page.render(scale=150 / 72)) as bitmap:
                image = bitmap.to_pil()
                try:
                    if (image.width, image.height) != (verdict.largeur_px_150dpi, verdict.hauteur_px_150dpi):
                        raise RefusOCR("OCR_RESULTAT_INVALIDE")
                    sortie = io.BytesIO()
                    image.save(sortie, format="PNG")
                    png = sortie.getvalue()
                    if not 1 <= len(png) <= PNG_MAX:
                        raise RefusOCR("OCR_RESULTAT_INVALIDE")
                    return png
                finally:
                    image.close()


def _traiter(source: bytes, arguments: list[str]):
    if (len(arguments) != 3 or not 1 <= len(source) <= SOURCE_MAX or not source.startswith(b"%PDF-")
            or not source.rstrip(b" \r\n\t").endswith(b"%%EOF")):
        raise RefusOCR("OCR_SOURCE_INVALIDE")
    profil = _charger("ocr_profile_worker", "/profile.py")
    contrat = _charger("ocr_contract_worker", "/contract.py")
    structure = _charger("ocr_structure_worker", "/structure.py")
    contexte = contrat.ContexteOCR(
        lot_id=arguments[0], revision_source=int(arguments[1]), source_sha256=arguments[2],
        configuration_sha256=CONFIGURATION_SHA256, rasteriseur="pypdfium2-5.13.0",
        moteur="tesseract-5.5.0", leptonica="leptonica-1.84.1",
        pdfium_sha256=profil.PDFIUM_SHA256, modele_sha256=profil.MODELE_SHA256,
    )
    if hashlib.sha256(source).hexdigest() != contexte.source_sha256:
        raise RefusOCR("OCR_SOURCE_INVALIDE")
    pypdf = _parser()
    pypdf.overwrite_configuration(
        maximum_declared_stream_length=2_097_152, array_based_stream_maximum_output_length=2_097_152,
        zlib_maximum_output_length=2_097_152, lzw_maximum_output_length=2_097_152,
        run_length_maximum_output_length=2_097_152, jbig2_maximum_output_length=2_097_152,
        image_maximum_buffer_size=2_097_152, xmp_maximum_input_length=2_097_152,
        page_tree_maximum_entries=128, page_tree_maximum_depth=16,
        xform_maximum_invocations_per_extraction=128, jbig2dec_binary=None,
    )
    verdict = structure.classer_page_image(pypdf.PdfReader(io.BytesIO(source), strict=True))
    if verdict.code != "IMAGE_SEULE_CANDIDATE":
        raise RefusOCR("OCR_STRUCTURE_REFUSEE")
    try:
        pdfium = _dependances(profil)
    except profil.OCRProfilErreur:
        raise RefusOCR("OCR_PROFIL_INDISPONIBLE") from None
    png = _raster(source, verdict, pdfium)
    tsv = _pomper([
        "/usr/bin/tesseract", "stdin", "stdout", "--tessdata-dir", "/bundle/tessdata",
        "-l", "fra", "--psm", "6", "--dpi", "150", "-c", "tessedit_create_tsv=1",
    ], png, TSV_MAX)
    try:
        return contrat.candidat_depuis_tsv(
            tsv, contexte=contexte, largeur_px=verdict.largeur_px_150dpi, hauteur_px=verdict.hauteur_px_150dpi,
        )
    except contrat.OCRContratErreur:
        raise RefusOCR("OCR_RESULTAT_INVALIDE") from None


def main() -> int:
    signal = Avertissements()
    logger = logging.getLogger("pypdf")
    logger.handlers = [signal]
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    with warnings.catch_warnings(record=True) as avertissements:
        warnings.simplefilter("always")
        try:
            _charger("ocr_policy_worker", "/policy.py")._limites()
        except Exception:
            resultat = {"ok": False, "code": "OCR_LIMITES_INDISPONIBLES"}
        else:
            try:
                resultat = _traiter(sys.stdin.buffer.read(SOURCE_MAX + 1), sys.argv[1:])
            except RefusOCR as exc:
                resultat = {"ok": False, "code": exc.code}
            except Exception:
                resultat = {"ok": False, "code": "OCR_RUNTIME_INDISPONIBLE"}
        if signal.detecte or avertissements:
            resultat = {"ok": False, "code": "OCR_STRUCTURE_REFUSEE"}
    brut = json.dumps(resultat, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if len(brut) > 262_144:
        brut = b'{"ok":false,"code":"OCR_RESULTAT_INVALIDE"}'
    sys.stdout.buffer.write(brut)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
