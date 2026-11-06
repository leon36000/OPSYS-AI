"""Conserve l'auteur des déclarations de matériaux d'appareil pour l'idempotence M6."""

import sqlalchemy as sa
from alembic import op

revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None

_TABLE = "mutations_appliquees"
_COLUMN = "personne_origine"


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend des mutations d'appareil non pris en charge")
    colonnes = {colonne["name"] for colonne in sa.inspect(cnx).get_columns(_TABLE)}
    if _COLUMN not in colonnes:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(64), nullable=True))


def downgrade():
    cnx = op.get_bind()
    colonnes = {colonne["name"] for colonne in sa.inspect(cnx).get_columns(_TABLE)}
    if _COLUMN not in colonnes:
        return
    if cnx.execute(sa.text(f"SELECT 1 FROM {_TABLE} WHERE {_COLUMN} IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("rétrogradation refusée : auteurs de déclarations M6 conservés")
    op.drop_column(_TABLE, _COLUMN)
