"""M8 : entrepôt analytique dérivé (M8.2) et pont BI en lecture seule (M8.14).

NUMÉROTATION : 0046 est le numéro réservé à M8 (vague 3). Sa `down_revision` est « 0044 » sur CETTE branche, parce que
la
0045 (M2) n'existe pas ici ; à l'intégration, l'architecte réaligne `down_revision` sur la tête réelle (0045 si M2 est
déjà
intégré). Ce choix garde la branche montable et testable seule.

Neuf tables additives : sept pour l'entrepôt (`m8_ent_*`, dérivées et reconstructibles, jamais une source de vérité)
et deux
pour le pont BI (`pont_bi_jetons`, métadonnées des jetons de lecture ; `pont_bi_acces`, journal d'accès APPEND-ONLY par
déclencheurs SQLite et PostgreSQL). La rétrogradation est refusée dès que le journal d'accès ou les jetons portent une
ligne
(un historique d'accès ne se supprime pas) ; les tables dérivées de l'entrepôt, elles, sont reconstructibles et se
détruisent sans perte de vérité.
"""

import sqlalchemy as sa
from alembic import op

from opsys.stockage.schema import M8_ENTREPOT_TABLES, PONT_BI_ACCES, PONT_BI_JETONS

revision = "0046"
down_revision = "0044"
branch_labels = None
depends_on = None

_JOURNAL = "pont_bi_acces"


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend de l'entrepôt M8 non pris en charge")
    for table in M8_ENTREPOT_TABLES:
        table.create(cnx)
    PONT_BI_JETONS.create(cnx)
    PONT_BI_ACCES.create(cnx)
    if cnx.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION pont_bi_acces_immuable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'journal d''acces du pont BI immuable' USING ERRCODE = '23514';
        END $$""")
        op.execute(
            "CREATE TRIGGER pont_bi_acces_immuable BEFORE UPDATE OR DELETE ON pont_bi_acces "
            "FOR EACH ROW EXECUTE FUNCTION pont_bi_acces_immuable()"
        )
        return
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER pont_bi_acces_no_{action.lower()} BEFORE {action} ON {_JOURNAL} "
            "BEGIN SELECT RAISE(ABORT,'journal d''acces du pont BI immuable'); END"
        )


def downgrade():
    cnx = op.get_bind()
    for nom in (_JOURNAL, "pont_bi_jetons"):
        if cnx.execute(sa.text(f"SELECT 1 FROM {nom} LIMIT 1")).first() is not None:
            raise RuntimeError(f"rétrogradation refusée : {nom} contient des données (aucune suppression)")
    if cnx.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS pont_bi_acces_immuable ON pont_bi_acces")
        op.execute("DROP FUNCTION IF EXISTS pont_bi_acces_immuable()")
    else:
        for action in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS pont_bi_acces_no_{action}")
    PONT_BI_ACCES.drop(cnx)
    PONT_BI_JETONS.drop(cnx)
    for table in reversed(M8_ENTREPOT_TABLES):
        table.drop(cnx)
