"""Bases de connaissances par département : sources versionnées, fragments, index lexical, espaces vectoriels ;
succède à 0040.

NUMÉROTATION : 0041 succède à 0040 (connecteurs courriel) ; voir docs/architecture/CONNAISSANCES.md, « Migration ».

Additive : aucune table existante n'est touchée. Les versions, leurs états, leurs fragments, les espaces vectoriels, les
vecteurs et le journal d'indexation sont append-only (déclencheurs SQLite et PostgreSQL) : une version n'est jamais
réécrite, un état n'est jamais modifié, un retrait est un événement. Seule la ligne de `connaissances_bases` (espace
vectoriel actif) se met à jour. L'index lexical FTS5 est une table virtuelle propre à SQLite : sur PostgreSQL, l'index
BM25 (pg_textsearch) et la colonne pgvector sont un plan documenté, non exécuté.

La rétrogradation est refusée dès qu'une ligne existe (elle détruirait des sources, leur historique d'états ou leurs
vecteurs : suppression définitive = frontière humaine) ; sur des tables vides, elle retire proprement déclencheurs,
index et tables.
"""

import sqlalchemy as sa
from alembic import op

from opsys.stockage.schema import (
    CONNAISSANCES_BASES,
    CONNAISSANCES_ESPACES,
    CONNAISSANCES_ETATS,
    CONNAISSANCES_FRAGMENTS,
    CONNAISSANCES_INDEXATIONS,
    CONNAISSANCES_SOURCES,
    CONNAISSANCES_VECTEURS,
    CONNAISSANCES_VERSIONS,
)

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

# Ordre de création (les clés étrangères pointent vers les précédentes).
_TABLES = (
    CONNAISSANCES_ESPACES, CONNAISSANCES_BASES, CONNAISSANCES_SOURCES, CONNAISSANCES_VERSIONS, CONNAISSANCES_ETATS,
    CONNAISSANCES_FRAGMENTS, CONNAISSANCES_VECTEURS, CONNAISSANCES_INDEXATIONS,
)
_IMMUABLES = (
    "connaissances_espaces", "connaissances_sources", "connaissances_versions", "connaissances_etats",
    "connaissances_fragments", "connaissances_vecteurs", "connaissances_indexations",
)
_FTS = "connaissances_fts"


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend des bases de connaissances non pris en charge")
    for table in _TABLES:
        table.create(cnx)
    if cnx.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION connaissances_immuable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'table de connaissances immuable (append-only)' USING ERRCODE = '23514';
        END $$""")
        for nom in _IMMUABLES:
            op.execute(f"CREATE TRIGGER {nom}_immuable BEFORE UPDATE OR DELETE ON {nom} "
                       "FOR EACH ROW EXECUTE FUNCTION connaissances_immuable()")
        return
    for nom in _IMMUABLES:
        for action in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER {nom}_no_{action.lower()} BEFORE {action} ON {nom} "
                       "BEGIN SELECT RAISE(ABORT,'table de connaissances immuable (append-only)'); END")
    # Index lexical : termes déjà normalisés (accents repliés, radicaux) par `opsys.connaissances.normalisation`,
    # classés par bm25() ; `chunk_id` n'est pas indexé, il relie la ligne au fragment.
    op.execute(f"CREATE VIRTUAL TABLE {_FTS} USING fts5(terme, chunk_id UNINDEXED, tokenize='unicode61')")


def downgrade():
    cnx = op.get_bind()
    for table in _TABLES:
        if cnx.execute(sa.text(f"SELECT 1 FROM {table.name} LIMIT 1")).first() is not None:
            raise RuntimeError(f"rétrogradation refusée : {table.name} contient des données (aucune suppression)")
    if cnx.dialect.name == "postgresql":
        for nom in _IMMUABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {nom}_immuable ON {nom}")
        op.execute("DROP FUNCTION IF EXISTS connaissances_immuable()")
    else:
        op.execute(f"DROP TABLE IF EXISTS {_FTS}")
        for nom in _IMMUABLES:
            for action in ("update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS {nom}_no_{action}")
    for table in reversed(_TABLES):
        table.drop(cnx)
