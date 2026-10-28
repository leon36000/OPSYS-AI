"""Classement manuel compagnon, sans modification des originaux reçus."""
import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pieces_classements",
        sa.Column("piece_id", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.String(200), nullable=False),
        sa.Column("categorie", sa.String(24), nullable=False),
        sa.Column("avant", sa.String(24), nullable=False),
        sa.Column("motif", sa.String(24), nullable=False),
        sa.Column("auteur", sa.String(200), nullable=False),
        sa.Column("mutation_id", sa.String(32), nullable=False),
        sa.Column("empreinte", sa.String(64), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("horodatage", sa.String(40), nullable=False),
        sa.Column("precedent", sa.String(64), nullable=False),
        sa.Column("chaine", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("piece_id", "revision"),
        sa.ForeignKeyConstraint(["piece_id"], ["pieces_projet.piece_id"],
                                name=op.f("fk_pieces_classements_piece_id_pieces_projet")),
        sa.UniqueConstraint("auteur", "mutation_id", name="uq_pieces_classements_saisie"),
        sa.CheckConstraint("revision >= 1 AND revision <= 32",
                           name=op.f("ck_pieces_classements_classements_revision")),
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM pieces_classements LIMIT 1")).first() is not None:
        raise RuntimeError("rétrogradation refusée : elle supprimerait l’historique de classement")
    op.drop_table("pieces_classements")
