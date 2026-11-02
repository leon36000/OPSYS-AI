"""Rejeu PostgreSQL : M7 -> M5 -> M8 : la chaîne de la dépense publicitaire.

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine bâtit son monde sur un fichier SQLite ;
`rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test comme un fichier neuf. Aucun test n'est modifié ;
sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_interconnexion_m7_m5_m8.py", rediriger_sqlite=True)
