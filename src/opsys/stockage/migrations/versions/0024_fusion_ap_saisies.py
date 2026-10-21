"""Lie les PDF/AP aux saisies humaines M5, sans recopier une vérité comptable."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fusion_ap_saisies",
        sa.Column("lot_id", sa.String(36), primary_key=True),
        sa.Column("acteur", sa.String(64), nullable=False),
        sa.Column("mutation_id", sa.String(128), nullable=False),
        sa.Column("commande_sha256", sa.String(64), nullable=False),
        sa.Column("preuve_json", sa.Text(), nullable=False),
        sa.Column("approbation_id", sa.String(12), nullable=False, unique=True),
        sa.Column("facture_id", sa.String(64), nullable=False),
        sa.Column("maillon_id", sa.String(64), nullable=False),
        sa.Column("rang_maillon", sa.Integer(), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["lot_id"], ["fusion_ap_brouillons.lot_id"]),
        sa.ForeignKeyConstraint(["approbation_id"], ["approbations.id"]),
        sa.UniqueConstraint("acteur", "mutation_id", name="uq_fusion_ap_saisies_acteur_mutation"),
        sa.CheckConstraint("length(commande_sha256) = 64 AND length(maillon_id) = 64",
                           name=op.f("ck_fusion_ap_saisies_empreintes")),
        sa.CheckConstraint("rang_maillon >= 0", name=op.f("ck_fusion_ap_saisies_rang")),
        sa.CheckConstraint("length(preuve_json) BETWEEN 2 AND 4096", name=op.f("ck_fusion_ap_saisies_preuve_bornee")),
    )


def downgrade() -> None:
    existe = op.get_bind().execute(sa.text("SELECT 1 FROM fusion_ap_saisies LIMIT 1")).first()
    if existe is not None:
        raise RuntimeError("rétrogradation refusée : elle effacerait des provenances de saisie M5")
    op.drop_table("fusion_ap_saisies")
