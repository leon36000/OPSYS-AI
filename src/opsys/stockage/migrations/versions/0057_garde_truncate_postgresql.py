"""Parité PostgreSQL : `TRUNCATE` refusé sur les journaux et tables append-only ; succède à 0056.

NUMÉROTATION : 0057 succède à 0056 (parité PostgreSQL).

PostgreSQL SEULEMENT (SQLite : aucune opération ; SQLite n'a pas de `TRUNCATE`).

Les déclencheurs d'immuabilité des migrations précédentes sont des déclencheurs de LIGNE (`BEFORE UPDATE OR DELETE FOR
EACH ROW`). Sur PostgreSQL, `TRUNCATE` ne déclenche JAMAIS un déclencheur de ligne : `TRUNCATE courriel_journal,
coffre_acces, connaissances_etats` vidait un journal « immuable » sans qu'aucun déclencheur ne se réveille, alors que
l'équivalent SQLite (`DELETE`) est refusé. Trouvé à la revue adverse en cherchant les voies d'écriture qui contournent
les déclencheurs (rvi). Cette migration pose, sur chacune des tables qui portent un déclencheur d'immuabilité ou de
garde (liste fermée ci-dessous, 29 tables), un déclencheur d'INSTRUCTION `BEFORE TRUNCATE` qui refuse avec le même
code d'erreur que les autres (SQLSTATE 23514). `TRUNCATE … CASCADE` depuis une table parente est refusé aussi : le
déclencheur se réveille pour chaque table touchée.

Ce que cela ne couvre PAS : le propriétaire de la table peut toujours `DROP TRIGGER`, `ALTER TABLE … DISABLE TRIGGER`
ou `DROP TABLE` ; un super-utilisateur peut poser `session_replication_role = replica`. La séparation du rôle de
migration et du rôle d'exécution est une décision de déploiement (docs/qualification/QUALIFICATION-POSTGRESQL.md).

SCHÉMA : comme 0056, rien n'est qualifié (la chaîne s'installe dans n'importe quel schéma). La rétrogradation retire
les déclencheurs et la fonction ; elle ne détruit aucune donnée.
"""

from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

_FONCTION = "opsys_truncate_interdit"
_TABLES = (
    "avatars_consentements", "avatars_qualifications", "coffre_acces", "connaissances_espaces", "connaissances_etats",
    "connaissances_fragments", "connaissances_indexations", "connaissances_lexique", "connaissances_sources",
    "connaissances_vecteurs", "connaissances_versions", "courriel_journal", "cout_certifie_reconciliations",
    "fusion_ap_ocr_sources", "graphe_aretes", "graphe_aretes_etats", "graphe_noeuds", "ingestion_journal",
    "planificateur_approbations", "planificateur_journal", "pont_bi_acces", "service_attestations_m4",
    "service_politiques", "service_politiques_journal", "service_recalcul_attestations_v2",
    "service_recalcul_intentions", "service_recalcul_resultats", "wct_attentes", "wct_attentes_audit",
)


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"""CREATE FUNCTION {_FONCTION}() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'TRUNCATE interdit sur % (table append-only ou journal immuable)', TG_TABLE_NAME
            USING ERRCODE = '23514';
    END $$""")
    for table in _TABLES:
        op.execute(f"CREATE TRIGGER {table}_sans_truncate BEFORE TRUNCATE ON {table} "
                   f"FOR EACH STATEMENT EXECUTE FUNCTION {_FONCTION}()")


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in reversed(_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_sans_truncate ON {table}")
    op.execute(f"DROP FUNCTION IF EXISTS {_FONCTION}()")
