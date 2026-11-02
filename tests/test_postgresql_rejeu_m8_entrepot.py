"""Rejeu PostgreSQL (département M8) : L'entrepôt de M8 (tables `m8_ent_*` : construction atomique, remplacement en
bloc, historique append-only, `inchange` sans écriture, état en retard, reconstruction identique).

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine, dans `departments/m08-analytics/tests`, bâtit
sa base
sur un fichier SQLite ; `rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test. Aucun test n'est
modifié ; sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(globals(), "../departments/m08-analytics/tests/test_entrepot.py", rediriger_sqlite=True)
