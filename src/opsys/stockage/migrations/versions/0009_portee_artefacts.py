"""Portée départementale des artefacts tronqués.

Révision : 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("artefacts", sa.Column("departement", sa.String(64), nullable=True))
    op.add_column("artefacts", sa.Column("origine", sa.String(64), nullable=True))


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : les artefacts sont sensibles ; restaurer une sauvegarde")
