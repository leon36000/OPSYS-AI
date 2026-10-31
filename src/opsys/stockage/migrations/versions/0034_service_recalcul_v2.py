"""Candidat privé SQLite : intentions et attestation v2, sans grant initial."""

from alembic import op

from opsys.stockage.schema import SERVICE_RECALCUL_ATTESTATIONS, SERVICE_RECALCUL_INTENTIONS, SERVICE_RECALCUL_RESULTATS

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None
_TABLES = (SERVICE_RECALCUL_INTENTIONS, SERVICE_RECALCUL_ATTESTATIONS, SERVICE_RECALCUL_RESULTATS)


def upgrade():
    c = op.get_bind()
    if c.dialect.name != "sqlite":
        raise RuntimeError("recalcul v2 non qualifié sur ce backend")
    for table in _TABLES:
        table.create(c)
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {table.name}_no_{action.lower()} BEFORE {action} ON {table.name} "
                "BEGIN SELECT RAISE(ABORT,'historique immuable'); END"
            )


def downgrade():
    c = op.get_bind()
    for table in _TABLES:
        if c.execute(table.select().limit(1)).first():
            raise RuntimeError("historique recalcul présent")
    for table in reversed(_TABLES):
        for action in ("update", "delete"):
            op.execute(f"DROP TRIGGER {table.name}_no_{action}")
        table.drop(c)
