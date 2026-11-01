"""Rejeu PostgreSQL : édition de textes, calendrier et médias M7 de la console (écritures humaines du studio et de la
stratégie).
"""

import importlib

import pytest
from pg_rejeu import espionner_verrou, installer

INJECTES = installer(
    globals(),
    "test_console_marketing_edition_textes.py",
    "test_console_calendrier_marketing.py",
    "test_console_m73a_medias.py",
)


@pytest.fixture(autouse=True)
def _verrou_d_ecriture_de_console_tenu_a_la_revision_de_texte(monkeypatch):
    """La révision humaine d'un texte M7 lit puis ajoute un maillon : sous PostgreSQL elle doit tenir le verrou
    d'écriture de console quand le service du studio s'exécute (sans lui, deux révisions lues sur la même version
    s'ajouteraient toutes deux)."""
    service = importlib.import_module("m7_marketing.usine.service")
    journal = espionner_verrou(monkeypatch, service, "reviser_texte_humain")
    yield journal
    assert journal["sans_verrou"] == 0, f"révision de texte M7 sans verrou d'écriture de console : {journal}"
