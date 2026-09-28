"""Orchestration du floutage déterministe avant mise en file de publication (PLAN T4.3,
M7-audit.md §3.5, §4-Phase1.4 : « ajouter la vérification de §3.5 comme étape obligatoire avant
`approval.propose()` pour tout content-item portant un média »).

Chaque détection (visage ou plaque) trouvée par le `Detecteur` injecté est floutée — sous le
seuil de confiance ou non, plus prudent que de ne flouter que les détections « sûres ». Le
RAPPORT distingue les détections dont la confiance est SOUS `seuil_confiance` (fourni par
l'appelant : un seuil est une décision de politique, jamais une valeur devinée ici — AGENTS.md
« le code calcule, le LLM orchestre ») : `revue_humaine_requise=True` force une revue humaine
avant toute publication, jamais une publication automatique sur un doute de détection.

Limite documentée, jamais cachée : l'ABSENCE de détection n'est pas une preuve d'absence de
visage ou de plaque — un détecteur imprécis (ex. cascade Haar entraînée sur des plaques russes,
voir `detection.py`) peut manquer une zone entière. Ce module ne peut garantir que ce qu'il
détecte ET floute ; l'approbation humaine finale de la publication réelle (N5, hors périmètre de
M7) reste la seule garantie de dernier recours.

Module pur : aucun import `opsys`.
"""

from __future__ import annotations

import dataclasses

from .detection import Detecteur, Detection
from .image import ImageSynthetique, flouter_zone


class SeuilInvalide(ValueError):
    """`seuil_confiance` n'est pas dans l'intervalle [0, 1]."""


@dataclasses.dataclass(frozen=True)
class DetectionTraitee:
    """Une détection, après floutage : `doute` dit si sa confiance était sous le seuil fourni."""

    detection: Detection
    floutee: bool
    doute: bool


@dataclasses.dataclass(frozen=True)
class RapportPhoto:
    """Rapport de floutage d'une photo : ce qui a été détecté/flouté, et si une revue humaine
    est requise avant toute publication (jamais automatique sur un doute de détection)."""

    reference: str
    detections: tuple[DetectionTraitee, ...]
    revue_humaine_requise: bool
    motif_revue_humaine: str | None


def flouter_photo(
    reference: str,
    image: ImageSynthetique,
    detecteur: Detecteur,
    seuil_confiance: float,
) -> tuple[ImageSynthetique, RapportPhoto]:
    """Détecte puis floute chaque zone de `image` ; retourne `(image_floutee, rapport)`.

    Lève `SeuilInvalide` si `seuil_confiance` n'est pas dans [0, 1] : un seuil hors bornes est une
    erreur d'appelant, jamais silencieusement clampée. Si le floutage d'une détection échoue
    (boîte hors image, `image.DimensionInvalide`), l'exception se propage : aucune photo n'est
    mise en file partiellement floutée — un floutage qui échoue à moitié est un échec complet.
    """
    if not (0.0 <= seuil_confiance <= 1.0):
        raise SeuilInvalide(f"seuil_confiance hors de [0, 1] : {seuil_confiance}")

    detections = list(detecteur.detecter(image))

    image_floutee = image
    traitees: list[DetectionTraitee] = []
    for det in detections:
        image_floutee = flouter_zone(image_floutee, det.boite)
        doute = det.confiance < seuil_confiance
        traitees.append(DetectionTraitee(detection=det, floutee=True, doute=doute))

    doutes = [t for t in traitees if t.doute]
    revue_requise = bool(doutes)
    motif: str | None = None
    if revue_requise:
        details = ", ".join(
            f"{t.detection.type} (confiance {t.detection.confiance:.2f})" for t in doutes
        )
        motif = (
            f"{len(doutes)} détection(s) sous le seuil de confiance {seuil_confiance:.2f} pour "
            f"« {reference} » : {details} — revue humaine obligatoire avant toute publication."
        )

    rapport = RapportPhoto(
        reference=reference,
        detections=tuple(traitees),
        revue_humaine_requise=revue_requise,
        motif_revue_humaine=motif,
    )
    return image_floutee, rapport
