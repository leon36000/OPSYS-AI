"""Rejeu PostgreSQL : M5 -> M2 : une facture payée ou annulée (`m5.facture_emise_constatee`) lève la relance de
créance que M2 gardait.

Sur un VRAI PostgreSQL 17 (conteneur jetable). Le fichier d'origine bâtit son monde sur un fichier SQLite ;
`rediriger_sqlite` en fait une base PostgreSQL vide migrée par le test comme un fichier neuf. Aucun test n'est modifié ;
sans Docker, chaque test est IGNORÉ avec la raison exacte.
"""

from pg_rejeu import installer

INJECTES = installer(globals(), "test_creance_levee_paiement.py", rediriger_sqlite=True)
