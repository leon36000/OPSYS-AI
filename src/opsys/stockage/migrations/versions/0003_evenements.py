"""Bus d'événements (ADR-0009 §3) : evenements_sortants, evenements_recus.

Révision : 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evenements_sortants",
        sa.Column("evenement_id", sa.String(128), nullable=False),
        sa.Column("type_evenement", sa.String(128), nullable=False),
        sa.Column("producteur", sa.String(64), nullable=False),
        sa.Column("charge", sa.Text(), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("evenement_id", name="pk_evenements_sortants"),
    )
    op.create_index("ix_evenements_sortants_type", "evenements_sortants", ["type_evenement", "cree_le"])

    op.create_table(
        "evenements_recus",
        sa.Column("evenement_id", sa.String(128), nullable=False),
        sa.Column("consommateur", sa.String(64), nullable=False),
        sa.Column("statut", sa.String(16), nullable=False),
        sa.Column("tentatives", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("prochaine_tentative", sa.Text()),
        sa.Column("resultat", sa.Text()),
        sa.Column("derniere_erreur", sa.Text()),
        sa.PrimaryKeyConstraint("evenement_id", "consommateur", name="pk_evenements_recus"),
        sa.ForeignKeyConstraint(
            ["evenement_id"], ["evenements_sortants.evenement_id"],
            name="fk_evenements_recus_evenement_id_evenements_sortants",
        ),
        sa.CheckConstraint(
            "statut IN ('echec','traite','quarantaine')",
            name="ck_evenements_recus_statut_valide",
        ),
    )
    op.create_index("ix_evenements_recus_statut", "evenements_recus", ["statut", "prochaine_tentative"])


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : le bus d'événements est sensible ; restaurer une sauvegarde")
