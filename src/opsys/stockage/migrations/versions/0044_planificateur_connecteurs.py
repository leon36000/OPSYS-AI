"""Planificateur des connecteurs : exécuteurs durables, baux, journal ; genre de brouillon « courriel_contact ».

NUMÉROTATION : 0044 succède à 0041 (connaissances M10) ; 0042 et 0043 sont réservés mais non utilisés à ce jour.

Trois tables additives (`planificateur_executeurs`, `planificateur_baux`, `planificateur_journal`) ; le journal est
append-only (déclencheurs SQLite et PostgreSQL). La contrainte CHECK `ingestion_brouillons.genre` s'élargit à
« courriel_contact » (remplacée en place sur SQLite, sans reconstruire la table : même technique que la 0040). La
rétrogradation est refusée dès qu'une ligne existe dans une table du chantier ou qu'un brouillon «
courriel_contact » est
présent : elle détruirait un historique d'activation, de bail ou des candidats du CRM (suppression définitive =
frontière humaine).
"""

import re

import sqlalchemy as sa
from alembic import op

from opsys.stockage.schema import PLANIFICATEUR_BAUX, PLANIFICATEUR_EXECUTEURS, PLANIFICATEUR_JOURNAL

revision = "0044"
down_revision = "0041"
branch_labels = None
depends_on = None

_TABLES = (PLANIFICATEUR_EXECUTEURS, PLANIFICATEUR_BAUX, PLANIFICATEUR_JOURNAL)
_BROUILLONS = "ingestion_brouillons"
_CHECK = "ck_ingestion_brouillons_genre_valide"
_ANCIENS = "'ap_facture_fournisseur','crm_client'"
_NOUVEAUX = _ANCIENS + ",'courriel_contact'"
_NAMING = {"ck": "%(constraint_name)s"}
_MOTIF_GENRE = re.compile(r"genre IN \([^)]*\)")


def _remplacer_genres_sqlite(liste: str) -> None:
    """Remplace la CHECK de genre en place (modification directe du schéma documentée par SQLite) : la reconstruction
    de table échouerait dès que des lignes enfants existent."""
    cnx = op.get_bind()
    ddl = cnx.execute(sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"),
                      {"n": _BROUILLONS}).scalar_one()
    neuf, nombre = _MOTIF_GENRE.subn(f"genre IN ({liste})", ddl)
    if nombre != 1:
        raise RuntimeError("la contrainte de genre attendue est introuvable dans ingestion_brouillons")
    version = cnx.execute(sa.text("PRAGMA schema_version")).scalar_one()
    op.execute("PRAGMA writable_schema = ON")
    try:
        cnx.execute(sa.text("UPDATE sqlite_master SET sql = :sql WHERE type='table' AND name = :n"),
                    {"sql": neuf, "n": _BROUILLONS})
        op.execute(f"PRAGMA schema_version = {int(version) + 1}")
    finally:
        op.execute("PRAGMA writable_schema = OFF")
    if cnx.execute(sa.text("PRAGMA integrity_check")).scalar_one() != "ok":
        raise RuntimeError("le schéma modifié ne passe pas integrity_check")


def _remplacer_genres(liste: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        _remplacer_genres_sqlite(liste)
        return
    with op.batch_alter_table(_BROUILLONS, recreate="auto", naming_convention=_NAMING) as batch:
        batch.drop_constraint(op.f(_CHECK), type_="check")
        batch.create_check_constraint(op.f(_CHECK), f"genre IN ({liste})")


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend du planificateur de connecteurs non pris en charge")
    for table in _TABLES:
        table.create(cnx)
    _remplacer_genres(_NOUVEAUX)
    if cnx.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION planificateur_journal_immuable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'journal du planificateur immuable' USING ERRCODE = '23514';
        END $$""")
        op.execute("CREATE TRIGGER planificateur_journal_immuable BEFORE UPDATE OR DELETE ON planificateur_journal "
                   "FOR EACH ROW EXECUTE FUNCTION planificateur_journal_immuable()")
        return
    for action in ("UPDATE", "DELETE"):
        op.execute(f"CREATE TRIGGER planificateur_journal_no_{action.lower()} BEFORE {action} ON planificateur_journal "
                   "BEGIN SELECT RAISE(ABORT,'journal du planificateur immuable'); END")


def downgrade():
    cnx = op.get_bind()
    for table in _TABLES:
        if cnx.execute(sa.text(f"SELECT 1 FROM {table.name} LIMIT 1")).first() is not None:
            raise RuntimeError(f"rétrogradation refusée : {table.name} contient des données (aucune suppression)")
    if cnx.execute(sa.text(f"SELECT 1 FROM {_BROUILLONS} WHERE genre = 'courriel_contact' LIMIT 1")).first() \
            is not None:
        raise RuntimeError("rétrogradation refusée : des brouillons « courriel_contact » existent (aucune suppression)")
    if cnx.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS planificateur_journal_immuable ON planificateur_journal")
        op.execute("DROP FUNCTION IF EXISTS planificateur_journal_immuable()")
    else:
        for action in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS planificateur_journal_no_{action}")
    _remplacer_genres(_ANCIENS)
    for table in reversed(_TABLES):
        table.drop(cnx)
