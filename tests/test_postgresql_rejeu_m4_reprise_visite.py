"""Rejeu PostgreSQL : reprise de visite M4 depuis la console."""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_console_reprise_visite.py")
