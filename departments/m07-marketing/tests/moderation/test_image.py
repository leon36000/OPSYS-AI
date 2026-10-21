"""Tests — floutage déterministe pur (PLAN T4.3). Images synthétiques uniquement (jamais une
vraie personne ni une vraie plaque, AGENTS.md « données inventées »)."""

from __future__ import annotations

import pytest
from m7_marketing.moderation.image import (
    Boite,
    DimensionInvalide,
    ImageSynthetique,
    flouter_zone,
)

ROUGE = (255, 0, 0)
VERT = (0, 255, 0)
BLEU = (0, 0, 255)
JAUNE = (255, 255, 0)
NOIR = (0, 0, 0)
BLANC = (255, 255, 255)


def _image_4x1_quatre_couleurs() -> ImageSynthetique:
    """Image 4x1 : rouge, vert, bleu, jaune — synthétique, jamais une vraie photo."""
    return ImageSynthetique(largeur=4, hauteur=1, pixels=(ROUGE, VERT, BLEU, JAUNE))


# ---------------------------------------------------------------------------
# ImageSynthetique / Boite : validation à la construction
# ---------------------------------------------------------------------------
def test_image_nombre_de_pixels_incoherent_refuse():
    with pytest.raises(DimensionInvalide):
        ImageSynthetique(largeur=2, hauteur=2, pixels=(NOIR, BLANC))  # 2 fournis, 4 attendus


def test_image_dimensions_non_positives_refusees():
    with pytest.raises(DimensionInvalide):
        ImageSynthetique(largeur=0, hauteur=2, pixels=())


def test_boite_dimensions_non_positives_refusees():
    with pytest.raises(DimensionInvalide):
        Boite(x=0, y=0, largeur=0, hauteur=1)


# ---------------------------------------------------------------------------
# flouter_zone : pixellisation déterministe par bloc (jamais une moyenne globale de la boîte)
# ---------------------------------------------------------------------------
def test_flouter_zone_moyenne_par_bloc_jamais_globale():
    """Deux blocs de 2 pixels dans une boîte de 4 : chaque bloc obtient SA propre moyenne,
    jamais la moyenne des 4 pixels ensemble — preuve que le floutage est bien PAR BLOC."""
    image = _image_4x1_quatre_couleurs()
    boite = Boite(x=0, y=0, largeur=4, hauteur=1)

    resultat = flouter_zone(image, boite, taille_bloc=2)

    # Bloc 0 (rouge+vert) : (255+0)//2=127, (0+255)//2=127, (0+0)//2=0
    assert resultat.pixels[0] == (127, 127, 0)
    assert resultat.pixels[1] == (127, 127, 0)
    # Bloc 1 (bleu+jaune) : (0+255)//2=127, (0+255)//2=127, (255+0)//2=127
    assert resultat.pixels[2] == (127, 127, 127)
    assert resultat.pixels[3] == (127, 127, 127)
    # Les deux blocs restent DISTINCTS (jamais une moyenne unique sur toute la boîte)
    assert resultat.pixels[0] != resultat.pixels[2]


def test_flouter_zone_ne_mute_jamais_limage_originale():
    image = _image_4x1_quatre_couleurs()
    original = image.pixels
    flouter_zone(image, Boite(x=0, y=0, largeur=4, hauteur=1), taille_bloc=2)
    assert image.pixels == original  # jamais mutée : une nouvelle image est retournée


def test_flouter_zone_hors_de_la_boite_inchange():
    """Seuls les pixels DANS la boîte changent ; le reste de l'image reste identique."""
    image = ImageSynthetique(
        largeur=4,
        hauteur=2,
        pixels=(ROUGE, ROUGE, ROUGE, ROUGE, NOIR, BLANC, NOIR, BLANC),
    )
    # Ne floute que la deuxième rangée (y=1)
    resultat = flouter_zone(image, Boite(x=0, y=1, largeur=4, hauteur=1), taille_bloc=4)
    assert resultat.pixels[0:4] == (ROUGE, ROUGE, ROUGE, ROUGE)  # rangée 0 intacte
    moyenne_attendue = (127, 127, 127)  # (0+255+0+255)//4 par canal
    assert resultat.pixels[4:8] == (moyenne_attendue,) * 4


def test_flouter_zone_boite_partiellement_hors_image_coupee_aux_bords():
    """Une boîte qui déborde de l'image est coupée à ses bords, jamais une erreur d'index."""
    image = _image_4x1_quatre_couleurs()
    resultat = flouter_zone(image, Boite(x=2, y=0, largeur=10, hauteur=10), taille_bloc=2)
    # x=0,1 (rouge, vert) hors boîte -> inchangés ; x=2,3 (bleu, jaune) floutés ensemble
    assert resultat.pixels[0] == ROUGE
    assert resultat.pixels[1] == VERT
    assert resultat.pixels[2] == resultat.pixels[3] == (127, 127, 127)


def test_flouter_zone_boite_entierement_hors_image_refuse():
    """Un floutage qui ne floute rien n'est pas un floutage silencieux : échec nommé
    (M7-audit.md §3.5, « refus fail-closed ... si le floutage échoue »)."""
    image = _image_4x1_quatre_couleurs()
    with pytest.raises(DimensionInvalide):
        flouter_zone(image, Boite(x=100, y=100, largeur=5, hauteur=5))


def test_flouter_zone_taille_bloc_non_positive_refusee():
    image = _image_4x1_quatre_couleurs()
    with pytest.raises(DimensionInvalide):
        flouter_zone(image, Boite(x=0, y=0, largeur=4, hauteur=1), taille_bloc=0)


def test_flouter_zone_deterministe():
    """Mêmes entrées -> mêmes pixels de sortie, à chaque appel."""
    image = _image_4x1_quatre_couleurs()
    boite = Boite(x=0, y=0, largeur=4, hauteur=1)
    resultat1 = flouter_zone(image, boite, taille_bloc=2)
    resultat2 = flouter_zone(image, boite, taille_bloc=2)
    assert resultat1 == resultat2


def test_module_pur_image_naimporte_jamais_opsys():
    import inspect

    from m7_marketing.moderation import image as module_image

    source = inspect.getsource(module_image)
    assert "import opsys" not in source
    assert "from opsys" not in source
