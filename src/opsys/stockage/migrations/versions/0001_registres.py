"""Registres append-only des départements.

Révision : 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registres_maillons",
        sa.Column("departement", sa.String(64), nullable=False),
        sa.Column("registre", sa.String(64), nullable=False),
        sa.Column("rang", sa.Integer(), nullable=False),
        sa.Column("maillon", sa.Text(), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("departement", "registre", "rang", name="pk_registres_maillons"),
    )


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : les registres sont append-only ; restaurer une sauvegarde")
