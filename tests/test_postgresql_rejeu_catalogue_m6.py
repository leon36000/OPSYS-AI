"""Rejeu PostgreSQL : catalogue, prix, fournisseurs M6 de la console (écritures humaines, deux écrivains)."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_catalogue_m6.py",
    "test_console_prix_m6.py",
    "test_console_fournisseurs_m6.py",
)
