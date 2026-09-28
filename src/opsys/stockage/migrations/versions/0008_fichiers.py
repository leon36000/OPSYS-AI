"""Dépôt de fichiers adressé par contenu (T1.4-e2) : fichiers, fichiers_blocs.

Révision : 0008 (après 0007_cles_chiffrement)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fichiers",
        sa.Column("empreinte_sha256", sa.String(64), nullable=False),
        sa.Column("taille_octets", sa.Integer(), nullable=False),
        sa.Column("type_mime", sa.String(32), nullable=False),
        sa.Column("nombre_blocs", sa.Integer(), nullable=False),
        sa.Column("complet", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.Column("complete_le", sa.Text()),
        sa.PrimaryKeyConstraint("empreinte_sha256", name="pk_fichiers"),
        sa.CheckConstraint("type_mime IN ('image/jpeg','image/png')", name="ck_fichiers_type_mime_valide"),
        sa.CheckConstraint("taille_octets BETWEEN 1 AND 10485760", name="ck_fichiers_taille_octets_valide"),
        sa.CheckConstraint("nombre_blocs BETWEEN 1 AND 64", name="ck_fichiers_nombre_blocs_valide"),
    )
    op.create_table(
        "fichiers_blocs",
        sa.Column("empreinte_sha256", sa.String(64), nullable=False),
        sa.Column("index_bloc", sa.Integer(), nullable=False),
        sa.Column("contenu_base64", sa.Text(), nullable=False),
        sa.Column("taille_octets", sa.Integer(), nullable=False),
        sa.Column("recu_le", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["empreinte_sha256"], ["fichiers.empreinte_sha256"],
            name="fk_fichiers_blocs_empreinte_sha256_fichiers",
        ),
        sa.PrimaryKeyConstraint("empreinte_sha256", "index_bloc", name="pk_fichiers_blocs"),
        sa.CheckConstraint("index_bloc >= 0", name="ck_fichiers_blocs_index_bloc_valide"),
    )


def downgrade() -> None:
    # Même garde que 0004/0005/0007 : une rétrogradation supprimerait des preuves de chantier
    # (photos après, signature) encore référencées par des interventions déjà complétées.
    raise RuntimeError("rétrogradation refusée : le dépôt de fichiers est sensible ; restaurer une sauvegarde")
