"""Clés de chiffrement destructibles (PLAN T4.2, POLITIQUE-geolocalisation.md §5) : effacement
cryptographique pour une donnée personnelle qu'un registre append-only ne peut jamais modifier ni
supprimer une fois écrite (`registres_maillons`, INSERT seul). Voir `opsys.stockage.schema.
CLES_CHIFFREMENT` et `opsys.cles_chiffrement` pour l'usage.

Révision : 0007 (après 0006_appareils)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cles_chiffrement",
        sa.Column("portee", sa.String(128), nullable=False),
        sa.Column("identifiant", sa.String(128), nullable=False),
        sa.Column("cle", sa.Text(), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("portee", "identifiant", name="pk_cles_chiffrement"),
    )


def downgrade() -> None:
    # Même garde que 0005 (identité) : une rétrogradation supprimerait des clés encore vivantes,
    # rendant irrécupérables des positions pourtant dans leur période de rétention valide —
    # l'inverse exact de ce que cette table protège.
    raise RuntimeError("rétrogradation refusée : les clés de chiffrement sont sensibles ; restaurer une sauvegarde")
