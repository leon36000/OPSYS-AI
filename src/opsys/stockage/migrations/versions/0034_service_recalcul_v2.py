"""Registres de recalcul append-only, sans grant initial."""

from alembic import op

from opsys.stockage.schema import SERVICE_RECALCUL_ATTESTATIONS, SERVICE_RECALCUL_INTENTIONS, SERVICE_RECALCUL_RESULTATS

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None
_TABLES = (SERVICE_RECALCUL_INTENTIONS, SERVICE_RECALCUL_ATTESTATIONS, SERVICE_RECALCUL_RESULTATS)


def upgrade():
    c = op.get_bind()
    if c.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend recalcul non pris en charge")
    if c.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION service_recalcul_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'historique immuable' USING ERRCODE = '23514';
        END $$""")
    for table in _TABLES:
        table.create(c)
        if c.dialect.name == "postgresql":
            op.execute(f"CREATE TRIGGER {table.name}_immutable BEFORE UPDATE OR DELETE ON {table.name} "
                       "FOR EACH ROW EXECUTE FUNCTION service_recalcul_immutable()")
            continue
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {table.name}_no_{action.lower()} BEFORE {action} ON {table.name} "
                "BEGIN SELECT RAISE(ABORT,'historique immuable'); END"
            )


def downgrade():
    c = op.get_bind()
    if c.dialect.name == "postgresql":
        for table in _TABLES:
            op.execute(f"LOCK TABLE {table.name} IN ACCESS EXCLUSIVE MODE")
    elif c.dialect.name != "sqlite":
        raise RuntimeError("backend recalcul non pris en charge")
    for table in _TABLES:
        if c.execute(table.select().limit(1)).first():
            raise RuntimeError("historique recalcul présent")
    for table in reversed(_TABLES):
        if c.dialect.name == "postgresql":
            op.execute(f"DROP TRIGGER {table.name}_immutable ON {table.name}")
        else:
            for action in ("update", "delete"):
                op.execute(f"DROP TRIGGER {table.name}_no_{action}")
        table.drop(c)
    if c.dialect.name == "postgresql":
        op.execute("DROP FUNCTION service_recalcul_immutable()")
