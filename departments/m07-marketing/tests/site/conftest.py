"""Site fictif complet d'une PME de rénovation extérieure québécoise (fr-CA + en-CA), commun aux tests des sites."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from m7_marketing.site import rendu_statique

FICTIF = True
DOSSIER_DEMO = Path(__file__).resolve().parents[2] / "fixtures" / "sites" / "revetements-horizon-fictif"
_SCHEMA = json.loads((DOSSIER_DEMO / "site.json").read_text(encoding="utf-8"))
_ACTIFS = {
    p.relative_to(DOSSIER_DEMO / "actifs").as_posix(): p.read_bytes()
    for p in sorted((DOSSIER_DEMO / "actifs").rglob("*")) if p.is_file()
}


@pytest.fixture
def schema():
    """Une copie modifiable du schéma de démonstration (`fictif: true`)."""
    return copy.deepcopy(_SCHEMA)


@pytest.fixture
def actifs():
    return dict(_ACTIFS)


@pytest.fixture(scope="module")
def fichiers_demo():
    """Le site généré par le moteur Python, une fois par module (lecture seule : copier avant de muter)."""
    return rendu_statique.rendre_site(copy.deepcopy(_SCHEMA), dict(_ACTIFS))


@pytest.fixture
def fichiers(fichiers_demo):
    return dict(fichiers_demo)
