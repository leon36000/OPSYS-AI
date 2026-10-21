"""Identifiants de cycles réels du runtime dans les admissions.

Révision : 0012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents_reservations") as batch:
        batch.drop_constraint("uq_agents_reservations_execution_tentative", type_="unique")
        batch.add_column(sa.Column("attempt_id", sa.String(160), nullable=True))
        batch.add_column(sa.Column("cycle_id", sa.String(160), nullable=True))
        batch.add_column(sa.Column("candidate_index", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("stream_ordinal", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("is_fallback_retry", sa.Boolean(), nullable=True))
        batch.create_unique_constraint("uq_agents_reservations_cycle", ["cycle_id"])
        batch.create_check_constraint("stream_ordinal_valide", "stream_ordinal IS NULL OR stream_ordinal >= 0")


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : métadonnées de cycles d'admission à conserver")
