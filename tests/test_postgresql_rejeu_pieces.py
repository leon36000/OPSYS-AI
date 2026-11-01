"""Rejeu PostgreSQL : classement des pièces de projet (console, deux classements simultanés de la même révision)."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_classement_pieces.py",
)
