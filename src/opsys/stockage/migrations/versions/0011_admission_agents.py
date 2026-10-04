"""Budgets globaux et réservations atomiques des agents.

Révision : 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents_politique_entreprise",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("budget_jour", sa.Integer(), nullable=False),
        sa.Column("budget_mois", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("modifie_le", sa.Text(), nullable=False),
        sa.Column("modifie_par", sa.String(64), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_agents_politique_entreprise_singleton"),
        sa.CheckConstraint("budget_jour > 0 AND budget_mois >= budget_jour",
                           name="ck_agents_politique_entreprise_budgets_valides"),
        sa.CheckConstraint("revision > 0", name="ck_agents_politique_entreprise_revision_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_agents_politique_entreprise"),
    )
    op.create_table(
        "agents_reservations",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("departement", sa.String(64), nullable=False),
        sa.Column("execution_id", sa.String(128), nullable=False),
        sa.Column("cle_idempotence", sa.String(128), nullable=False),
        sa.Column("tokens_plafond", sa.Integer(), nullable=False),
        sa.Column("tokens_reels", sa.Integer()),
        sa.Column("jour", sa.Text(), nullable=False),
        sa.Column("mois", sa.String(7), nullable=False),
        sa.Column("tours", sa.Integer(), nullable=False),
        sa.Column("reessais", sa.Integer(), nullable=False),
        sa.Column("statut", sa.String(16), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.Column("modifie_le", sa.Text(), nullable=False),
        sa.CheckConstraint("tokens_plafond > 0 AND (tokens_reels IS NULL OR tokens_reels >= 0)",
                           name="ck_agents_reservations_tokens_valides"),
        sa.CheckConstraint("tours > 0 AND reessais >= 0", name="ck_agents_reservations_tours_valides"),
        sa.CheckConstraint("statut IN ('reservee','conciliee','liberee')",
                           name="ck_agents_reservations_statut_valide"),
        sa.PrimaryKeyConstraint("id", name="pk_agents_reservations"),
        sa.UniqueConstraint("agent_id", "cle_idempotence", name="uq_agents_reservations_agent_cle"),
        sa.UniqueConstraint("agent_id", "execution_id", "reessais",
                            name="uq_agents_reservations_execution_tentative"),
    )
    op.create_table(
        "agents_reservations_historique",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("reservation_id", sa.String(32), nullable=False),
        sa.Column("evenement", sa.String(16), nullable=False),
        sa.Column("tokens_reels", sa.Integer()),
        sa.Column("raison", sa.Text(), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.CheckConstraint("evenement IN ('reservee','conciliee','liberee')",
                           name="ck_agents_reservations_historique_evenement_valide"),
        sa.PrimaryKeyConstraint("id", name="pk_agents_reservations_historique"),
    )
    op.create_index("ix_agents_reservations_active", "agents_reservations", ["statut", "agent_id", "jour"])


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : historique financier des admissions à conserver")
