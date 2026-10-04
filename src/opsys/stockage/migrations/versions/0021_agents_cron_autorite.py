"""Autorité privée et ACK des remises cron, sans second registre de profils."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents_declencheurs_remises",
        sa.Column("intention_id", sa.String(64), primary_key=True),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("capability_hash", sa.String(64), nullable=False),
        sa.Column("declaration_hash", sa.String(64), nullable=False),
        sa.Column("native_expected_revision", sa.Integer()),
        sa.Column("native_job_id", sa.String(128)),
        sa.Column("native_config_revision", sa.Integer()),
        sa.Column("etat", sa.String(16), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.Text(), nullable=False),
        sa.Column("lease_seconds", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.Column("modifie_le", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["intention_id"], ["agents_declencheurs_intentions.id"]),
        sa.CheckConstraint("epoch > 0 AND lease_epoch > 0",
                           name=op.f("ck_agents_declencheurs_remises_agents_cron_remises_epochs")),
        sa.CheckConstraint("length(capability_hash) = 64 AND length(declaration_hash) = 64",
                           name=op.f("ck_agents_declencheurs_remises_agents_cron_remises_empreintes")),
        sa.CheckConstraint("attempts BETWEEN 1 AND 3",
                           name=op.f("ck_agents_declencheurs_remises_agents_cron_remises_tentatives")),
        sa.CheckConstraint("lease_seconds BETWEEN 1 AND 120",
                           name=op.f("ck_agents_declencheurs_remises_agents_cron_remises_lease")),
        sa.CheckConstraint("etat IN ('preparation','remise','revoquee')",
                           name=op.f("ck_agents_declencheurs_remises_agents_cron_remises_etat")),
        sa.CheckConstraint("native_expected_revision IS NULL OR native_expected_revision > 0",
                           name=op.f("ck_agents_declencheurs_remises_agents_cron_remises_revision_attendue")),
        sa.CheckConstraint("native_config_revision IS NULL OR native_config_revision > 0",
                           name=op.f("ck_agents_declencheurs_remises_agents_cron_remises_revision_native")),
        sa.CheckConstraint("etat != 'remise' OR (native_job_id IS NOT NULL AND native_config_revision IS NOT NULL)",
                           name=op.f("ck_agents_declencheurs_remises_agents_cron_remises_ack")),
    )


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : elle supprimerait des autorités cron conservées")
