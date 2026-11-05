"""Conserve la couverture structurée des mesures M8, sans inférer les historiques anciens."""

import sqlalchemy as sa
from alembic import op

revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None

_TABLES = ("m8_ent_mesures_courantes", "m8_ent_mesures_hist")


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend de l'entrepôt M8 non pris en charge")
    for table in _TABLES:
        colonnes = {colonne["name"] for colonne in sa.inspect(cnx).get_columns(table)}
        if "couverture" not in colonnes:
            op.add_column(table, sa.Column("couverture", sa.JSON(none_as_null=True), nullable=True))


def downgrade():
    cnx = op.get_bind()
    for table in _TABLES:
        if (
            "couverture" in {colonne["name"] for colonne in sa.inspect(cnx).get_columns(table)}
            and cnx.execute(sa.text(f"SELECT 1 FROM {table} WHERE couverture IS NOT NULL LIMIT 1")).first()
        ):
            raise RuntimeError("rétrogradation refusée : couvertures M8 présentes")
    for table in _TABLES:
        if "couverture" in {colonne["name"] for colonne in sa.inspect(cnx).get_columns(table)}:
            op.drop_column(table, "couverture")
