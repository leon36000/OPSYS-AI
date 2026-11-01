"""Fixtures des tests des médias payants : base SQLite fictive migrée, deux personnes (propriétaire, administrateur)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "signaux"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "studio"))

from opsys import identite, stockage  # noqa: E402


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Instance migrée, `OPSYS_HOME` privé, `nathan` (nathan_owner) et `gestion` (admin)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Propriétaire fictif", "mot-de-passe-test-1234", ["nathan_owner"])
        identite.creer_personne(cnx, "gestion", "Gestionnaire fictif", "mot-de-passe-test-1234", ["admin"])
    yield tmp_path / "opsys-home"
    stockage.liberer()
