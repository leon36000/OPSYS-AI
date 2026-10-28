"""Originaux courriel chiffrés internes, sans rattachement ou permission de canal."""
import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "receptions_courriel",
        sa.Column("identite_id", sa.String(64), nullable=False),
        sa.Column("recu_id", sa.String(32), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("taille_octets", sa.Integer(), nullable=False),
        sa.Column("version_format", sa.Integer(), nullable=False),
        sa.Column("enregistre_le", sa.String(24), nullable=False),
        sa.Column("cle_reference", sa.String(32), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("chiffre", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("identite_id"),
        sa.UniqueConstraint("recu_id", name=op.f("uq_receptions_courriel_recu_id")),
        sa.CheckConstraint("version_format = 1", name=op.f("ck_receptions_courriel_courriel_version")),
        sa.CheckConstraint("taille_octets > 0 AND taille_octets <= 1048576",
                           name=op.f("ck_receptions_courriel_courriel_taille")),
        sa.CheckConstraint("length(nonce) = 12 AND length(chiffre) > 16 AND length(chiffre) <= 1064980",
                           name=op.f("ck_receptions_courriel_courriel_chiffre")),
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM receptions_courriel LIMIT 1")).first() is not None:
        raise RuntimeError("rétrogradation refusée : elle supprimerait les originaux courriel")
    op.drop_table("receptions_courriel")
