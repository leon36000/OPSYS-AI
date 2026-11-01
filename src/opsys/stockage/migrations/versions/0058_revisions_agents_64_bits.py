"""Révisions de profil d'agent sur 64 bits (PostgreSQL) ; succède à 0057 (garde TRUNCATE PostgreSQL de la ligne architecte).

NUMÉROTATION : 0058 succède à 0057 (la ligne architecte a pris 0057 ; consigne du coordinateur).

PROBLÈME (défaut latent L6 du rapport de qualification PostgreSQL) : le code accepte une révision de profil d'agent
jusqu'à 2**53 - 1 (`agents_declencheurs`, `console.application`), mais les colonnes qui la portent étaient des
`INTEGER` : SQLite stocke des entiers sur 64 bits sans rien dire, PostgreSQL refuse tout ce qui dépasse
2 147 483 647 (« integer out of range »). Une révision acceptée par le code et refusée par la base est un échec en
cours d'écriture, jamais un refus typé.

CORRECTION : les cinq colonnes qui portent la révision d'un profil d'agent (`agents_configurables.revision`, sa copie
d'historique, et les trois colonnes `profile_revision` des intentions cron, des autorisations CFO et des tickets CFO)
passent à `BIGINT`. PostgreSQL SEULEMENT : SQLite est déjà sur 64 bits, la révision avance sans changer le schéma.

CE QUI N'EST PAS CHANGÉ, volontairement : `epoch`, `lease_epoch`, `native_expected_revision` et
`native_config_revision` des tables cron sont des COMPTEURS que le code borne lui-même à 2**31 - 1 (`_positif`,
`_revision_values` de `agents_cron_autorite`) : la colonne et la borne du code concordent déjà. Ce ne sont pas des
secondes depuis 1970 (aucun débordement en 2038).

La rétrogradation REFUSE de perdre des données : elle s'arrête si une révision dépasse 2 147 483 647.
"""

import sqlalchemy as sa
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None

_COLONNES = (
    ("agents_configurables", "revision"),
    ("agents_configurables_historique", "revision"),
    ("agents_declencheurs_intentions", "profile_revision"),
    ("agents_grants_cfo", "profile_revision"),
    ("agents_tickets_cfo", "profile_revision"),
)
_MAX_32_BITS = 2_147_483_647


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, colonne in _COLONNES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {colonne} TYPE BIGINT")


def downgrade():
    cnx = op.get_bind()
    if cnx.dialect.name != "postgresql":
        return
    for table, colonne in _COLONNES:
        if cnx.execute(sa.text(f"SELECT 1 FROM {table} WHERE {colonne} > :m LIMIT 1"), {"m": _MAX_32_BITS}).first():
            raise RuntimeError(
                f"rétrogradation refusée : {table}.{colonne} contient une valeur supérieure à {_MAX_32_BITS}")
    for table, colonne in reversed(_COLONNES):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {colonne} TYPE INTEGER")
