"""Rejeu PostgreSQL : confirmation des dates d'un plan M4 appliqué (écriture humaine, garde de rôle relue)."""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_console_dates_cedule.py")
