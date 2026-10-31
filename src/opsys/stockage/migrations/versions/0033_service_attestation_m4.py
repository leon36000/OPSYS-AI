"""Private candidate: append-only historical M4 service linkage, no grants."""

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "service_attestations_m4",
        sa.Column("audit_id", sa.Integer, sa.ForeignKey("service_audit.id"), primary_key=True),
        sa.Column("instance_id", sa.String(36), nullable=False),
        sa.Column("evenement_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("trace_rang", sa.Integer, nullable=False),
        sa.Column("trace_sha256", sa.String(64), nullable=False),
        sa.Column("source_m4", sa.String(64), nullable=False),
        sa.Column("projection_sha256", sa.String(64), nullable=False),
        sa.Column("version_m4", sa.String(64), nullable=False),
        sa.UniqueConstraint("instance_id", "trace_rang", name="service_attestation_trace_unique"),
        sa.CheckConstraint("trace_rang >= 0 AND revision > 0", name="service_attestation_bounds"),
    )
    if op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER service_attestation_no_{action.lower()} BEFORE {action} ON service_attestations_m4 "
                "BEGIN SELECT RAISE(ABORT,'attestation immutable'); END"
            )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM service_attestations_m4 LIMIT 1")).first():
        raise RuntimeError("historique présent")
    if op.get_bind().dialect.name == "sqlite":
        for action in ("update", "delete"):
            op.execute("DROP TRIGGER service_attestation_no_" + action)
    op.drop_table("service_attestations_m4")
