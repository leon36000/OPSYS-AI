"""Lots d'import CSV chiffrés, propositions et quota atomique."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fusion_lots",
        sa.Column("lot_id", sa.String(36), primary_key=True),
        sa.Column("acteur", sa.String(64), nullable=False),
        sa.Column("mutation_id", sa.String(128), nullable=False),
        sa.Column("empreinte_requete", sa.String(64), nullable=False),
        sa.Column("cle_deduplication", sa.String(64), nullable=False, unique=True),
        sa.Column("compte_interne_id", sa.String(64), nullable=False),
        sa.Column("devise", sa.String(3), nullable=False),
        sa.Column("mapping_colonnes", sa.Text(), nullable=False),
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
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_empreinte", sa.String(64)),
        sa.Column("statut", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("curseur", sa.Integer(), nullable=False),
        sa.Column("total_lignes", sa.Integer()),
        sa.Column("nombre_propositions", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.Text()),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.Column("modifie_le", sa.Text(), nullable=False),
        sa.UniqueConstraint("acteur", "mutation_id", name="uq_fusion_lots_acteur_mutation"),
        sa.CheckConstraint("devise = 'CAD'", name="ck_fusion_lots_devise_cad"),
        sa.CheckConstraint("source_octets BETWEEN 1 AND 1048576", name="ck_fusion_lots_source_taille"),
        sa.CheckConstraint("source_cipher_octets >= source_octets", name="ck_fusion_lots_source_cipher_taille"),
        sa.CheckConstraint("resultat_cipher_octets >= 0", name="ck_fusion_lots_resultat_cipher_taille"),
        sa.CheckConstraint("snapshot_version >= 0", name="ck_fusion_lots_snapshot_version"),
        sa.CheckConstraint("revision > 0 AND curseur >= 0", name="ck_fusion_lots_revision_curseur"),
        sa.CheckConstraint("nombre_propositions >= 0", name="ck_fusion_lots_nombre_propositions"),
        sa.CheckConstraint(
            "statut IN ('RECU','EN_COURS','PROPOSITIONS','AUCUNE_PROPOSITION','REFUSE',"
            "'SNAPSHOT_OBSOLETE','ERREUR_REPRENABLE')",
            name="ck_fusion_lots_statut_valide",
        ),
    )
    op.create_index("ix_fusion_lots_cree", "fusion_lots", ["cree_le"])
    op.create_index("ix_fusion_lots_acteur", "fusion_lots", ["acteur"])
    op.create_table(
        "fusion_commandes",
        sa.Column("acteur", sa.String(64), primary_key=True),
        sa.Column("mutation_id", sa.String(128), primary_key=True),
        sa.Column("empreinte_requete", sa.String(64), nullable=False),
        sa.Column("lot_id", sa.String(36), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["lot_id"], ["fusion_lots.lot_id"]),
    )
    op.create_table(
        "fusion_lignes",
        sa.Column("lot_id", sa.String(36), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.String(24), nullable=False),
        sa.Column("cipher", sa.Text(), nullable=False),
        sa.Column("cipher_octets", sa.Integer(), nullable=False),
        sa.Column("est_proposition", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["lot_id"], ["fusion_lots.lot_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("lot_id", "numero"),
        sa.CheckConstraint("numero >= 2", name="ck_fusion_lignes_numero_csv"),
        sa.CheckConstraint("cipher_octets > 0", name="ck_fusion_lignes_cipher_taille"),
    )
    op.create_table(
        "fusion_quota",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lots", sa.Integer(), nullable=False),
        sa.Column("octets_cipher", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_fusion_quota_singleton"),
        sa.CheckConstraint("lots BETWEEN 0 AND 64", name="ck_fusion_quota_lots_borne"),
        sa.CheckConstraint("octets_cipher BETWEEN 0 AND 67108864", name="ck_fusion_quota_octets_bornes"),
    )
    op.get_bind().execute(sa.text("INSERT INTO fusion_quota (id, lots, octets_cipher) VALUES (1, 0, 0)"))


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : elle supprimerait les imports financiers conservés")
