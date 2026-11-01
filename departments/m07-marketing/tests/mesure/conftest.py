"""Fixtures des tests de la mesure marketing : base SQLite fictive migrée, avec une personne admin fictive."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from opsys import identite, stockage  # noqa: E402


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home-fictif"))
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin fictif", "mot-de-passe-fictif-123", ["admin"])
    yield
    stockage.liberer()
