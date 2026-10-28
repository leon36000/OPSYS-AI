"""File durable de nettoyage des fichiers courants, distincte du DELETE logique."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "effacements_cles",
        sa.Column("purge_id", sa.String(32), nullable=False),
        sa.Column("portee", sa.String(128), nullable=False),
        sa.Column("identifiant", sa.String(128), nullable=False),
        sa.Column("demande_id", sa.Text(), nullable=True),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.Column("cle_detruite", sa.Boolean(), nullable=False),
        sa.Column("etat_fichiers", sa.String(24), nullable=False),
        sa.Column("motif", sa.String(40), nullable=True),
        sa.PrimaryKeyConstraint("purge_id"),
        sa.CheckConstraint("etat_fichiers IN ('en_attente','termine','non_qualifie')",
                           name=op.f("ck_effacements_cles_etat_fichiers_valide")),
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM effacements_cles LIMIT 1")).first() is not None:
        raise RuntimeError("rétrogradation refusée : elle supprimerait des effacements durables")
    op.drop_table("effacements_cles")
