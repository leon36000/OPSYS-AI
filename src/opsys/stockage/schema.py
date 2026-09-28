"""Tables de la base de l'instance (SQLAlchemy Core, portable SQLite et PostgreSQL).

Toute évolution passe par une migration Alembic (`migrations/versions/`), jamais par `create_all`.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, func

META = MetaData(naming_convention={
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
})

# Registres append-only des départements : un maillon par ligne, dans l'ordre de la chaîne.
# La clé (département, registre, rang) interdit deux maillons au même rang, même en écriture
# concurrente depuis deux processus.
REGISTRES = Table(
    "registres_maillons",
    META,
    Column("departement", String(64), primary_key=True),
    Column("registre", String(64), primary_key=True),
    Column("rang", Integer, primary_key=True),
    Column("maillon", Text, nullable=False),
    Column("cree_le", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
