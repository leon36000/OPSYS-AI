"""Rôles de modèles et passerelle LiteLLM ; succède à 0058.

NUMÉROTATION : 0086 est le numéro réservé au chantier « modèles/passerelle » (vague 11) ; `down_revision` = « 0058 », la
tête réelle de la ligne de base. L'architecte réaligne `down_revision` à l'intégration (une seule ligne).

Quatre tables : `modeles_roles` (affectation d'un rôle à un fournisseur du registre), `modeles_reglages` (passerelle,
escalade vers le raisonnement), `modeles_historique` (append-only : retour arrière et audit) et `modeles_usage`
(compteurs par rôle et par jour). Portable SQLite et PostgreSQL ; aucune garde « SQLite seulement ». La rétrogradation
est refusée dès qu'une ligne existe (suppression définitive = frontière humaine).
"""

import sqlalchemy as sa
from alembic import op

from opsys.stockage.schema import MODELES_HISTORIQUE, MODELES_REGLAGES, MODELES_ROLES, MODELES_USAGE

revision = "0086"
down_revision = "0058"
branch_labels = None
depends_on = None

_TABLES = (MODELES_ROLES, MODELES_REGLAGES, MODELES_HISTORIQUE, MODELES_USAGE)


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend des rôles de modèles non pris en charge")
    for table in _TABLES:
        table.create(cnx)
    if cnx.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION modeles_historique_immuable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'historique des modèles immuable' USING ERRCODE = '23514';
        END $$""")
        op.execute("CREATE TRIGGER modeles_historique_immuable BEFORE UPDATE OR DELETE ON modeles_historique "
                   "FOR EACH ROW EXECUTE FUNCTION modeles_historique_immuable()")
        # `TRUNCATE` ne réveille jamais un déclencheur de ligne : même garde d'instruction que 0057, qui pose la
        # fonction.
        op.execute("CREATE TRIGGER modeles_historique_sans_truncate BEFORE TRUNCATE ON modeles_historique "
                   "FOR EACH STATEMENT EXECUTE FUNCTION opsys_truncate_interdit()")
        return
    for action in ("UPDATE", "DELETE"):
        op.execute(f"CREATE TRIGGER modeles_historique_no_{action.lower()} BEFORE {action} ON modeles_historique "
                   "BEGIN SELECT RAISE(ABORT,'historique des modèles immuable'); END")


def downgrade():
    cnx = op.get_bind()
    for table in _TABLES:
        if cnx.execute(sa.text(f"SELECT 1 FROM {table.name} LIMIT 1")).first() is not None:
            raise RuntimeError(f"rétrogradation refusée : {table.name} contient des données (aucune suppression)")
    if cnx.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS modeles_historique_sans_truncate ON modeles_historique")
        op.execute("DROP TRIGGER IF EXISTS modeles_historique_immuable ON modeles_historique")
        op.execute("DROP FUNCTION IF EXISTS modeles_historique_immuable()")
    else:
        for action in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS modeles_historique_no_{action}")
    for table in reversed(_TABLES):
        table.drop(cnx)
