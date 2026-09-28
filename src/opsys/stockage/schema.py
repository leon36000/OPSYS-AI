"""Tables de la base de l'instance (SQLAlchemy Core, portable SQLite et PostgreSQL).

Toute évolution passe par une migration Alembic (`migrations/versions/`), jamais par `create_all`.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, DateTime, Index, Integer, MetaData, String, Table, Text, func, text

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

# Plan de contrôle (ADR-0009) : approbations humaines, jetons consommés, artefacts tronqués,
# journal d'audit, mode effectif des départements. Vivait dans `~/.opsys/etat.db` (sqlite3 brut) ;
# migré ici (`opsys.etat.importer_etat_si_necessaire`) pour que la décision humaine et l'exécution
# de l'outil approuvé partagent une seule transaction avec le métier (`outils.executer_atomique`).
#
# Dates en texte ISO, pas en `DateTime` : elles repartent telles quelles vers les API JSON et les
# gabarits HTML de la console (`console/pages.py::_date`, qui attend une chaîne), et `usage_tokens.jour`
# sert de borne à des comparaisons `BETWEEN` textuelles (ISO trie comme le calendrier) ; un type
# `DateTime` renverrait des objets natifs côté Python et romprait ces deux usages sans rien gagner
# en portabilité, la colonne texte se comportant déjà à l'identique sur SQLite et PostgreSQL.

APPROBATIONS = Table(
    "approbations",
    META,
    Column("id", String(32), primary_key=True),
    Column("cree_le", Text, nullable=False),
    Column("departement", String(64), nullable=False),
    Column("outil", String(128), nullable=False),
    Column("arguments", Text, nullable=False),
    Column("motif_demande", Text, nullable=False, server_default=text("''")),
    Column("statut", String(16), nullable=False),
    Column("decide_par", Text),
    Column("decide_le", Text),
    Column("motif_decision", Text),
    Column("resultat", Text),
    CheckConstraint(
        "statut IN ('en_attente','en_cours','refusee','executee','echec')", name="statut_valide"
    ),
    Index("ix_approbations_statut", "statut", "cree_le"),
)

USAGE_TOKENS = Table(
    "usage_tokens",
    META,
    Column("jour", Text, primary_key=True),
    Column("departement", String(64), primary_key=True),
    Column("modele", String(128), primary_key=True),
    Column("appels", Integer, nullable=False, server_default=text("0")),
    Column("tokens_entree", Integer, nullable=False, server_default=text("0")),
    Column("tokens_sortie", Integer, nullable=False, server_default=text("0")),
    Column("tokens_cache_lus", Integer, nullable=False, server_default=text("0")),
)

ARTEFACTS = Table(
    "artefacts",
    META,
    Column("id", String(32), primary_key=True),
    Column("cree_le", Text, nullable=False),
    Column("source", String(128), nullable=False),
    Column("taille", Integer, nullable=False),
    Column("contenu", Text, nullable=False),
)

JOURNAL = Table(
    "journal",
    META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("quand", Text, nullable=False),
    Column("par", Text, nullable=False),
    Column("action", String(128), nullable=False),
    Column("cible", Text, nullable=False),
    Column("details", Text, nullable=False, server_default=text("'{}'")),
)

MODES_DEPARTEMENTS = Table(
    "modes_departements",
    META,
    Column("departement", String(64), primary_key=True),
    Column("mode", String(16), nullable=False),
    Column("modifie_par", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    CheckConstraint("mode IN ('ombre','supervise','autonome')", name="mode_valide"),
)
