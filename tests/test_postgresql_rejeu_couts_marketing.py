"""Rejeu PostgreSQL : coûts de marketing affectés (console N4 du propriétaire) et révocation d'une politique du service
M4 (primitive interne) ; les bases SQLite fichier que ces tests bâtissent sont remplacées par des bases PostgreSQL."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_couts_marketing.py",
    "test_operateur_politiques_service.py",
    rediriger_sqlite=True,
)
