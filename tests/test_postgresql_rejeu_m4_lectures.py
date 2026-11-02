"""Rejeu PostgreSQL : lectures privées M4 de la console (instantanés bornés par octets SQL, comptes internes, journal
d'équipes, préparation de chantier).
"""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_absences_personnes.py",
    "test_console_compositions_equipes.py",
    "test_console_comptes_terrain.py",
    "test_console_journal_equipes.py",
    "test_console_preparation_chantier.py",
    "test_console_memoire_chantier.py",
    "test_console_visites_chantier.py",
)
