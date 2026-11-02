"""Rejeu PostgreSQL : dossier client, correction de coordonnées M2 (deux transactions), agenda M2 de la console."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_crm.py",
    "test_console_agenda.py",
    "test_contact_m2_m10.py",
)
