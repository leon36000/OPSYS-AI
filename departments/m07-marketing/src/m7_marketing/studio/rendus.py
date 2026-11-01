"""Trois rendus du même plan : PNG (raster, social et épreuve), SVG (source vectorielle éditable), PDF (impression).

Le PNG est la sortie qui part vers un réseau ; le PDF l'imprimeur ; le SVG la source éditable (texte vivant, police
nommée mais NON incorporée : l'aperçu d'un SVG dépend des polices du lecteur, le rendu de référence est le PNG/PDF).
Dans le PDF, le texte est converti en COURBES (texte vectorisé : R5 §4.2 l'accepte, « polices incorporées ou texte
vectorisé ») et chaque ligne est enveloppée dans un contenu marqué `/ActualText` (texte de remplacement, accessibilité).

PDF écrit à la main : 1.4, boîtes `MediaBox` (fond perdu compris), `TrimBox` (format fini) et `BleedBox`, image de fond
`DeviceRGB` (RVB déclaré), métadonnées `Info` + XMP. Ce que ce PDF n'est PAS : un PDF/X (aucun `OutputIntent`, aucun
CMJN) ; voir la section « Impression » de `M7-STUDIO-CREATIF.md` pour le plan WeasyPrint ≥ 67 / pikepdf.

Marquage « généré par IA » : le même dictionnaire de métadonnées (`marquage`) est écrit dans le PNG (`tEXt`), le SVG
(`<metadata>`) et le PDF (`Info` + XMP). Les lecteurs (`lire_svg`, `lire_pdf`) le relisent pour le contrôle qualité.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import zlib
from collections.abc import Mapping
from typing import Any
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from . import plan as p
from . import png, vecteur
from .polices import RegistrePolices
from .toile import Toile, couleur_hex, hex_couleur

CLE_MARQUAGE_PNG = "OPSYS-Studio"
REJ_SVG = "REJ-STUDIO-SVG-INVALIDE"
REJ_PDF = "REJ-STUDIO-PDF-INVALIDE"
_ID_SUR = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def _n(valeur: float) -> str:
    texte = f"{valeur:.2f}".rstrip("0").rstrip(".")
    return "0" if texte in ("-0", "") else texte


def _hex(couleur: p.Couleur) -> str:
    return hex_couleur(couleur)


def marquage_json(marquage: Mapping[str, Any]) -> str:
    return json.dumps(marquage, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


# -- fond ------------------------------------------------------------------------------------------------------
def image_degrade(c1: p.Couleur, c2: p.Couleur, largeur: int = 2, hauteur: int = 512) -> png.ImageRVB:
    """Dégradé vertical déterministe (haut : c1, bas : c2) : un fond sans modèle, donc sans IA."""
    lignes = bytearray()
    for y in range(hauteur):
        t = y / (hauteur - 1)
        pixel = bytes(round(a + (b - a) * t) for a, b in zip(c1, c2, strict=True))
        lignes += pixel * largeur
    return png.ImageRVB(largeur, hauteur, bytes(lignes))


def _fond_image(plan: p.Plan, fond_png: bytes | None) -> png.ImageRVB | None:
    mode = plan.fond["mode"]
    if mode == "uni":
        return None
    if mode == "degrade":
        return image_degrade(_couleur(plan.fond["couleur"]), _couleur(plan.fond["couleur2"]))
    if fond_png is None:
        raise ValueError("fond généré sans image")
    return png.decoder(fond_png)


def _couleur(texte: str) -> p.Couleur:
    return couleur_hex(texte)


# -- PNG -------------------------------------------------------------------------------------------------------
def rendre_png(
    plan: p.Plan,
    fond_png: bytes | None,
    polices: RegistrePolices,
    marquage: Mapping[str, Any],
    *,
    sans_texte: bool = False,
) -> bytes:
    toile = Toile(plan.largeur_px, plan.hauteur_px, _couleur(plan.fond["couleur"]))
    image = _fond_image(plan, fond_png)
    if image is not None:
        toile.image_couvrir(image, 0, 0, plan.largeur_px, plan.hauteur_px)
    for element in plan.elements:
        if isinstance(element, p.Rect):
            toile.rectangle(
                element.x, element.y, element.x + element.w, element.y + element.h, element.couleur, element.opacite
            )
        elif isinstance(element, p.LogoPose):
            echelle_x, echelle_y = element.w / element.vb_w, element.h / element.vb_h
            polys = [
                poly
                for chemin in element.chemins
                for poly in vecteur.polygones(chemin, echelle_x, echelle_y, element.x, element.y)
            ]
            toile.remplir(polys, element.couleur)
        elif isinstance(element, p.Ligne) and not sans_texte:
            police = polices.obtenir(element.police_id)
            toile.texte(police, element.texte, element.x, element.baseline, element.taille_px, element.couleur)
    return png.encoder(toile.vers_image(), {CLE_MARQUAGE_PNG: marquage_json(marquage)})


# -- SVG -------------------------------------------------------------------------------------------------------
def rendre_svg(plan: p.Plan, fond_png: bytes | None, polices: RegistrePolices, marquage: Mapping[str, Any]) -> bytes:
    L, H = plan.largeur_px, plan.hauteur_px
    sortie = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{L}" height="{H}" viewBox="0 0 {L} {H}" role="img">',
        "<title>Visuel du studio créatif (source éditable)</title>",
        f'<metadata id="opsys-metadonnees">{escape(marquage_json(marquage))}</metadata>',
        f'<clipPath id="page"><rect x="0" y="0" width="{L}" height="{H}"/></clipPath>',
        '<g clip-path="url(#page)">',
    ]
    mode = plan.fond["mode"]
    if mode == "uni":
        sortie.append(f'<rect x="0" y="0" width="{L}" height="{H}" fill="{plan.fond["couleur"]}"/>')
    else:
        if mode == "degrade":
            image = png.encoder(image_degrade(_couleur(plan.fond["couleur"]), _couleur(plan.fond["couleur2"])))
        else:
            if fond_png is None:
                raise ValueError("fond généré sans image")
            image = fond_png
        charge = base64.b64encode(image).decode("ascii")
        sortie.append(
            f'<image x="0" y="0" width="{L}" height="{H}" preserveAspectRatio="xMidYMid slice" '
            f'href="data:image/png;base64,{charge}"/>'
        )
    for element in plan.elements:
        if isinstance(element, p.Rect):
            sortie.append(
                f'<rect data-opsys-id="{_id(element.id)}" x="{_n(element.x)}" y="{_n(element.y)}" '
                f'width="{_n(element.w)}" height="{_n(element.h)}" fill="{_hex(element.couleur)}" '
                f'fill-opacity="{_n(element.opacite)}"/>'
            )
        elif isinstance(element, p.LogoPose):
            sx, sy = element.w / element.vb_w, element.h / element.vb_h
            chemins = "".join(f'<path d="{escape(c, {chr(34): "&quot;"})}"/>' for c in element.chemins)
            sortie.append(
                f'<g data-opsys-id="{_id(element.id)}" fill="{_hex(element.couleur)}" '
                f'transform="translate({_n(element.x)} {_n(element.y)}) scale({sx:.5f} {sy:.5f})">{chemins}</g>'
            )
        elif isinstance(element, p.Ligne):
            famille = polices.obtenir(element.police_id).famille
            lang = f' lang="{element.langue}"' if element.langue else ""
            sortie.append(
                f'<text data-opsys-id="{_id(element.id)}" data-opsys-n="{element.n}" data-opsys-role="{element.role}"'
                f'{lang} x="{_n(element.x)}" y="{_n(element.baseline)}" font-family="{escape(famille)}, sans-serif" '
                f'font-size="{_n(element.taille_px)}" fill="{_hex(element.couleur)}" xml:space="preserve">'
                f"{escape(element.texte)}</text>"
            )
    sortie.append("</g>")
    sortie.append("</svg>")
    return ("\n".join(sortie) + "\n").encode("utf-8")


def _id(valeur: str) -> str:
    if not _ID_SUR.fullmatch(valeur):
        raise ValueError("identifiant d'élément non sûr")
    return valeur


class SvgInvalide(ValueError):
    def __init__(self, detail: str) -> None:
        super().__init__(f"{REJ_SVG} : {detail}")
        self.code, self.detail = REJ_SVG, detail


_SVG_INTERDITS = re.compile(
    rb"<!DOCTYPE|<!ENTITY|<script|<foreignObject|<iframe|<use\b|\bon[a-z]+\s*=|javascript:", re.I
)
TAILLE_SVG_MAX = 20 * 1024 * 1024


def lire_svg(octets: bytes) -> dict[str, Any]:
    """Relit un SVG du studio : textes par élément logique (lignes dans l'ordre), métadonnées, dimensions. Refuse tout
    contenu actif, entité, doctype ou image externe : le même lecteur sert de garde pour un SVG qu'on publie."""
    if not isinstance(octets, bytes) or len(octets) > TAILLE_SVG_MAX:
        raise SvgInvalide("SVG absent ou trop volumineux")
    if _SVG_INTERDITS.search(octets):
        raise SvgInvalide("contenu actif, entité ou doctype interdit")
    try:
        racine = ElementTree.fromstring(octets)
    except ElementTree.ParseError:
        raise SvgInvalide("XML mal formé") from None
    ns = "{http://www.w3.org/2000/svg}"
    if racine.tag != ns + "svg":
        raise SvgInvalide("racine svg attendue")
    textes: dict[str, list[tuple[int, str]]] = {}
    for noeud in racine.iter(ns + "text"):
        identifiant = noeud.get("data-opsys-id")
        if identifiant is None:
            continue
        textes.setdefault(identifiant, []).append((int(noeud.get("data-opsys-n", "0")), noeud.text or ""))
    for noeud in racine.iter():
        for cle, valeur in noeud.attrib.items():
            if cle.endswith("href") and not (valeur.startswith("data:image/png;base64,") or valeur.startswith("#")):
                raise SvgInvalide("référence externe interdite")
    metadonnees = None
    meta = racine.find(ns + "metadata")
    if meta is not None and meta.text:
        try:
            metadonnees = json.loads(meta.text)
        except json.JSONDecodeError:
            raise SvgInvalide("métadonnées illisibles") from None
    return {
        "textes": {i: [t for _n_, t in sorted(v)] for i, v in textes.items()},
        "metadonnees": metadonnees,
        "largeur": racine.get("width"),
        "hauteur": racine.get("height"),
    }


# -- PDF -------------------------------------------------------------------------------------------------------
def _chaine_pdf(texte: str) -> str:
    return "<FEFF" + texte.encode("utf-16-be").hex().upper() + ">"


def _ops_contour(
    contour: tuple, echelle: float, origine_x: float, baseline: float, hauteur_px: float, k: float
) -> list[str]:
    def pt(x: float, y: float) -> str:
        return f"{_n3((origine_x + x * echelle) * k)} {_n3((hauteur_px - (baseline - y * echelle)) * k)}"

    depart, segments = contour
    ops = [f"{pt(*depart)} m"]
    x0, y0 = depart
    for segment in segments:
        if segment[0] == "L":
            ops.append(f"{pt(segment[1], segment[2])} l")
            x0, y0 = segment[1], segment[2]
        else:
            cx, cy, x1, y1 = segment[1:]
            ops.append(
                f"{pt(x0 + 2 / 3 * (cx - x0), y0 + 2 / 3 * (cy - y0))} "
                f"{pt(x1 + 2 / 3 * (cx - x1), y1 + 2 / 3 * (cy - y1))} {pt(x1, y1)} c"
            )
            x0, y0 = x1, y1
    ops.append("h")
    return ops


def _n3(valeur: float) -> str:
    texte = f"{valeur:.3f}".rstrip("0").rstrip(".")
    return "0" if texte in ("-0", "") else texte


def _rgb(couleur: p.Couleur) -> str:
    return " ".join(_n3(c / 255) for c in couleur)


def rendre_pdf(plan: p.Plan, fond_png: bytes | None, polices: RegistrePolices, marquage: Mapping[str, Any]) -> bytes:
    k = 72.0 / plan.ppp
    L, H = plan.largeur_px, plan.hauteur_px
    Lp, Hp = L * k, H * k
    image = _fond_image(plan, fond_png)
    opacites = sorted({e.opacite for e in plan.elements if isinstance(e, p.Rect) and e.opacite < 1.0})
    flux: list[str] = []
    if image is None:
        flux.append(f"q {_rgb(_couleur(plan.fond['couleur']))} rg 0 0 {_n3(Lp)} {_n3(Hp)} re f Q")
    else:
        s = max(Lp / image.largeur, Hp / image.hauteur)
        flux.append(
            f"q 0 0 {_n3(Lp)} {_n3(Hp)} re W n {_n3(image.largeur * s)} 0 0 {_n3(image.hauteur * s)} "
            f"{_n3((Lp - image.largeur * s) / 2)} {_n3((Hp - image.hauteur * s) / 2)} cm /Fond Do Q"
        )
    for element in plan.elements:
        if isinstance(element, p.Rect):
            gs = f"/GS{opacites.index(element.opacite)} gs " if element.opacite < 1.0 else ""
            flux.append(
                f"q {gs}{_rgb(element.couleur)} rg {_n3(element.x * k)} {_n3((H - element.y - element.h) * k)} "
                f"{_n3(element.w * k)} {_n3(element.h * k)} re f Q"
            )
        elif isinstance(element, p.LogoPose):
            ops = [
                vecteur.operateurs_pdf(
                    c, element.w / element.vb_w, element.h / element.vb_h, element.x, element.y, H, k
                )
                for c in element.chemins
            ]
            flux.append(f"q {_rgb(element.couleur)} rg\n" + "\n".join(ops) + "\nf Q")
        elif isinstance(element, p.Ligne):
            police = polices.obtenir(element.police_id)
            echelle = element.taille_px / police.ttf.unites_par_em
            ops: list[str] = []
            for polys in _glyphes_contours(police, element):
                for contour, origine in polys:
                    ops += _ops_contour(contour, echelle, origine, round(element.baseline), H, k)
            actuel = _chaine_pdf(element.texte)
            flux.append(
                f"/Span << /ActualText {actuel} >> BDC\nq {_rgb(element.couleur)} rg\n" + "\n".join(ops) + "\nf Q\nEMC"
            )
    contenu = "\n".join(flux).encode("latin-1")
    boite = tuple(
        round(v, 3)
        for v in (plan.rognage[0] * k, (H - plan.rognage[3]) * k, plan.rognage[2] * k, (H - plan.rognage[1]) * k)
    )
    objets: dict[int, bytes] = {}
    ressources = ""
    if image is not None:
        ressources += "/XObject << /Fond 5 0 R >> "
        brut = zlib.compress(image.pixels, 9)
        objets[5] = (
            (
                f"<< /Type /XObject /Subtype /Image /Width {image.largeur} /Height {image.hauteur} "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(brut)} >>\n"
            ).encode("latin-1")
            + b"stream\n"
            + brut
            + b"\nendstream"
        )
    if opacites:
        ressources += (
            "/ExtGState << "
            + " ".join(f"/GS{i} << /ca {_n3(o)} /CA {_n3(o)} >>" for i, o in enumerate(opacites))
            + " >> "
        )
    objets[1] = b"<< /Type /Catalog /Pages 2 0 R /Metadata 7 0 R /Lang (fr-CA) >>"
    objets[2] = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    boites = " ".join(_n3(v) for v in (0, 0, Lp, Hp))
    trim = " ".join(_n3(v) for v in boite)
    objets[3] = (
        f"<< /Type /Page /Parent 2 0 R /MediaBox [{boites}] /TrimBox [{trim}] /BleedBox [{boites}] "
        f"/Contents 4 0 R /Resources << {ressources}>> >>"
    ).encode("latin-1")
    objets[4] = f"<< /Length {len(contenu)} >>\n".encode("latin-1") + b"stream\n" + contenu + b"\nendstream"
    mots_cles = (
        f"opsys-studio; ia-generee={'oui' if marquage.get('ia_generee') else 'non'}; "
        f"provenance={marquage.get('provenance') or 'aucune'}"
    )
    objets[6] = (
        f"<< /Title {_chaine_pdf('Visuel du studio créatif')} /Producer {_chaine_pdf('OPSYS-AI studio créatif')} "
        f"/Creator {_chaine_pdf('OPSYS-AI M7')} /Keywords {_chaine_pdf(mots_cles)} "
        f"/OpsysMarquage {_chaine_pdf(marquage_json(marquage))} >>"
    ).encode("latin-1")
    xmp = _xmp(marquage).encode("utf-8")
    objets[7] = (
        (f"<< /Type /Metadata /Subtype /XML /Length {len(xmp)} >>\n").encode("latin-1")
        + b"stream\n"
        + xmp
        + b"\nendstream"
    )
    sortie = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    positions: dict[int, int] = {}
    for numero in sorted(objets):
        positions[numero] = len(sortie)
        sortie += f"{numero} 0 obj\n".encode("latin-1") + objets[numero] + b"\nendobj\n"
    debut_xref = len(sortie)
    maximum = max(objets) + 1
    sortie += f"xref\n0 {maximum}\n".encode("latin-1") + b"0000000000 65535 f \n"
    for numero in range(1, maximum):
        if numero in positions:
            sortie += f"{positions[numero]:010d} 00000 n \n".encode("latin-1")
        else:
            sortie += b"0000000000 65535 f \n"
    identifiant = hashlib.sha256(bytes(sortie)).hexdigest()[:32]
    sortie += (
        f"trailer\n<< /Size {maximum} /Root 1 0 R /Info 6 0 R /ID [<{identifiant}> <{identifiant}>] >>\n"
        f"startxref\n{debut_xref}\n%%EOF\n"
    ).encode("latin-1")
    return bytes(sortie)


def _glyphes_contours(police: Any, ligne: p.Ligne):
    """Par glyphe : liste de `(contour, abscisse de départ du glyphe)` ; l'abscisse est entière comme au raster."""
    ttf = police.ttf
    echelle = ligne.taille_px / ttf.unites_par_em
    pen = ligne.x
    for caractere in ligne.texte:
        if caractere != " ":
            origine = float(round(pen))
            contours = ttf.contours(caractere)
            if contours:
                yield [(c, origine) for c in contours]
        pen += ttf.avance(caractere) * echelle


def _xmp(marquage: Mapping[str, Any]) -> str:
    def attr(nom: str, valeur: Any) -> str:
        return f'{nom}="{escape(str(valeur), {chr(34): "&quot;"})}"'

    champs = " ".join(
        attr(f"opsys:{cle}", marquage[cle]) for cle in sorted(marquage) if not isinstance(marquage[cle], (dict, list))
    )
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        f'<rdf:Description rdf:about="" xmlns:opsys="https://opsys.example/ns/studio/1.0/" {champs}/>'
        '</rdf:RDF></x:xmpmeta>\n<?xpacket end="w"?>'
    )


class PdfInvalide(ValueError):
    def __init__(self, detail: str) -> None:
        super().__init__(f"{REJ_PDF} : {detail}")
        self.code, self.detail = REJ_PDF, detail


_BOITE = re.compile(rb"/(MediaBox|TrimBox|BleedBox) \[([0-9. -]+)\]")
_ACTUALTEXT = re.compile(rb"/ActualText <([0-9A-F]+)>")


def lire_pdf(octets: bytes) -> dict[str, Any]:
    """Relit un PDF du studio : structure (table xref vérifiée), boîtes de page, textes de remplacement, marquage."""
    if not isinstance(octets, bytes) or not octets.startswith(b"%PDF-1.") or not octets.rstrip().endswith(b"%%EOF"):
        raise PdfInvalide("en-tête ou fin de fichier PDF absent")
    trouve = re.search(rb"startxref\n(\d+)\n%%EOF\s*$", octets)
    if trouve is None:
        raise PdfInvalide("startxref absent")
    debut = int(trouve.group(1))
    if debut >= len(octets) or not octets[debut:].startswith(b"xref\n"):
        raise PdfInvalide("table xref introuvable à l'offset annoncé")
    entete = re.match(rb"xref\n0 (\d+)\n", octets[debut:])
    if entete is None:
        raise PdfInvalide("table xref illisible")
    nombre = int(entete.group(1))
    corps = octets[debut + entete.end() : debut + entete.end() + 20 * nombre]
    for numero in range(1, nombre):
        ligne = corps[20 * numero : 20 * numero + 20]
        if ligne[17:18] == b"n":
            offset = int(ligne[:10])
            if not octets[offset:].startswith(f"{numero} 0 obj\n".encode("latin-1")):
                raise PdfInvalide(f"l'objet {numero} n'est pas à l'offset annoncé")
    boites: dict[str, list[float]] = {}
    for nom, valeurs in _BOITE.findall(octets):
        boites[nom.decode()] = [float(v) for v in valeurs.split()]
    textes = []
    for brut in _ACTUALTEXT.findall(octets):
        textes.append(bytes.fromhex(brut.decode()).decode("utf-16-be").removeprefix("﻿"))
    if octets.count(b" BDC") != octets.count(b"\nEMC"):
        raise PdfInvalide("contenu marqué déséquilibré (BDC/EMC)")
    marquage = None
    trouve_marquage = re.search(rb"/OpsysMarquage <([0-9A-F]+)>", octets)
    if trouve_marquage:
        try:
            marquage = json.loads(bytes.fromhex(trouve_marquage.group(1).decode()).decode("utf-16-be").removeprefix("﻿"))
        except (ValueError, json.JSONDecodeError):
            raise PdfInvalide("marquage illisible") from None
    return {
        "boites": boites,
        "textes": textes,
        "marquage": marquage,
        "xmp": b"opsys:ia_generee" in octets,
        "incorpore_image": b"/Subtype /Image" in octets,
    }
