"""Rejeu PostgreSQL : Les réessais du bus (backoff, fraîcheur, reprise après panne) et l'ordre de publication.

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine bâtit son monde sur un fichier SQLite ;
`rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test comme un fichier neuf. Aucun test n'est modifié ;
sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_evenements_retry_fraicheur.py", rediriger_sqlite=True)
