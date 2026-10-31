"""Journal de l'opérateur des politiques de service (D1) et du réconciliateur du coût certifié (E8).

Append-only, sans aucune ligne initiale : la migration n'octroie rien. La rétrogradation est refusée dès qu'une
ligne existe (aucun historique d'autorité n'est jamais effacé par une migration).
"""

from alembic import op

from opsys.stockage.schema import COUT_CERTIFIE_RECONCILIATIONS, SERVICE_POLITIQUES_JOURNAL

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None
_TABLES = (SERVICE_POLITIQUES_JOURNAL, COUT_CERTIFIE_RECONCILIATIONS)


def upgrade():
    c = op.get_bind()
    if c.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend non pris en charge")
    if c.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION opsys_journal_0036_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'journal immuable' USING ERRCODE = '23514';
        END $$""")
    for table in _TABLES:
        table.create(c)
        if c.dialect.name == "postgresql":
            op.execute(f"CREATE TRIGGER {table.name}_immutable BEFORE UPDATE OR DELETE ON {table.name} "
                       "FOR EACH ROW EXECUTE FUNCTION opsys_journal_0036_immutable()")
            continue
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {table.name}_no_{action.lower()} BEFORE {action} ON {table.name} "
                "BEGIN SELECT RAISE(ABORT,'journal immuable'); END"
            )


def downgrade():
    c = op.get_bind()
    if c.dialect.name == "postgresql":
        for table in _TABLES:
            op.execute(f"LOCK TABLE {table.name} IN ACCESS EXCLUSIVE MODE")
    elif c.dialect.name != "sqlite":
        raise RuntimeError("backend non pris en charge")
    for table in _TABLES:
        if c.execute(table.select().limit(1)).first():
            raise RuntimeError("rétrogradation refusée : journal d'autorité ou de réconciliation présent")
    for table in reversed(_TABLES):
        if c.dialect.name == "postgresql":
            op.execute(f"DROP TRIGGER {table.name}_immutable ON {table.name}")
        else:
            for action in ("update", "delete"):
                op.execute(f"DROP TRIGGER {table.name}_no_{action}")
        table.drop(c)
    if c.dialect.name == "postgresql":
        op.execute("DROP FUNCTION opsys_journal_0036_immutable()")
