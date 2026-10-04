"""Profils versionnés pour agents configurables.

Révision : 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents_configurables",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("departement", sa.String(64), nullable=False),
        sa.Column("responsabilite", sa.Text(), nullable=False),
        sa.Column("palier_modele", sa.String(16), nullable=False),
        sa.Column("outils", sa.Text(), nullable=False),
        sa.Column("budget_jour", sa.Integer(), nullable=False),
        sa.Column("budget_mois", sa.Integer(), nullable=False),
        sa.Column("limite_tours", sa.Integer(), nullable=False),
        sa.Column("limite_reessais", sa.Integer(), nullable=False),
        sa.Column("limite_concurrence", sa.Integer(), nullable=False),
        sa.Column("declencheurs", sa.Text(), nullable=False),
        sa.Column("actif", sa.Boolean(), nullable=False),
        sa.Column("supprime", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.Column("modifie_le", sa.Text(), nullable=False),
        sa.Column("modifie_par", sa.String(64), nullable=False),
        sa.Column("mutation_id", sa.String(128), nullable=False),
        sa.Column("mutation_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("palier_modele IN ('local','rapide','standard','fort')",
                           name="ck_agents_configurables_palier_valide"),
        sa.CheckConstraint("budget_jour > 0 AND budget_mois > 0",
                           name="ck_agents_configurables_budgets_positifs"),
        sa.CheckConstraint("limite_tours > 0 AND limite_reessais >= 0 AND limite_concurrence > 0",
                           name="ck_agents_configurables_limites_valides"),
        sa.CheckConstraint("revision > 0", name="ck_agents_configurables_revision_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_agents_configurables"),
    )
    op.create_table(
        "agents_configurables_historique",
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("instantane", sa.Text(), nullable=False),
        sa.Column("modifie_le", sa.Text(), nullable=False),
        sa.Column("modifie_par", sa.String(64), nullable=False),
        sa.Column("mutation_id", sa.String(128), nullable=False),
        sa.PrimaryKeyConstraint("agent_id", "revision", name="pk_agents_configurables_historique"),
    )
    op.create_table(
        "agents_configurables_commandes",
        sa.Column("mutation_id", sa.String(128), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("empreinte", sa.String(64), nullable=False),
        sa.Column("reponse", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("mutation_id", name="pk_agents_configurables_commandes"),
    )


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : l'historique durable des profils serait perdu")
