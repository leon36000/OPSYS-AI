"""Détection injectable de visages et de plaques (PLAN T4.3, M7-audit.md §3.5).

La logique de floutage (`floutage.py`) ne dépend JAMAIS d'une implémentation concrète, seulement
du protocole `Detecteur` ci-dessous — c'est ce qui la rend testable avec un faux détecteur
déterministe piloté par des images synthétiques (jamais une vraie personne ni une vraie plaque,
AGENTS.md « données inventées »), et remplaçable par une vraie implémentation sans toucher la
logique de décision (seuil de confiance, floutage, revue humaine).

Briques retenues pour l'implémentation RÉELLE (recherche de licence, AGENTS.md, inscrites dans
`docs/research/INGREDIENTS.md` § M7 — Marketing) :

  - **Visages** : OpenCV (paquet `opencv-python-headless`, CODE, licence Apache-2.0 depuis la
    version 4.5.0 — vérifié <https://opencv.org/license/>) + le modèle **YuNet**
    (`face_detection_yunet_2023mar.onnx`, POIDS, licence **MIT**, Shiqi Yu 2020 — vérifié dans
    `models/face_detection_yunet/LICENSE` du dépôt github.com/opencv/opencv_zoo, distinct de la
    licence Apache-2.0 du dépôt `opencv_zoo` lui-même). Appelé via `cv2.FaceDetectorYN`.
  - **Plaques** : le cascade Haar `haarcascade_russian_plate_number.xml`, livré DANS le dépôt
    principal `opencv/opencv` (`data/haarcascades/`) — donc sous la MÊME licence Apache-2.0 que le
    code OpenCV, aucun poids ni dépôt tiers à vérifier séparément. Limite connue, jamais cachée :
    entraîné sur les proportions des plaques russes, imprécis sur les plaques québécoises — c'est
    justement pourquoi toute détection sous le seuil de confiance fourni force une revue humaine
    (`floutage.py`) plutôt qu'un floutage silencieusement supposé suffisant. À réévaluer (modèle
    spécifique aux plaques québécoises) avant tout volume réel de publication.
  - **Explicitement écarté** : YOLOv8/YOLO11 (Ultralytics) en dépendance directe vendorisée —
    licence **AGPL-3.0** du dépôt, incompatible avec AGENTS.md hors service séparé non modifié
    (inscrit dans `docs/research/INGREDIENTS.md` § Refusées).

`cv2` n'est **pas installable dans ce bac à sable** (`ModuleNotFoundError` vérifié, aucun accès
réseau pip confirmé pour un paquet aussi volumineux) : `detecteur_opencv_par_defaut()` échoue avec
`DetecteurIndisponible`, un refus nommé et testé — jamais un faux vert (AGENTS.md « Preuve avant
DONE »). L'appel réel (`cv2.FaceDetectorYN.create(...)`, `cv2.CascadeClassifier(...)`) reste à
écrire et à tester le jour où la dépendance est réellement installée dans l'environnement cible ;
la logique qui en dépend (`floutage.py`) est déjà écrite et testée contre le protocole ci-dessous.

Module pur : aucun import `opsys`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Literal, Protocol

from .image import Boite, ImageSynthetique

TypeDetection = Literal["visage", "plaque"]
TYPES_DETECTION: tuple[TypeDetection, ...] = ("visage", "plaque")


class ConfianceInvalide(ValueError):
    """Une confiance de détection hors de l'intervalle [0, 1]."""


@dataclasses.dataclass(frozen=True)
class Detection:
    """Une détection unique : quoi (`type`), où (`boite`), avec quelle confiance ([0, 1])."""

    type: TypeDetection
    boite: Boite
    confiance: float

    def __post_init__(self) -> None:
        if self.type not in TYPES_DETECTION:
            raise ValueError(f"type de détection inconnu : {self.type!r} (attendus : {TYPES_DETECTION})")
        if not (0.0 <= self.confiance <= 1.0):
            raise ConfianceInvalide(f"confiance hors de [0, 1] : {self.confiance}")


class Detecteur(Protocol):
    """Détecteur injectable : la seule dépendance de `floutage.py`. Une implémentation de test
    (image synthétique -> détections connues) et une implémentation réelle (OpenCV) partagent ce
    même protocole ; rien dans `floutage.py` ne sait laquelle est utilisée."""

    def detecter(self, image: ImageSynthetique) -> Sequence[Detection]:
        """Détections trouvées dans `image`. Jamais d'exception pour « rien trouvé » — une
        séquence vide est un résultat valide, pas une panne."""
        ...


class DetecteurIndisponible(RuntimeError):
    """La brique de détection réelle n'est pas installée/branchée dans cet environnement."""


def detecteur_opencv_par_defaut() -> Detecteur:
    """Détecteur réel par défaut (YuNet + cascade Haar, voir docstring du module).

    Échec nommé et testé dans ce bac à sable : `cv2` y est absent (voir docstring). Un appelant
    (l'adaptateur `outils.py`) attrape `DetecteurIndisponible` et rend un verdict de blocage,
    jamais une exception qui casse l'appel — même doctrine que `NotAutorise`/`AdapterDisabled`
    dans `social/postiz_adapter.py`.
    """
    try:
        import cv2  # noqa: F401  (import différé : ne casse jamais le simple import du module)
    except ImportError as exc:
        raise DetecteurIndisponible(
            "cv2 (opencv-python-headless) n'est pas installé dans cet environnement : détection "
            "de visages (YuNet, MIT) et de plaques (cascade Haar, Apache-2.0) indisponible. "
            "Voir docs/research/INGREDIENTS.md § M7 — Marketing et "
            "m7_marketing.moderation.detection pour les briques retenues et leurs licences ; "
            "injecter un `Detecteur` de test (images synthétiques) en attendant."
        ) from exc
    # cv2 est importable mais aucun adaptateur réel (cv2.FaceDetectorYN / CascadeClassifier)
    # n'est encore écrit ici (PLAN T4.3 : logique + interface injectable livrées et testées ;
    # le branchement réel reste à écrire ET À TESTER avec la dépendance réellement disponible,
    # jamais livré sans preuve). Refus nommé, jamais un détecteur qui prétend fonctionner sans
    # jamais rien détecter.
    raise DetecteurIndisponible(
        "cv2 est disponible mais aucun adaptateur réel n'est encore branché dans "
        "m7_marketing.moderation.detection (PLAN T4.3 : reste à faire, voir INGREDIENTS.md)."
    )
