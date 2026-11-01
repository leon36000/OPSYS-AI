"""Rejeu PostgreSQL : compositions d'équipe M4 (console, deux transactions concurrentes, une seule révision)."""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_console_composition_ecriture.py")
