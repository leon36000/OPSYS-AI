"""Rejeu PostgreSQL (département M8) : Le consommateur `m5.cash_libre_constate` de M8 (un fait par identifiant, dernier
constat quel que soit l'ordre de livraison).

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine, dans `departments/m08-analytics/tests`, bâtit sa
base sur un fichier SQLite ; `rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test. Aucun test n'est
modifié ; sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(
    globals(), "../departments/m08-analytics/tests/test_evenements_cash_libre.py",
    rediriger_sqlite=True,
)
