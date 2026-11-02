"""Rejeu PostgreSQL : Scénario de bout en bout du retrait du consentement de suivi (M4, M1, sas d'envoi, approbation).

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine bâtit son monde sur un fichier SQLite ;
`rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test comme un fichier neuf. Aucun test n'est modifié ;
sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_consentement_suivi_retire_scenario.py", rediriger_sqlite=True)
