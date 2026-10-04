"""Intentions de remise cron des profils ; leur configuration reste au registre existant."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents_declencheurs_intentions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("instance_id", sa.String(36), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("trigger_hash", sa.String(64), nullable=False),
        sa.Column("memory_policy_hash", sa.String(64), nullable=False),
        sa.Column("fuseau", sa.String(64), nullable=False),
        sa.Column("declaration_key", sa.String(96), nullable=False, unique=True),
        sa.Column("statut", sa.String(24), nullable=False),
        sa.Column("demande_par", sa.String(64), nullable=False),
        sa.Column("demande_role", sa.String(32), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.Column("modifie_le", sa.Text(), nullable=False),
        sa.Column("retrait_par", sa.String(64)),
        sa.CheckConstraint("profile_revision > 0",
                           name=op.f("ck_agents_declencheurs_intentions_agents_cron_revision_positive")),
        sa.CheckConstraint("statut IN ('a_declarer','a_retirer','retiree')",
                           name=op.f("ck_agents_declencheurs_intentions_agents_cron_statut_valide")),
    )
    op.create_index("ix_agents_cron_attente", "agents_declencheurs_intentions", ["statut", "agent_id"])
    op.create_table(
        "agents_declencheurs_commandes",
        sa.Column("acteur", sa.String(64), primary_key=True),
        sa.Column("mutation_id", sa.String(128), primary_key=True),
        sa.Column("empreinte", sa.String(64), nullable=False),
        sa.Column("reponse", sa.Text(), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : elle supprimerait intentions et reçus de remise cron")
