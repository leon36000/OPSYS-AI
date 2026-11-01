"""Logos : vectorisation par le port (double), SVG sûr, déclinaisons, contrôle de forme, avertissement partout."""

from __future__ import annotations

import fabriques_studio as f
import pytest
from m7_marketing.studio import actifs, logos, png, rendus, vecteur


def _raster(motif, echelle=4):
    """Raster en noir sur blanc à partir d'un motif de caractères (# = forme)."""
    hauteur, largeur = len(motif) * echelle, len(motif[0]) * echelle
    pixels = bytearray()
    for y in range(hauteur):
        for x in range(largeur):
            pixels += bytes((0, 0, 0)) if motif[y // echelle][x // echelle] == "#" else bytes((255, 255, 255))
    return png.ImageRVB(largeur, hauteur, bytes(pixels))


MOTIF = ["####....", "####....", "....####", "....####"]


def test_le_double_vectorise_en_rectangles_fusionnes():
    logo = logos.VectoriseurDouble().vectoriser(_raster(MOTIF), 128)
    assert logo.vb_w == 32 and logo.vb_h == 16 and len(logo.chemins) == 2
    assert set(logo.chemins) == {"M 0 0 H 16 V 8 H 0 Z", "M 16 8 H 32 V 16 H 16 Z"}


def test_trop_de_formes_ou_aucune_forme_ou_raster_enorme_refuses():
    vide = png.ImageRVB(8, 8, bytes([255]) * 192)
    with pytest.raises(vecteur.CheminInvalide):
        logos.VectoriseurDouble().vectoriser(vide, 128)
    damier = ["#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#.#."] * 1
    rangees = [damier[0] if i % 2 == 0 else damier[0][1:] + "." for i in range(30)]
    with pytest.raises(vecteur.CheminInvalide) as erreur:
        logos.VectoriseurDouble().vectoriser(_raster(rangees, 1), 128)
    assert "trop complexe" in str(erreur.value)
    with pytest.raises(vecteur.CheminInvalide):
        logos.VectoriseurDouble().vectoriser(png.ImageRVB(700, 700, bytes(3 * 700 * 700)), 128)


@pytest.mark.parametrize(
    ("chemins", "vb"),
    [
        ([], (10, 10)),
        (["M 0 0 L 1"], (10, 10)),
        (["M 0 0 H 5 V 5 Z"], (0, 10)),
        (["M 0 0 H 5 V 5 Z"] * 201, (10, 10)),
        (["M 0 0 H 5 V 5 Z"], (10, 10_001)),
    ],
)
def test_un_logo_hors_du_sous_ensemble_ou_hors_bornes_est_refuse(chemins, vb):
    with pytest.raises(vecteur.CheminInvalide):
        logos.logo_depuis_chemins(chemins, *vb)


def test_le_svg_est_autonome_sans_script_sans_raster_et_porte_l_avertissement():
    logo = logos.logo_depuis_chemins(["M 0 0 H 10 V 10 H 0 Z"], 10, 10)
    svg = logos.svg_du_logo(logo)
    lu = rendus.lire_svg(svg)  # le lecteur refuse tout contenu actif : le SVG du logo le passe
    assert lu["largeur"] == "10"
    for interdit in (b"<script", b"<image", b"href", b"onload", b"<foreignObject"):
        assert interdit not in svg
    assert actifs.AVERTISSEMENT_LOGO.encode() in svg and b"marque de commerce" in svg


def test_declinaisons_monochrome_et_negatif():
    logo = logos.logo_depuis_chemins(["M 0 0 H 10 V 10 H 0 Z"], 10, 10)
    declinaisons = logos.declinaisons(logo)
    assert set(declinaisons) == {"monochrome", "negatif"}
    assert b'fill="#000000"' in declinaisons["monochrome"] and b'fill="#FFFFFF"' in declinaisons["negatif"]
    assert b'<rect width="10" height="10" fill="#000000"/>' in declinaisons["negatif"]
    with pytest.raises(ValueError):
        logos.svg_du_logo(logo, "noir")


def test_le_rapport_de_controle_est_signe_et_juge_la_forme_seulement():
    logo = logos.logo_depuis_chemins(["M 0 0 H 60 V 100 H 0 Z", "M 70 0 H 100 V 100 H 70 Z"], 100, 100)
    rapport = logos.rapport_controle(
        logo, logos.svg_du_logo(logo), maintenant=f.MAINTENANT, source="s", outil={"nom": "x"}
    )
    from m7_marketing.studio import controle

    assert rapport["conforme"] and controle.verifier_empreinte_rapport(rapport)
    assert {c["code"] for c in rapport["constats"]} == {
        "QC-LOGO-CHEMINS",
        "QC-LOGO-SANS-RASTER",
        "QC-LOGO-LISIBLE-16PX",
        "QC-LOGO-AVERTISSEMENT",
    }
    assert (
        any("antériorité" in lim for lim in rapport["limites"]) and rapport["limites"][0] == actifs.AVERTISSEMENT_LOGO
    )


def test_un_logo_illisible_a_16_px_est_refuse_par_le_controle():
    minuscule = logos.logo_depuis_chemins(["M 0 0 H 1 V 1 H 0 Z"], 1000, 1000)  # un point dans une grande boîte
    rapport = logos.rapport_controle(
        minuscule, logos.svg_du_logo(minuscule), maintenant=f.MAINTENANT, source="s", outil={"nom": "x"}
    )
    assert not rapport["conforme"]
    assert [c["code"] for c in rapport["constats"] if not c["ok"]] == ["QC-LOGO-LISIBLE-16PX"]
    plein = logos.logo_depuis_chemins(["M 0 0 H 100 V 100 H 0 Z"], 100, 100)
    assert not logos.rapport_controle(
        plein, logos.svg_du_logo(plein), maintenant=f.MAINTENANT, source="s", outil={"nom": "x"}
    )["conforme"]


def test_un_svg_qui_perd_l_avertissement_ou_ajoute_un_raster_est_pris():
    logo = logos.logo_depuis_chemins(["M 0 0 H 60 V 100 H 0 Z"], 100, 100)
    svg = logos.svg_du_logo(logo).replace(actifs.AVERTISSEMENT_LOGO.encode(), b"")
    rapport = logos.rapport_controle(logo, svg, maintenant=f.MAINTENANT, source="s", outil={"nom": "x"})
    assert "QC-LOGO-AVERTISSEMENT" in [c["code"] for c in rapport["constats"] if not c["ok"]]
    avec_image = logos.svg_du_logo(logo).replace(b"</svg>", b'<image href="data:x"/></svg>')
    rapport = logos.rapport_controle(logo, avec_image, maintenant=f.MAINTENANT, source="s", outil={"nom": "x"})
    assert "QC-LOGO-SANS-RASTER" in [c["code"] for c in rapport["constats"] if not c["ok"]]


def test_l_empreinte_d_un_logo_depend_de_ses_chemins_et_de_sa_boite():
    a = logos.logo_depuis_chemins(["M 0 0 H 5 V 5 Z"], 10, 10)
    assert a.empreinte() == logos.logo_depuis_chemins(["M 0 0 H 5 V 5 Z"], 10, 10).empreinte()
    assert a.empreinte() != logos.logo_depuis_chemins(["M 0 0 H 6 V 5 Z"], 10, 10).empreinte()
    assert a.empreinte() != logos.logo_depuis_chemins(["M 0 0 H 5 V 5 Z"], 10, 11).empreinte()
