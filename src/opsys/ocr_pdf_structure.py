"""Classification prudente d'une page PDF destinée au futur worker OCR.

Le lecteur doit déjà être créé et borné dans le worker isolé. Ce module ne
lit aucun fichier, ne rend pas d'image et n'interprète aucun texte.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

_CANDIDAT = "IMAGE_SEULE_CANDIDATE"
_REFUS = "PDF_STRUCTURE_REFUSEE"
_SOURCE_MAX = 1_048_576
_DIMENSION_MAX = 4_096
_IMAGE_PIXELS_MAX = 16_000_000
_RASTER_PIXELS_MAX = 4_000_000
_DPI = 150
_OPERATIONS_MAX = 128
_PROFONDEUR_Q_MAX = 16
_IMAGE_KEYS = frozenset({
    "/Type", "/Subtype", "/Width", "/Height", "/ColorSpace", "/BitsPerComponent",
    "/Filter", "/Length",
})
_ROOT_ACTIVE = frozenset({"/OpenAction", "/AA", "/AcroForm", "/Names", "/Perms", "/Collection"})
_PAGE_FORBIDDEN = frozenset({
    "/AA", "/Annots", "/CropBox", "/BleedBox", "/TrimBox", "/ArtBox",
    "/UserUnit", "/PieceInfo", "/StructParents", "/Group", "/Dur", "/Trans",
})
_PROCSET_ALLOWED = frozenset({"/PDF", "/ImageB", "/ImageC", "/ImageI"})
_FILTERS_ALLOWED = frozenset({"/DCTDecode", "/FlateDecode"})
_COULEURS_ALLOWED = frozenset({"/DeviceGray", "/DeviceRGB", "/DeviceCMYK"})
_ROOT_KEYS = frozenset({"/Type", "/Pages"})
_PAGE_KEYS = frozenset({"/Type", "/Parent", "/Resources", "/MediaBox", "/Contents", "/Rotate"})


@dataclass(frozen=True, slots=True)
class VerdictStructurePDF:
    """Verdict fermé et dimensions seulement; aucun contenu du document."""

    code: str
    page: int | None = None
    largeur_pt: float | None = None
    hauteur_pt: float | None = None
    largeur_px_150dpi: int | None = None
    hauteur_px_150dpi: int | None = None


def _objet(value: Any) -> Any:
    getter = getattr(value, "get_object", None)
    return getter() if callable(getter) else value


def _nombre(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    result = float(value)
    if not math.isfinite(result):
        raise ValueError
    return result


def _entier(value: Any, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError
    return value


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValueError
    return value


def _rect(page: Any) -> tuple[float, float, float, float]:
    box = page.get("/MediaBox")
    if box is None:
        raise ValueError
    box = _objet(box)
    if len(box) != 4:
        raise ValueError
    x0, y0, x1, y1 = (_nombre(value) for value in box)
    width, height = x1 - x0, y1 - y0
    if width <= 0 or height <= 0:
        raise ValueError
    return x0, y0, x1, y1


def _root(reader: Any) -> Any:
    trailer = _objet(reader.trailer)
    root = trailer.get("/Root")
    root = _objet(root)
    if not isinstance(root, dict) or set(root) - _ROOT_KEYS or any(key in root for key in _ROOT_ACTIVE):
        raise ValueError
    if "/Type" in root and _name(root["/Type"]) != "/Catalog":
        raise ValueError
    return root


def _image_obj(resources: Any) -> tuple[str, Any]:
    resources = _objet(resources)
    if not isinstance(resources, dict) or set(resources) - {"/XObject", "/ProcSet"}:
        raise ValueError
    procset = resources.get("/ProcSet")
    if procset is not None:
        procset = _objet(procset)
        if not isinstance(procset, (list, tuple)) or any(_name(item) not in _PROCSET_ALLOWED for item in procset):
            raise ValueError
    xobjects = _objet(resources.get("/XObject"))
    if not isinstance(xobjects, dict) or len(xobjects) != 1:
        raise ValueError
    name, reference = next(iter(xobjects.items()))
    name = _name(name)
    image = _objet(reference)
    if not isinstance(image, dict) or _name(image.get("/Subtype")) != "/Image":
        raise ValueError
    if image.get("/Type") not in (None, "/XObject"):
        raise ValueError
    if set(image) - _IMAGE_KEYS or any(key in image for key in (
        "/Mask", "/SMask", "/SMaskInData", "/ImageMask", "/Alternates", "/OC", "/Metadata", "/Decode",
        "/Intent", "/Matte",
    )):
        raise ValueError
    width = _entier(image.get("/Width"), 1, _DIMENSION_MAX)
    height = _entier(image.get("/Height"), 1, _DIMENSION_MAX)
    if width * height > _IMAGE_PIXELS_MAX:
        raise ValueError
    if _name(image.get("/ColorSpace")) not in _COULEURS_ALLOWED:
        raise ValueError
    if _entier(image.get("/BitsPerComponent"), 8, 8) != 8:
        raise ValueError
    filt = image.get("/Filter")
    if filt is not None:
        filt = _objet(filt)
        filters = list(filt) if isinstance(filt, (list, tuple)) else [filt]
        if len(filters) != 1 or _name(filters[0]) not in _FILTERS_ALLOWED:
            raise ValueError
    return name, image


def _operations(reader: Any, page: Any, image_name: str, rect: tuple[float, float, float, float]) -> None:
    from pypdf.generic import ContentStream

    content = page.get_contents()
    if content is None:
        raise ValueError
    content = _objet(content)
    operations = ContentStream(content, reader).operations
    if not operations or len(operations) > _OPERATIONS_MAX:
        raise ValueError
    stack: list[tuple[float, float, float, float, float, float] | None] = []
    # Aucun concaténat complexe : cette grammaire n'admet qu'une matrice cm
    # directe de placement du bitmap, avec q/Q équilibrés facultatifs.
    matrix: tuple[float, float, float, float, float, float] | None = None
    draws = 0
    for operands, operator in operations:
        if operator == b"q":
            if operands or len(stack) >= _PROFONDEUR_Q_MAX or draws:
                raise ValueError
            stack.append(matrix)
        elif operator == b"Q":
            if operands or not stack:
                raise ValueError
            matrix = stack.pop()
        elif operator == b"cm":
            if len(operands) != 6 or matrix is not None or draws:
                raise ValueError
            values = tuple(_nombre(value) for value in operands)
            if values[1] != 0 or values[2] != 0 or values[0] <= 0 or values[3] <= 0:
                raise ValueError
            matrix = values  # type: ignore[assignment]
        elif operator == b"Do":
            if len(operands) != 1 or _name(operands[0]) != image_name or draws:
                raise ValueError
            if matrix is None:
                raise ValueError
            draws += 1
            a, b, c, d, e, f = matrix
            x0, y0, x1, y1 = rect
            if (e != x0 or f != y0 or e + a != x1 or f + d != y1 or b != 0 or c != 0):
                raise ValueError
        else:
            # Texte, dessin vectoriel, clipping, propriétés de rendu ou tout
            # opérateur inconnu sont volontairement hors grammaire.
            raise ValueError
    if stack or draws != 1:
        raise ValueError


def classer_page_image(lecteur: Any) -> VerdictStructurePDF:
    """Retourne une candidature uniquement pour une image unique pleine page.

    `lecteur` doit provenir du futur worker après limites de parsing et de
    ressources. Tout objet invalide, inconnu ou hors grammaire est refusé.
    """
    try:
        if getattr(lecteur, "is_encrypted", True):
            return VerdictStructurePDF(_REFUS)
        root = _root(lecteur)
        del root
        pages = lecteur.pages
        if len(pages) != 1:
            return VerdictStructurePDF(_REFUS)
        page = _objet(pages[0])
        if not isinstance(page, dict) or set(page) - _PAGE_KEYS or any(key in page for key in _PAGE_FORBIDDEN):
            return VerdictStructurePDF(_REFUS)
        if page.get("/Type") != "/Page":
            return VerdictStructurePDF(_REFUS)
        if "/Rotate" in page and _entier(page["/Rotate"], 0, 0) != 0:
            return VerdictStructurePDF(_REFUS)
        rect = _rect(page)
        largeur_pt, hauteur_pt = rect[2] - rect[0], rect[3] - rect[1]
        echelle = _DPI / 72
        largeur_px = math.ceil(largeur_pt * echelle)
        hauteur_px = math.ceil(hauteur_pt * echelle)
        if (largeur_px <= 0 or hauteur_px <= 0 or largeur_px > _DIMENSION_MAX
                or hauteur_px > _DIMENSION_MAX or largeur_px * hauteur_px > _RASTER_PIXELS_MAX):
            return VerdictStructurePDF(_REFUS)
        resources = page.get("/Resources")
        name, image = _image_obj(resources)
        del image
        _operations(lecteur, page, name, rect)
        return VerdictStructurePDF(_CANDIDAT, 1, largeur_pt, hauteur_pt, largeur_px, hauteur_px)
    except Exception:
        return VerdictStructurePDF(_REFUS)
