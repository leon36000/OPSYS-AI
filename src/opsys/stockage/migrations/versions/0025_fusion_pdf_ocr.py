"""Compartiment OCR chiffré des candidats issus de lots PDF refusés."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

_RESERVATION_MAX = 262_160


def upgrade() -> None:
    op.create_table(
        "fusion_pdf_ocr_runs",
        sa.Column("ocr_run_id", sa.String(36), primary_key=True),
        sa.Column("pdf_lot_id", sa.String(36), nullable=False),
        sa.Column("acteur", sa.String(64), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("revision_pdf_source", sa.Integer(), nullable=False),
        sa.Column("configuration_sha256", sa.String(64), nullable=False),
        sa.Column("profil_id", sa.String(32), nullable=False),
        sa.Column("cle_reference", sa.String(64), nullable=False),
        sa.Column("version_format", sa.Integer(), nullable=False),
        sa.Column("revision_run", sa.Integer(), nullable=False),
        sa.Column("statut", sa.String(24), nullable=False),
        sa.Column("reserve_octets", sa.Integer(), nullable=False),
        sa.Column("resultat_nonce", sa.String(24)),
        sa.Column("resultat_cipher", sa.Text()),
        sa.Column("resultat_cipher_octets", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(64)),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.Column("modifie_le", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["pdf_lot_id"], ["fusion_pdf_lots.lot_id"]),
        sa.UniqueConstraint(
            "pdf_lot_id", "source_sha256", "revision_pdf_source", "configuration_sha256",
            name="uq_fusion_pdf_ocr_runs_source_profil",
        ),
        sa.CheckConstraint("length(ocr_run_id) = 36 AND length(pdf_lot_id) = 36",
                           name="ck_fusion_pdf_ocr_runs_ids_taille"),
        sa.CheckConstraint("length(acteur) BETWEEN 1 AND 64", name="ck_fusion_pdf_ocr_runs_acteur_taille"),
        sa.CheckConstraint("length(source_sha256) = 64 AND length(configuration_sha256) = 64",
                           name="ck_fusion_pdf_ocr_runs_empreintes"),
        sa.CheckConstraint("revision_pdf_source BETWEEN 1 AND 2147483647",
                           name="ck_fusion_pdf_ocr_runs_revision_pdf_source_borne"),
        sa.CheckConstraint("length(profil_id) BETWEEN 1 AND 32", name="ck_fusion_pdf_ocr_runs_profil_taille"),
        sa.CheckConstraint("length(cle_reference) BETWEEN 1 AND 64",
                           name="ck_fusion_pdf_ocr_runs_cle_reference_taille"),
        sa.CheckConstraint("version_format = 1", name="ck_fusion_pdf_ocr_runs_version_format"),
        sa.CheckConstraint("revision_run BETWEEN 1 AND 2147483647",
                           name="ck_fusion_pdf_ocr_runs_revision_run_borne"),
        sa.CheckConstraint(
            "statut IN ('RESERVE','A_REVOIR','REFUSE','ERREUR_REPRENABLE','PERIME')",
            name="ck_fusion_pdf_ocr_runs_statut_valide",
        ),
        sa.CheckConstraint("reserve_octets BETWEEN 0 AND 262160",
                           name="ck_fusion_pdf_ocr_runs_reserve_octets_borne"),
        sa.CheckConstraint("resultat_cipher_octets BETWEEN 0 AND 262160",
                           name="ck_fusion_pdf_ocr_runs_resultat_taille"),
        sa.CheckConstraint("code IS NULL OR length(code) BETWEEN 1 AND 64",
                           name="ck_fusion_pdf_ocr_runs_code_taille"),
        sa.CheckConstraint(
            "(statut = 'RESERVE' AND reserve_octets = 262160 AND resultat_nonce IS NULL "
            "AND resultat_cipher IS NULL AND resultat_cipher_octets = 0 AND code IS NULL) OR "
            "(statut = 'A_REVOIR' AND reserve_octets = 0 AND resultat_nonce IS NOT NULL "
            "AND length(resultat_nonce) = 16 AND resultat_cipher IS NOT NULL "
            "AND resultat_cipher_octets BETWEEN 17 AND 262160 "
            "AND length(resultat_cipher) BETWEEN 24 AND 349548 "
            "AND length(resultat_cipher) = 4 * ((resultat_cipher_octets + 2) / 3) AND code IS NULL) OR "
            "(statut IN ('REFUSE','ERREUR_REPRENABLE','PERIME') AND reserve_octets = 0 "
            "AND resultat_nonce IS NULL AND resultat_cipher IS NULL AND resultat_cipher_octets = 0 "
            "AND code IS NOT NULL AND length(code) BETWEEN 1 AND 64)",
            name="ck_fusion_pdf_ocr_runs_etat_payload_reservation",
        ),
    )
    op.create_index("ix_fusion_pdf_ocr_runs_cree", "fusion_pdf_ocr_runs", ["cree_le"])
    op.create_table(
        "fusion_pdf_ocr_commandes",
        sa.Column("acteur", sa.String(64), primary_key=True),
        sa.Column("mutation_id", sa.String(128), primary_key=True),
        sa.Column("empreinte_requete", sa.String(64), nullable=False),
        sa.Column("ocr_run_id", sa.String(36), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["ocr_run_id"], ["fusion_pdf_ocr_runs.ocr_run_id"]),
        sa.CheckConstraint("length(acteur) BETWEEN 1 AND 64", name="ck_fusion_pdf_ocr_commandes_acteur_taille"),
        sa.CheckConstraint("length(mutation_id) BETWEEN 1 AND 128",
                           name="ck_fusion_pdf_ocr_commandes_mutation_taille"),
        sa.CheckConstraint("length(empreinte_requete) = 64",
                           name="ck_fusion_pdf_ocr_commandes_empreinte_taille"),
        sa.CheckConstraint("length(ocr_run_id) = 36", name="ck_fusion_pdf_ocr_commandes_run_id_taille"),
    )
    op.create_index("ix_fusion_pdf_ocr_commandes_run", "fusion_pdf_ocr_commandes", ["ocr_run_id"])
    op.create_table(
        "fusion_pdf_ocr_quota",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lots", sa.Integer(), nullable=False),
        sa.Column("octets_cipher", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_fusion_pdf_ocr_quota_singleton"),
        sa.CheckConstraint("lots BETWEEN 0 AND 16", name="ck_fusion_pdf_ocr_quota_lots_borne"),
        sa.CheckConstraint("octets_cipher BETWEEN 0 AND 4194304",
                           name="ck_fusion_pdf_ocr_quota_octets_bornes"),
    )
    op.get_bind().execute(sa.text(
        "INSERT INTO fusion_pdf_ocr_quota (id, lots, octets_cipher) VALUES (1, 0, 0)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    existe_run = bind.execute(sa.text("SELECT 1 FROM fusion_pdf_ocr_runs LIMIT 1")).first()
    existe_commande = bind.execute(sa.text("SELECT 1 FROM fusion_pdf_ocr_commandes LIMIT 1")).first()
    quota_non_vide = bind.execute(sa.text(
        "SELECT 1 FROM fusion_pdf_ocr_quota WHERE lots <> 0 OR octets_cipher <> 0 LIMIT 1"
    )).first()
    if existe_run is not None or existe_commande is not None or quota_non_vide is not None:
        raise RuntimeError("rétrogradation refusée : elle supprimerait des runs OCR ou leur quota réservé")
    op.drop_index("ix_fusion_pdf_ocr_commandes_run", table_name="fusion_pdf_ocr_commandes")
    op.drop_table("fusion_pdf_ocr_commandes")
    op.drop_index("ix_fusion_pdf_ocr_runs_cree", table_name="fusion_pdf_ocr_runs")
    op.drop_table("fusion_pdf_ocr_runs")
    op.drop_table("fusion_pdf_ocr_quota")
