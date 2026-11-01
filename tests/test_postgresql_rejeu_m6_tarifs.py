"""Rejeu PostgreSQL : historique des prix, import et confirmation de tarifs M6, réceptions de tarifs (captures SQL
bornées, écriture humaine).
"""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_historique_prix_m6.py",
    "test_console_import_tarifs_m6.py",
    "test_console_import_tarifs_confirmation_m6.py",
    "test_receptions_tarifs.py",
)
