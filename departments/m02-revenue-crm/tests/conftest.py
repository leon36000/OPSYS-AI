"""Fixtures des tests « ventes » de M2 (profil de propriété, score, coach, analytique). Les aides vivent dans
`ventes_aide.py` (importable : ce dossier est ajouté au chemin ici, car le nom `conftest` est déjà pris par la
racine)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from m2_revenue_crm import outils  # noqa: E402
from ventes_aide import Monde  # noqa: E402

from opsys import identite, stockage  # noqa: E402


@pytest.fixture
def monde(tmp_path, monkeypatch):
    """Base SQLite migrée + personnes fictives + stockage durable de M2 ; remis à zéro après le test."""
    url = f"sqlite:///{tmp_path / 'opsys-m2-ventes.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", "mot-de-passe-vendeur-un-1", ["seller"])
        identite.creer_personne(cnx, "vendeur.deux", "Vendeur Deux", "mot-de-passe-vendeur-deux", ["seller"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(
            cnx, "ancien.vendeur", "Ancien Vendeur", "mot-de-passe-ancien-123", ["seller"], actif=False
        )
    monde_ = Monde(tmp_path, monkeypatch)
    monde_.configurer()
    try:
        yield monde_
    finally:
        outils.reinitialiser_registre()
        stockage.liberer()
