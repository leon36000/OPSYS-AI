"""Tests — protocole de détection injectable et détecteur réel par défaut (PLAN T4.3).

`cv2` (OpenCV) n'est pas installé dans ce bac à sable (vérifié) : ces tests prouvent le refus
nommé et fail-closed (`DetecteurIndisponible`), jamais un faux vert (AGENTS.md « Preuve avant
DONE »). Le second test simule un `cv2` disponible (sans jamais l'installer) pour prouver que
même dans ce cas, aucun détecteur non testé n'est livré silencieusement.
"""

from __future__ import annotations

import importlib
import inspect
import sys
import types

import pytest
from m7_marketing.moderation.detection import (
    ConfianceInvalide,
    DetecteurIndisponible,
    Detection,
    detecteur_opencv_par_defaut,
)
from m7_marketing.moderation.image import Boite


def test_cv2_reellement_absent_de_ce_bac_a_sable():
    """Précondition documentée du module : si ce test devient rouge, cv2 a été installé et
    `detection.py`/INGREDIENTS.md doivent être mis à jour en conséquence."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("cv2")


def test_detection_confiance_hors_bornes_refusee():
    with pytest.raises(ConfianceInvalide):
        Detection(type="visage", boite=Boite(0, 0, 1, 1), confiance=1.5)


def test_detection_type_inconnu_refuse():
    with pytest.raises(ValueError):
        Detection(type="chapeau", boite=Boite(0, 0, 1, 1), confiance=0.5)  # type: ignore[arg-type]


def test_detecteur_par_defaut_indisponible_sans_cv2():
    with pytest.raises(DetecteurIndisponible, match="cv2"):
        detecteur_opencv_par_defaut()


def test_detecteur_par_defaut_refuse_meme_si_cv2_devient_importable(monkeypatch):
    """Même si `cv2` devient importable (simulé ici, jamais installé), aucun adaptateur réel non
    testé n'est livré silencieusement : refus nommé et distinct du cas « cv2 absent »."""
    faux_cv2 = types.ModuleType("cv2")
    monkeypatch.setitem(sys.modules, "cv2", faux_cv2)

    with pytest.raises(DetecteurIndisponible) as exc_info:
        detecteur_opencv_par_defaut()
    assert "branché" in str(exc_info.value)


def test_module_pur_detection_naimporte_jamais_opsys():
    from m7_marketing.moderation import detection as module_detection

    source = inspect.getsource(module_detection)
    assert "import opsys" not in source
    assert "from opsys" not in source
