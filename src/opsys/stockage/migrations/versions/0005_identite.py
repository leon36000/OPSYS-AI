"""Identité (ADR-0009 §5) : personnes, rôles, et colonnes de décision (niveau, rôle, attestation).

Révision : 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_ROLES = ("nathan_owner", "admin", "finance", "manager", "seller", "employee", "client", "system_agent")


def upgrade() -> None:
    op.create_table(
        "personnes",
        sa.Column("identifiant", sa.String(64), nullable=False),
        sa.Column("nom", sa.Text(), nullable=False),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mot_de_passe_hash", sa.Text(), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("identifiant", name="pk_personnes"),
    )
    op.create_table(
        "roles",
        sa.Column("identifiant", sa.String(64), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["identifiant"], ["personnes.identifiant"],
                                name="fk_roles_identifiant_personnes"),
        sa.PrimaryKeyConstraint("identifiant", "role", name="pk_roles"),
        sa.CheckConstraint(f"role IN ({', '.join(repr(r) for r in _ROLES)})", name="ck_roles_role_valide"),
    )
    # Colonnes ajoutées, nullables : une demande importée de l'ancien `etat.db` (pré-ADR-0009) n'a
    # ni niveau ni rôle ni attestation ; le socle retombe alors sur le comportement le plus
    # restrictif (voir `opsys.approbations.decider`). Simple ADD COLUMN, pas de mode batch requis
    # (aucune contrainte ajoutée sur une table existante).
    op.add_column("approbations", sa.Column("niveau", sa.String(4)))
    op.add_column("approbations", sa.Column("decide_role", sa.Text()))
    op.add_column("approbations", sa.Column("attestation", sa.Text()))


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : identité et décisions sont sensibles ; restaurer une sauvegarde")
