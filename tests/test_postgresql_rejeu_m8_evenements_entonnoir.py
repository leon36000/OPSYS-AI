"""Rejeu PostgreSQL (département M8) : Les consommateurs d'entonnoir de M8 (devis, leads, clients).

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine, dans `departments/m08-analytics/tests`, bâtit sa
base sur un fichier SQLite ; `rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test. Aucun test n'est
modifié ; sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(
    globals(), "../departments/m08-analytics/tests/test_evenements_entonnoir.py",
    rediriger_sqlite=True,
)
