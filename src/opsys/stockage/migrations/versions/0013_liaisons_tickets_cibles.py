"""Tickets privés de liaison de cible M2/M3.

Révision : 0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("approbations", sa.Column("ticket_cible_hash", sa.String(64), nullable=True))
    op.create_table(
        "liaisons_tickets",
        sa.Column("ticket_hash", sa.String(64), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.Column("expire_le", sa.Text(), nullable=False),
        sa.Column("departement", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("cle_session", sa.Text(), nullable=False),
        sa.Column("affaire_id", sa.String(197), nullable=False),
        sa.Column("genre_affaire", sa.String(16), nullable=False),
        sa.Column("ligne_liaison_id", sa.String(64), nullable=False),
        sa.Column("outil", sa.String(128), nullable=False),
        sa.Column("empreinte_arguments", sa.String(64), nullable=False),
        sa.Column("statut", sa.String(16), server_default=sa.text("'disponible'"), nullable=False),
        sa.Column("demande_id", sa.String(32), nullable=True),
        sa.Column("reponse", sa.Text(), nullable=True),
        sa.Column("consomme_le", sa.Text(), nullable=True),
        sa.CheckConstraint("genre_affaire IN ('lead','opportunite')", name="ck_liaisons_tickets_genre_affaire_valide"),
        sa.CheckConstraint("statut IN ('disponible','scelle','consomme')", name="ck_liaisons_tickets_statut_valide"),
        sa.PrimaryKeyConstraint("ticket_hash", name="pk_liaisons_tickets"),
        sa.UniqueConstraint("demande_id", name="uq_liaisons_tickets_demande_id"),
    )
    op.create_index("ix_liaisons_tickets_expire", "liaisons_tickets", ["expire_le", "statut"])


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : tickets d'autorisation à conserver")
