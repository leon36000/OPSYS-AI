"""Fixtures des tests du studio créatif : le dossier des fabriques est mis sur le chemin d'import."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


import pytest  # noqa: E402

from opsys import identite, stockage  # noqa: E402


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Base de l'instance migrée, deux personnes (propriétaire et administrateur) et `OPSYS_HOME` privé."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Propriétaire fictif", "mot-de-passe-test-1234", ["nathan_owner"])
        identite.creer_personne(cnx, "gestion", "Gestionnaire fictif", "mot-de-passe-test-1234", ["admin"])
    yield tmp_path / "opsys-home"
    stockage.liberer()
