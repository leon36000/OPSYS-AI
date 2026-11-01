"""Fixtures des tests GEO/SEO : base SQLite fictive migrée, horloge, masqueur. Données FICTIVES."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fabriques_geo import Horloge  # noqa: E402

from opsys import stockage  # noqa: E402
from opsys.observabilite.pii import MasqueurMotifs  # noqa: E402


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home-fictif"))
    stockage.migrer()
    yield
    stockage.liberer()


@pytest.fixture
def horloge():
    return Horloge()


@pytest.fixture
def pii():
    return MasqueurMotifs(b"\x07" * 32)
