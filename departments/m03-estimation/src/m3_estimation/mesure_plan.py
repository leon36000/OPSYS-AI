"""Géométrie préparatoire d'un segment dans un plan M3.

Cette tranche ne détecte ni ne segmente un objet et n'accepte pas de photo
réelle. Elle projette des points explicitement fournis sur un plan métrique,
à partir d'une image synthétique en mémoire et d'un profil caméra versionné.
Une future collecte réelle doit passer par un adaptateur M3 autorisé avant
toute lecture/décodage d'octets; cette fonction n'est pas un endpoint.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "CodeRefusMesure",
    "CorrespondancesPlan",
    "ModeSource",
    "ProfilCalibrationCamera",
    "ProvenanceMesure",
    "ResultatMesure",
    "RefusMesure",
    "mesurer_segment_plan",
]

VERSION_ALGORITHME = "m3-homographie-plan-v1"
VERSION_PROFIL_CAMERA = "m3-profil-camera-v1"
_LARGEUR_MAX_PX = 8192
_PIXELS_MAX = 24_000_000
_POINTS_MAX = 32
_POINTS_TOTAL_MAX = 64
_COORDONNEE_PLANE_MAX_M = 500.0
_RESIDU_MAX_M = 0.05
_IDENTIFIANT_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class ModeSource(StrEnum):
    """Sources fermées. Les photos réelles restent refusées dans cette tranche."""

    SYNTHESE_FICTIVE = "SYNTHESE_FICTIVE"
    PHOTO_REELLE = "PHOTO_REELLE"


class CodeRefusMesure(StrEnum):
    PHOTO_REELLE_NON_AUTORISEE = "PHOTO_REELLE_NON_AUTORISEE"
    DEPENDANCE_INDISPONIBLE = "DEPENDANCE_INDISPONIBLE"
    CALIBRATION_INVALIDE = "CALIBRATION_INVALIDE"
    IMAGE_INVALIDE = "IMAGE_INVALIDE"
    RESOLUTION_INCOMPATIBLE = "RESOLUTION_INCOMPATIBLE"
    COPLANARITE_NON_ATTESTEE = "COPLANARITE_NON_ATTESTEE"
    POINTS_INSUFFISANTS = "POINTS_INSUFFISANTS"
    POINTS_INVALIDES = "POINTS_INVALIDES"
    GEOMETRIE_DEGENEREE = "GEOMETRIE_DEGENEREE"
    RESIDU_CONTROLE_DEPASSE = "RESIDU_CONTROLE_DEPASSE"
    SEUIL_INVALIDE = "SEUIL_INVALIDE"
    CALCUL_IMPOSSIBLE = "CALCUL_IMPOSSIBLE"


@dataclass(frozen=True)
class ProfilCalibrationCamera:
    """Profil caméra immuable; son empreinte couvre toutes les valeurs de calibration."""

    version: str
    identifiant: str
    resolution_px: tuple[int, int]
    matrice_intrinseque: tuple[tuple[float, float, float], ...]
    coefficients_distorsion: tuple[float, float, float, float, float]
    empreinte_sha256: str

    @classmethod
    def creer(
        cls,
        *,
        identifiant: str,
        resolution_px: tuple[int, int],
        matrice_intrinseque: tuple[tuple[float, float, float], ...],
        coefficients_distorsion: tuple[float, float, float, float, float],
        version: str = VERSION_PROFIL_CAMERA,
    ) -> ProfilCalibrationCamera:
        """Construit l'empreinte canonique du profil sans prétendre valider sa calibration."""
        candidat = cls(
            version=version,
            identifiant=identifiant,
            resolution_px=resolution_px,
            matrice_intrinseque=matrice_intrinseque,
            coefficients_distorsion=coefficients_distorsion,
            empreinte_sha256="",
        )
        empreinte = _empreinte_profil(candidat)
        return cls(
            version=version,
            identifiant=identifiant,
            resolution_px=resolution_px,
            matrice_intrinseque=matrice_intrinseque,
            coefficients_distorsion=coefficients_distorsion,
            empreinte_sha256=empreinte,
        )


@dataclass(frozen=True)
class CorrespondancesPlan:
    """Coordonnées ajustement et contrôle tenues séparément, dans pixels et mètres."""

    pixels_ajustement: tuple[tuple[float, float], ...]
    coordonnees_ajustement_m: tuple[tuple[float, float], ...]
    pixels_controle: tuple[tuple[float, float], ...]
    coordonnees_controle_m: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class ProvenanceMesure:
    source: str
    sha256_image: str
    sha256_profil_calibration: str
    version_profil_calibration: str
    resolution_px: tuple[int, int]
    version_algorithme: str
    version_opencv: str
    nombre_points_ajustement: int
    nombre_points_controle: int
    pixels_ajustement: tuple[tuple[float, float], ...]
    coordonnees_ajustement_m: tuple[tuple[float, float], ...]
    pixels_controle: tuple[tuple[float, float], ...]
    coordonnees_controle_m: tuple[tuple[float, float], ...]
    conditionnement_ajustement: float
    residus_controle_m: tuple[float, ...]
    seuil_residu_maximal_m: float
    coplanarite_attestee: bool
    extremites_image_px: tuple[tuple[float, float], tuple[float, float]]
    extremites_plan_m: tuple[tuple[float, float], tuple[float, float]]


@dataclass(frozen=True)
class ResultatMesure:
    statut: str
    longueur_projetee_m: float
    incertitude_terrain: str
    faits: tuple[str, ...]
    hypotheses: tuple[str, ...]
    provenance: ProvenanceMesure


@dataclass(frozen=True)
class RefusMesure:
    statut: str
    code: CodeRefusMesure
    detail: str


def _refuser(code: CodeRefusMesure, detail: str) -> RefusMesure:
    return RefusMesure(statut="REFUS", code=code, detail=detail)


def _est_nombre_fini(valeur: Any) -> bool:
    if type(valeur) not in (int, float):
        return False
    try:
        return math.isfinite(valeur)
    except OverflowError:
        return False


def _charge_utile_profil(profil: ProfilCalibrationCamera) -> dict[str, Any]:
    return {
        "version": profil.version,
        "identifiant": profil.identifiant,
        "resolution_px": profil.resolution_px,
        "matrice_intrinseque": profil.matrice_intrinseque,
        "coefficients_distorsion": profil.coefficients_distorsion,
    }


def _empreinte_profil(profil: ProfilCalibrationCamera) -> str:
    contenu = json.dumps(
        _charge_utile_profil(profil),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(contenu).hexdigest()


def _valider_profil(profil: Any) -> tuple[CodeRefusMesure, str] | None:
    if not isinstance(profil, ProfilCalibrationCamera):
        return CodeRefusMesure.CALIBRATION_INVALIDE, "profil caméra absent ou de type invalide"
    if (
        not isinstance(profil.version, str)
        or profil.version != VERSION_PROFIL_CAMERA
        or not isinstance(profil.identifiant, str)
        or not _IDENTIFIANT_RE.fullmatch(profil.identifiant)
    ):
        return CodeRefusMesure.CALIBRATION_INVALIDE, "version ou identifiant de profil non admis"
    if (
        not isinstance(profil.resolution_px, tuple)
        or len(profil.resolution_px) != 2
        or any(type(n) is not int or n <= 0 or n > _LARGEUR_MAX_PX for n in profil.resolution_px)
        or profil.resolution_px[0] * profil.resolution_px[1] > _PIXELS_MAX
    ):
        return CodeRefusMesure.CALIBRATION_INVALIDE, "résolution du profil invalide"
    if (
        not isinstance(profil.matrice_intrinseque, tuple)
        or len(profil.matrice_intrinseque) != 3
        or any(not isinstance(ligne, tuple) or len(ligne) != 3 for ligne in profil.matrice_intrinseque)
        or any(not _est_nombre_fini(valeur) for ligne in profil.matrice_intrinseque for valeur in ligne)
    ):
        return CodeRefusMesure.CALIBRATION_INVALIDE, "matrice intrinsèque invalide"
    k = profil.matrice_intrinseque
    if (
        k[0][0] <= 0
        or k[1][1] <= 0
        or k[2] != (0, 0, 1)
        or not (0 <= k[0][2] < profil.resolution_px[0])
        or not (0 <= k[1][2] < profil.resolution_px[1])
    ):
        return CodeRefusMesure.CALIBRATION_INVALIDE, "intrinsèques caméra hors bornes"
    if (
        not isinstance(profil.coefficients_distorsion, tuple)
        or len(profil.coefficients_distorsion) != 5
        or any(not _est_nombre_fini(x) or abs(x) > 2 for x in profil.coefficients_distorsion)
    ):
        return CodeRefusMesure.CALIBRATION_INVALIDE, "cinq coefficients de distorsion finis sont requis"
    if not isinstance(profil.empreinte_sha256, str) or not _SHA256_RE.fullmatch(profil.empreinte_sha256):
        return CodeRefusMesure.CALIBRATION_INVALIDE, "empreinte de profil invalide"
    try:
        empreinte_attendue = _empreinte_profil(profil)
    except (TypeError, ValueError):
        return CodeRefusMesure.CALIBRATION_INVALIDE, "profil non sérialisable canoniquement"
    if profil.empreinte_sha256 != empreinte_attendue:
        return CodeRefusMesure.CALIBRATION_INVALIDE, "empreinte du profil discordante"
    return None


def _tableau_points(np: Any, valeurs: Any, maximum: int) -> Any | None:
    if not isinstance(valeurs, (tuple, list)) or not 1 <= len(valeurs) <= maximum:
        return None
    points = []
    for point in valeurs:
        if (
            not isinstance(point, (tuple, list))
            or len(point) != 2
            or any(not _est_nombre_fini(x) for x in point)
        ):
            return None
        points.append((float(point[0]), float(point[1])))
    return np.asarray(points, dtype=np.float64)


def _points_distincts(np: Any, points: Any) -> bool:
    return len(np.unique(np.round(points, decimals=9), axis=0)) == len(points)


def _dimension_plane(np: Any, points: Any) -> bool:
    centres = points - np.mean(points, axis=0)
    valeurs = np.linalg.svd(centres, compute_uv=False)
    return len(valeurs) >= 2 and valeurs[0] > 1e-12 and valeurs[1] > valeurs[0] * 1e-6


def _condition_dlt(np: Any, source: Any, destination: Any) -> float:
    def normaliser(points: Any) -> Any:
        centre = np.mean(points, axis=0)
        distances = np.linalg.norm(points - centre, axis=1)
        moyenne = float(np.mean(distances))
        if not math.isfinite(moyenne) or moyenne <= 1e-12:
            raise ValueError("points confondus")
        echelle = math.sqrt(2.0) / moyenne
        return (points - centre) * echelle

    src = normaliser(source)
    dst = normaliser(destination)
    lignes = []
    for (x, y), (u, v) in zip(src, dst, strict=True):
        lignes.append((-x, -y, -1.0, 0.0, 0.0, 0.0, u * x, u * y, u))
        lignes.append((0.0, 0.0, 0.0, -x, -y, -1.0, v * x, v * y, v))
    design = np.asarray(lignes, dtype=np.float64)
    valeurs = np.linalg.svd(design, compute_uv=False)
    plus_petite_non_nulle = valeurs[-2] if len(valeurs) >= 9 else valeurs[-1]
    if plus_petite_non_nulle <= valeurs[0] * 1e-12:
        raise ValueError("matrice de correspondances mal conditionnée")
    return float(valeurs[0] / plus_petite_non_nulle)


def _undistordre_points(cv2: Any, np: Any, points: Any, matrice: Any, distorsion: Any) -> Any:
    entree = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
    sortie = cv2.undistortPoints(entree, matrice, distorsion, P=matrice)
    return sortie.reshape(-1, 2)


def _projeter_points(cv2: Any, np: Any, points: Any, homographie: Any) -> Any:
    entree = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
    sortie = cv2.perspectiveTransform(entree, homographie)
    return sortie.reshape(-1, 2)


def mesurer_segment_plan(
    profil: ProfilCalibrationCamera,
    image_bgr: Any,
    correspondances: CorrespondancesPlan,
    extremites_px: tuple[tuple[float, float], tuple[float, float]],
    *,
    source: ModeSource,
    coplanarite_attestee: bool,
    residu_maximal_m: float,
) -> ResultatMesure | RefusMesure:
    """Projette deux extrémités dans le plan métrique après contrôles fail-closed.

    La fonction n'ouvre pas de fichier et n'accepte que ``SYNTHESE_FICTIVE``.
    Points de calibration et de validation sont fournis séparément; les points
    de validation ne participent jamais à l'ajustement de l'homographie.
    """
    if source is not ModeSource.SYNTHESE_FICTIVE:
        return _refuser(
            CodeRefusMesure.PHOTO_REELLE_NON_AUTORISEE,
            "seules les images synthétiques sont admises avant l'adaptateur M3 autorisé",
        )
    if type(coplanarite_attestee) is not bool or coplanarite_attestee is not True:
        return _refuser(
            CodeRefusMesure.COPLANARITE_NON_ATTESTEE,
            "les correspondances, la cible et le segment doivent être attestés dans un même plan",
        )
    if (
        not _est_nombre_fini(residu_maximal_m)
        or residu_maximal_m <= 0
        or residu_maximal_m > _RESIDU_MAX_M
    ):
        return _refuser(
            CodeRefusMesure.SEUIL_INVALIDE,
            f"le seuil explicite doit être supérieur à 0 et inférieur ou égal à {_RESIDU_MAX_M} m",
        )

    try:
        import cv2
        import numpy as np
    except ImportError:
        return _refuser(CodeRefusMesure.DEPENDANCE_INDISPONIBLE, "OpenCV et NumPy sont requis")

    rejet_profil = _valider_profil(profil)
    if rejet_profil is not None:
        return _refuser(*rejet_profil)
    if (
        not isinstance(image_bgr, np.ndarray)
        or image_bgr.dtype != np.uint8
        or image_bgr.ndim != 3
        or image_bgr.shape[2] != 3
        or not image_bgr.flags.c_contiguous
    ):
        return _refuser(CodeRefusMesure.IMAGE_INVALIDE, "image synthétique BGR contiguë uint8 requise")
    hauteur, largeur = image_bgr.shape[:2]
    if (
        largeur <= 0
        or hauteur <= 0
        or largeur > _LARGEUR_MAX_PX
        or hauteur > _LARGEUR_MAX_PX
        or largeur * hauteur > _PIXELS_MAX
    ):
        return _refuser(CodeRefusMesure.IMAGE_INVALIDE, "dimensions image hors bornes")
    if profil.resolution_px != (largeur, hauteur):
        return _refuser(CodeRefusMesure.RESOLUTION_INCOMPATIBLE, "résolution image/profil discordante")
    if not isinstance(correspondances, CorrespondancesPlan):
        return _refuser(CodeRefusMesure.POINTS_INVALIDES, "correspondances de plan absentes ou de type invalide")

    pixels_fit = _tableau_points(np, correspondances.pixels_ajustement, _POINTS_MAX)
    metres_fit = _tableau_points(np, correspondances.coordonnees_ajustement_m, _POINTS_MAX)
    pixels_test = _tableau_points(np, correspondances.pixels_controle, _POINTS_MAX)
    metres_test = _tableau_points(np, correspondances.coordonnees_controle_m, _POINTS_MAX)
    if any(points is None for points in (pixels_fit, metres_fit, pixels_test, metres_test)):
        return _refuser(CodeRefusMesure.POINTS_INVALIDES, "points pixels/métriques invalides ou absents")
    if len(pixels_fit) != len(metres_fit) or len(pixels_test) != len(metres_test):
        return _refuser(CodeRefusMesure.POINTS_INVALIDES, "chaque point pixel doit avoir sa coordonnée métrique")
    if (
        len(pixels_fit) < 4
        or len(pixels_test) < 2
        or len(pixels_fit) + len(pixels_test) > _POINTS_TOTAL_MAX
    ):
        return _refuser(
            CodeRefusMesure.POINTS_INSUFFISANTS,
            "quatre correspondances d'ajustement et deux contrôles indépendants sont requis",
        )
    pixels_tous = np.vstack((pixels_fit, pixels_test))
    metres_tous = np.vstack((metres_fit, metres_test))
    if (
        not _points_distincts(np, pixels_tous)
        or not _points_distincts(np, metres_tous)
        or np.any(pixels_tous[:, 0] < 0)
        or np.any(pixels_tous[:, 0] >= largeur)
        or np.any(pixels_tous[:, 1] < 0)
        or np.any(pixels_tous[:, 1] >= hauteur)
        or np.any(np.abs(metres_tous) > _COORDONNEE_PLANE_MAX_M)
    ):
        return _refuser(CodeRefusMesure.POINTS_INVALIDES, "correspondances dupliquées ou hors bornes")
    if not _dimension_plane(np, pixels_fit) or not _dimension_plane(np, metres_fit):
        return _refuser(CodeRefusMesure.GEOMETRIE_DEGENEREE, "les points d'ajustement ne couvrent pas un plan 2D")

    points_terminaux = _tableau_points(np, extremites_px, 2)
    if (
        points_terminaux is None
        or len(points_terminaux) != 2
        or np.any(points_terminaux[:, 0] < 0)
        or np.any(points_terminaux[:, 0] >= largeur)
        or np.any(points_terminaux[:, 1] < 0)
        or np.any(points_terminaux[:, 1] >= hauteur)
        or not _points_distincts(np, points_terminaux)
    ):
        return _refuser(CodeRefusMesure.POINTS_INVALIDES, "deux extrémités distinctes dans l'image sont requises")

    matrice = np.asarray(profil.matrice_intrinseque, dtype=np.float64)
    distorsion = np.asarray(profil.coefficients_distorsion, dtype=np.float64).reshape(1, 5)
    try:
        pixels_fit_corriges = _undistordre_points(cv2, np, pixels_fit, matrice, distorsion)
        pixels_test_corriges = _undistordre_points(cv2, np, pixels_test, matrice, distorsion)
        pixels_extremites_corriges = _undistordre_points(cv2, np, points_terminaux, matrice, distorsion)
        conditionnement = _condition_dlt(np, pixels_fit_corriges, metres_fit)
        if not math.isfinite(conditionnement) or conditionnement > 1e8:
            raise ValueError("conditionnement supérieur au seuil numérique")
        homographie, _masque = cv2.findHomography(pixels_fit_corriges, metres_fit, method=0)
        if homographie is None or homographie.shape != (3, 3) or not np.isfinite(homographie).all():
            raise ValueError("homographie absente ou non finie")
        norme = float(np.linalg.norm(homographie))
        if norme <= 1e-15:
            raise ValueError("homographie nulle")
        homographie_normalisee = homographie / norme
        if abs(float(np.linalg.det(homographie_normalisee))) <= 1e-15:
            raise ValueError("homographie singulière")

        controles_projetes = _projeter_points(cv2, np, pixels_test_corriges, homographie)
        erreurs = np.linalg.norm(controles_projetes - metres_test, axis=1)
        if not np.isfinite(erreurs).all():
            raise ValueError("résidu de contrôle non fini")
        erreurs_tuple = tuple(float(x) for x in erreurs)
        if max(erreurs_tuple) > residu_maximal_m:
            return _refuser(
                CodeRefusMesure.RESIDU_CONTROLE_DEPASSE,
                "au moins un point de contrôle dépasse le seuil de reprojection fourni",
            )

        plan_extremites = _projeter_points(cv2, np, pixels_extremites_corriges, homographie)
        if not np.isfinite(plan_extremites).all() or np.any(np.abs(plan_extremites) > _COORDONNEE_PLANE_MAX_M):
            raise ValueError("extrémités projetées hors bornes")
        longueur = float(np.linalg.norm(plan_extremites[1] - plan_extremites[0]))
        if not math.isfinite(longueur) or longueur <= 0 or longueur > 2 * _COORDONNEE_PLANE_MAX_M:
            raise ValueError("longueur projetée nulle ou hors bornes")
    except (cv2.error, np.linalg.LinAlgError, TypeError, ValueError, OverflowError):
        return _refuser(CodeRefusMesure.GEOMETRIE_DEGENEREE, "transformation projective invalide ou mal conditionnée")

    image_digest = hashlib.sha256(memoryview(image_bgr).cast("B")).hexdigest()
    ext_plan = tuple((float(x), float(y)) for x, y in plan_extremites)
    ext_pixels = tuple((float(x), float(y)) for x, y in points_terminaux)
    provenance = ProvenanceMesure(
        source=ModeSource.SYNTHESE_FICTIVE.value,
        sha256_image=image_digest,
        sha256_profil_calibration=profil.empreinte_sha256,
        version_profil_calibration=profil.version,
        resolution_px=profil.resolution_px,
        version_algorithme=VERSION_ALGORITHME,
        version_opencv=cv2.__version__,
        nombre_points_ajustement=len(pixels_fit),
        nombre_points_controle=len(pixels_test),
        pixels_ajustement=tuple(tuple(float(v) for v in point) for point in pixels_fit),
        coordonnees_ajustement_m=tuple(tuple(float(v) for v in point) for point in metres_fit),
        pixels_controle=tuple(tuple(float(v) for v in point) for point in pixels_test),
        coordonnees_controle_m=tuple(tuple(float(v) for v in point) for point in metres_test),
        conditionnement_ajustement=conditionnement,
        residus_controle_m=erreurs_tuple,
        seuil_residu_maximal_m=float(residu_maximal_m),
        coplanarite_attestee=True,
        extremites_image_px=(ext_pixels[0], ext_pixels[1]),
        extremites_plan_m=(ext_plan[0], ext_plan[1]),
    )
    return ResultatMesure(
        statut="PROPOSITION_PREPARATOIRE_NON_QUALIFIEE",
        longueur_projetee_m=longueur,
        incertitude_terrain="NON_QUALIFIEE",
        faits=(
            "longueur calculée par homographie à partir de points opérateur et de coordonnées métriques fournies",
            f"résidu maximal observé sur les points de contrôle indépendants : {max(erreurs_tuple):.9g} m",
            f"empreinte du profil caméra : {profil.empreinte_sha256}",
        ),
        hypotheses=(
            "la cible et le segment appartiennent au même plan rigide",
            "la taille métrique des repères et le profil caméra fournis sont exacts et applicables à cette résolution",
            "les deux extrémités pixel choisies correspondent aux extrémités physiques du segment",
            "le résidu géométrique observé ne constitue pas une incertitude de terrain calibrée",
        ),
        provenance=provenance,
    )
