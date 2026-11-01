"""Connecteurs courriel : comptes, états OAuth, idempotence, brouillons sortants, journal ; capacité « courriel ».

NUMÉROTATION : 0040 succède à 0039 (voix et visages des avatars) ; la tête alembic est « 0040 ».
Voir docs/architecture/CONNECTEURS-COURRIEL.md, « Migration ».

Additive pour les tables. Le journal est append-only (déclencheurs SQLite et PostgreSQL). La contrainte CHECK
`fournisseurs_configurations.capacite` s'élargit à « courriel » (reconstruction de table sur SQLite). La
rétrogradation est refusée dès qu'une ligne existe dans une table du chantier ou qu'un fournisseur « courriel » est
configuré : elle détruirait des comptes, des brouillons scellés ou leur historique (suppression définitive = frontière
humaine). """

import sqlalchemy as sa
from alembic import op

from opsys.stockage.schema import (
    COURRIEL_BROUILLONS,
    COURRIEL_COMPTES,
    COURRIEL_ETATS_OAUTH,
    COURRIEL_JOURNAL,
    COURRIEL_MESSAGES,
    COURRIEL_REFS,
)

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

_TABLES = (COURRIEL_COMPTES, COURRIEL_ETATS_OAUTH, COURRIEL_MESSAGES, COURRIEL_REFS, COURRIEL_BROUILLONS,
           COURRIEL_JOURNAL)
_CONFIG = "fournisseurs_configurations"
_CHECK = "ck_fournisseurs_configurations_capacite_valide"
_ANCIENNES = "'llm','embeddings','reranker','ocr','stt','tts','avatar','image','video','recherche_web'"
_NAMING = {"ck": "%(constraint_name)s"}


def _remplacer_capacites_sqlite(liste: str) -> None:
    """Remplace la CHECK de capacité en place, sans reconstruire la table.

    La reconstruction habituelle (copie, suppression de l'ancienne, renommage) échoue sur SQLite quand des tables
    enfants (avatars 0039, ingestion) contiennent des lignes : on ne peut pas y désactiver les clés étrangères dans une
    transaction, et le renommage réécrit leurs références. Changer le texte d'une CHECK ne modifie aucune donnée sur
    disque : c'est le cas que la documentation de SQLite réserve à la modification directe du schéma
    (`writable_schema`, puis incrément de `schema_version`)."""
    import re

    cnx = op.get_bind()
    ddl = cnx.execute(sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"),
                      {"n": _CONFIG}).scalar_one()
    neuf, nombre = re.subn(r"capacite IN \([^)]*\)", f"capacite IN ({liste})", ddl)
    if nombre != 1:
        raise RuntimeError("la contrainte de capacité attendue est introuvable dans fournisseurs_configurations")
    version = cnx.execute(sa.text("PRAGMA schema_version")).scalar_one()
    op.execute("PRAGMA writable_schema = ON")
    try:
        cnx.execute(sa.text("UPDATE sqlite_master SET sql = :sql WHERE type='table' AND name = :n"),
                    {"sql": neuf, "n": _CONFIG})
        op.execute(f"PRAGMA schema_version = {int(version) + 1}")
    finally:
        op.execute("PRAGMA writable_schema = OFF")
    if cnx.execute(sa.text("PRAGMA integrity_check")).scalar_one() != "ok":
        raise RuntimeError("le schéma modifié ne passe pas integrity_check")


def _remplacer_capacites(liste: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        _remplacer_capacites_sqlite(liste)
        return
    with op.batch_alter_table(_CONFIG, recreate="auto", naming_convention=_NAMING) as batch:
        batch.drop_constraint(op.f(_CHECK), type_="check")
        batch.create_check_constraint(op.f(_CHECK), f"capacite IN ({liste})")


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend des connecteurs courriel non pris en charge")
    for table in _TABLES:
        table.create(cnx)
    _remplacer_capacites(_ANCIENNES + ",'courriel'")
    if cnx.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION courriel_journal_immuable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'journal courriel immuable' USING ERRCODE = '23514';
        END $$""")
        op.execute("CREATE TRIGGER courriel_journal_immuable BEFORE UPDATE OR DELETE ON courriel_journal "
                   "FOR EACH ROW EXECUTE FUNCTION courriel_journal_immuable()")
        return
    for action in ("UPDATE", "DELETE"):
        op.execute(f"CREATE TRIGGER courriel_journal_no_{action.lower()} BEFORE {action} ON courriel_journal "
                   "BEGIN SELECT RAISE(ABORT,'journal courriel immuable'); END")


def downgrade():
    cnx = op.get_bind()
    for table in _TABLES:
        if cnx.execute(sa.text(f"SELECT 1 FROM {table.name} LIMIT 1")).first() is not None:
            raise RuntimeError(f"rétrogradation refusée : {table.name} contient des données (aucune suppression)")
    if cnx.execute(sa.text(f"SELECT 1 FROM {_CONFIG} WHERE capacite = 'courriel' LIMIT 1")).first() is not None:
        raise RuntimeError("rétrogradation refusée : un fournisseur « courriel » est configuré (aucune suppression)")
    if cnx.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS courriel_journal_immuable ON courriel_journal")
        op.execute("DROP FUNCTION IF EXISTS courriel_journal_immuable()")
    else:
        for action in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS courriel_journal_no_{action}")
    _remplacer_capacites(_ANCIENNES)
    for table in reversed(_TABLES):
        table.drop(cnx)
