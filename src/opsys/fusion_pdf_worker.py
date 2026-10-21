"""Worker autonome : exécuté uniquement dans bubblewrap, aucun import OPSYS."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import resource
import sys
import warnings
from importlib.metadata import PackageNotFoundError, version

SOURCE_MAX = 1_048_576
PAGES_MAX = 20
CONTENU_PAGE_MAX = 2_097_152
CONTENU_TOTAL_MAX = 8_388_608
TEXTE_MAX = 262_144
SORTIE_MAX = 524_288
EXTRACTEUR = "pypdf-6.19.0/pdf-natif-1"
CONFIGURATION = (
    "pdf-natif-1;linux-bwrap;source=1048576;pages=20;decoded-page=2097152;"
    "decoded-total=8388608;text=262144;stdout=524288;as=536870912;cpu=10;wall=15"
)


class RefusPDF(Exception):
    def __init__(self, code: str):
        self.code = code


class Avertissements(logging.Handler):
    """Conserve seulement le signal : les messages peuvent contenir du texte privé."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.detecte = False

    def emit(self, record):
        self.detecte = True


def _limites() -> None:
    for nom, plafond in (
        (resource.RLIMIT_AS, 536_870_912), (resource.RLIMIT_CPU, 10),
        (resource.RLIMIT_CORE, 0), (resource.RLIMIT_FSIZE, 0), (resource.RLIMIT_NOFILE, 64),
    ):
        souple, dur = resource.getrlimit(nom)
        dur = plafond if dur == resource.RLIM_INFINITY else min(dur, plafond)
        souple = plafond if souple == resource.RLIM_INFINITY else min(souple, plafond)
        resource.setrlimit(nom, (min(souple, dur), dur))


def _extraire(source: bytes) -> dict:
    from pypdf import PdfReader, overwrite_configuration
    from pypdf.errors import LimitReachedError
    from pypdf.generic import ContentStream

    if not source.rstrip(b" \r\n\t").endswith(b"%%EOF"):
        raise RefusPDF("PDF_MALFORME")
    overwrite_configuration(
        maximum_declared_stream_length=CONTENU_PAGE_MAX,
        array_based_stream_maximum_output_length=CONTENU_PAGE_MAX,
        zlib_maximum_output_length=CONTENU_PAGE_MAX,
        lzw_maximum_output_length=CONTENU_PAGE_MAX,
        run_length_maximum_output_length=CONTENU_PAGE_MAX,
        jbig2_maximum_output_length=CONTENU_PAGE_MAX,
        image_maximum_buffer_size=CONTENU_PAGE_MAX,
        xmp_maximum_input_length=CONTENU_PAGE_MAX,
        page_tree_maximum_entries=128, page_tree_maximum_depth=16,
        xform_maximum_invocations_per_extraction=128, jbig2dec_binary=None,
    )
    try:
        lecteur = PdfReader(io.BytesIO(source), strict=True)
        if lecteur.is_encrypted:
            raise RefusPDF("PDF_CHIFFRE")
        racine = lecteur.trailer["/Root"].get_object()
        noms = racine.get("/Names", {})
        noms = noms.get_object() if hasattr(noms, "get_object") else noms
        if any(cle in racine for cle in ("/OpenAction", "/AA", "/AcroForm")) or any(
            cle in noms for cle in ("/JavaScript", "/EmbeddedFiles")
        ):
            raise RefusPDF("PDF_ACTIF")
        if not 1 <= len(lecteur.pages) <= PAGES_MAX:
            raise RefusPDF("PDF_PAGES_BORNEES")

        contenu_total = 0
        texte_total = 0
        formes_vues: set[int] = set()

        def controler_stream(stream) -> None:
            nonlocal contenu_total
            if stream is None:
                return
            donnees = stream.get_data()
            contenu_total += len(donnees)
            if len(donnees) > CONTENU_PAGE_MAX or contenu_total > CONTENU_TOTAL_MAX:
                raise RefusPDF("PDF_CONTENU_BORNE")
            operations = stream if isinstance(stream, ContentStream) else ContentStream(stream, lecteur)
            for operandes, operateur in operations.operations:
                if operateur == b"INLINE IMAGE":
                    raise RefusPDF("PDF_IMAGE_OU_MIXTE")
                if operateur == b"Tr" and operandes != [0]:
                    raise RefusPDF("PDF_AMBIGU")

        def controler_ressources(ressources, profondeur: int = 0) -> None:
            if profondeur > 16:
                raise RefusPDF("PDF_AMBIGU")
            ressources = ressources.get_object() if hasattr(ressources, "get_object") else ressources
            if any(cle in ressources for cle in ("/Pattern", "/Shading")):
                raise RefusPDF("PDF_AMBIGU")
            objets = ressources.get("/XObject", {})
            objets = objets.get_object() if hasattr(objets, "get_object") else objets
            if len(objets) > 128:
                raise RefusPDF("PDF_CONTENU_BORNE")
            for reference in objets.values():
                objet = reference.get_object()
                if objet.get("/Subtype") == "/Image":
                    raise RefusPDF("PDF_IMAGE_OU_MIXTE")
                if objet.get("/Subtype") != "/Form":
                    raise RefusPDF("PDF_AMBIGU")
                identifiant = id(objet)
                if identifiant in formes_vues:
                    continue
                formes_vues.add(identifiant)
                if len(formes_vues) > 128:
                    raise RefusPDF("PDF_CONTENU_BORNE")
                controler_stream(objet)
                controler_ressources(objet.get("/Resources", {}), profondeur + 1)

        pages = []
        for numero, page in enumerate(lecteur.pages, 1):
            if page.get("/Rotate", 0) != 0 or "/AA" in page or page.get("/Annots"):
                raise RefusPDF("PDF_AMBIGU")
            controler_ressources(page.get("/Resources", {}))
            controler_stream(page.get_contents())
            texte = page.extract_text()
            if not texte.strip():
                raise RefusPDF("PDF_SANS_TEXTE")
            if "\ufffd" in texte or any(ord(c) < 32 and c not in "\n\r\t" for c in texte):
                raise RefusPDF("PDF_AMBIGU")
            texte_octets = texte.encode("utf-8")
            texte_total += len(texte_octets)
            if texte_total > TEXTE_MAX:
                raise RefusPDF("PDF_TEXTE_BORNE")
            pages.append({"numero": numero, "fragments": [{
                "id": f"p{numero}-f1", "texte": texte,
                "sha256": hashlib.sha256(texte_octets).hexdigest(),
            }]})
        return {
            "schema_version": 1, "source_sha256": hashlib.sha256(source).hexdigest(),
            "extracteur": EXTRACTEUR, "configuration_sha256": hashlib.sha256(CONFIGURATION.encode()).hexdigest(),
            "pages": pages,
        }
    except LimitReachedError as exc:
        raise RefusPDF("PDF_CONTENU_BORNE") from exc


def main() -> int:
    signal = Avertissements()
    logger = logging.getLogger("pypdf")
    logger.handlers = [signal]
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    with warnings.catch_warnings(record=True) as avertissements:
        warnings.simplefilter("always")
        try:
            _limites()  # Avant import du parseur, lecture et décompression.
        except (OSError, ValueError):
            reponse = {"ok": False, "code": "PDF_LIMITES_INDISPONIBLES"}
        else:
            try:
                if version("pypdf") != "6.19.0":
                    raise RefusPDF("PDF_DEPENDANCE_INDISPONIBLE")
                source = sys.stdin.buffer.read(SOURCE_MAX + 1)
                if not 1 <= len(source) <= SOURCE_MAX or not source.startswith(b"%PDF-"):
                    raise RefusPDF("PDF_SOURCE_BORNEE")
                reponse = {"ok": True, "resultat": _extraire(source)}
            except (ImportError, PackageNotFoundError):
                reponse = {"ok": False, "code": "PDF_DEPENDANCE_INDISPONIBLE"}
            except RefusPDF as exc:
                reponse = {"ok": False, "code": exc.code}
            except MemoryError:
                reponse = {"ok": False, "code": "PDF_MEMOIRE_BORNEE"}
            except Exception:
                reponse = {"ok": False, "code": "PDF_MALFORME"}
        if signal.detecte or avertissements:
            reponse = {"ok": False, "code": "PDF_AVERTISSEMENT"}
    sortie = json.dumps(reponse, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(sortie) > SORTIE_MAX:
        sortie = b'{"ok":false,"code":"PDF_SORTIE_BORNEE"}'
    sys.stdout.buffer.write(sortie)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
