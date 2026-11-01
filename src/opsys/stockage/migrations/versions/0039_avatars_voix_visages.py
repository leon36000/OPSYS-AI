"""Registre des voix et visages des avatars, consentements, qualifications et canaux ; succède à 0038.

Additive : aucune table existante n'est touchée. Les consentements ne se modifient ni ne se suppriment (une seule
révocation, irréversible) ; les qualifications sont append-only (déclencheurs SQLite et PostgreSQL). La rétrogradation
est refusée dès qu'une ligne existe (elle détruirait des consentements ou la preuve d'une qualification exécutée :
suppression définitive = frontière humaine) ; sur des tables vides, elle retire proprement déclencheurs et tables.
"""

import sqlalchemy as sa
from alembic import op

from opsys.stockage.schema import (
    AVATARS_CANAUX,
    AVATARS_CONSENTEMENTS,
    AVATARS_ENTREES,
    AVATARS_QUALIFICATIONS,
)

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

_TABLES = (AVATARS_ENTREES, AVATARS_CONSENTEMENTS, AVATARS_QUALIFICATIONS, AVATARS_CANAUX)
# Colonnes d'un consentement qui ne changent jamais ; seules `revoque_*` passent de NULL à une valeur, une fois.
_FIGEES = ("consentement_id", "identifiant", "locuteur_ref", "portee", "forme", "document_ref", "document_sha256",
           "signe_le", "expire_le", "enregistre_le", "enregistre_par")


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend du registre des voix et visages non pris en charge")
    for table in _TABLES:
        table.create(cnx)
    if cnx.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION avatars_qualifications_immuable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'journal des qualifications d''avatars immuable' USING ERRCODE = '23514';
        END $$""")
        op.execute("CREATE TRIGGER avatars_qualifications_immuable BEFORE UPDATE OR DELETE ON avatars_qualifications "
                   "FOR EACH ROW EXECUTE FUNCTION avatars_qualifications_immuable()")
        comparaisons = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in _FIGEES)
        op.execute(f"""CREATE FUNCTION avatars_consentements_proteges() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'consentement d''avatar non supprimable' USING ERRCODE = '23514';
            END IF;
            IF OLD.revoque_le IS NOT NULL OR {comparaisons} THEN
                RAISE EXCEPTION 'consentement d''avatar immuable (seule la révocation, une fois, est permise)'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$""")
        op.execute("CREATE TRIGGER avatars_consentements_proteges BEFORE UPDATE OR DELETE ON avatars_consentements "
                   "FOR EACH ROW EXECUTE FUNCTION avatars_consentements_proteges()")
        return
    for action in ("UPDATE", "DELETE"):
        op.execute(f"CREATE TRIGGER avatars_qualifications_no_{action.lower()} BEFORE {action} ON "
                   "avatars_qualifications BEGIN SELECT RAISE(ABORT,'journal des qualifications d''avatars "
                   "immuable'); END")
    op.execute("CREATE TRIGGER avatars_consentements_no_delete BEFORE DELETE ON avatars_consentements "
               "BEGIN SELECT RAISE(ABORT,'consentement d''avatar non supprimable'); END")
    comparaisons = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in _FIGEES)
    op.execute("CREATE TRIGGER avatars_consentements_no_update BEFORE UPDATE ON avatars_consentements "
               f"WHEN OLD.revoque_le IS NOT NULL OR {comparaisons} "
               "BEGIN SELECT RAISE(ABORT,'consentement d''avatar immuable (seule la révocation, une fois, est "
               "permise)'); END")


def downgrade():
    cnx = op.get_bind()
    for table in _TABLES:
        if cnx.execute(sa.text(f"SELECT 1 FROM {table.name} LIMIT 1")).first() is not None:
            raise RuntimeError(f"rétrogradation refusée : {table.name} contient des données (aucune suppression)")
    if cnx.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS avatars_consentements_proteges ON avatars_consentements")
        op.execute("DROP FUNCTION IF EXISTS avatars_consentements_proteges()")
        op.execute("DROP TRIGGER IF EXISTS avatars_qualifications_immuable ON avatars_qualifications")
        op.execute("DROP FUNCTION IF EXISTS avatars_qualifications_immuable()")
    else:
        for nom in ("avatars_qualifications_no_update", "avatars_qualifications_no_delete",
                    "avatars_consentements_no_delete", "avatars_consentements_no_update"):
            op.execute(f"DROP TRIGGER IF EXISTS {nom}")
    for table in reversed(_TABLES):
        table.drop(cnx)
