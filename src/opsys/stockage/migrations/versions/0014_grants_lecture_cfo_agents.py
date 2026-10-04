"""Droits humains et tickets privés de lecture CFO préparatoire des profils."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opsys_instance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instance_id", sa.String(36), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_opsys_instance_singleton"),
        sa.PrimaryKeyConstraint("id", name="pk_opsys_instance"),
        sa.UniqueConstraint("instance_id", name="uq_opsys_instance_instance_id"),
    )
    op.bulk_insert(
        sa.table("opsys_instance", sa.column("id", sa.Integer()), sa.column("instance_id", sa.String())),
        [{"id": 1, "instance_id": str(uuid.uuid4())}],
    )
    op.create_table(
        "agents_grants_cfo",
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("instance_id", sa.String(128), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("tools", sa.Text(), nullable=False),
        sa.Column("reports_per_day", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("report_date_start", sa.String(10), nullable=False),
        sa.Column("report_date_end", sa.String(10), nullable=False),
        sa.Column("granted_by", sa.String(64), nullable=False),
        sa.Column("granted_role", sa.String(32), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("modified_at", sa.Text(), nullable=False),
        sa.Column("modified_by", sa.String(64), nullable=False),
        sa.Column("modified_role", sa.String(32), nullable=False),
        sa.CheckConstraint("profile_revision > 0 AND version > 0", name="ck_agents_grants_cfo_revision_positive"),
        sa.CheckConstraint("report_date_start <= report_date_end", name="ck_agents_grants_cfo_report_dates_ordered"),
        sa.CheckConstraint("reports_per_day BETWEEN 1 AND 20", name="ck_agents_grants_cfo_quota_valid"),
        sa.PrimaryKeyConstraint("agent_id", name="pk_agents_grants_cfo"),
    )
    op.create_table(
        "agents_grants_cfo_historique",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(16), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("actor_role", sa.String(32), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint("event IN ('grant','revocation')", name="ck_agents_grants_cfo_event_valid"),
        sa.PrimaryKeyConstraint("id", name="pk_agents_grants_cfo_historique"),
    )
    op.create_table(
        "agents_tickets_cfo",
        sa.Column("ticket_hash", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("grant_version", sa.Integer(), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("instance_id", sa.String(128), nullable=False),
        sa.Column("tool", sa.String(128), nullable=False),
        sa.Column("arguments_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), server_default=sa.text("'available'"), nullable=False),
        sa.Column("consumed_at", sa.Text()),
        sa.CheckConstraint(
            "tool IN ('m5_preparer_dossier_decision_cfo','m5_preparer_decision_capital')",
            name="ck_agents_tickets_cfo_tool_valid",
        ),
        sa.CheckConstraint("status IN ('available','consumed')", name="ck_agents_tickets_cfo_status_valid"),
        sa.PrimaryKeyConstraint("ticket_hash", name="pk_agents_tickets_cfo"),
    )
    op.create_index("ix_agents_tickets_cfo_agent_created", "agents_tickets_cfo", ["agent_id", "created_at"])


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : grants et tickets d'accès financiers doivent être conservés")
