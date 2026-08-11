"""Tests pour core/src/opsys_core/persistence/{config,connection}.py
(C05-001) — configuration PostgreSQL autoritative, PREMIÈRE tâche de la
phase C05 et PREMIER contact du Core avec un service externe réel
(jusqu'ici C00-C04 = stdlib pur, aucune I/O réseau persistante).

Couvre les 3 cas RED obligatoires de tasks/C05-001.md :
  1. refuser DSN en clair
  2. refuser SQLite/in-memory comme profil production
  3. timeout et pool invalides bloquent

Conception revue par architecture AVANT code (subagent `architecte`,
Claude Opus 5 natif) — verdict complet dans l'Evidence Bundle. Un point
de la revue a été VÉRIFIÉ PUIS CORRIGÉ avant ce code (jamais accepté
sur la seule autorité du reviewer, CLAIMS UNVERIFIED) : l'architecte
recommandait de NE PAS ajouter psycopg (dépendance PyPI) cette tâche,
au motif que le réseau sortant serait indisponible (mesuré : échec DNS
sur production.cloudfront.docker.com, le CDN Docker Hub). Vérifié
directement : PyPI répond HTTP 200, `pip download psycopg==3.2.3
psycopg-binary==3.2.3 --no-deps --only-binary=:all:` réussit avec des
hash sha256 réels et reproductibles. `libpq` n'est PAS installée comme
lib système sur cette machine (mesuré : `ldconfig -p` vide) — parade :
`psycopg-binary` embarque son propre libpq statiquement lié, aucune
installation système requise. **Chaîne bout-en-bout vérifiée par
exécution réelle avant d'écrire ce fichier** : conteneur Postgres
éphémère démarré (digest épinglé), `pg_isready` borné, connexion
`psycopg` réelle, `SELECT version()` réel, conteneur supprimé. La
dépendance est donc ajoutée réellement (core/requirements.lock, hash
réel) plutôt que différée à une tâche future.

Aucun `conftest.py` (convention déjà mesurée : aucun n'existe sous
core/tests/, chaque fichier insère core/src lui-même) — la fixture de
conteneur éphémère vit DANS ce fichier (sortie déclarée), pas dans un
fichier séparé hors périmètre.
"""
from __future__ import annotations

import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Iterator, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from config.vault import SecretProvider, SecretRef

from opsys_core.persistence.config import (
    DatabaseConfig,
    DsnEnClairRefuse,
    ParametresPoolOuTimeoutInvalides,
)
from opsys_core.persistence.connection import (
    CibleNonPostgreSqlRefusee,
    ConnexionPostgreSql,
    FakeDatabase,
    open_database,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Digest épinglé, vérifié réel par exécution directe (docker run réussi,
# "postgres (PostgreSQL) 16.14") avant l'écriture de ce fichier — jamais
# un tag flottant.
_POSTGRES_DIGEST = (
    "postgres@sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb"
)

# Services PostgreSQL EXISTANTS sur cette machine — interdiction absolue
# de s'y connecter (spec C05-001, "interdire explicitement toute
# réutilisation des bases LiteLLM, Langfuse ou d'un service déjà
# présent"). Le harnais ci-dessous ne se connecte QUE au port qu'il a
# lui-même publié (identité par construction, jamais une liste noire —
# une liste noire serait fail-open).
_NOMS_SERVICES_INTERDITS = ("serveur-litellm-db", "serveur-langfuse-db")


class _ConteneurPostgres(NamedTuple):
    host: str
    port: int
    admin_password: str  # proof:allow — annotation de type sur un nom de champ, aucune valeur
    dbname: str
    nom_conteneur: str


def _docker_disponible() -> bool:
    try:
        resultat = subprocess.run(
            ["docker", "--version"], capture_output=True, timeout=5, text=True
        )
        return resultat.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.fixture(scope="module")
def conteneur_postgres_ephemere() -> Iterator[_ConteneurPostgres]:
    """Conteneur PostgreSQL ÉPHÉMÈRE, réseau/volume/secret propres à ce
    run — jamais les services existants. Docker absent = échec EXPLICITE
    (jamais un skip silencieux, cohérent avec la doctrine déjà écrite
    dans core-ci.yml pour les gates sans mécanisme réel : bloquer en
    clair plutôt qu'inventer un vert)."""
    if not _docker_disponible():
        pytest.fail(
            "Docker indisponible — BLOCKED_WITH_CAUSE au niveau tâche "
            "(cas d'acceptation C05-001.md : absence de Docker/Podman)"
        )

    import secrets as secrets_stdlib

    nom_conteneur = f"opsys-c05-001-{uuid.uuid4().hex[:12]}"
    admin_password = secrets_stdlib.token_urlsafe(24)  # proof:allow — généré aléatoirement à l'exécution, jamais un secret constant
    dbname = "opsys_test_c05_001"

    argv_run = [
        "docker", "run", "-d",
        "--name", nom_conteneur,
        "-e", f"POSTGRES_PASSWORD={admin_password}",  # proof:allow — interpole la valeur aléatoire ci-dessus, aucun littéral
        "-e", f"POSTGRES_DB={dbname}",
        "-p", "127.0.0.1::5432",
        _POSTGRES_DIGEST,
    ]
    resultat = subprocess.run(argv_run, capture_output=True, text=True, timeout=30)
    if resultat.returncode != 0:
        pytest.fail(f"échec démarrage conteneur PostgreSQL éphémère : {resultat.stderr}")

    try:
        # Identité par construction : le port réel publié, jamais un port fixe deviné.
        port_result = subprocess.run(
            ["docker", "port", nom_conteneur, "5432/tcp"],
            capture_output=True, text=True, timeout=10,
        )
        assert port_result.returncode == 0, f"impossible de lire le port publié : {port_result.stderr}"
        port = int(port_result.stdout.strip().split(":")[-1])

        # Readiness bornée par pg_isready (TCP interne au conteneur) —
        # JAMAIS un sleep arbitraire (l'entrypoint officiel démarre un
        # serveur temporaire qui n'écoute pas encore en TCP pendant
        # l'init : un check socket externe rendrait "prêt" trop tôt).
        pret = False
        for _ in range(60):
            check = subprocess.run(
                ["docker", "exec", nom_conteneur, "pg_isready", "-h", "127.0.0.1", "-p", "5432"],
                capture_output=True, timeout=5,
            )
            if check.returncode == 0:
                pret = True
                break
            time.sleep(0.5)
        if not pret:
            pytest.fail("conteneur PostgreSQL jamais devenu prêt (pg_isready) après 30s")

        yield _ConteneurPostgres(
            host="127.0.0.1", port=port, admin_password=admin_password,  # proof:allow — transmet la valeur aléatoire ci-dessus, aucun littéral
            dbname=dbname, nom_conteneur=nom_conteneur,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", nom_conteneur], capture_output=True, timeout=15)


class _ProviderTest(SecretProvider):
    """SecretProvider minimal pour les tests — dict figé fourni au
    constructeur, jamais un état de module (aucun singleton, cf.
    C04-004 cas RED 1)."""

    def __init__(self, secrets_map: dict[str, str]) -> None:
        self._secrets = dict(secrets_map)
        self._cache: dict[str, str] = {}

    def get_secret(self, name: str) -> SecretRef | None:
        if name not in self._secrets:
            return None
        valeur = self._secrets[name]
        self._cache[name] = valeur
        return SecretRef(name, valeur)

    def known_secret_values(self) -> list[str]:
        return list(self._cache.values())


def _conninfo_valide(ctr: _ConteneurPostgres) -> str:
    return (
        f"host={ctr.host} port={ctr.port} dbname={ctr.dbname} "
        f"user=postgres password={ctr.admin_password}"  # proof:allow — interpole la valeur aléatoire du conteneur éphémère, aucun littéral
    )


# ---------------------------------------------------------------------------
# Cas RED 1 — refuser DSN en clair
# ---------------------------------------------------------------------------


def test_tablir_la_configuration_postgresql_autoritative_1():
    """DSN en clair refusé À LA CONSTRUCTION de DatabaseConfig (fail
    fast, jamais différé à open_database) — 4 formes indépendantes +
    contrôle positif (sans lui, un DatabaseConfig qui refuserait TOUT
    passerait ce test sans rien prouver)."""
    formes_en_clair = {
        "url_postgresql": "postgresql://user:pass@host:5432/db",
        "url_sqlite": "sqlite:///chemin/local.db",
        "keyword_value_libpq": "host=localhost port=5432 dbname=x user=y password=z",  # proof:allow — donnée de test négative (valeur factice "z"), jamais un secret réel
        "userinfo_arobase": "user@password-ressemble-a-une-valeur",
    }
    for nom_forme, valeur in formes_en_clair.items():
        with pytest.raises(DsnEnClairRefuse):
            DatabaseConfig(dsn_secret_ref=valeur, pool_min=1, pool_max=5, statement_timeout_ms=5000)

    # Contrôle positif : un NOM de secret légitime ne lève pas.
    config = DatabaseConfig(
        dsn_secret_ref="core_db_dsn", pool_min=1, pool_max=5, statement_timeout_ms=5000
    )
    assert config.dsn_secret_ref == "core_db_dsn"


# ---------------------------------------------------------------------------
# Cas RED 2 — refuser SQLite/in-memory comme profil production
# ---------------------------------------------------------------------------


def test_tablir_la_configuration_postgresql_autoritative_2():
    """open_database refuse INCONDITIONNELLEMENT toute cible résolue
    non-PostgreSQL — le secret est résolu AVEC SUCCÈS (le provider
    trouve bien le nom), la garde vient du CONTENU résolu, pas d'un
    échec de résolution (sinon la mauvaise garde serait prouvée : un
    échec de résolution du provider donnerait la même exception pour
    une raison totalement différente)."""
    cibles_non_postgres = {
        "sqlite_fichier": "sqlite:///chemin/local.db",
        "sqlite_memoire": ":memory:",
        "sqlite_memoire_partagee": "file::memory:?cache=shared",
    }
    for nom_cible, valeur_resolue in cibles_non_postgres.items():
        provider = _ProviderTest({"cible_test": valeur_resolue})
        config = DatabaseConfig(
            dsn_secret_ref="cible_test", pool_min=1, pool_max=5, statement_timeout_ms=5000
        )
        with pytest.raises(CibleNonPostgreSqlRefusee):
            open_database(config, provider=provider)

    # Garde structurelle : open_database n'a AUCUN paramètre permettant
    # d'autoriser une cible non-PostgreSQL — pas d'interrupteur caché.
    import inspect

    parametres = set(inspect.signature(open_database).parameters)
    assert parametres == {"config", "provider"}, (
        f"open_database expose un paramètre inattendu qui pourrait autoriser sqlite : {parametres}"
    )


def test_open_database_ne_retourne_jamais_fake_database(conteneur_postgres_ephemere):
    """FakeDatabase n'est JAMAIS atteignable via open_database, quel que
    soit l'input — vérifié à la fois sur le chemin refusé (cas RED 2)
    et sur le chemin RÉUSSI (conteneur réel)."""
    ctr = conteneur_postgres_ephemere
    provider = _ProviderTest({"dsn_reel": _conninfo_valide(ctr)})
    config = DatabaseConfig(
        dsn_secret_ref="dsn_reel", pool_min=1, pool_max=5, statement_timeout_ms=5000
    )
    db = open_database(config, provider=provider)
    try:
        assert not isinstance(db, FakeDatabase)
        assert isinstance(db, ConnexionPostgreSql)
    finally:
        db.fermer()


# ---------------------------------------------------------------------------
# Cas RED 3 — timeout et pool invalides bloquent
# ---------------------------------------------------------------------------


def test_tablir_la_configuration_postgresql_autoritative_3():
    """Chaque garde testée SÉPARÉMENT (un cas qui viole 2 règles à la
    fois ne prouverait que la première évaluée) + contrôle positif."""
    base = {"dsn_secret_ref": "core_db_dsn", "statement_timeout_ms": 5000}

    with pytest.raises(ParametresPoolOuTimeoutInvalides):
        DatabaseConfig(pool_min=-1, pool_max=5, **base)
    with pytest.raises(ParametresPoolOuTimeoutInvalides):
        DatabaseConfig(pool_min=1, pool_max=0, **base)
    with pytest.raises(ParametresPoolOuTimeoutInvalides):
        DatabaseConfig(pool_min=5, pool_max=1, **base)  # min > max
    with pytest.raises(ParametresPoolOuTimeoutInvalides):
        DatabaseConfig(dsn_secret_ref="core_db_dsn", pool_min=1, pool_max=5, statement_timeout_ms=0)
    with pytest.raises(ParametresPoolOuTimeoutInvalides):
        DatabaseConfig(dsn_secret_ref="core_db_dsn", pool_min=1, pool_max=5, statement_timeout_ms=-1)
    with pytest.raises(ParametresPoolOuTimeoutInvalides):
        # bool EST un int en Python (True == 1) — doit être refusé explicitement.
        DatabaseConfig(dsn_secret_ref="core_db_dsn", pool_min=True, pool_max=5, statement_timeout_ms=5000)

    # Contrôle positif : un quadruplet valide construit sans erreur.
    config = DatabaseConfig(dsn_secret_ref="core_db_dsn", pool_min=1, pool_max=5, statement_timeout_ms=5000)
    assert config.pool_min == 1 and config.pool_max == 5


# ---------------------------------------------------------------------------
# Preuve de bout en bout — connexion RÉELLE via le conteneur éphémère
# ---------------------------------------------------------------------------


def test_open_database_se_connecte_reellement_au_conteneur_ephemere(conteneur_postgres_ephemere):
    """Preuve que la chaîne complète fonctionne : conteneur éphémère
    (jamais serveur-litellm-db/serveur-langfuse-db) -> résolution du
    secret -> connexion psycopg réelle -> requête réelle -> fermeture."""
    ctr = conteneur_postgres_ephemere
    assert ctr.nom_conteneur not in _NOMS_SERVICES_INTERDITS

    provider = _ProviderTest({"dsn_reel": _conninfo_valide(ctr)})
    config = DatabaseConfig(
        dsn_secret_ref="dsn_reel", pool_min=1, pool_max=5, statement_timeout_ms=5000
    )
    db = open_database(config, provider=provider)
    try:
        # Protocol Database volontairement minimal (fermer() uniquement,
        # même discipline anti-sur-spécification que ports/contracts.py
        # C04-001) : la preuve de connectivité passe par l'attribut
        # public .conn de l'implémentation CONCRÈTE (déjà vérifié
        # isinstance ConnexionPostgreSql ci-dessus), pas par une méthode
        # ajoutée au Protocol public sans besoin sourcé.
        with db.conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
        assert "PostgreSQL" in version
    finally:
        db.fermer()


def test_open_database_exige_un_provider_explicite():
    """Aucun provider implicite (EnvSecretProvider() construit en
    silence) — cf. discipline C04-004 : l'appelant fournit tout, jamais
    un état global/implicite. provider est keyword-only ET obligatoire."""
    config = DatabaseConfig(dsn_secret_ref="core_db_dsn", pool_min=1, pool_max=5, statement_timeout_ms=5000)
    with pytest.raises(TypeError):
        open_database(config)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Croisement avec le harnais existant (dependency-rules.toml)
# ---------------------------------------------------------------------------


def test_dependency_rules_toml_declare_persistence_sous_adapters():
    """Même patron que C04-003 (compat/) et C04-004 (composition/
    provider_registry) : sans cette déclaration, test_union_des_couches_
    couvre_exactement_tous_les_py_de_core_src (C04-001, déjà mergé)
    part rouge dès que persistence/{config,connection}.py existent."""
    import tomllib

    regles = tomllib.loads((_REPO_ROOT / "core" / "dependency-rules.toml").read_text(encoding="utf-8"))
    chemins_adapters = regles["layers"]["adapters"]["paths"]
    assert any(p.rstrip("/") == "opsys_core/persistence" for p in chemins_adapters), (
        f"'opsys_core/persistence/' absent de [layers.adapters].paths : {chemins_adapters}"
    )
    # Garde de non-régression : le vocabulaire de couches reste EXACT
    # (test_toutes_les_couches_du_vocabulaire_du_spec_sont_declarees,
    # C04-001, déjà mergé) — aucune 6e couche n'a été ajoutée.
    assert set(regles["layers"]) == {"kernel", "domain", "ports", "application", "adapters"}
