"""Rejeu PostgreSQL : aperçu M10 des propositions d'apprentissage (instantané borné, mesure d'octets SQL avant
décodage).
"""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_memoire_apprentissage.py",
)
