"""Rejeu PostgreSQL : édition de textes, calendrier et médias M7 de la console (écritures humaines du studio et de la
stratégie).
"""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_marketing_edition_textes.py",
    "test_console_calendrier_marketing.py",
    "test_console_m73a_medias.py",
)
