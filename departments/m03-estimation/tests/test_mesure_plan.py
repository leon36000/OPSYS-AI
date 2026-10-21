"""Oracles synthétiques de géométrie pour le pilote photo M3.

Toutes les images sont générées en mémoire par OpenCV à partir de points
connus. Ces cas vérifient le calcul projectif et ses refus; ils ne constituent
ni des données client ni une calibration d'exactitude terrain.
"""

import sys
from dataclasses import replace
from pathlib import Path

import pytest

# Import réel sans mock; les seuls tests ignorés en absence du groupe optionnel
# sont les cas qui calculent des homographies ou fabriquent des pixels.
try:
    import numpy as np
except ImportError:
    np = None

try:
    import cv2
except ImportError:
    cv2 = None

_VISION_EXTRA_ABSENT = cv2 is None or np is None
_RAISON_EXTRA_ABSENT = "sélection géométrique dépendante de l’extra optionnel vision-photo"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m3_estimation.mesure_plan import (  # noqa: E402
    CodeRefusMesure,
    CorrespondancesPlan,
    ModeSource,
    ProfilCalibrationCamera,
    ResultatMesure,
    mesurer_segment_plan,
)


def _cas_synthetique():
    """Construit une perspective et sa vérité métrique à partir d'une pose connue."""
    largeur, hauteur = 800, 600
    matrice = (
        (900.0, 0.0, 400.0),
        (0.0, 900.0, 300.0),
        (0.0, 0.0, 1.0),
    )
    distorsion = (0.08, -0.03, 0.001, -0.002, 0.005)
    profil = ProfilCalibrationCamera.creer(
        identifiant="fixture-camera-synthetique-r1",
        resolution_px=(largeur, hauteur),
        matrice_intrinseque=matrice,
        coefficients_distorsion=distorsion,
    )

    ajustement_m = np.array(
        [[0.0, 0.0], [4.0, 0.0], [4.0, 2.0], [0.0, 2.0], [2.0, 0.4], [1.0, 1.5]],
        dtype=np.float64,
    )
    controle_m = np.array([[1.0, 0.0], [3.2, 1.1], [2.7, 1.8]], dtype=np.float64)
    extremites_m = np.array([[0.5, 1.0], [3.5, 1.0]], dtype=np.float64)

    def projeter(plan):
        points_3d = np.column_stack((plan, np.zeros(len(plan)))).reshape(-1, 1, 3)
        pixels, _ = cv2.projectPoints(
            points_3d,
            np.array([0.1, -0.15, 0.02], dtype=np.float64),
            np.array([-2.0, -1.0, 6.0], dtype=np.float64),
            np.asarray(matrice, dtype=np.float64),
            np.asarray(distorsion, dtype=np.float64),
        )
        return pixels.reshape(-1, 2)

    ajustement_px = projeter(ajustement_m)
    controle_px = projeter(controle_m)
    extremites_px = projeter(extremites_m)
    image = np.zeros((hauteur, largeur, 3), dtype=np.uint8)
    for x, y in np.concatenate((ajustement_px, controle_px, extremites_px)):
        cv2.circle(image, (round(x), round(y)), 4, (0, 255, 255), -1)

    correspondances = CorrespondancesPlan(
        pixels_ajustement=tuple(map(tuple, ajustement_px.tolist())),
        coordonnees_ajustement_m=tuple(map(tuple, ajustement_m.tolist())),
        pixels_controle=tuple(map(tuple, controle_px.tolist())),
        coordonnees_controle_m=tuple(map(tuple, controle_m.tolist())),
    )
    return profil, image, correspondances, tuple(map(tuple, extremites_px.tolist()))


def _mesurer(profil, image, correspondances, extremites, **surcharges):
    arguments = {
        "source": ModeSource.SYNTHESE_FICTIVE,
        "coplanarite_attestee": True,
        "residu_maximal_m": 0.01,
    }
    arguments.update(surcharges)
    return mesurer_segment_plan(profil, image, correspondances, extremites, **arguments)


@pytest.mark.skipif(_VISION_EXTRA_ABSENT, reason=_RAISON_EXTRA_ABSENT)
def test_homographie_perspective_projette_un_segment_en_metres_sans_promesse_terrain():
    profil, image, correspondances, extremites = _cas_synthetique()

    resultat = _mesurer(profil, image, correspondances, extremites)

    assert isinstance(resultat, ResultatMesure)
    assert resultat.statut == "PROPOSITION_PREPARATOIRE_NON_QUALIFIEE"
    assert resultat.longueur_projetee_m == pytest.approx(3.0, abs=0.005)
    assert resultat.incertitude_terrain == "NON_QUALIFIEE"
    assert resultat.provenance.sha256_image == resultat.provenance.sha256_image.lower()
    assert len(resultat.provenance.sha256_image) == 64
    assert resultat.provenance.sha256_profil_calibration == profil.empreinte_sha256
    assert resultat.provenance.version_profil_calibration == profil.version
    assert resultat.provenance.resolution_px == (800, 600)
    assert resultat.provenance.version_opencv == cv2.__version__
    assert len(resultat.provenance.pixels_ajustement) == len(correspondances.pixels_ajustement)
    assert len(resultat.provenance.pixels_controle) == len(correspondances.pixels_controle)
    assert resultat.provenance.conditionnement_ajustement < 1e8
    assert max(resultat.provenance.residus_controle_m) < 0.005
    assert "mesure réelle" not in " ".join(resultat.hypotheses).lower()


def test_photo_reelle_est_refusee_et_extra_absent_est_nommee():
    if _VISION_EXTRA_ABSENT:
        refus_photo = mesurer_segment_plan(
            None,
            None,
            None,
            (),
            source=ModeSource.PHOTO_REELLE,
            coplanarite_attestee=True,
            residu_maximal_m=0.01,
        )
        refus_extra = mesurer_segment_plan(
            None,
            None,
            None,
            (),
            source=ModeSource.SYNTHESE_FICTIVE,
            coplanarite_attestee=True,
            residu_maximal_m=0.01,
        )

        assert refus_photo.code == CodeRefusMesure.PHOTO_REELLE_NON_AUTORISEE
        assert refus_extra.code == CodeRefusMesure.DEPENDANCE_INDISPONIBLE
        return

    profil, image, correspondances, extremites = _cas_synthetique()

    resultat = _mesurer(
        profil,
        image,
        correspondances,
        extremites,
        source=ModeSource.PHOTO_REELLE,
    )

    assert resultat.code == CodeRefusMesure.PHOTO_REELLE_NON_AUTORISEE


@pytest.mark.skipif(_VISION_EXTRA_ABSENT, reason=_RAISON_EXTRA_ABSENT)
def test_refuse_coplanarite_non_attestee():
    profil, image, correspondances, extremites = _cas_synthetique()

    resultat = _mesurer(profil, image, correspondances, extremites, coplanarite_attestee=False)

    assert resultat.code == CodeRefusMesure.COPLANARITE_NON_ATTESTEE


@pytest.mark.skipif(_VISION_EXTRA_ABSENT, reason=_RAISON_EXTRA_ABSENT)
def test_refuse_residu_de_controle_superieur_au_seuil():
    profil, image, correspondances, extremites = _cas_synthetique()
    controle = list(correspondances.coordonnees_controle_m)
    controle[1] = (controle[1][0] + 0.25, controle[1][1])
    correspondances = replace(correspondances, coordonnees_controle_m=tuple(controle))

    resultat = _mesurer(profil, image, correspondances, extremites, residu_maximal_m=0.001)

    assert resultat.code == CodeRefusMesure.RESIDU_CONTROLE_DEPASSE


@pytest.mark.skipif(_VISION_EXTRA_ABSENT, reason=_RAISON_EXTRA_ABSENT)
def test_refuse_correspondances_degenerees_ou_nombre_insuffisant():
    profil, image, correspondances, extremites = _cas_synthetique()
    pixels = correspondances.pixels_ajustement
    metrages = correspondances.coordonnees_ajustement_m
    degeneres = replace(
        correspondances,
        pixels_ajustement=tuple((float(i * 50 + 20), 100.0) for i in range(6)),
        coordonnees_ajustement_m=tuple((float(i), 0.0) for i in range(6)),
        coordonnees_controle_m=((10.0, 0.0), (11.0, 0.0), (12.0, 0.0)),
    )
    peu = replace(
        correspondances,
        pixels_ajustement=pixels[:3],
        coordonnees_ajustement_m=metrages[:3],
    )

    assert _mesurer(profil, image, degeneres, extremites).code == CodeRefusMesure.GEOMETRIE_DEGENEREE
    assert _mesurer(profil, image, peu, extremites).code == CodeRefusMesure.POINTS_INSUFFISANTS


@pytest.mark.skipif(_VISION_EXTRA_ABSENT, reason=_RAISON_EXTRA_ABSENT)
def test_refuse_hash_profil_invalide_et_resolution_differente():
    profil, image, correspondances, extremites = _cas_synthetique()
    mauvais_hash = replace(profil, empreinte_sha256="0" * 64)
    autre_resolution = np.zeros((599, 800, 3), dtype=np.uint8)
    mauvais_identifiant = ProfilCalibrationCamera.creer(
        identifiant=7,
        resolution_px=profil.resolution_px,
        matrice_intrinseque=profil.matrice_intrinseque,
        coefficients_distorsion=profil.coefficients_distorsion,
    )

    resultat_hash = _mesurer(mauvais_hash, image, correspondances, extremites)
    resultat_resolution = _mesurer(profil, autre_resolution, correspondances, extremites)

    assert resultat_hash.code == CodeRefusMesure.CALIBRATION_INVALIDE
    assert resultat_resolution.code == CodeRefusMesure.RESOLUTION_INCOMPATIBLE
    resultat_identifiant = _mesurer(mauvais_identifiant, image, correspondances, extremites)
    assert resultat_identifiant.code == CodeRefusMesure.CALIBRATION_INVALIDE


@pytest.mark.skipif(_VISION_EXTRA_ABSENT, reason=_RAISON_EXTRA_ABSENT)
def test_octets_bruts_ne_sont_pas_acceptes_comme_image_deja_preparee():
    profil, image, correspondances, extremites = _cas_synthetique()

    resultat = _mesurer(profil, image.tobytes(), correspondances, extremites)

    assert resultat.code == CodeRefusMesure.IMAGE_INVALIDE


@pytest.mark.skipif(_VISION_EXTRA_ABSENT, reason=_RAISON_EXTRA_ABSENT)
def test_refuse_coordonnees_non_finies_hors_image_et_valeurs_boolennes():
    profil, image, correspondances, extremites = _cas_synthetique()
    px = list(correspondances.pixels_ajustement)
    px[0] = (float("nan"), px[0][1])
    invalides = replace(correspondances, pixels_ajustement=tuple(px))
    hors_image = ((-1.0, 10.0), extremites[1])
    booleens = ((True, 10.0), extremites[1])

    assert _mesurer(profil, image, invalides, extremites).code == CodeRefusMesure.POINTS_INVALIDES
    assert _mesurer(profil, image, correspondances, hors_image).code == CodeRefusMesure.POINTS_INVALIDES
    assert _mesurer(profil, image, correspondances, booleens).code == CodeRefusMesure.POINTS_INVALIDES


@pytest.mark.skipif(_VISION_EXTRA_ABSENT, reason=_RAISON_EXTRA_ABSENT)
def test_refuse_longueurs_de_tableaux_et_seuils_ambigus():
    profil, image, correspondances, extremites = _cas_synthetique()
    mauvais_nombre = replace(
        correspondances,
        coordonnees_ajustement_m=correspondances.coordonnees_ajustement_m[:-1],
    )

    assert _mesurer(profil, image, mauvais_nombre, extremites).code == CodeRefusMesure.POINTS_INVALIDES
    bool_seuil = _mesurer(profil, image, correspondances, extremites, residu_maximal_m=True)
    seuil_trop_large = _mesurer(profil, image, correspondances, extremites, residu_maximal_m=1.0)

    assert bool_seuil.code == CodeRefusMesure.SEUIL_INVALIDE
    assert seuil_trop_large.code == CodeRefusMesure.SEUIL_INVALIDE
