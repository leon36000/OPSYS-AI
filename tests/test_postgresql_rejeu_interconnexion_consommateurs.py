"""Rejeu PostgreSQL : Les consommateurs d'interconnexion de M1 à M10 (vrai bus, vrais consommateurs, vrais registres
durables).

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine bâtit son monde sur un fichier SQLite ;
`rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test comme un fichier neuf. Aucun test n'est modifié
; sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_interconnexion_consommateurs.py", rediriger_sqlite=True)
