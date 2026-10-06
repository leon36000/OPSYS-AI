"""Lie un brouillon AP à une révision exacte d'un candidat OCR chiffré."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fusion_ap_ocr_sources",
        sa.Column("lot_id", sa.String(36), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("ocr_run_id", sa.String(36), nullable=False),
        sa.Column("revision_run", sa.Integer(), nullable=False),
        sa.Column("ocr_configuration_sha256", sa.String(64), nullable=False),
        sa.Column("ocr_profil_id", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["lot_id"], ["fusion_ap_brouillons.lot_id"]),
        sa.ForeignKeyConstraint(["ocr_run_id"], ["fusion_pdf_ocr_runs.ocr_run_id"]),
        sa.PrimaryKeyConstraint("lot_id"),
        sa.CheckConstraint("source_type = 'OCR_CANDIDAT'",
            name=op.f("ck_fusion_ap_ocr_sources_source_type_ocr_candidat"),
        ),
        sa.CheckConstraint("revision_run > 0", name=op.f("ck_fusion_ap_ocr_sources_revision_run_positive")),
        sa.CheckConstraint("length(ocr_configuration_sha256) = 64",
            name=op.f("ck_fusion_ap_ocr_sources_configuration_sha256_taille"),
        ),
        sa.CheckConstraint("length(ocr_profil_id) BETWEEN 1 AND 32",
            name=op.f("ck_fusion_ap_ocr_sources_profil_id_taille"),
        ),
    )
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER fusion_ap_ocr_sources_immutable_update "
            "BEFORE UPDATE ON fusion_ap_ocr_sources "
            "BEGIN SELECT RAISE(ABORT, 'source OCR AP immuable'); END"
        )
        op.execute(
            "CREATE TRIGGER fusion_ap_ocr_sources_immutable_delete "
            "BEFORE DELETE ON fusion_ap_ocr_sources "
            "BEGIN SELECT RAISE(ABORT, 'source OCR AP immuable'); END"
        )


def downgrade() -> None:
    existe = op.get_bind().execute(sa.text("SELECT 1 FROM fusion_ap_ocr_sources LIMIT 1")).first()
    if existe is not None:
        raise RuntimeError("rétrogradation refusée : elle supprimerait des références OCR de brouillons AP")
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS fusion_ap_ocr_sources_immutable_update")
        op.execute("DROP TRIGGER IF EXISTS fusion_ap_ocr_sources_immutable_delete")
    op.drop_table("fusion_ap_ocr_sources")
