"""Rejeu PostgreSQL (département M8) : Les consommateurs de contenus de M8 (`m7.contenu_exporte`, `m1.lead_qualifie`).

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine, dans `departments/m08-analytics/tests`, bâtit
sa base
sur un fichier SQLite ; `rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test. Aucun test n'est
modifié ; sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(
    globals(), "../departments/m08-analytics/tests/test_evenements_contenus.py",
    rediriger_sqlite=True,
)
