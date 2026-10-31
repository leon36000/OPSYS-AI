"""Registre des politiques inactif à l'installation ; aucun octroi initial."""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "service_politiques",
        sa.Column("instance_id", sa.String(36), sa.ForeignKey("opsys_instance.instance_id"), primary_key=True),
        sa.Column("consommateur", sa.String(128), primary_key=True),
        sa.Column("operation", sa.String(64), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("expire_le", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "revision > 0 AND expire_le > 0", name=op.f("ck_service_politiques_service_politique_revision")
        ),
        sa.CheckConstraint("active IN (false, true)", name=op.f("ck_service_politiques_service_politique_active")),
    )
    op.create_table(
        "service_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("instance_id", sa.String(36), nullable=False),
        sa.Column("consommateur", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("evenement_id", sa.String(128)),
        sa.Column("action", sa.String(24), nullable=False),
        sa.CheckConstraint("action IN ('usage','revocation')", name=op.f("ck_service_audit_service_audit_action")),
    )
    if op.get_bind().dialect.name == "postgresql":
        # This serializes every insertion, including direct SQL writers, on the
        # instance row. It does not grant a service authority or protect M4.
        op.execute("""CREATE FUNCTION service_policy_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE current_revision integer;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'service historique immutable' USING ERRCODE = '23514';
            END IF;
            PERFORM 1 FROM opsys_instance WHERE instance_id = NEW.instance_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'service instance absente' USING ERRCODE = '23514';
            END IF;
            SELECT COALESCE(MAX(revision), 0) INTO current_revision
            FROM service_politiques WHERE instance_id = NEW.instance_id
                AND consommateur = NEW.consommateur AND operation = NEW.operation;
            IF NEW.revision <> current_revision + 1 THEN
                RAISE EXCEPTION 'service revision non monotone' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$""")
        op.execute("""CREATE TRIGGER service_pol_pg_insert BEFORE INSERT ON service_politiques
        FOR EACH ROW EXECUTE FUNCTION service_policy_guard()""")
        op.execute("""CREATE TRIGGER service_pol_pg_immutable BEFORE UPDATE OR DELETE ON service_politiques
        FOR EACH ROW EXECUTE FUNCTION service_policy_guard()""")
    if op.get_bind().dialect.name == "sqlite":
        op.execute("""CREATE TRIGGER service_pol_seq BEFORE INSERT ON service_politiques
        WHEN NEW.revision != COALESCE((SELECT MAX(revision) FROM service_politiques
            WHERE instance_id=NEW.instance_id AND consommateur=NEW.consommateur
            AND operation=NEW.operation),0)+1
        BEGIN SELECT RAISE(ABORT,'service revision non monotone'); END""")
        for action in ("UPDATE", "DELETE"):
            op.execute(f"""CREATE TRIGGER service_pol_no_{action.lower()} BEFORE {action} ON service_politiques
            BEGIN SELECT RAISE(ABORT,'service historique immutable'); END""")


def downgrade():
    cnx = op.get_bind()
    if (
        cnx.execute(sa.text("SELECT 1 FROM service_politiques LIMIT 1")).first()
        or cnx.execute(sa.text("SELECT 1 FROM service_audit LIMIT 1")).first()
    ):
        raise RuntimeError("rétrogradation refusée : historique de service présent")
    if cnx.dialect.name == "sqlite":
        for name in ("service_pol_seq", "service_pol_no_update", "service_pol_no_delete"):
            op.execute("DROP TRIGGER " + name)
    if cnx.dialect.name == "postgresql":
        op.execute("DROP TRIGGER service_pol_pg_insert ON service_politiques")
        op.execute("DROP TRIGGER service_pol_pg_immutable ON service_politiques")
    op.drop_table("service_audit")
    op.drop_table("service_politiques")
    if cnx.dialect.name == "postgresql":
        op.execute("DROP FUNCTION service_policy_guard()")
