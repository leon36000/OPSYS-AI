"""Configuration versionnée et diagnostics bornés du connecteur STT M1."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connecteurs_stt",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("actif", sa.Boolean(), nullable=False),
        sa.Column("references", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("modifie_le", sa.Text(), nullable=False),
        sa.Column("modifie_par", sa.String(64), nullable=False),
        sa.Column("mutation_id", sa.String(128), nullable=False),
        sa.Column("mutation_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("id = 'stt-m1'", name="ck_connecteurs_stt_id_valide"),
        sa.CheckConstraint("revision > 0", name="ck_connecteurs_stt_revision_positive"),
    )
    op.create_table(
        "connecteurs_stt_historique",
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("instantane", sa.Text(), nullable=False),
    )
    op.create_table(
        "connecteurs_stt_commandes",
        sa.Column("mutation_id", sa.String(128), primary_key=True),
        sa.Column("acteur", sa.String(64), nullable=False),
        sa.Column("empreinte", sa.String(64), nullable=False),
        sa.Column("reponse", sa.Text(), nullable=False),
    )
    op.create_table(
        "connecteurs_stt_diagnostics",
        sa.Column("mutation_id", sa.String(128), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("acteur", sa.String(64), nullable=False),
        sa.Column("jeton", sa.String(64), nullable=False),
        sa.Column("statut", sa.String(32), nullable=False),
        sa.Column("resultat", sa.Text()),
        sa.Column("expire_le", sa.Text(), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : elle supprimerait configuration et historique STT")
