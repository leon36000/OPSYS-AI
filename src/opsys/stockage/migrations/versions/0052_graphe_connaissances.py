"""Graphe de connaissances d'entités de M10 (nœuds, arêtes, états d'arêtes) ; succède à 0049.

NUMÉROTATION : 0052 est le numéro réservé à la ligne m10-self-graphe (vague 4). Dans cette branche, `down_revision` est
« 0049 », la tête réelle de la ligne de base ; les numéros réservés 0050 et 0051 (autres branches de la vague 4)
n'y existent pas encore. L'architecte réaligne `down_revision` sur « 0051 » à l'intégration (une seule ligne à changer,
aucune autre dépendance).

Additive : aucune table existante n'est touchée. Les trois tables sont append-only (déclencheurs SQLite et PostgreSQL) :
un nœud ou une arête n'est jamais réécrit, l'état d'une arête est son dernier événement, une fermeture est un événement
qui pose `valide_a`. Le modèle de soi et les leçons de M10 n'ont pas de table : ils vivent dans des registres
append-only chaînés (`stockage.maillons`), comme les faits analytiques.

La rétrogradation est refusée dès qu'une ligne existe (elle détruirait des relations sourcées et leur historique :
suppression définitive = frontière humaine) ; sur des tables vides, elle retire proprement déclencheurs et tables.
"""

import sqlalchemy as sa
from alembic import op

from opsys.stockage.schema import GRAPHE_ARETES, GRAPHE_ARETES_ETATS, GRAPHE_NOEUDS

revision = "0052"
down_revision = "0049"
branch_labels = None
depends_on = None

_TABLES = (GRAPHE_NOEUDS, GRAPHE_ARETES, GRAPHE_ARETES_ETATS)
_IMMUABLES = ("graphe_noeuds", "graphe_aretes", "graphe_aretes_etats")


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend du graphe de connaissances non pris en charge")
    for table in _TABLES:
        table.create(cnx)
    if cnx.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION graphe_immuable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'table du graphe immuable (append-only)' USING ERRCODE = '23514';
        END $$""")
        for nom in _IMMUABLES:
            op.execute(
                f"CREATE TRIGGER {nom}_immuable BEFORE UPDATE OR DELETE ON {nom} "
                "FOR EACH ROW EXECUTE FUNCTION graphe_immuable()"
            )
        return
    for nom in _IMMUABLES:
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {nom}_no_{action.lower()} BEFORE {action} ON {nom} "
                "BEGIN SELECT RAISE(ABORT,'table du graphe immuable (append-only)'); END"
            )


def downgrade():
    cnx = op.get_bind()
    for table in _TABLES:
        if cnx.execute(sa.text(f"SELECT 1 FROM {table.name} LIMIT 1")).first() is not None:
            raise RuntimeError(f"rétrogradation refusée : {table.name} contient des données (aucune suppression)")
    if cnx.dialect.name == "postgresql":
        for nom in _IMMUABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {nom}_immuable ON {nom}")
        op.execute("DROP FUNCTION IF EXISTS graphe_immuable()")
    else:
        for nom in _IMMUABLES:
            for action in ("update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS {nom}_no_{action}")
    for table in reversed(_TABLES):
        table.drop(cnx)
