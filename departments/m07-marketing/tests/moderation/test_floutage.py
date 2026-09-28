"""Tests — orchestration du floutage (détecteur injecté + seuil de confiance), PLAN T4.3.

Détecteur toujours FAUX ici (jamais une vraie brique, jamais une vraie personne/plaque) : c'est
précisément le point d'injection que `moderation.detection.Detecteur` existe pour permettre.
"""

from __future__ import annotations

import inspect

import pytest
from m7_marketing.moderation.detection import Detection
from m7_marketing.moderation.floutage import SeuilInvalide, flouter_photo
from m7_marketing.moderation.image import Boite, DimensionInvalide, ImageSynthetique

ROUGE = (255, 0, 0)


def _image_unie(largeur: int, hauteur: int, couleur=ROUGE) -> ImageSynthetique:
    return ImageSynthetique(largeur=largeur, hauteur=hauteur, pixels=(couleur,) * (largeur * hauteur))


class _DetecteurFixe:
    """Faux détecteur déterministe : retourne toujours les mêmes détections, peu importe
    l'image — suffisant pour tester la logique de `floutage.py` sans brique réelle."""

    def __init__(self, detections):
        self._detections = detections

    def detecter(self, image):
        return list(self._detections)


class _DetecteurQuiExplose:
    def detecter(self, image):
        raise RuntimeError("détecteur en panne")


# ---------------------------------------------------------------------------
# Détections toutes confiantes -> aucune revue humaine requise
# ---------------------------------------------------------------------------
def test_detections_confiantes_ne_requierent_aucune_revue():
    image = _image_unie(4, 4)
    detecteur = _DetecteurFixe(
        [Detection(type="visage", boite=Boite(0, 0, 2, 2), confiance=0.95)]
    )
    image_floutee, rapport = flouter_photo("photo-1", image, detecteur, seuil_confiance=0.8)

    assert rapport.revue_humaine_requise is False
    assert rapport.motif_revue_humaine is None
    assert len(rapport.detections) == 1
    assert rapport.detections[0].doute is False
    assert rapport.detections[0].floutee is True
    assert image_floutee.largeur == image.largeur and image_floutee.hauteur == image.hauteur
    assert rapport.reference == "photo-1"


# ---------------------------------------------------------------------------
# Doute de détection (confiance sous le seuil fourni) -> revue humaine OBLIGATOIRE
# ---------------------------------------------------------------------------
def test_doute_de_detection_force_la_revue_humaine():
    image = _image_unie(4, 4)
    detecteur = _DetecteurFixe(
        [
            Detection(type="visage", boite=Boite(0, 0, 2, 2), confiance=0.95),
            Detection(type="plaque", boite=Boite(2, 2, 2, 2), confiance=0.40),
        ]
    )
    _, rapport = flouter_photo("photo-2", image, detecteur, seuil_confiance=0.80)

    assert rapport.revue_humaine_requise is True
    assert rapport.motif_revue_humaine is not None
    assert "plaque" in rapport.motif_revue_humaine
    assert "0.40" in rapport.motif_revue_humaine
    # Les DEUX détections sont tout de même floutées (plus prudent), le doute ne dispense pas
    # du floutage — seule la publication automatique est bloquée (hors périmètre de ce module).
    assert all(t.floutee for t in rapport.detections)
    doutes = [t for t in rapport.detections if t.doute]
    assert len(doutes) == 1
    assert doutes[0].detection.type == "plaque"


def test_confiance_exactement_au_seuil_nest_pas_un_doute():
    """`doute = confiance < seuil` (strictement inférieur) : au seuil pile, ce n'est pas un
    doute — un seuil est une frontière explicite, jamais une zone grise supplémentaire."""
    image = _image_unie(2, 2)
    detecteur = _DetecteurFixe([Detection(type="visage", boite=Boite(0, 0, 1, 1), confiance=0.5)])
    _, rapport = flouter_photo("photo-3", image, detecteur, seuil_confiance=0.5)
    assert rapport.revue_humaine_requise is False


# ---------------------------------------------------------------------------
# Aucune détection : résultat valide, image inchangée
# ---------------------------------------------------------------------------
def test_aucune_detection_image_inchangee():
    image = _image_unie(3, 3)
    detecteur = _DetecteurFixe([])
    image_floutee, rapport = flouter_photo("photo-4", image, detecteur, seuil_confiance=0.8)
    assert image_floutee == image
    assert rapport.detections == ()
    assert rapport.revue_humaine_requise is False


# ---------------------------------------------------------------------------
# Fail-closed : seuil hors bornes, floutage qui échoue vraiment
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("seuil", [-0.1, 1.1])
def test_seuil_hors_bornes_refuse(seuil):
    image = _image_unie(2, 2)
    with pytest.raises(SeuilInvalide):
        flouter_photo("photo-5", image, _DetecteurFixe([]), seuil_confiance=seuil)


def test_boite_de_detection_hors_image_echoue_sans_publication_partielle():
    """Une détection dont la boîte est hors image doit faire échouer tout l'appel — jamais une
    photo mise en file à moitié floutée."""
    image = _image_unie(2, 2)
    detecteur = _DetecteurFixe([Detection(type="visage", boite=Boite(50, 50, 5, 5), confiance=0.9)])
    with pytest.raises(DimensionInvalide):
        flouter_photo("photo-6", image, detecteur, seuil_confiance=0.8)


def test_erreur_du_detecteur_se_propage():
    image = _image_unie(2, 2)
    with pytest.raises(RuntimeError, match="panne"):
        flouter_photo("photo-7", image, _DetecteurQuiExplose(), seuil_confiance=0.8)


def test_module_pur_floutage_naimporte_jamais_opsys():
    from m7_marketing.moderation import floutage as module_floutage

    source = inspect.getsource(module_floutage)
    assert "import opsys" not in source
    assert "from opsys" not in source
