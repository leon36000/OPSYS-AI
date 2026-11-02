"""Rejeu PostgreSQL : Les constats planifiés : déclarations des manifestes, calcul des arguments par créneau
(fuseau, changement d'heure), cadence dérivée du catalogue de M8, définitions d'exécuteurs et garde-fous, base
PostgreSQL pour les tests qui en bâtissent une.

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine bâtit son monde sur un fichier SQLite ;
`rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test comme un fichier neuf. Aucun test n'est modifié ;
sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_constats_planifies.py", rediriger_sqlite=True)
