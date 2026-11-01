"""Rejeu PostgreSQL : stratégie CMO et observations Growth de la console M7 (écritures humaines privées)."""

import importlib

import pytest
from pg_rejeu import espionner_verrou, installer

INJECTES = installer(
    globals(),
    "test_console_cmo_strategies.py",
    "test_console_growth.py",
    rediriger_sqlite=True,
)


@pytest.fixture(autouse=True)
def _verrou_d_ecriture_de_console_tenu_aux_ports_cmo_et_growth(monkeypatch):
    """Les écritures humaines de la stratégie CMO et de Growth tiennent le verrou d'écriture de console (PostgreSQL)
    quand le service du département s'exécute : il remplace l'écrivain unique de SQLite."""
    cmo = importlib.import_module("m7_marketing.cmo_strategie")
    growth = importlib.import_module("m7_marketing.growth")
    journaux = {
        "cmo": espionner_verrou(monkeypatch, cmo, "executer"),
        "growth": espionner_verrou(monkeypatch, growth, "enregistrer_observation_humaine"),
    }
    yield journaux
    for nom, journal in journaux.items():
        assert journal["sans_verrou"] == 0, f"port {nom} sans verrou d'écriture de console : {journal}"
