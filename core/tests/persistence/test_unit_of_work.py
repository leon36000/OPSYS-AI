"""Tests pour core/src/opsys_core/persistence/{uow,repository}.py
(C05-003) — unité de travail transactionnelle PostgreSQL, TROISIÈME
tâche de la phase C05 (après C05-001 configuration/connexion, C05-002
migrations — dépendance directe C05-002).

Couvre les 3 cas RED obligatoires de tasks/C05-003.md :
  1. exception avant commit ne laisse aucun effet
  2. commit partiel interdit
  3. transaction sérialisable disponible pour réservations critiques

Conception revue par architecture AVANT code (subagent `architecte`,
Claude Opus 5 natif) — verdict complet dans l'Evidence Bundle. La revue
a LU LE CODE SOURCE psycopg 3.2.3 vendorisé réel (pas une supposition
d'API) et trouvé un piège DÉCISIF : `Connection.transaction()` (context
manager natif psycopg) interdit `conn.commit()`/`conn.rollback()`
explicites en son sein — incompatible avec l'interface imposée
`UnitOfWork.commit()->None`/`UnitOfWork.rollback()->None`. `UnitOfWork`
bascule donc MANUELLEMENT `conn.autocommit`, jamais via `conn.transaction()`
— cf. docstring de `uow.py` pour le détail complet du raisonnement.

Chaque test isole une propriété avec un CONTRÔLE POSITIF ou NÉGATIF
dédié (jamais un seul côté du contraste) — patron déjà établi
C05-001/C05-002 sur ce dépôt.

Table de test dédiée `uow_test_reservations(slot PK, tenant_id)`, créée
directement par SQL brut (PAS via migrations.py, un validateur
purement statique qui ne s'exécute jamais lui-même). Slots UNIQUES par
test (uuid) — la fixture de conteneur est `scope="module"`, partagée
entre tous les tests de ce fichier.

Aucun `conftest.py` (convention déjà mesurée sur ce dépôt) — fixture de
conteneur éphémère DUPLIQUÉE fidèlement depuis
test_postgres_configuration.py (C05-001, même digest épinglé, même
séquence docker run/port/pg_isready bornée), pas importée d'un autre
fichier de test.
"""
from __future__ import annotations

import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Iterator, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import psycopg
import pytest

from config.vault import SecretProvider, SecretRef

from opsys_core.persistence.config import DatabaseConfig
from opsys_core.persistence.connection import ConnexionPostgreSql, open_database
from opsys_core.persistence.repository import Repository
from opsys_core.persistence.uow import (
    SessionNonInactiveRefusee,
    TraceOuTenantInvalide,
    TransactionEnEchec,
    UnitOfWork,
    UnitOfWorkFermee,
)

# ---------------------------------------------------------------------------
# Fixture de conteneur éphémère — DUPLIQUÉE fidèlement depuis
# test_postgres_configuration.py (C05-001), même digest épinglé.
# ---------------------------------------------------------------------------

_POSTGRES_DIGEST = (
    "postgres@sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb"
)

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
    """Conteneur PostgreSQL ÉPHÉMÈRE, propre à ce run — jamais les
    services existants. Docker absent = échec EXPLICITE (jamais un skip
    silencieux)."""
    if not _docker_disponible():
        pytest.fail(
            "Docker indisponible — BLOCKED_WITH_CAUSE au niveau tâche "
            "(cas d'acceptation C05-003.md : absence de Docker/Podman)"
        )

    import secrets as secrets_stdlib

    nom_conteneur = f"opsys-c05-003-{uuid.uuid4().hex[:12]}"
    admin_password = secrets_stdlib.token_urlsafe(24)  # proof:allow — généré aléatoirement à l'exécution, jamais un secret constant
    dbname = "opsys_test_c05_003"

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
        port_result = subprocess.run(
            ["docker", "port", nom_conteneur, "5432/tcp"],
            capture_output=True, text=True, timeout=10,
        )
        assert port_result.returncode == 0, f"impossible de lire le port publié : {port_result.stderr}"
        port = int(port_result.stdout.strip().split(":")[-1])

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


def _ouvrir_connexion(ctr: _ConteneurPostgres) -> ConnexionPostgreSql:
    provider = _ProviderTest({"dsn_reel": _conninfo_valide(ctr)})
    config = DatabaseConfig(
        dsn_secret_ref="dsn_reel", pool_min=1, pool_max=5, statement_timeout_ms=5000
    )
    db = open_database(config, provider=provider)
    # open_database retourne le Protocol Database (volontairement réduit
    # à fermer() — même discipline anti-sur-spécification que
    # ports/contracts.py) ; ce helper de test a besoin de .conn, donc
    # narrowing explicite (même patron que test_postgres_configuration.py
    # C05-001) — jamais atteignable en pratique (FakeDatabase n'est
    # jamais retourné par open_database), mais mypy ne le sait pas sans
    # cette assertion.
    assert isinstance(db, ConnexionPostgreSql)
    return db


@pytest.fixture(scope="module")
def conteneur_avec_table(conteneur_postgres_ephemere: _ConteneurPostgres) -> _ConteneurPostgres:
    """Même conteneur, avec la table de test créée UNE SEULE FOIS (scope
    module). Schéma minimal pour les cas RED de cette tâche, créé par
    SQL brut — PAS via opsys_core.persistence.migrations (validateur
    purement statique de tasks/migrations, ne s'exécute jamais
    lui-même, hors périmètre ici)."""
    ctr = conteneur_postgres_ephemere
    db = _ouvrir_connexion(ctr)
    try:
        with db.conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS uow_test_reservations ("
                "slot text PRIMARY KEY, tenant_id text NOT NULL)"
            )
    finally:
        db.fermer()
    return ctr


def _compter(ctr: _ConteneurPostgres, sql: str, parametres: tuple) -> int:
    """Lecture de vérification depuis une connexion INDÉPENDANTE, en
    dehors de toute UnitOfWork (autocommit, lecture seule, simple)."""
    db = _ouvrir_connexion(ctr)
    try:
        with db.conn.cursor() as cur:
            cur.execute(sql, parametres)
            ligne = cur.fetchone()
            assert ligne is not None, "COUNT(*) doit toujours retourner exactement une ligne"
            return ligne[0]
    finally:
        db.fermer()


# ---------------------------------------------------------------------------
# Cas RED obligatoire #1 : exception avant commit ne laisse aucun effet
# ---------------------------------------------------------------------------


def test_impl_menter_l_unit_de_travail_transactionnelle_1(conteneur_avec_table):
    ctr = conteneur_avec_table
    slot = f"slot-{uuid.uuid4().hex[:12]}"

    db = _ouvrir_connexion(ctr)
    try:
        uow = UnitOfWork(db, trace_id="t1-trace", tenant_id="tenant-t1")
        repo = uow.repository()
        repo.executer(
            "INSERT INTO uow_test_reservations (slot, tenant_id) VALUES (%s, %s)",
            (slot, "tenant-t1"),
        )
        # Une exception survient AVANT tout commit() — design : pas de
        # rollback automatique (pas de __enter__/__exit__), l'ABSENCE de
        # commit() suffit à garantir l'absence d'effet durable.
        try:
            raise RuntimeError("panne applicative simulée avant tout commit()")
        except RuntimeError:
            pass  # commit() n'est simplement jamais appelé
        uow.rollback()  # clôture explicite propre (ne laisse rien traîner sur la connexion)
    finally:
        db.fermer()

    assert _compter(ctr, "SELECT count(*) FROM uow_test_reservations WHERE slot = %s", (slot,)) == 0

    # Contrôle positif : SANS exception, un commit() laisse bien l'effet
    # (sans lui, une UnitOfWork qui n'écrirait jamais rien passerait ce
    # test sans rien prouver).
    slot_positif = f"slot-{uuid.uuid4().hex[:12]}"
    db2 = _ouvrir_connexion(ctr)
    try:
        uow2 = UnitOfWork(db2, trace_id="t1-positif", tenant_id="tenant-t1")
        uow2.repository().executer(
            "INSERT INTO uow_test_reservations (slot, tenant_id) VALUES (%s, %s)",
            (slot_positif, "tenant-t1"),
        )
        uow2.commit()
    finally:
        db2.fermer()

    assert _compter(ctr, "SELECT count(*) FROM uow_test_reservations WHERE slot = %s", (slot_positif,)) == 1


# ---------------------------------------------------------------------------
# Cas RED obligatoire #2 : commit partiel interdit
# ---------------------------------------------------------------------------


def test_impl_menter_l_unit_de_travail_transactionnelle_2(conteneur_avec_table):
    ctr = conteneur_avec_table
    slot_ok = f"slot-{uuid.uuid4().hex[:12]}"

    db = _ouvrir_connexion(ctr)
    try:
        uow = UnitOfWork(db, trace_id="t2-trace", tenant_id="tenant-t2")
        repo = uow.repository()
        # Première écriture : réussit.
        repo.executer(
            "INSERT INTO uow_test_reservations (slot, tenant_id) VALUES (%s, %s)",
            (slot_ok, "tenant-t2"),
        )
        # Deuxième écriture : viole la contrainte PRIMARY KEY (même slot)
        # — met la transaction en état d'échec (INERROR) côté serveur.
        with pytest.raises(psycopg.errors.UniqueViolation):
            repo.executer(
                "INSERT INTO uow_test_reservations (slot, tenant_id) VALUES (%s, %s)",
                (slot_ok, "tenant-t2"),
            )
        # commit() doit REFUSER — sans cette garde, PostgreSQL convertit
        # silencieusement un COMMIT sur transaction INERROR en ROLLBACK
        # côté serveur et retourne COMMAND_OK : un faux DONE parfait.
        with pytest.raises(TransactionEnEchec):
            uow.commit()
    finally:
        db.fermer()

    # C'est la disparition de la PREMIÈRE écriture (réussie) qui prouve
    # "pas de commit partiel" — pas la seconde, qui a de toute façon
    # échoué.
    assert _compter(ctr, "SELECT count(*) FROM uow_test_reservations WHERE slot = %s", (slot_ok,)) == 0

    # Contrôle positif : une UoW qui écrit 2 slots distincts SANS
    # violation, puis commit(), laisse bien les 2 lignes.
    slot_a = f"slot-{uuid.uuid4().hex[:12]}"
    slot_b = f"slot-{uuid.uuid4().hex[:12]}"
    db2 = _ouvrir_connexion(ctr)
    try:
        uow2 = UnitOfWork(db2, trace_id="t2-positif", tenant_id="tenant-t2")
        repo2 = uow2.repository()
        repo2.executer("INSERT INTO uow_test_reservations (slot, tenant_id) VALUES (%s, %s)", (slot_a, "tenant-t2"))
        repo2.executer("INSERT INTO uow_test_reservations (slot, tenant_id) VALUES (%s, %s)", (slot_b, "tenant-t2"))
        uow2.commit()
    finally:
        db2.fermer()

    assert _compter(ctr, "SELECT count(*) FROM uow_test_reservations WHERE slot IN (%s, %s)", (slot_a, slot_b)) == 2


# ---------------------------------------------------------------------------
# Cas RED obligatoire #3 : transaction sérialisable disponible pour
# réservations critiques
# ---------------------------------------------------------------------------


def test_impl_menter_l_unit_de_travail_transactionnelle_3(conteneur_avec_table):
    ctr = conteneur_avec_table

    # (1) Contrôle négatif : sans isolation_level explicite, niveau par
    # défaut PostgreSQL = read committed (sans lui, un test qui lirait
    # un GUC serveur global serait vert pour la mauvaise raison).
    db1 = _ouvrir_connexion(ctr)
    try:
        uow1 = UnitOfWork(db1, trace_id="t3-defaut", tenant_id="tenant-t3")
        rows = uow1.repository().executer("SHOW transaction_isolation")
        assert rows[0][0] == "read committed"
        uow1.rollback()
    finally:
        db1.fermer()

    # (2) SERIALIZABLE explicite = niveau réellement appliqué (réponse
    # du serveur réel, immockable).
    db2 = _ouvrir_connexion(ctr)
    try:
        uow2 = UnitOfWork(
            db2, trace_id="t3-serial", tenant_id="tenant-t3",
            isolation_level=psycopg.IsolationLevel.SERIALIZABLE,
        )
        rows = uow2.repository().executer("SHOW transaction_isolation")
        assert rows[0][0] == "serializable"
        uow2.rollback()

        # (3) Contrôle de non-fuite : une NOUVELLE UoW par défaut SUR LA
        # MÊME CONNEXION revient à read committed — prouve que
        # isolation_level (attribut de CONNEXION, pas de transaction)
        # est bien restauré à la clôture, jamais laissé fuiter.
        uow3 = UnitOfWork(db2, trace_id="t3-apres", tenant_id="tenant-t3")
        rows = uow3.repository().executer("SHOW transaction_isolation")
        assert rows[0][0] == "read committed"
        uow3.rollback()
    finally:
        db2.fermer()


def test_conflit_serialisable_reel_propage_serializationfailure_au_commit(conteneur_avec_table):
    """4e test (nom libre, hors des 3 noms minimaux imposés) : preuve
    qu'un VRAI conflit de sérialisation détecté par PostgreSQL (SSI —
    Serializable Snapshot Isolation) est PROPAGÉ par commit(), jamais
    avalé. Ce que ce test prouve n'est pas l'algorithme SSI de
    PostgreSQL lui-même (hors périmètre) mais le comportement de NOTRE
    code : un `except Exception: pass` dans commit() resterait
    indétectable sans ce test.

    Reproducteur SSI minimal canonique : deux transactions SERIALIZABLE
    lisent le MÊME prédicat (« combien de réservations pour ce tenant »),
    puis chacune insère une ligne qui matcherait ce même prédicat — cycle
    de rw-antidépendances que PostgreSQL détecte à la validation. Écrit
    sur des LIGNES DIFFÉRENTES (slots distincts) — jamais la même ligne :
    un conflit write-write direct BLOQUERAIT (jusqu'à statement_timeout,
    donnant QueryCanceled et non SerializationFailure), au lieu de lever
    immédiatement à la détection SSI."""
    ctr = conteneur_avec_table
    tenant_partage = f"tenant-ssi-{uuid.uuid4().hex[:12]}"

    db1 = _ouvrir_connexion(ctr)
    db2 = _ouvrir_connexion(ctr)
    try:
        uow1 = UnitOfWork(
            db1, trace_id="ssi-1", tenant_id=tenant_partage,
            isolation_level=psycopg.IsolationLevel.SERIALIZABLE,
        )
        uow2 = UnitOfWork(
            db2, trace_id="ssi-2", tenant_id=tenant_partage,
            isolation_level=psycopg.IsolationLevel.SERIALIZABLE,
        )
        repo1, repo2 = uow1.repository(), uow2.repository()

        # Les deux lisent le MÊME prédicat (aucune ligne pour ce tenant).
        repo1.executer(
            "SELECT count(*) FROM uow_test_reservations WHERE tenant_id = %s", (tenant_partage,)
        )
        repo2.executer(
            "SELECT count(*) FROM uow_test_reservations WHERE tenant_id = %s", (tenant_partage,)
        )

        # Chacune insère une ligne DIFFÉRENTE (slot distinct) mais qui
        # matche le MÊME prédicat lu ci-dessus (tenant_id partagé).
        repo1.executer(
            "INSERT INTO uow_test_reservations (slot, tenant_id) VALUES (%s, %s)",
            (f"slot-ssi-a-{uuid.uuid4().hex[:8]}", tenant_partage),
        )
        repo2.executer(
            "INSERT INTO uow_test_reservations (slot, tenant_id) VALUES (%s, %s)",
            (f"slot-ssi-b-{uuid.uuid4().hex[:8]}", tenant_partage),
        )

        uow1.commit()  # réussit — premier arrivé
        with pytest.raises(psycopg.errors.SerializationFailure):
            uow2.commit()  # anomalie de sérialisation détectée par PostgreSQL (SQLSTATE 40001)
    finally:
        db1.fermer()
        db2.fermer()


# ---------------------------------------------------------------------------
# Validation trace_id/tenant_id
# ---------------------------------------------------------------------------


def test_trace_id_vide_refuse(conteneur_avec_table):
    ctr = conteneur_avec_table
    db = _ouvrir_connexion(ctr)
    try:
        with pytest.raises(TraceOuTenantInvalide):
            UnitOfWork(db, trace_id="", tenant_id="tenant-valide")
    finally:
        db.fermer()


def test_tenant_id_vide_refuse(conteneur_avec_table):
    ctr = conteneur_avec_table
    db = _ouvrir_connexion(ctr)
    try:
        with pytest.raises(TraceOuTenantInvalide):
            UnitOfWork(db, trace_id="trace-valide", tenant_id="")
    finally:
        db.fermer()


# ---------------------------------------------------------------------------
# R1 (revue d'architecture) — refus d'une 2e UnitOfWork sur session
# non-IDLE (corruption silencieuse inter-tenants sinon)
# ---------------------------------------------------------------------------


def test_refuse_une_2e_unitofwork_sur_session_non_idle(conteneur_avec_table):
    ctr = conteneur_avec_table
    db = _ouvrir_connexion(ctr)
    try:
        uow1 = UnitOfWork(db, trace_id="r1-a", tenant_id="tenant-r1")
        with pytest.raises(SessionNonInactiveRefusee):
            UnitOfWork(db, trace_id="r1-b", tenant_id="tenant-r1-autre")
        uow1.rollback()
    finally:
        db.fermer()


# ---------------------------------------------------------------------------
# R2 (revue d'architecture) — l'UoW ne ferme jamais la connexion
# ---------------------------------------------------------------------------


def test_uow_ne_ferme_jamais_la_connexion(conteneur_avec_table):
    ctr = conteneur_avec_table
    db = _ouvrir_connexion(ctr)
    try:
        uow = UnitOfWork(db, trace_id="r2", tenant_id="tenant-r2")
        uow.commit()
        # La connexion doit rester utilisable après la clôture de l'UoW.
        with db.conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1
        # Une NOUVELLE UnitOfWork doit pouvoir s'ouvrir sur la MÊME
        # connexion (la session est bien revenue à IDLE).
        uow2 = UnitOfWork(db, trace_id="r2-bis", tenant_id="tenant-r2")
        uow2.rollback()
    finally:
        db.fermer()


# ---------------------------------------------------------------------------
# R3 (revue d'architecture) — idempotence de clôture
# ---------------------------------------------------------------------------


def test_commit_deux_fois_refuse(conteneur_avec_table):
    ctr = conteneur_avec_table
    db = _ouvrir_connexion(ctr)
    try:
        uow = UnitOfWork(db, trace_id="r3-a", tenant_id="tenant-r3")
        uow.commit()
        with pytest.raises(UnitOfWorkFermee):
            uow.commit()
    finally:
        db.fermer()


def test_rollback_apres_commit_refuse(conteneur_avec_table):
    ctr = conteneur_avec_table
    db = _ouvrir_connexion(ctr)
    try:
        uow = UnitOfWork(db, trace_id="r3-b", tenant_id="tenant-r3")
        uow.commit()
        with pytest.raises(UnitOfWorkFermee):
            uow.rollback()
    finally:
        db.fermer()


def test_repository_apres_cloture_refuse(conteneur_avec_table):
    ctr = conteneur_avec_table
    db = _ouvrir_connexion(ctr)
    try:
        uow = UnitOfWork(db, trace_id="r3-c", tenant_id="tenant-r3")
        uow.rollback()
        with pytest.raises(UnitOfWorkFermee):
            uow.repository()
    finally:
        db.fermer()


def test_repository_executer_apres_cloture_refuse(conteneur_avec_table):
    """La garde vit sur Repository.executer(), pas seulement sur
    UnitOfWork.repository() — un Repository obtenu AVANT la clôture,
    utilisé APRÈS, doit être refusé lui aussi (aucune écriture ne peut
    s'échapper de l'unité de travail après sa clôture)."""
    ctr = conteneur_avec_table
    db = _ouvrir_connexion(ctr)
    try:
        uow = UnitOfWork(db, trace_id="r3-d", tenant_id="tenant-r3")
        repo = uow.repository()
        uow.commit()
        with pytest.raises(UnitOfWorkFermee):
            repo.executer("SELECT 1")
    finally:
        db.fermer()


# ---------------------------------------------------------------------------
# Propagation trace_id/tenant_id — observable dans la transaction,
# non-fuite après clôture
# ---------------------------------------------------------------------------


def test_trace_id_et_tenant_id_observables_dans_la_transaction(conteneur_avec_table):
    ctr = conteneur_avec_table
    db = _ouvrir_connexion(ctr)
    try:
        uow = UnitOfWork(db, trace_id="trace-observable-xyz", tenant_id="tenant-observable-abc")
        repo = uow.repository()
        # Lu en REQUÊTE SÉPARÉE de celle qui a fixé la GUC (set_config
        # dans __init__) — ne peut renvoyer la valeur que si un VRAI
        # bloc transactionnel est ouvert (si autocommit était resté
        # True, is_local=true ne survivrait pas à la fin du statement).
        # Ce test prouve donc simultanément la propagation ET la
        # non-régression du piège autocommit=True.
        rows_trace = repo.executer("SELECT current_setting('opsys.trace_id', true)")
        rows_tenant = repo.executer("SELECT current_setting('opsys.tenant_id', true)")
        assert rows_trace[0][0] == "trace-observable-xyz"
        assert rows_tenant[0][0] == "tenant-observable-abc"
        uow.commit()

        # Non-fuite : après commit(), sur la MÊME connexion, la GUC ne
        # vaut plus la valeur précédente (portée transaction seulement,
        # is_local=true) — contamination inter-tenants sinon si la
        # connexion est réutilisée pour une future UoW d'un autre tenant.
        with db.conn.cursor() as cur:
            cur.execute("SELECT current_setting('opsys.tenant_id', true)")
            valeur_apres = cur.fetchone()[0]
        assert valeur_apres != "tenant-observable-abc"
    finally:
        db.fermer()


# ---------------------------------------------------------------------------
# Repository — paramètres liés (jamais d'interpolation SQL), retour
# vide pour les commandes sans jeu de résultats
# ---------------------------------------------------------------------------


def test_executer_traite_les_parametres_comme_litteraux_jamais_comme_sql(conteneur_avec_table):
    """Preuve réelle (pas structurelle) de sécurité par requête
    paramétrée : une charge « injection » passée en PARAMÈTRE est
    stockée littéralement, jamais exécutée comme SQL — et la table
    existe toujours après (aucun DROP TABLE réellement exécuté)."""
    ctr = conteneur_avec_table
    db = _ouvrir_connexion(ctr)
    slot = f"slot-{uuid.uuid4().hex[:12]}"
    charge_malveillante = "x'; DROP TABLE uow_test_reservations; --"
    try:
        uow = UnitOfWork(db, trace_id="injection", tenant_id="tenant-injection")
        repo = uow.repository()
        repo.executer(
            "INSERT INTO uow_test_reservations (slot, tenant_id) VALUES (%s, %s)",
            (slot, charge_malveillante),
        )
        rows = repo.executer(
            "SELECT tenant_id FROM uow_test_reservations WHERE slot = %s", (slot,)
        )
        uow.rollback()
        assert rows[0][0] == charge_malveillante
    finally:
        db.fermer()

    # La table est toujours utilisable — le DROP TABLE n'a jamais été
    # exécuté comme commande, seulement stocké comme donnée.
    assert _compter(ctr, "SELECT count(*) FROM uow_test_reservations WHERE slot = %s", (slot,)) == 0


def test_executer_retourne_liste_vide_pour_insert_sans_returning(conteneur_avec_table):
    ctr = conteneur_avec_table
    db = _ouvrir_connexion(ctr)
    slot = f"slot-{uuid.uuid4().hex[:12]}"
    try:
        uow = UnitOfWork(db, trace_id="vide", tenant_id="tenant-vide")
        repo = uow.repository()
        resultat = repo.executer(
            "INSERT INTO uow_test_reservations (slot, tenant_id) VALUES (%s, %s)",
            (slot, "tenant-vide"),
        )
        assert resultat == []
        uow.rollback()
    finally:
        db.fermer()


def test_executer_retourne_les_lignes_pour_select(conteneur_avec_table):
    ctr = conteneur_avec_table
    db = _ouvrir_connexion(ctr)
    slot = f"slot-{uuid.uuid4().hex[:12]}"
    try:
        uow = UnitOfWork(db, trace_id="select", tenant_id="tenant-select")
        repo = uow.repository()
        repo.executer(
            "INSERT INTO uow_test_reservations (slot, tenant_id) VALUES (%s, %s)",
            (slot, "tenant-select"),
        )
        rows = repo.executer(
            "SELECT slot, tenant_id FROM uow_test_reservations WHERE slot = %s", (slot,)
        )
        uow.rollback()
        assert rows == [(slot, "tenant-select")]
    finally:
        db.fermer()


# ---------------------------------------------------------------------------
# Objection mineure (civ_review tour 1, Qwen3.7-Max, VÉRIFIÉE VRAIE par
# lecture directe du code avant correction) — filet de restauration si
# la bascule du constructeur échoue EN COURS DE ROUTE
# ---------------------------------------------------------------------------


class _CurseurQuiEchoueUneFois:
    """Double de test (mock autorisé — service externe, AGENTS.md) :
    délègue à un curseur RÉEL, mais lève une exception simulée à son 2e
    appel `execute()` — reproduit une panne réseau survenant PENDANT la
    bascule du constructeur d'UnitOfWork, APRÈS le 1er set_config()
    (trace_id) mais AVANT le 2e (tenant_id)."""

    def __init__(self, curseur_reel) -> None:
        self._reel = curseur_reel
        self._appels = 0

    def __enter__(self) -> "_CurseurQuiEchoueUneFois":
        self._reel.__enter__()
        return self

    def __exit__(self, *exc) -> bool | None:
        return self._reel.__exit__(*exc)

    def execute(self, sql, params=None):
        self._appels += 1
        if self._appels == 2:
            raise RuntimeError("panne réseau simulée pendant set_config (2e appel)")
        return self._reel.execute(sql, params)


class _ConnDeleguee:
    """Enveloppe une connexion psycopg RÉELLE : délègue TOUT (lectures
    ET écritures d'attribut) via `__getattr__`/`__setattr__` sauf
    `.cursor()`, qui renvoie le curseur défaillant ci-dessus.

    `__setattr__` est INDISPENSABLE ici, pas seulement `__getattr__` :
    `UnitOfWork.__init__` fait `conn.autocommit = False` (une AFFECTATION
    d'attribut, jamais interceptée par `__getattr__` qui ne gère QUE les
    lectures d'attribut absent) — sans lui, cette écriture atterrirait
    silencieusement sur l'ENVELOPPE elle-même plutôt que sur la
    connexion réelle, rendant les assertions de restauration de
    `test_init_restaure_l_etat_si_la_bascule_echoue_en_cours_de_route`
    vraies quoi qu'il arrive (test vert pour la mauvaise raison — piège
    déjà rencontré et corrigé PENDANT ce tour, confirmé par mutation :
    sans ce correctif, désactiver la restauration réelle dans uow.py ne
    faisait PAS échouer ce test)."""

    def __init__(self, conn_reelle) -> None:
        object.__setattr__(self, "_reel", conn_reelle)

    def __getattr__(self, nom):
        return getattr(self._reel, nom)

    def __setattr__(self, nom, valeur):
        setattr(self._reel, nom, valeur)

    def cursor(self):
        return _CurseurQuiEchoueUneFois(self._reel.cursor())


class _ConnexionAvecCurseurQuiEchoue:
    """Enveloppe une `ConnexionPostgreSql` réelle avec le même contrat
    (`.conn`, `.fermer()`) — UnitOfWork ne distingue pas ce double d'une
    vraie `ConnexionPostgreSql` (typage structurel)."""

    def __init__(self, db_reelle: ConnexionPostgreSql) -> None:
        self._db_reelle = db_reelle

    @property
    def conn(self):
        return _ConnDeleguee(self._db_reelle.conn)

    def fermer(self) -> None:
        self._db_reelle.fermer()


def test_init_restaure_l_etat_si_la_bascule_echoue_en_cours_de_route(conteneur_avec_table):
    """Objection mineure Qwen3.7-Max (civ_review tour 1), vérifiée VRAIE
    par lecture directe du code AVANT correction (CLAIMS UNVERIFIED) :
    si `set_config()` échoue APRÈS `conn.autocommit=False` mais AVANT la
    fin du constructeur, la connexion (possédée par l'APPELANT, pas par
    cette UnitOfWork qui n'a jamais fini de se construire) doit être
    restaurée à son état d'origine — sinon elle resterait
    `autocommit=False` (+ `isolation_level` potentiellement modifié)
    SANS AUCUNE UnitOfWork pour jamais la restaurer : fuite d'état
    silencieuse vers le prochain utilisateur de la connexion."""
    ctr = conteneur_avec_table
    db_reelle = _ouvrir_connexion(ctr)
    autocommit_avant = db_reelle.conn.autocommit
    isolation_avant = db_reelle.conn.isolation_level
    db_defaillante = _ConnexionAvecCurseurQuiEchoue(db_reelle)
    try:
        with pytest.raises(RuntimeError, match="panne réseau simulée"):
            UnitOfWork(db_defaillante, trace_id="panne", tenant_id="tenant-panne")
        # La connexion RÉELLE sous-jacente doit être restaurée malgré l'échec.
        assert db_reelle.conn.autocommit == autocommit_avant
        assert db_reelle.conn.isolation_level == isolation_avant
        assert db_reelle.conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        # Contrôle positif : une VRAIE UnitOfWork peut s'ouvrir ensuite
        # sur la même connexion, sans aucun état résiduel de la panne.
        uow = UnitOfWork(db_reelle, trace_id="apres-panne", tenant_id="tenant-apres-panne")
        uow.rollback()
    finally:
        db_reelle.fermer()


# ---------------------------------------------------------------------------
# repository() retourne une instance Repository réelle
# ---------------------------------------------------------------------------


def test_repository_retourne_une_instance_repository(conteneur_avec_table):
    ctr = conteneur_avec_table
    db = _ouvrir_connexion(ctr)
    try:
        uow = UnitOfWork(db, trace_id="typage", tenant_id="tenant-typage")
        repo = uow.repository()
        assert isinstance(repo, Repository)
        uow.rollback()
    finally:
        db.fermer()
