"""Conserve les ACK privés de retrait Cron, sans effacer intentions/grants/journal."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents_cron_retraits",
        sa.Column("intention_id", sa.String(64), primary_key=True),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("receipt_id", sa.String(64), nullable=False, unique=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("retrait_par", sa.String(64), nullable=False),
        sa.Column("mutation_id", sa.String(128), nullable=False),
        sa.Column("commande_hash", sa.String(64), nullable=False),
        sa.Column("retire_le", sa.Text(), nullable=False),
        sa.Column("native_job_id", sa.String(128), nullable=False),
        sa.Column("native_revision", sa.String(50), nullable=False),
        sa.Column("declaration_hash", sa.String(64), nullable=False),
        sa.Column("acquitte_le", sa.Text(), nullable=False),
        sa.Column("reponse", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["intention_id"], ["agents_declencheurs_intentions.id"]),
        sa.CheckConstraint("epoch > 0", name="agents_cron_retraits_epoch"),
        sa.CheckConstraint("length(receipt_id) = 64 AND length(source_hash) = 64 AND "
                           "length(commande_hash) = 64 AND length(declaration_hash) = 64",
                           name="agents_cron_retraits_empreintes"),
        sa.CheckConstraint("length(native_revision) = 50 AND substr(native_revision, 1, 7) = 'sha256:'",
                           name="agents_cron_retraits_revision_native"),
    )


def downgrade() -> None:
    existe = op.get_bind().execute(sa.text("SELECT 1 FROM agents_cron_retraits LIMIT 1")).first()
    if existe is not None:
        raise RuntimeError("rétrogradation refusée : elle effacerait des preuves de retrait cron")
    op.drop_table("agents_cron_retraits")
