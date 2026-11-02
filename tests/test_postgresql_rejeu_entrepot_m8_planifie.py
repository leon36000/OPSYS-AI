"""Rejeu PostgreSQL : De bout en bout : le planificateur déclenche les VRAIS constats des départements, le bus les
livre à M8, M8 calcule des mesures EXACTES, la vraie console affiche les wallboards, le copilote répond, M9 et M10
voient le fait consolidé.

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine bâtit son monde sur un fichier SQLite ;
`rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test comme un fichier neuf. Aucun test n'est modifié ;
sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_entrepot_m8_planifie.py", rediriger_sqlite=True)
