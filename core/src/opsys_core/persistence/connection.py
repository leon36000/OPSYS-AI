"""Connexion PostgreSQL autoritative (C05-001).

`open_database(config, *, provider)` — `provider` est keyword-only et
OBLIGATOIRE (aucun `EnvSecretProvider()` implicite construit en
silence) : même discipline d'injection explicite que
`opsys_core.composition.build_core` (C04-004, « aucun état au niveau
module … l'appelant fournit tout »).

Deux surfaces distinctes, jamais confondues :
  - `Database` (Protocol minimal, `fermer()` uniquement — même
    discipline anti-sur-spécification que `ports/contracts.py`,
    C04-001 : aucune méthode métier sans besoin sourcé) implémentée par
    `ConnexionPostgreSql`, la SEULE valeur qu'`open_database` peut
    retourner en cas de succès.
  - `FakeDatabase` : fake explicite pour tests UNIQUEMENT (spec :
    « proposer un fake explicite uniquement pour tests »). JAMAIS
    atteignable via `open_database`, qui refuse INCONDITIONNELLEMENT
    toute cible résolue non-PostgreSQL AVANT toute construction —
    propriété structurelle, pas une convention (cas RED « refuser
    SQLite/in-memory comme profil production »).

Dépendance PyPI RÉELLE ajoutée par cette tâche (psycopg + psycopg-
binary, core/requirements.lock, hash sha256 réels) — première du Core
hors PyYAML. Écart à la discipline « stdlib d'abord » documenté ici
comme les précédents (core/quality-gates.toml, core/dependency-
rules.toml) : aucun driver PostgreSQL n'existe en stdlib Python,
réimplémenter le protocole de connexion (+ SCRAM-SHA-256) serait une
surface de faille en soi. `psycopg-binary` choisi (plutôt que `psycopg`
nu + `libpq` système) : mesuré sur cette machine, `libpq` n'est PAS
installée comme bibliothèque système (`ldconfig -p` vide) et son
installation système est explicitement interdite par le spec de cette
tâche (« aucune installation système persistante par apt/dnf/… »).
`psycopg-binary` embarque son propre `libpq` statiquement lié — vérifié
par exécution réelle avant ce commit (import réussi + connexion réelle
à un conteneur PostgreSQL éphémère + `SELECT version()` réel).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import psycopg

from config.vault import SecretProvider

from .config import DatabaseConfig

# Nom d'application PostgreSQL : liste blanche stricte (protection
# contre l'injection dans la chaîne de connexion — revue d'architecture
# AVANT code : `application_name`/`options` ne doivent JAMAIS être
# concaténés dans un DSN texte, seulement passés en paramètres SÉPARÉS
# à psycopg.connect(), qui gère l'échappement correctement).
_APPLICATION_NAME = "opsys-core"

_CIBLES_NON_POSTGRESQL = ("sqlite:", "sqlite3:")
_MARQUEURS_MEMOIRE = (":memory:", "file::memory:")
_MOTS_CLES_POSTGRESQL = ("postgresql://", "postgres://", "host=", "dbname=")


class CibleNonPostgreSqlRefusee(ValueError):
    """Levée par `open_database` quand le DSN RÉSOLU (après passage par
    le `SecretProvider`) ne désigne pas une cible PostgreSQL — jamais
    levée à la construction de `DatabaseConfig` (qui ne connaît que le
    NOM du secret, pas sa valeur résolue)."""

    def __init__(self, motif: str) -> None:
        super().__init__(
            f"cible non-PostgreSQL refusée en profil production : {motif}"
        )
        self.code = "POLICY_DENIED"
        self.motif = motif


def _detecter_cible_non_postgresql(dsn_resolu: str) -> str | None:
    """Retourne le motif de refus si `dsn_resolu` ne désigne pas
    PostgreSQL ; `None` si c'est accepté. Fail-closed : une cible NI
    explicitement PostgreSQL NI explicitement sqlite/mémoire est quand
    même refusée (liste blanche, jamais une liste noire — une liste
    noire serait fail-open, classe d'erreur déjà documentée cette
    session, cf. mémoire opérationnelle)."""
    minuscule = dsn_resolu.lower().strip()
    for marqueur in _MARQUEURS_MEMOIRE:
        if marqueur in minuscule:
            return f"cible in-memory ({marqueur})"
    for prefixe in _CIBLES_NON_POSTGRESQL:
        if minuscule.startswith(prefixe):
            return f"schéma non-PostgreSQL ({prefixe})"
    if any(mc in minuscule for mc in _MOTS_CLES_POSTGRESQL):
        return None
    return "cible non reconnue comme PostgreSQL (fail-closed, liste blanche)"


@runtime_checkable
class Database(Protocol):
    """Port minimal représentant une connexion active. Volontairement
    réduit à `fermer()` — aucune méthode métier sans besoin sourcé par
    tasks/C05-001.md (même discipline que ports/contracts.py, C04-001)."""

    def fermer(self) -> None: ...


class ConnexionPostgreSql:
    """Implémentation RÉELLE — enveloppe une connexion `psycopg`
    active. `.conn` est l'attribut public exposant la connexion brute
    (les futures tâches C05-002+ qui ont besoin d'exécuter des requêtes
    l'utilisent directement — aucune méthode de requête ajoutée ici
    sans besoin sourcé par CETTE tâche)."""

    def __init__(self, conn: "psycopg.Connection") -> None:
        self.conn = conn

    def fermer(self) -> None:
        self.conn.close()

    def __repr__(self) -> str:
        return "ConnexionPostgreSql(***REDIGE***)"

    def __str__(self) -> str:
        return "ConnexionPostgreSql(***REDIGE***)"


class FakeDatabase:
    """Fake EXPLICITE pour tests uniquement (spec C05-001). Nom
    délibérément distinct de `Database`/`ConnexionPostgreSql` — jamais
    retourné par `open_database`, qui refuse structurellement toute
    cible non-PostgreSQL avant toute construction d'objet (cf.
    `_detecter_cible_non_postgresql`, appelé AVANT tout `psycopg.connect`)."""

    def __init__(self) -> None:
        self.fermee = False

    def fermer(self) -> None:
        self.fermee = True


def open_database(config: DatabaseConfig, *, provider: SecretProvider) -> Database:
    """Résout `config.dsn_secret_ref` via `provider`, refuse toute
    cible résolue non-PostgreSQL, ouvre une connexion réelle. `provider`
    keyword-only et sans défaut : un appel `open_database(config)` lève
    `TypeError` (paramètre manquant), jamais un `EnvSecretProvider()`
    implicite construit en silence."""
    secret = provider.get_secret(config.dsn_secret_ref)  # proof:allow — nom de variable (objet SecretRef), aucun secret littéral
    if secret is None:
        raise ValueError(
            f"secret introuvable via le provider fourni : {config.dsn_secret_ref!r}"
        )
    dsn_resolu = secret.reveal(f"open_database:{_APPLICATION_NAME}")

    motif_refus = _detecter_cible_non_postgresql(dsn_resolu)
    if motif_refus is not None:
        raise CibleNonPostgreSqlRefusee(motif_refus)

    # connect_timeout distinct de statement_timeout_ms (GUC serveur,
    # appliqué APRÈS connexion) — limitation documentée, pas un 5e champ
    # non sourcé sur DatabaseConfig (4 champs figés par l'interface
    # imposée). Valeur par défaut bornée en interne : 10s.
    conn = psycopg.connect(
        dsn_resolu,
        application_name=_APPLICATION_NAME,
        connect_timeout=10,
        options=f"-c statement_timeout={config.statement_timeout_ms}",
        autocommit=True,
    )
    return ConnexionPostgreSql(conn)
