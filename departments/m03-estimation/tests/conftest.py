from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_RACINE = _TESTS.parents[2]
sys.path.insert(0, str(_TESTS / "outils_preuve"))
sys.path.insert(0, str(_RACINE / "tests" / "fixtures"))
from campagne_gardes import CampagneGardes  # noqa: E402

# Campagne de mutation M3 : chaque cas qui en dépend relance la suite M3 complète en sous-processus
# (référence verte puis une exécution par mutation), soit plus de cent exécutions d'environ 50 s
# pour `test_gardes_des_outils.py` seul. Ce n'est pas un blocage : en série, le fichier dure plus
# d'une heure et semble figé vers son 14e cas (première batterie nominale, onze exécutions).
# Elle est qualifiée par le job CI `m03-preuves` (huit parts, variable posée) ; sans la variable,
# `pytest departments/m03-estimation` saute ces cas en le disant, au lieu de durer des heures.
ENV_QUALIFIER_MUTATIONS = "OPSYS_QUALIFIER_M3_MUTATIONS"
RAISON_SANS_QUALIFICATION = (
    "campagne de mutation M3 (plus de cent exécutions complètes de la suite M3, plus d'une heure en "
    f"série) réservée au job CI m03-preuves ; {ENV_QUALIFIER_MUTATIONS}=1 pour la lancer ici"
)


@pytest.fixture(scope="session")
def campagne_gardes():
    if os.environ.get(ENV_QUALIFIER_MUTATIONS) != "1":
        pytest.skip(RAISON_SANS_QUALIFICATION)
    dossier = Path(os.environ.get("M3_CAMPAGNE_PREUVES", "preuves/m3-campagnes"))
    if not dossier.is_absolute():
        dossier = _RACINE / dossier
    campagne = CampagneGardes(_RACINE, dossier)
    try:
        yield campagne
    finally:
        campagne.fermer()
