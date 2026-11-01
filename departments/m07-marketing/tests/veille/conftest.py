"""Fixtures des tests de la veille concurrentielle : base SQLite fictive migrée (propriétaire et gestionnaire
fictifs)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from opsys import identite, stockage  # noqa: E402


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home-fictif"))
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Propriétaire fictif", "mot-de-passe-test-1234", ["nathan_owner"])
        identite.creer_personne(cnx, "gestion", "Gestionnaire fictif", "mot-de-passe-test-1234", ["admin"])
    yield
    stockage.liberer()
