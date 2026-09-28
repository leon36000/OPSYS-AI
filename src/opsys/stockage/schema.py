"""Tables de la base de l'instance (SQLAlchemy Core, portable SQLite et PostgreSQL).

Toute évolution passe par une migration Alembic (`migrations/versions/`), jamais par `create_all`.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    text,
)

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

# Bus d'événements (ADR-0009 §3) : outbox durcie. `publier()` insère dans EVENEMENTS_SORTANTS dans
# la transaction métier courante (même point de sauvegarde que l'écriture qui le déclenche) ; le
# répartiteur (`opsys.evenements.repartir`) livre chaque événement à chacun de ses consommateurs
# abonnés et trace le résultat dans EVENEMENTS_RECUS. `evenement_id` est fourni (idempotence du
# producteur) ou un uuid4 hex généré par défaut ; sa clé primaire porte l'unicité exigée par
# l'ADR. `charge` est le JSON typé du codec (`stockage.codec`), comme les maillons de registre.
EVENEMENTS_SORTANTS = Table(
    "evenements_sortants",
    META,
    Column("evenement_id", String(128), primary_key=True),
    Column("type_evenement", String(128), nullable=False),
    Column("producteur", String(64), nullable=False),
    Column("charge", Text, nullable=False),
    Column("cree_le", Text, nullable=False),
    Index("ix_evenements_sortants_type", "type_evenement", "cree_le"),
)

# Un reçu par (événement, consommateur) : UNIQUE(evenement_id, consommateur) est la clé primaire
# elle-même, donc une relivraison ne peut jamais créer un second reçu « traité » pour la même paire
# (idempotence effective). `statut` : 'echec' (réessai plus tard selon `prochaine_tentative`,
# backoff exponentiel), 'traite' (résumé du consommateur dans `resultat`, jamais rejoué), ou
# 'quarantaine' (5 échecs : plus aucune relivraison automatique, visible dans `opsys evenements etat`).
EVENEMENTS_RECUS = Table(
    "evenements_recus",
    META,
    Column("evenement_id", String(128), ForeignKey("evenements_sortants.evenement_id"), primary_key=True),
    Column("consommateur", String(64), primary_key=True),
    Column("statut", String(16), nullable=False),
    Column("tentatives", Integer, nullable=False, server_default=text("0")),
    Column("prochaine_tentative", Text),
    Column("resultat", Text),
    Column("derniere_erreur", Text),
    CheckConstraint("statut IN ('echec','traite','quarantaine')", name="statut_valide"),
    Index("ix_evenements_recus_statut", "statut", "prochaine_tentative"),
)

# Idempotence des mutations d'appareil (T1.4-b ; contrat R12 §4, `docs/architecture/IDEMPOTENCE.md`).
# `(appareil, cle_idempotence)` est la clé posée par `opsys.idempotence.reclamer`, dans la MÊME
# transaction que l'exécution de l'outil (`opsys.capacites.Capacites._appeler_idempotent`) : un
# renvoi de la même clé, du même outil et des mêmes arguments (`empreinte_arguments`) rejoue
# `reponse` (encodée par `stockage.codec`, comme les maillons de registre) sans ré-exécuter.
# `statut='en_cours'` n'est jamais visible hors de sa transaction : `finaliser` l'écrase avant le
# commit, ou la transaction entière (réclamation comprise) s'annule avec une panne interne — jamais
# enregistrée, pour qu'un renvoi réel réessaie. `horodatage_appareil` (heure de l'appareil, affichage
# seulement) et `recu_le` (heure du serveur, fait foi — ex. la paie, M4/T1.4-d) sont du texte ISO,
# comme les autres dates du plan de contrôle (voir la note sur APPROBATIONS ci-dessus).
MUTATIONS_APPLIQUEES = Table(
    "mutations_appliquees",
    META,
    Column("appareil", String(128), primary_key=True),
    Column("cle_idempotence", String(128), primary_key=True),
    Column("outil", String(128), nullable=False),
    Column("empreinte_arguments", String(64), nullable=False),
    Column("reponse", Text, nullable=False),
    Column("horodatage_appareil", Text, nullable=False),
    Column("recu_le", Text, nullable=False),
    Column("statut", String(24), nullable=False),
    CheckConstraint(
        "statut IN ('en_cours','ok','refus_metier','en_attente_approbation')", name="statut_valide"
    ),
)
