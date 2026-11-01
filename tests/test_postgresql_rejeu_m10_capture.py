"""Rejeu PostgreSQL : capture de paquets M10, documents de chantier et lecture documentaire de la console."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_capture_paquets_m10.py",
    "test_console_documents_chantier.py",
)
