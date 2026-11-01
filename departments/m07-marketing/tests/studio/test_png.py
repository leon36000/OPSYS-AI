"""PNG en Python pur : aller-retour, métadonnées, refus des formats non pris en charge, entrées hostiles."""

from __future__ import annotations

import struct
import zlib

import pytest
from m7_marketing.studio import png


def _image(largeur=7, hauteur=5):
    return png.ImageRVB(
        largeur,
        hauteur,
        bytes((x * 31 + y * 17 + c * 5) % 256 for y in range(hauteur) for x in range(largeur) for c in range(3)),
    )


def test_aller_retour_exact_et_metadonnees():
    image = _image()
    octets = png.encoder(image, {"OPSYS-IA": "genere", "Provenance": "abc123"})
    assert octets.startswith(png.SIGNATURE)
    assert png.decoder(octets) == image
    assert png.metadonnees(octets) == {"OPSYS-IA": "genere", "Provenance": "abc123"}
    assert png.dimensions(octets) == (7, 5)


def test_encodage_deterministe():
    assert png.encoder(_image(), {"b": "2", "a": "1"}) == png.encoder(_image(), {"a": "1", "b": "2"})


def test_dimensions_et_tampon_incoherents_refuses():
    with pytest.raises(png.PngInvalide):
        png.ImageRVB(2, 2, b"\x00" * 11)
    with pytest.raises(png.PngInvalide):
        png.ImageRVB(0, 2, b"")
    with pytest.raises(png.PngInvalide):
        png.ImageRVB(png.DIMENSION_MAX + 1, 1, b"\x00" * 3 * (png.DIMENSION_MAX + 1))


def test_metadonnee_non_latin1_ou_cle_invalide_refusee():
    with pytest.raises(png.PngInvalide):
        png.encoder(_image(), {"cle": "œuvre €"})
    with pytest.raises(png.PngInvalide):
        png.encoder(_image(), {"": "x"})
    with pytest.raises(png.PngInvalide):
        png.encoder(_image(), {"clé": "x"})


def _bloc(type_bloc, donnees):
    return struct.pack(">I", len(donnees)) + type_bloc + donnees + struct.pack(">I", zlib.crc32(type_bloc + donnees))


def _png_brut(couleur, canaux, largeur=2, hauteur=2, filtres=None, profondeur=8, entrelace=0):
    filtres = filtres or [0] * hauteur
    lignes = b""
    for y in range(hauteur):
        lignes += bytes([filtres[y]]) + bytes((10 * (y + 1) + i) % 256 for i in range(canaux * largeur))
    ihdr = struct.pack(">IIBBBBB", largeur, hauteur, profondeur, couleur, 0, 0, entrelace)
    return png.SIGNATURE + _bloc(b"IHDR", ihdr) + _bloc(b"IDAT", zlib.compress(lignes)) + _bloc(b"IEND", b"")


@pytest.mark.parametrize("filtre", [0, 1, 2, 3, 4])
def test_les_cinq_filtres_png_sont_defiltres_comme_la_norme(filtre):
    # Référence indépendante : on filtre nous-mêmes une image connue puis on compare au décodage.
    largeur, hauteur = 4, 3
    attendu = bytes((x * 40 + y * 60 + c * 7) % 256 for y in range(hauteur) for x in range(largeur) for c in range(3))
    lignes = b""
    precedente = bytes(3 * largeur)
    for y in range(hauteur):
        courante = attendu[y * 12 : (y + 1) * 12]
        filtree = bytearray()
        for i, v in enumerate(courante):
            a = courante[i - 3] if i >= 3 else 0
            b = precedente[i]
            c = precedente[i - 3] if i >= 3 else 0
            if filtre == 0:
                p = 0
            elif filtre == 1:
                p = a
            elif filtre == 2:
                p = b
            elif filtre == 3:
                p = (a + b) // 2
            else:
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                p = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
            filtree.append((v - p) & 0xFF)
        lignes += bytes([filtre]) + bytes(filtree)
        precedente = courante
    ihdr = struct.pack(">IIBBBBB", largeur, hauteur, 8, 2, 0, 0, 0)
    brut = png.SIGNATURE + _bloc(b"IHDR", ihdr) + _bloc(b"IDAT", zlib.compress(lignes)) + _bloc(b"IEND", b"")
    assert png.decoder(brut).pixels == attendu


def test_gris_et_rvba_lus_alpha_sur_blanc():
    gris = png.decoder(_png_brut(0, 1))
    assert gris.pixels[:3] == bytes((10, 10, 10))
    rvba = _png_brut(6, 4)
    image = png.decoder(rvba)
    assert len(image.pixels) == 2 * 2 * 3


@pytest.mark.parametrize(("couleur", "profondeur", "entrelace"), [(3, 8, 0), (2, 16, 0), (2, 8, 1), (5, 8, 0)])
def test_formats_non_pris_en_charge_refuses_avec_code(couleur, profondeur, entrelace):
    brut = _png_brut(couleur if couleur != 3 else 2, 3, profondeur=profondeur, entrelace=entrelace)
    if couleur == 3:
        brut = brut.replace(b"IHDR", b"IHDR")  # palette : couleur 3 dans l'en-tête
        ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 3, 0, 0, 0)
        brut = (
            png.SIGNATURE
            + _bloc(b"IHDR", ihdr)
            + _bloc(b"PLTE", b"\x00" * 3)
            + _bloc(b"IDAT", zlib.compress(b"\x00\x00\x00" * 2))
            + _bloc(b"IEND", b"")
        )
    with pytest.raises(png.PngInvalide) as erreur:
        png.decoder(brut)
    assert erreur.value.code in (png.REJ_PNG_NON_PRIS_EN_CHARGE, png.REJ_PNG)


@pytest.mark.parametrize("mutation", ["crc", "tronque", "signature", "iend", "bombe"])
def test_entrees_hostiles_refusees_sans_exception_brute(mutation):
    octets = png.encoder(_image())
    if mutation == "crc":
        octets = octets[:-5] + bytes([octets[-5] ^ 1]) + octets[-4:]
        octets = octets[:20] + bytes([octets[20] ^ 0xFF]) + octets[21:]
    elif mutation == "tronque":
        octets = octets[:40]
    elif mutation == "signature":
        octets = b"XPNG" + octets[4:]
    elif mutation == "iend":
        octets = octets[:-12]
    else:
        ihdr = struct.pack(">IIBBBBB", 100, 100, 8, 2, 0, 0, 0)
        octets = (
            png.SIGNATURE
            + _bloc(b"IHDR", ihdr)
            + _bloc(b"IDAT", zlib.compress(b"\x00" * 10_000_000))
            + _bloc(b"IEND", b"")
        )
    with pytest.raises(png.PngInvalide):
        png.decoder(octets)
