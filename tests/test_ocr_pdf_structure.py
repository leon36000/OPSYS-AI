"""Classification structurelle conservative des PDF de scans fictifs."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NullObject,
    NumberObject,
)

from opsys.ocr_pdf_structure import classer_page_image

FICTIF = True


def _image(writer: PdfWriter, width: int = 1275, height: int = 1650, filter_name="/FlateDecode") -> object:
    image = DecodedStreamObject()
    # Payload fictif minimal : le classificateur valide la structure, il ne décode pas l'image.
    image.set_data(b"\xff\x00" * 8)
    if filter_name == "/FlateDecode":
        image = image.flate_encode()
    image.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(width),
        NameObject("/Height"): NumberObject(height),
        NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
        NameObject("/BitsPerComponent"): NumberObject(8),
    })
    if filter_name != "/FlateDecode":
        image[NameObject("/Filter")] = NameObject(filter_name)
    return writer._add_object(image)


def _pdf_image_seule(*, width_pt=612, height_pt=792, image_width=1275, image_height=1650,
                     corps=None, pages=1) -> bytes:
    writer = PdfWriter()
    image = _image(writer, image_width, image_height)
    for _ in range(pages):
        page = writer.add_blank_page(width=width_pt, height=height_pt)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image}),
        })
        stream = DecodedStreamObject()
        stream.set_data(corps or f"q {width_pt} 0 0 {height_pt} 0 0 cm /Im0 Do Q".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    sortie = io.BytesIO()
    writer.write(sortie)
    return sortie.getvalue()


def _lecteur(source: bytes):
    return PdfReader(io.BytesIO(source), strict=True)


def test_image_unique_pleine_page_est_candidat_sans_texte_ni_correction():
    verdict = classer_page_image(_lecteur(_pdf_image_seule()))

    assert verdict.code == "IMAGE_SEULE_CANDIDATE"
    assert verdict.page == 1
    assert verdict.largeur_pt == 612
    assert verdict.hauteur_pt == 792
    assert verdict.largeur_px_150dpi == 1275
    assert verdict.hauteur_px_150dpi == 1651
    assert not hasattr(verdict, "texte")
    with pytest.raises(AttributeError):
        verdict.code = "AUTRE"  # type: ignore[misc]


@pytest.mark.parametrize("corps", [
    b"q 612 0 0 792 0 0 cm /Im0 Do Q BT /F1 12 Tf (hidden) Tj ET",
    b"q 612 0 0 792 0 0 cm /Im0 Do Q 0 0 10 10 re f",
    b"q 612 0 0 792 0 0 cm /Im0 Do /Im0 Do Q",
    b"q 612 0 0 792 0 0 cm /Unknown Do Q",
    b"q 612 0 0 792 0 0 cm /Im0 Do",
], ids=["texte-overlay", "dessin-overlay", "image-reutilisee", "ressource-inconnue", "pile-q-incomplete"])
def test_contenu_overlay_repetition_ou_grammaire_incomplete_refuse(corps):
    verdict = classer_page_image(_lecteur(_pdf_image_seule(corps=corps)))

    assert verdict.code != "IMAGE_SEULE_CANDIDATE"


@pytest.mark.parametrize("type_modification", [
    "texte", "annotation", "rotation", "crop", "action", "formulaire", "transparence",
    "rotation_bool", "rotation_null", "rotation_float", "root_extra", "page_extra",
])
def test_structures_non_image_seule_refusees(type_modification):
    writer = PdfWriter()
    image = _image(writer)
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image}),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"q 612 0 0 792 0 0 cm /Im0 Do Q")
    page[NameObject("/Contents")] = writer._add_object(stream)
    if type_modification == "texte":
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 12 Tf 10 10 Td (hidden) Tj ET")
        page[NameObject("/Contents")] = ArrayObject([page["/Contents"], writer._add_object(content)])
    elif type_modification == "annotation":
        page[NameObject("/Annots")] = ArrayObject([])
    elif type_modification == "rotation":
        page[NameObject("/Rotate")] = NumberObject(90)
    elif type_modification == "crop":
        page[NameObject("/CropBox")] = ArrayObject([FloatObject(0), FloatObject(0), FloatObject(600), FloatObject(792)])
    elif type_modification == "action":
        writer._root_object[NameObject("/OpenAction")] = DictionaryObject()
    elif type_modification == "formulaire":
        writer._root_object[NameObject("/AcroForm")] = DictionaryObject()
    elif type_modification == "transparence":
        resources = page["/Resources"]
        resources[NameObject("/ExtGState")] = DictionaryObject({NameObject("/GS0"): DictionaryObject({
            NameObject("/ca"): FloatObject(0.5),
        })})
    elif type_modification == "rotation_bool":
        page[NameObject("/Rotate")] = BooleanObject(False)
    elif type_modification == "rotation_null":
        page[NameObject("/Rotate")] = NullObject()
    elif type_modification == "rotation_float":
        page[NameObject("/Rotate")] = FloatObject(0)
    elif type_modification == "root_extra":
        writer._root_object[NameObject("/ViewerPreferences")] = DictionaryObject()
    elif type_modification == "page_extra":
        page[NameObject("/Metadata")] = writer._add_object(DecodedStreamObject())
    sortie = io.BytesIO()
    writer.write(sortie)

    verdict = classer_page_image(_lecteur(sortie.getvalue()))

    assert verdict.code != "IMAGE_SEULE_CANDIDATE"


@pytest.mark.parametrize("width_pt,height_pt", [(0, 792), (-1, 792), (612, 0), (100_000, 100_000), (2_100, 100)])
def test_geometrie_absente_non_positive_ou_hors_borne_refuse(width_pt, height_pt):
    verdict = classer_page_image(_lecteur(_pdf_image_seule(width_pt=width_pt, height_pt=height_pt)))

    assert verdict.code != "IMAGE_SEULE_CANDIDATE"


def test_image_partielle_hors_page_refuse_et_dimensions_source_sont_declarees():
    partial = _pdf_image_seule(corps=b"q 300 0 0 792 0 0 cm /Im0 Do Q")
    small_image = _pdf_image_seule(image_width=1274, image_height=1650)

    assert classer_page_image(_lecteur(partial)).code != "IMAGE_SEULE_CANDIDATE"
    # DPI du raster cible ne décrit pas la résolution native de l'image incorporée.
    assert classer_page_image(_lecteur(small_image)).code == "IMAGE_SEULE_CANDIDATE"


def test_filtre_non_epingle_refuse():
    writer = PdfWriter()
    image = _image(writer, filter_name="/JBIG2Decode")
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image}),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"q 612 0 0 792 0 0 cm /Im0 Do Q")
    page[NameObject("/Contents")] = writer._add_object(stream)
    sortie = io.BytesIO()
    writer.write(sortie)

    assert classer_page_image(_lecteur(sortie.getvalue())).code != "IMAGE_SEULE_CANDIDATE"


@pytest.mark.parametrize("modification", [
    "mask", "smask", "couleur", "filtre_chain", "dimensions_bool", "dimensions_trop_grandes",
])
def test_proprietes_image_non_epinglees_refusees(modification):
    writer = PdfWriter()
    image = _image(writer, width=4097 if modification == "dimensions_trop_grandes" else 1275).get_object()
    if modification == "mask":
        image[NameObject("/Mask")] = ArrayObject([NumberObject(0)] * 6)
    elif modification == "smask":
        image[NameObject("/SMask")] = _image(writer, 1275, 1650)
    elif modification == "couleur":
        image[NameObject("/ColorSpace")] = NameObject("/DeviceN")
    elif modification == "filtre_chain":
        image[NameObject("/Filter")] = ArrayObject([NameObject("/FlateDecode"), NameObject("/DCTDecode")])
    elif modification == "dimensions_bool":
        image[NameObject("/Width")] = BooleanObject(True)
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image}),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"q 612 0 0 792 0 0 cm /Im0 Do Q")
    page[NameObject("/Contents")] = writer._add_object(stream)
    sortie = io.BytesIO()
    writer.write(sortie)

    assert classer_page_image(_lecteur(sortie.getvalue())).code != "IMAGE_SEULE_CANDIDATE"


def test_multipage_refuse_meme_si_chaque_page_a_une_image():
    verdict = classer_page_image(_lecteur(_pdf_image_seule(pages=2)))

    assert verdict.code != "IMAGE_SEULE_CANDIDATE"


def test_ressource_image_declares_inutilisee_refuse():
    writer = PdfWriter()
    image0 = _image(writer)
    image1 = _image(writer)
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image0, NameObject("/Im1"): image1}),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"q 612 0 0 792 0 0 cm /Im0 Do Q")
    page[NameObject("/Contents")] = writer._add_object(stream)
    sortie = io.BytesIO()
    writer.write(sortie)

    assert classer_page_image(_lecteur(sortie.getvalue())).code != "IMAGE_SEULE_CANDIDATE"


def test_grammaire_depasse_borne_operations_refuse():
    many_ops = b"q Q " * 65 + b"q 612 0 0 792 0 0 cm /Im0 Do Q"

    assert classer_page_image(_lecteur(_pdf_image_seule(corps=many_ops))).code != "IMAGE_SEULE_CANDIDATE"
