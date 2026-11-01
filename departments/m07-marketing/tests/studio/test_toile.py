"""Toile raster : remplissage (aire exacte), texte déterministe, contraste WCAG, image couvrante."""

from __future__ import annotations

import fabriques_studio as f
import police_pixel
import pytest
from m7_marketing.studio import polices, toile
from m7_marketing.studio.png import ImageRVB


@pytest.fixture(scope="module")
def police(tmp_path_factory):
    dossier = f.ecrire_polices(tmp_path_factory.mktemp("polices"))
    return polices.charger_dossier(dossier, production=False).obtenir(f.POLICE_ID)


def test_rectangle_opaque_et_translucide():
    t = toile.Toile(10, 10, (255, 255, 255))
    t.rectangle(2, 2, 5, 5, (0, 0, 0))
    assert t.pixels[3 * (3 * 10 + 3) : 3 * (3 * 10 + 3) + 3] == bytes((0, 0, 0))
    t.rectangle(0, 0, 10, 10, (0, 0, 0), 0.5)
    assert t.pixels[0:3] == bytes((128, 128, 128)) or t.pixels[0:3] == bytes((127, 127, 127))


def test_rectangle_hors_toile_ne_deborde_pas():
    t = toile.Toile(4, 4)
    t.rectangle(-10, -10, 100, 100, (10, 20, 30))
    assert set(bytes(t.pixels[i : i + 3]) for i in range(0, len(t.pixels), 3)) == {bytes((10, 20, 30))}


def test_aire_d_un_cercle_a_courbes_quadratiques(police):
    taille = 200.0
    echelle = taille / police.ttf.unites_par_em
    contours = police.ttf.contours(chr(police_pixel.CERCLE))
    polys = [toile.aplatir(c, echelle, 0.0, 200.0) for c in contours]
    x0, y0, largeur, hauteur, valeurs = toile.couverture(polys)
    aire = sum(min(1.0, v) for v in valeurs)
    attendu = police_pixel.AIRE_CERCLE_UNITES2 * echelle * echelle
    assert aire == pytest.approx(attendu, rel=0.02)


def test_composites_aire_deux_fois_et_un_quart(police):
    echelle = 0.2

    def aire(caractere):
        polys = [toile.aplatir(c, echelle, 0.0, 200.0) for c in police.ttf.contours(caractere)]
        _x, _y, _w, _h, valeurs = toile.couverture(polys)
        return sum(min(1.0, v) for v in valeurs)

    base = police_pixel.AIRE_CERCLE_UNITES2 * echelle * echelle
    assert aire(chr(police_pixel.DEUX_CERCLES)) == pytest.approx(2 * base, rel=0.02)
    assert aire(chr(police_pixel.CERCLE_REDUIT)) == pytest.approx(base / 4, rel=0.03)


def test_texte_deterministe_et_encre_dans_la_boite(police):
    def rendu():
        t = toile.Toile(200, 60, (255, 255, 255))
        t.texte(police, "Allô 514", 10, 40, 30, (0, 0, 0))
        return bytes(t.pixels)

    a, b = rendu(), rendu()
    assert a == b
    t = toile.Toile(200, 60, (255, 255, 255))
    t.texte(police, "I", 10, 40, 30, (0, 0, 0))
    encre = [(i // 3) for i in range(0, len(t.pixels), 3) if t.pixels[i] < 128]
    assert encre, "le glyphe doit laisser de l'encre"
    xs = [p % 200 for p in encre]
    ys = [p // 200 for p in encre]
    assert min(xs) >= 10 and max(xs) <= 10 + 3 * 5 + 1
    assert max(ys) <= 39 and min(ys) >= 40 - 21 - 1  # 7 cellules de 3 px au-dessus de la ligne de base


def test_texte_sans_glyphe_refuse(police):
    t = toile.Toile(50, 50)
    with pytest.raises(polices.PoliceErreur):
        t.texte(police, "日本", 0, 20, 12, (0, 0, 0))


def test_contraste_wcag_valeurs_connues():
    assert toile.rapport_contraste((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert toile.rapport_contraste((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0)
    assert toile.rapport_contraste((119, 119, 119), (255, 255, 255)) == pytest.approx(4.48, abs=0.02)


def test_couleurs_hex():
    assert toile.couleur_hex("#0A141E") == (10, 20, 30)
    assert toile.hex_couleur((10, 20, 30)) == "#0A141E"
    for mauvais in ("0A141E", "#0A14", "#GGGGGG", 12):
        with pytest.raises(ValueError):
            toile.couleur_hex(mauvais)


def test_image_couvrir_rogne_au_centre():
    # Image 4x2 : colonne 0 rouge, 1-2 verts, 3 bleue ; destination carrée 2x2 : le rognage centré garde 1-2.
    pixels = b"".join(bytes(c) for _ in range(2) for c in ((255, 0, 0), (0, 255, 0), (0, 255, 0), (0, 0, 255)))
    t = toile.Toile(2, 2)
    t.image_couvrir(ImageRVB(4, 2, pixels), 0, 0, 2, 2)
    assert set(bytes(t.pixels[i : i + 3]) for i in range(0, 12, 3)) == {bytes((0, 255, 0))}
