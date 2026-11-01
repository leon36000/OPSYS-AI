"""Rendus du même plan : PNG, SVG, PDF ; lecteurs de SVG et de PDF ; chemins vectoriels des logos."""

from __future__ import annotations

import re

import fabriques_studio as f
import pytest
from m7_marketing.studio import brief as b
from m7_marketing.studio import composition, png, polices, rendus, vecteur


@pytest.fixture(scope="module")
def registre(tmp_path_factory):
    return polices.charger_dossier(f.ecrire_polices(tmp_path_factory.mktemp("p")), production=False)


def _compose(registre, donnees=None, **kw):
    brief, refus = b.depuis_dict(donnees or f.brief())
    assert brief is not None, refus
    return composition.composer_visuel(brief, registre, f.POLICE_ID, **kw)


@pytest.fixture(scope="module")
def carte(registre):
    return _compose(registre)


def test_la_composition_produit_trois_artefacts_pour_l_impression_et_deux_pour_l_ecran(registre, carte):
    assert set(carte.artefacts) == {"svg", "png", "pdf"}
    assert set(_compose(registre, f.brief("banniere_social")).artefacts) == {"svg", "png"}


def test_les_rendus_sont_reproductibles_octet_pour_octet(registre, carte):
    autre = _compose(registre)
    assert autre.artefacts["svg"] == carte.artefacts["svg"] and autre.artefacts["pdf"] == carte.artefacts["pdf"]
    assert png.decoder(autre.artefacts["png"]) == png.decoder(carte.artefacts["png"])
    assert autre.empreinte() == carte.empreinte()


def test_le_png_a_les_dimensions_du_plan_et_porte_le_marquage(carte):
    assert png.dimensions(carte.artefacts["png"]) == (carte.plan.largeur_px, carte.plan.hauteur_px)
    meta = png.metadonnees(carte.artefacts["png"])
    assert rendus.CLE_MARQUAGE_PNG in meta and '"ia_generee":false' in meta[rendus.CLE_MARQUAGE_PNG]


def test_le_svg_relu_redonne_les_lignes_et_le_marquage(carte):
    lu = rendus.lire_svg(carte.artefacts["svg"])
    attendu = {i: [ligne.texte for ligne in lignes] for i, lignes in carte.plan.elements_logiques().items()}
    assert lu["textes"] == attendu
    assert lu["metadonnees"] == dict(carte.marquage)


def test_texte_hostile_dans_un_titre_est_echappe_et_se_relit_a_l_identique(registre):
    donnees = f.brief()
    donnees["textes"]["titre"]["fr"] = 'A < B & "C" > D'
    brief, refus = b.depuis_dict(donnees)
    assert brief is not None, refus
    comp = composition.composer_visuel(brief, registre, f.POLICE_ID)
    svg = comp.artefacts["svg"].decode("utf-8")
    assert "<B" not in svg.replace("&lt;", "") and "&lt;" in svg and "&amp;" in svg
    lu = rendus.lire_svg(comp.artefacts["svg"])
    assert " ".join(lu["textes"]["titre.fr"]) == 'A < B & "C" > D'


@pytest.mark.parametrize(
    "piege",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
        b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="http://exemple.test/x.png"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"/></svg>',
        b"<svg",
        b"",
        b"<html/>",
    ],
)
def test_le_lecteur_de_svg_refuse_tout_contenu_actif_ou_externe(piege):
    with pytest.raises(rendus.SvgInvalide):
        rendus.lire_svg(piege)


def test_pdf_structure_boites_et_textes_de_remplacement(carte):
    lu = rendus.lire_pdf(carte.artefacts["pdf"])
    k = 72 / carte.plan.ppp
    assert lu["boites"]["TrimBox"] == pytest.approx(
        [
            carte.plan.rognage[0] * k,
            (carte.plan.hauteur_px - carte.plan.rognage[3]) * k,
            carte.plan.rognage[2] * k,
            (carte.plan.hauteur_px - carte.plan.rognage[1]) * k,
        ],
        abs=0.01,
    )
    assert lu["boites"]["MediaBox"] == lu["boites"]["BleedBox"]
    assert lu["boites"]["MediaBox"][0] < lu["boites"]["TrimBox"][0]
    assert lu["textes"] == [ligne.texte for ligne in carte.plan.lignes]
    assert lu["marquage"] == dict(carte.marquage) and lu["xmp"]
    assert carte.artefacts["pdf"].startswith(b"%PDF-1.4")


def test_le_texte_du_pdf_est_en_contours_pas_en_police_non_incorporee(carte):
    pdf = carte.artefacts["pdf"]
    assert b"/Font" not in pdf and b"/BaseFont" not in pdf and b"BT\n" not in pdf and b" Tj" not in pdf
    assert b" m\n" in pdf and b" l\n" in pdf  # contours remplis : texte vectorisé


def test_les_courbes_quadratiques_deviennent_des_cubiques_dans_le_pdf(registre):
    donnees = f.brief()
    donnees["textes"]["titre"]["fr"] = "Cercle " + chr(0x25CB) + " plein"
    comp = _compose(registre, donnees)
    assert b" c\n" in comp.artefacts["pdf"]
    assert rendus.lire_pdf(comp.artefacts["pdf"])["textes"][2].startswith("Cercle ")


@pytest.mark.parametrize("alteration", ["xref", "fin", "debut", "bdc"])
def test_pdf_altere_refuse(carte, alteration):
    pdf = bytearray(carte.artefacts["pdf"])
    if alteration == "xref":
        position = pdf.index(b"0000000015 00000 n") if b"0000000015 00000 n" in pdf else pdf.index(b" 00000 n")
        pdf[position + 5] = ord("9") if pdf[position + 5] != ord("9") else ord("8")
    elif alteration == "fin":
        pdf = pdf[:-8]
    elif alteration == "debut":
        pdf[:5] = b"%XXX-"
    else:
        pdf = bytearray(bytes(pdf).replace(b"\nEMC", b"\nXXX", 1))
    with pytest.raises(rendus.PdfInvalide):
        rendus.lire_pdf(bytes(pdf))


def test_fond_genere_s_incorpore_dans_les_trois_artefacts(registre):
    donnees = f.brief(fond={"mode": "genere", "sujet": "toiture de bardeaux gris sous un ciel de printemps"})
    comp = _compose(registre, donnees, fond_png=f.fond_synthetique(), provenance=f.PROVENANCE)
    assert comp.ia_generee and comp.marquage["provenance"] == f.PROVENANCE["chaine"]
    assert b"data:image/png;base64," in comp.artefacts["svg"] and b"/Subtype /Image" in comp.artefacts["pdf"]
    assert rendus.lire_pdf(comp.artefacts["pdf"])["marquage"]["ia_generee"] is True
    assert "OPSYS-Studio" in png.metadonnees(comp.artefacts["png"])


def test_degrade_est_un_fond_sans_modele(registre):
    comp = _compose(registre, f.brief(fond={"mode": "degrade"}))
    assert not comp.ia_generee and comp.fond_png is None
    haut = png.decoder(comp.artefacts["png"]).pixels[3 * 5 * comp.plan.largeur_px + 3 * (comp.plan.largeur_px - 5) :][
        :3
    ]
    assert tuple(haut) != (0, 0, 0)


def test_fond_genere_sans_provenance_ou_image_refuse(registre):
    donnees = f.brief(fond={"mode": "genere", "sujet": "toiture de bardeaux gris sous un ciel de printemps"})
    for kw in (
        {},
        {"fond_png": f.fond_synthetique()},
        {"provenance": f.PROVENANCE},
        {"fond_png": f.fond_synthetique(), "provenance": {"chaine": ""}},
    ):
        with pytest.raises(composition.CompositionRefusee) as erreur:
            _compose(registre, donnees, **kw)
        assert erreur.value.code == composition.REJ_FOND_SANS_PROVENANCE


def test_une_image_glissee_dans_un_visuel_sans_ia_est_refusee(registre):
    with pytest.raises(composition.CompositionRefusee) as erreur:
        _compose(registre, f.brief(), fond_png=f.fond_synthetique())
    assert erreur.value.code == composition.REJ_FOND_NON_DEMANDE
    with pytest.raises(composition.CompositionRefusee):
        _compose(registre, f.brief(), provenance=f.PROVENANCE)


def test_fond_illisible_refuse(registre):
    donnees = f.brief(fond={"mode": "genere", "sujet": "toiture de bardeaux gris sous un ciel de printemps"})
    with pytest.raises(composition.CompositionRefusee) as erreur:
        _compose(registre, donnees, fond_png=b"pas un png", provenance=f.PROVENANCE)
    assert erreur.value.code == composition.REJ_FOND_IMAGE


# -- chemins vectoriels ---------------------------------------------------------------------------------------
def test_chemin_valide_et_aplati():
    polys = vecteur.polygones("M 0 0 L 10 0 L 10 10 Q 5 20 0 10 Z", 1, 1, 0, 0)
    assert len(polys) == 1 and len(polys[0]) == 4 + 12 - 1 + 1 - 1 or len(polys[0]) > 4


def test_moveto_a_plusieurs_paires_devient_des_lineto():
    commandes = vecteur.analyser("M 0 0 10 0 10 10 Z")
    assert [c[0] for c in commandes] == ["M", "L", "L", "Z"]


@pytest.mark.parametrize(
    "d",
    [
        "",
        "L 1 1",
        "M 0 0 L 1",
        "M 0 0 Z 5",
        "M 0 0 L a b",
        "M 0 0 l 1 1",
        "M 0 0 A 1 1 0 0 0 5 5",
        "M 0 0 L 999999999 1",
        "M " + "0 0 L " * 5000,
        "M 0 0 L 1 1;<script>",
    ],
)
def test_chemin_hors_sous_ensemble_refuse(d):
    with pytest.raises(vecteur.CheminInvalide):
        vecteur.analyser(d)


def test_pdf_et_png_dessinent_le_meme_logo(registre):
    logo = {"id": "logo-fictif-1", "chemins": ["M 0 0 L 10 0 L 10 10 L 0 10 Z"], "vb_w": 10, "vb_h": 10}
    donnees = f.brief(elements_critiques=f.critiques("telephone"), mentions_obligatoires=[])
    comp = _compose(registre, donnees, logo=logo)
    pose = comp.plan.logo
    image = png.decoder(comp.artefacts["png"])
    milieu_x, milieu_y = int(pose.x + pose.w / 2), int(pose.y + pose.h / 2)
    p = 3 * (milieu_y * image.largeur + milieu_x)
    assert tuple(image.pixels[p : p + 3]) == pose.couleur
    assert (
        re.search(rb"\bh\nf Q", comp.artefacts["pdf"])
        and b'<path d="M 0 0 L 10 0 L 10 10 L 0 10 Z"/>' in comp.artefacts["svg"]
    )
