"""Brouillons de factures AP chiffrés et séparés du registre comptable."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fusion_ap_brouillons",
        sa.Column("lot_id", sa.String(36), primary_key=True),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("configuration_sha256", sa.String(64), nullable=False),
        sa.Column("extracteur", sa.String(64), nullable=False),
        sa.Column("revision_pdf", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("statut", sa.String(24), nullable=False),
        sa.Column("auteur", sa.String(64), nullable=False),
        sa.Column("modifie_par", sa.String(64), nullable=False),
        sa.Column("cle_reference", sa.String(64), nullable=False),
        sa.Column("version_format", sa.Integer(), nullable=False),
        sa.Column("proposition_nonce", sa.String(24), nullable=False),
        sa.Column("proposition_cipher", sa.Text(), nullable=False),
        sa.Column("proposition_cipher_octets", sa.Integer(), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.Column("modifie_le", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["lot_id"], ["fusion_pdf_lots.lot_id"]),
        sa.CheckConstraint(
            "length(source_sha256) = 64 AND length(configuration_sha256) = 64",
            name=op.f("ck_fusion_ap_brouillons_empreintes"),
        ),
        sa.CheckConstraint(
            "revision_pdf > 0 AND revision > 0 AND version_format = 1",
            name=op.f("ck_fusion_ap_brouillons_versions"),
        ),
        sa.CheckConstraint("statut = 'A_REVOIR'", name=op.f("ck_fusion_ap_brouillons_statut_revue")),
        sa.CheckConstraint("length(proposition_nonce) = 16", name=op.f("ck_fusion_ap_brouillons_nonce_taille")),
        sa.CheckConstraint(
            "proposition_cipher_octets BETWEEN 17 AND 8208",
            name=op.f("ck_fusion_ap_brouillons_proposition_taille"),
        ),
    )
    op.create_table(
        "fusion_ap_commandes",
        sa.Column("lot_id", sa.String(36), primary_key=True),
        sa.Column("acteur", sa.String(64), primary_key=True),
        sa.Column("mutation_id", sa.String(128), primary_key=True),
        sa.Column("empreinte_requete", sa.String(64), nullable=False),
        sa.Column("revision_resultat", sa.Integer(), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["lot_id"], ["fusion_ap_brouillons.lot_id"]),
        sa.CheckConstraint("length(empreinte_requete) = 64", name=op.f("ck_fusion_ap_commandes_empreinte_taille")),
        sa.CheckConstraint("revision_resultat > 0", name=op.f("ck_fusion_ap_commandes_revision_positive")),
    )
    op.create_index("ix_fusion_ap_commandes_lot", "fusion_ap_commandes", ["lot_id"])


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : elle supprimerait des brouillons AP conservés")
