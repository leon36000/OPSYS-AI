"""Rejeu PostgreSQL : Constats contradictoires (même clé de contenu, contenu différent) de M2, M5 et M8 : premier
état gardé, contradiction rangée une fois, bus réel, consommateurs réels.

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine bâtit son monde sur un fichier SQLite ;
`rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test comme un fichier neuf. Aucun test n'est modifié ;
sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_constats_contradictoires.py", rediriger_sqlite=True)
