"""Rejeu PostgreSQL : stratégie CMO et observations Growth de la console M7 (écritures humaines privées)."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_cmo_strategies.py",
    "test_console_growth.py",
    rediriger_sqlite=True,
)
