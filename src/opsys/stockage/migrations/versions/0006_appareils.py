"""Appairage d'appareil (ADR-0009 §5, T1.4-c2) : un appareil, une personne, un rôle de jeton.

Révision : 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_ROLES_APPAREIL = ("admin", "employee", "seller")


def upgrade() -> None:
    op.create_table(
        "appareils",
        sa.Column("identifiant", sa.String(128), nullable=False),
        sa.Column("personne", sa.String(64), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("appaire_le", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["personne"], ["personnes.identifiant"],
                                name="fk_appareils_personne_personnes"),
        sa.PrimaryKeyConstraint("identifiant", name="pk_appareils"),
        sa.CheckConstraint(f"role IN ({', '.join(repr(r) for r in _ROLES_APPAREIL)})",
                           name="ck_appareils_role_appareil_valide"),
    )


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : l'appairage d'appareil est sensible ; restaurer une sauvegarde")
