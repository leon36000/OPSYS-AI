"""Idempotence des mutations d'appareil (T1.4-b) : mutations_appliquees.

Révision : 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mutations_appliquees",
        sa.Column("appareil", sa.String(128), nullable=False),
        sa.Column("cle_idempotence", sa.String(128), nullable=False),
        sa.Column("outil", sa.String(128), nullable=False),
        sa.Column("empreinte_arguments", sa.String(64), nullable=False),
        sa.Column("reponse", sa.Text(), nullable=False),
        sa.Column("horodatage_appareil", sa.Text(), nullable=False),
        sa.Column("recu_le", sa.Text(), nullable=False),
        sa.Column("statut", sa.String(24), nullable=False),
        sa.PrimaryKeyConstraint("appareil", "cle_idempotence", name="pk_mutations_appliquees"),
        sa.CheckConstraint(
            "statut IN ('en_cours','ok','refus_metier','en_attente_approbation')",
            name="ck_mutations_appliquees_statut_valide",
        ),
    )


def downgrade() -> None:
    raise RuntimeError(
        "rétrogradation refusée : les mutations d'appareil sont sensibles ; restaurer une sauvegarde"
    )
