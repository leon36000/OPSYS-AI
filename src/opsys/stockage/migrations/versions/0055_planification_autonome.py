"""Planification autonome : approbations d'activation irréversible, échéances de rétention ; succède à 0052.

NUMÉROTATION : 0055 est le numéro réservé à la ligne planification-autonome (vague 5). Dans cette branche,
`down_revision` est « 0052 », la tête réelle de la ligne de base ; les numéros réservés 0053 et 0054 (autres branches de
la vague 5) n'y existent pas encore. L'architecte réaligne `down_revision` à l'intégration (une seule ligne).

Deux tables additives, aucune table existante touchée :
- `planificateur_approbations` : append-only (déclencheurs SQLite et PostgreSQL) ; la décision d'un admin humain
  d'activer
  un exécuteur dont l'effet est irréversible, avec l'empreinte de l'aperçu à blanc qu'il a vu ;
- `retention_echeances` : l'index (pseudonymes seulement) des clés de chiffrement à détruire à échéance.

La rétrogradation est refusée dès qu'une ligne existe (elle effacerait l'historique d'une décision humaine ou l'échéance
d'une donnée personnelle : suppression définitive = frontière humaine).
"""

import sqlalchemy as sa
from alembic import op

from opsys.stockage.schema import PLANIFICATEUR_APPROBATIONS, RETENTION_ECHEANCES

revision = "0055"
down_revision = "0052"
branch_labels = None
depends_on = None

_TABLES = (PLANIFICATEUR_APPROBATIONS, RETENTION_ECHEANCES)


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend de la planification autonome non pris en charge")
    for table in _TABLES:
        table.create(cnx)
    if cnx.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION planificateur_approbations_immuable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'approbations du planificateur immuables' USING ERRCODE = '23514';
        END $$""")
        op.execute("CREATE TRIGGER planificateur_approbations_immuable BEFORE UPDATE OR DELETE ON "
                   "planificateur_approbations FOR EACH ROW EXECUTE FUNCTION planificateur_approbations_immuable()")
        return
    for action in ("UPDATE", "DELETE"):
        op.execute(f"CREATE TRIGGER planificateur_approbations_no_{action.lower()} BEFORE {action} ON "
                   "planificateur_approbations "
                   "BEGIN SELECT RAISE(ABORT,'approbations du planificateur immuables'); END")


def downgrade():
    cnx = op.get_bind()
    for table in _TABLES:
        if cnx.execute(sa.text(f"SELECT 1 FROM {table.name} LIMIT 1")).first() is not None:
            raise RuntimeError(f"rétrogradation refusée : {table.name} contient des données (aucune suppression)")
    if cnx.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS planificateur_approbations_immuable ON planificateur_approbations")
        op.execute("DROP FUNCTION IF EXISTS planificateur_approbations_immuable()")
    else:
        for action in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS planificateur_approbations_no_{action}")
    for table in reversed(_TABLES):
        table.drop(cnx)
