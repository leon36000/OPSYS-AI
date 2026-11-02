"""Rejeu PostgreSQL : M8 reçoit les constats de M7, M5 et M3 (`faits_operations`) et la vue exécutive les montre.

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine bâtit son monde sur un fichier SQLite ;
`rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test comme un fichier neuf. Aucun test n'est modifié ;
sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_interconnexion_m8_operations.py", rediriger_sqlite=True)
