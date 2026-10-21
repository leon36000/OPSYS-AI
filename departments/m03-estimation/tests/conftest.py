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


@pytest.fixture(scope="session")
def campagne_gardes():
    dossier = Path(os.environ.get("M3_CAMPAGNE_PREUVES", "preuves/m3-campagnes"))
    if not dossier.is_absolute():
        dossier = _RACINE / dossier
    campagne = CampagneGardes(_RACINE, dossier)
    try:
        yield campagne
    finally:
        campagne.fermer()
