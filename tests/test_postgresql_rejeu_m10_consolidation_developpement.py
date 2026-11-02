"""Rejeu PostgreSQL (département M10) : les jobs de consolidation du magasin de développement (grant humain, capacité de
service, bail, rapport, checkpoint, reprise après expiration, fuseau, caps) sur un VRAI PostgreSQL 17.

Le garde `_sqlite_seulement` est levé : les écrivains prennent un verrou de transaction nommé (`m10-developpement`) à la
place de l'écrivain unique de SQLite. Le fichier d'origine bâtit sa base sur un fichier SQLite ; `rediriger_sqlite` en
fait une base PostgreSQL vide migrée par le test. Exclus (propres à SQLite) : le worker en sous-processus (il reçoit
l'URL SQLite du test) et l'export/restauration du FICHIER.
"""

from pg_rejeu import installer

INJECTES = installer(
    globals(), "../departments/m10-memoire/tests/test_consolidation_developpement.py", rediriger_sqlite=True,
    exclure=("test_worker_sous_processus_sur_sqlite_et_relecture_sans_secret",
             "test_export_restauration_canonique_retrouve_grant_rapport_et_rejeu"),
)
