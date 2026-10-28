"""Originaux reçus par projet, distincts de l’ingestion financière et du CAS M4."""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pieces_projet",
        sa.Column("piece_id", sa.String(32), nullable=False),
        sa.Column("lead_id", sa.String(200), nullable=False),
        sa.Column("client_id", sa.String(200), nullable=False),
        sa.Column("auteur", sa.String(200), nullable=False),
        sa.Column("mutation_id", sa.String(32), nullable=False),
        sa.Column("empreinte", sa.String(64), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("type_mime", sa.String(32), nullable=False),
        sa.Column("taille_octets", sa.Integer(), nullable=False),
        sa.Column("recu_le", sa.String(40), nullable=False),
        sa.Column("version_format", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.String(24), nullable=False),
        sa.Column("chiffre", sa.Text(), nullable=False),
        sa.Column("titre_nonce", sa.String(24), nullable=False),
        sa.Column("titre_chiffre", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("piece_id"),
        sa.UniqueConstraint("auteur", "mutation_id", name="uq_pieces_projet_saisie"),
        sa.CheckConstraint("version_format = 1", name=op.f("ck_pieces_projet_pieces_format")),
        sa.CheckConstraint("taille_octets > 0 AND taille_octets <= 1048576",
                           name=op.f("ck_pieces_projet_pieces_taille")),
        sa.CheckConstraint("type_mime IN ('image/jpeg','image/png','application/pdf')",
                           name=op.f("ck_pieces_projet_pieces_type")),
    )
    op.create_index("ix_pieces_projet_lead", "pieces_projet", ["lead_id", "recu_le", "piece_id"])


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM pieces_projet LIMIT 1")).first() is not None:
        raise RuntimeError("rétrogradation refusée : elle supprimerait des pièces reçues")
    op.drop_index("ix_pieces_projet_lead", table_name="pieces_projet")
    op.drop_table("pieces_projet")
