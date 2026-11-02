"""Rejeu PostgreSQL : dépôt de pièces de projet (console, deux dépôts simultanés de la même saisie)."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_pieces_projet.py",
)
