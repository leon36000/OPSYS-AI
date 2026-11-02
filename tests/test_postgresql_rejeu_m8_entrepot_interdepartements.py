"""Rejeu PostgreSQL (département M8) : L'entrepôt de M8 et les mesures de la phase 2 alimentées par les autres
départements.

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine, dans `departments/m08-analytics/tests`, bâtit
sa base
sur un fichier SQLite ; `rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test. Aucun test n'est
modifié ; sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(
    globals(), "../departments/m08-analytics/tests/test_entrepot_interdepartements.py",
    rediriger_sqlite=True,
)
