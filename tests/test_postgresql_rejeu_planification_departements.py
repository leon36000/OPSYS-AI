"""Rejeu PostgreSQL : Les exécuteurs de départements du planificateur (M8, M5, M10, vérifications) sous bail et créneau.

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine bâtit son monde sur un fichier SQLite ;
`rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test comme un fichier neuf. Aucun test n'est modifié ;
sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_planification_departements.py", rediriger_sqlite=True)
