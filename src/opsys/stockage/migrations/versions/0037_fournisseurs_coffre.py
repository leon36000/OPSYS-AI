"""Registre de fournisseurs et coffre de secrets chiffré ; succède à 0036.

Le journal d'accès du coffre est append-only (déclencheurs SQLite et PostgreSQL). La rétrogradation est
refusée dès qu'une ligne existe : elle détruirait des secrets chiffrés ou des configurations (suppression
définitive = frontière humaine) ; sur des tables vides, elle supprime proprement déclencheurs et tables.
"""

import sqlalchemy as sa
from alembic import op

from opsys.stockage.schema import (
    COFFRE_ACCES,
    COFFRE_JETONS,
    COFFRE_SECRETS,
    COFFRE_VERSIONS,
    FOURNISSEURS_CONFIGURATIONS,
    FOURNISSEURS_PROFIL,
    FOURNISSEURS_SELECTIONS,
)

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

_TABLES = (FOURNISSEURS_PROFIL, FOURNISSEURS_CONFIGURATIONS, FOURNISSEURS_SELECTIONS,
           COFFRE_SECRETS, COFFRE_VERSIONS, COFFRE_JETONS, COFFRE_ACCES)


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend du coffre non pris en charge")
    for table in _TABLES:
        table.create(cnx)
    if cnx.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION coffre_acces_immuable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'journal du coffre immuable' USING ERRCODE = '23514';
        END $$""")
        op.execute("CREATE TRIGGER coffre_acces_immuable BEFORE UPDATE OR DELETE ON coffre_acces "
                   "FOR EACH ROW EXECUTE FUNCTION coffre_acces_immuable()")
        return
    for action in ("UPDATE", "DELETE"):
        op.execute(f"CREATE TRIGGER coffre_acces_no_{action.lower()} BEFORE {action} ON coffre_acces "
                   "BEGIN SELECT RAISE(ABORT,'journal du coffre immuable'); END")


def downgrade():
    cnx = op.get_bind()
    for table in _TABLES:
        if cnx.execute(sa.text(f"SELECT 1 FROM {table.name} LIMIT 1")).first() is not None:
            raise RuntimeError(f"rétrogradation refusée : {table.name} contient des données (aucune suppression)")
    if cnx.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS coffre_acces_immuable ON coffre_acces")
        op.execute("DROP FUNCTION IF EXISTS coffre_acces_immuable()")
    else:
        for action in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS coffre_acces_no_{action}")
    for table in reversed(_TABLES):
        table.drop(cnx)
