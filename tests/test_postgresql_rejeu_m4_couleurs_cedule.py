"""Rejeu PostgreSQL : couleurs de la cédule M4 (deux éditeurs simultanés, une seule couleur gagne)."""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_console_couleurs_cedule.py")
