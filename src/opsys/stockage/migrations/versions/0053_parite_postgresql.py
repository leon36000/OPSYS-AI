"""Parité PostgreSQL : index lexical des connaissances (tsvector + GIN) et immuabilité de deux tables ; succède à 0052.

NUMÉROTATION : 0053 est le numéro réservé à la qualification PostgreSQL (vague 5). `down_revision` est « 0052 », la tête
réelle de la ligne de base ; l'architecte réaligne au besoin (une seule ligne).

PostgreSQL SEULEMENT (SQLite : aucune opération ; la révision avance sans changer le schéma) :

1. **Index lexical des connaissances.** La migration 0041 crée l'index lexical comme table virtuelle FTS5, propre à
SQLite ; sur PostgreSQL la recherche lexicale n'était pas portée. Table `connaissances_lexique` : `chunk_id` (clé
étrangère vers le fragment), `terme` (les termes déjà normalisés en Python, comme dans FTS5) et `tsv`, une colonne
GÉNÉRÉE `to_tsvector('simple', terme)` indexée en GIN. Configuration `simple` : voir `opsys.connaissances.lexical`.
Append-only comme les autres tables de connaissances (déclencheur de la fonction `connaissances_immuable()` de 0041).
2. **Immuabilité de `fusion_ap_ocr_sources` (0026) et de `service_attestations_m4` (0033).** Ces deux migrations ne
posaient leurs déclencheurs d'immuabilité que sur SQLite (`if dialect == "sqlite"`) : sur PostgreSQL les deux tables,
déclarées append-only, acceptaient `UPDATE` et `DELETE`. Trouvé en comparant les déclencheurs d'une base migrée sous
SQLite et sous PostgreSQL. Même message d'erreur qu'en SQLite, même classe d'erreur (SQLSTATE 23514, `IntegrityError`
côté SQLAlchemy).

3. **Identifiants d'événements plus longs que 128 caractères.** `evenement_id` est `VARCHAR(128)` dans six tables ;
SQLite ne fait pas respecter la longueur, PostgreSQL oui. L'identifiant que M2 construit pour une opportunité répétée
(`m2-lead-assigne-<lead>~opp~<wct>`, ~156 caractères avec des identifiants de 64) ne pouvait donc jamais être publié
sur PostgreSQL : le consommateur partait en quarantaine après cinq essais (`StringDataRightTruncation`). Les six
colonnes passent à `VARCHAR(512)`, de sorte que PostgreSQL accepte ce que SQLite accepte déjà. (Certains lecteurs en
aval — la provenance M5 de M8, l'inventaire de calibration — bornent encore l'identifiant à 128 : ils le traitent déjà
ainsi sous SQLite, ce n'est pas nouveau.)

SCHÉMA : toutes les tables et fonctions vivent dans le schéma COURANT (`search_path`) et rien n'est qualifié : la
chaîne de migrations s'installe dans n'importe quel schéma (c'est ce que prouve
`test_pg_recalcul_wct_migration_qa.py`), ce qu'un schéma dédié et fixe aurait cassé (le second schéma d'installation y
trouverait la table du premier).

La rétrogradation est refusée dès que `connaissances_lexique` contient une ligne (elle détruirait l'index d'une base
publiée : il faudrait la réindexer) ; sinon elle retire les déclencheurs, l'index, la table et la fonction.
"""

import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

_TABLE = "connaissances_lexique"
_FONCTION = "opsys_immuable_message"
_ID_EVENEMENT = (
    ("evenements_sortants", "evenement_id"), ("evenements_recus", "evenement_id"), ("wct_attentes", "evenement_id"),
    ("wct_attentes_audit", "evenement_id"), ("service_audit", "evenement_id"),
    ("service_attestations_m4", "evenement_id"),
)
_LONGUEUR_ID_EVENEMENT = 512
_IMMUABLES = (
    ("fusion_ap_ocr_sources", "source OCR AP immuable"),
    ("service_attestations_m4", "attestation immutable"),
)


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name != "postgresql":
        return
    op.execute(f"""CREATE TABLE {_TABLE} (
        chunk_id TEXT NOT NULL PRIMARY KEY REFERENCES connaissances_fragments (chunk_id),
        terme TEXT NOT NULL,
        tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', terme)) STORED
    )""")
    op.execute(f"CREATE INDEX ix_{_TABLE}_tsv ON {_TABLE} USING GIN (tsv)")
    op.execute(f"CREATE TRIGGER {_TABLE}_immuable BEFORE UPDATE OR DELETE ON {_TABLE} "
               "FOR EACH ROW EXECUTE FUNCTION connaissances_immuable()")
    # Une fonction générique : le message est l'argument du déclencheur (celui que SQLite affiche déjà).
    op.execute(f"""CREATE FUNCTION {_FONCTION}() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION '%', TG_ARGV[0] USING ERRCODE = '23514';
    END $$""")
    for table, message in _IMMUABLES:
        op.execute(f"CREATE TRIGGER {table}_immuable BEFORE UPDATE OR DELETE ON {table} "
                   f"FOR EACH ROW EXECUTE FUNCTION {_FONCTION}('{message}')")
    # La table parente d'abord : PostgreSQL reconstruit lui-même les clés étrangères qui en dépendent.
    for table, colonne in _ID_EVENEMENT:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {colonne} TYPE VARCHAR({_LONGUEUR_ID_EVENEMENT})")


def downgrade():
    cnx = op.get_bind()
    if cnx.dialect.name != "postgresql":
        return
    if cnx.execute(sa.text(f"SELECT 1 FROM {_TABLE} LIMIT 1")).first() is not None:
        raise RuntimeError(f"rétrogradation refusée : {_TABLE} contient des données (aucune suppression)")
    for table, colonne in _ID_EVENEMENT:
        if cnx.execute(sa.text(f"SELECT 1 FROM {table} WHERE length({colonne}) > 128 LIMIT 1")).first() is not None:
            raise RuntimeError(
                f"rétrogradation refusée : {table}.{colonne} contient un identifiant de plus de 128 caractères")
    for table, colonne in reversed(_ID_EVENEMENT):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {colonne} TYPE VARCHAR(128)")
    for table, _ in _IMMUABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immuable ON {table}")
    op.execute(f"DROP FUNCTION IF EXISTS {_FONCTION}()")
    op.execute(f"DROP TRIGGER IF EXISTS {_TABLE}_immuable ON {_TABLE}")
    op.execute(f"DROP INDEX IF EXISTS ix_{_TABLE}_tsv")
    op.execute(f"DROP TABLE {_TABLE}")
