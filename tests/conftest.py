from __future__ import annotations

import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(FIXTURES))


@pytest.fixture
def opsys_home(tmp_path, monkeypatch):
    home = tmp_path / "opsys-home"
    monkeypatch.setenv("OPSYS_HOME", str(home))
    return home


@pytest.fixture
def racine_demo() -> Path:
    return FIXTURES / "departements"


@pytest.fixture
def departements_demo(racine_demo):
    from opsys.departements import charger_departements

    return charger_departements(racine_demo)


@pytest.fixture
def session(opsys_home):
    from opsys import etat

    return etat.session
