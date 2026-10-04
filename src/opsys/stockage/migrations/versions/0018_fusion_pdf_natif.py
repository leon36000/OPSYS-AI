"""Compartiment PDF financier chiffré et préparatoire, sans modification CSV."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fusion_pdf_lots",
        sa.Column("lot_id", sa.String(36), primary_key=True),
        sa.Column("acteur", sa.String(64), nullable=False),
        sa.Column("mutation_id", sa.String(128), nullable=False),
        sa.Column("empreinte_requete", sa.String(64), nullable=False),
        sa.Column("cle_deduplication", sa.String(64), nullable=False, unique=True),
        sa.Column("type_source", sa.String(16), nullable=False),
        sa.Column("classe", sa.String(16), nullable=False),
        sa.Column("extracteur", sa.String(64), nullable=False),
        sa.Column("configuration_sha256", sa.String(64), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_octets", sa.Integer(), nullable=False),
        sa.Column("source_nonce", sa.String(24), nullable=False),
        sa.Column("source_cipher", sa.Text(), nullable=False),
        sa.Column("source_cipher_octets", sa.Integer(), nullable=False),
        sa.Column("resultat_nonce", sa.String(24)),
        sa.Column("resultat_cipher", sa.Text()),
        sa.Column("resultat_cipher_octets", sa.Integer(), nullable=False),
        sa.Column("cle_reference", sa.String(64), nullable=False),
        sa.Column("version_format", sa.Integer(), nullable=False),
        sa.Column("statut", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("total_pages", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(64)),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.Column("modifie_le", sa.Text(), nullable=False),
        sa.UniqueConstraint("acteur", "mutation_id", name="uq_fusion_pdf_lots_acteur_mutation"),
        sa.CheckConstraint(
            "type_source = 'pdf_natif' AND classe = 'FINANCIAL'", name="ck_fusion_pdf_lots_classification",
        ),
        sa.CheckConstraint("source_octets BETWEEN 1 AND 1048576", name="ck_fusion_pdf_lots_source_taille"),
        sa.CheckConstraint(
            "source_cipher_octets = source_octets + 16", name="ck_fusion_pdf_lots_source_cipher_taille",
        ),
        sa.CheckConstraint(
            "resultat_cipher_octets BETWEEN 0 AND 524304", name="ck_fusion_pdf_lots_resultat_taille",
        ),
        sa.CheckConstraint("version_format = 1 AND revision > 0", name="ck_fusion_pdf_lots_versions"),
        sa.CheckConstraint("total_pages BETWEEN 0 AND 20", name="ck_fusion_pdf_lots_pages_borne"),
        sa.CheckConstraint(
            "statut IN ('RECU','EXTRAIT_PREPARATOIRE','REFUSE','ERREUR_REPRENABLE')",
            name="ck_fusion_pdf_lots_statut_valide",
        ),
        sa.CheckConstraint(
            "(statut = 'EXTRAIT_PREPARATOIRE' AND resultat_nonce IS NOT NULL AND resultat_cipher IS NOT NULL "
            "AND resultat_cipher_octets > 16 AND total_pages > 0 AND code IS NULL) OR "
            "(statut <> 'EXTRAIT_PREPARATOIRE' AND resultat_nonce IS NULL AND resultat_cipher IS NULL "
            "AND resultat_cipher_octets = 0 AND total_pages = 0)", name="ck_fusion_pdf_lots_resultat_etat",
        ),
    )
    op.create_index("ix_fusion_pdf_lots_cree", "fusion_pdf_lots", ["cree_le"])
    op.create_table(
        "fusion_pdf_commandes",
        sa.Column("acteur", sa.String(64), primary_key=True),
        sa.Column("mutation_id", sa.String(128), primary_key=True),
        sa.Column("empreinte_requete", sa.String(64), nullable=False),
        sa.Column("lot_id", sa.String(36), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["lot_id"], ["fusion_pdf_lots.lot_id"]),
    )
    op.create_table(
        "fusion_pdf_quota",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lots", sa.Integer(), nullable=False),
        sa.Column("octets_cipher", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_fusion_pdf_quota_singleton"),
        sa.CheckConstraint("lots BETWEEN 0 AND 16", name="ck_fusion_pdf_quota_lots_borne"),
        sa.CheckConstraint("octets_cipher BETWEEN 0 AND 16777216", name="ck_fusion_pdf_quota_octets_bornes"),
    )
    op.get_bind().execute(sa.text("INSERT INTO fusion_pdf_quota (id, lots, octets_cipher) VALUES (1, 0, 0)"))


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : elle supprimerait les PDF financiers conservés")
