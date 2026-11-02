"""Rejeu PostgreSQL : absences journalières M4 (console, deux transactions concurrentes, une seule révision)."""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_console_absence_ecriture.py")
