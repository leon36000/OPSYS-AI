"""Ingestion d'onboarding : lots, documents, tâches durables, journal et brouillons ; succède à 0037.

Additive : aucune table existante n'est touchée. Le journal est append-only (déclencheurs SQLite et PostgreSQL). La
rétrogradation est refusée dès qu'une ligne existe (elle détruirait des originaux chiffrés, des brouillons ou leur
historique : suppression définitive = frontière humaine) ; sur des tables vides, elle retire proprement déclencheurs et
tables.
"""

import sqlalchemy as sa
from alembic import op

from opsys.stockage.schema import (
    INGESTION_BROUILLONS,
    INGESTION_DOCUMENTS,
    INGESTION_JOURNAL,
    INGESTION_LOTS,
    INGESTION_TACHES,
)

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

_TABLES = (INGESTION_LOTS, INGESTION_DOCUMENTS, INGESTION_TACHES, INGESTION_JOURNAL, INGESTION_BROUILLONS)


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend de l'ingestion d'onboarding non pris en charge")
    for table in _TABLES:
        table.create(cnx)
    if cnx.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION ingestion_journal_immuable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'journal d''ingestion immuable' USING ERRCODE = '23514';
        END $$""")
        op.execute("CREATE TRIGGER ingestion_journal_immuable BEFORE UPDATE OR DELETE ON ingestion_journal "
                   "FOR EACH ROW EXECUTE FUNCTION ingestion_journal_immuable()")
        return
    for action in ("UPDATE", "DELETE"):
        op.execute(f"CREATE TRIGGER ingestion_journal_no_{action.lower()} BEFORE {action} ON ingestion_journal "
                   "BEGIN SELECT RAISE(ABORT,'journal d''ingestion immuable'); END")


def downgrade():
    cnx = op.get_bind()
    for table in _TABLES:
        if cnx.execute(sa.text(f"SELECT 1 FROM {table.name} LIMIT 1")).first() is not None:
            raise RuntimeError(f"rétrogradation refusée : {table.name} contient des données (aucune suppression)")
    if cnx.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS ingestion_journal_immuable ON ingestion_journal")
        op.execute("DROP FUNCTION IF EXISTS ingestion_journal_immuable()")
    else:
        for action in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS ingestion_journal_no_{action}")
    for table in reversed(_TABLES):
        table.drop(cnx)
