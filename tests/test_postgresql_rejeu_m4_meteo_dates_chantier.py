"""Rejeu PostgreSQL : consultation météo des dates internes M4 (lecture privée sous transaction)."""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_console_meteo_dates_chantier.py")
