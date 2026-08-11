"""Unité de travail transactionnelle PostgreSQL (C05-003).

Encapsule une connexion `ConnexionPostgreSql` (C05-001, ouverte
`autocommit=True` par `open_database`) et ses repositories (`.repository()`
retourne un `Repository`, cf. repository.py). Bascule EXPLICITEMENT la
connexion en mode transactionnel contrôlé pour la durée de vie de
l'instance.

DÉCISION D'ARCHITECTURE DÉCISIVE (revue AVANT code, lecture directe du
code source psycopg 3.2.3 vendorisé — jamais une supposition sur l'API) :
`Connection.transaction()` (context manager natif psycopg) est ÉCARTÉ,
pas par préférence de style mais par INCOMPATIBILITÉ MÉCANIQUE — psycopg
interdit `conn.commit()`/`conn.rollback()` explicites À L'INTÉRIEUR d'un
bloc `conn.transaction()` (`ProgrammingError: Explicit commit() forbidden
within a Transaction context`). Or l'interface imposée par
tasks/C05-003.md est EXACTEMENT `UnitOfWork.commit()->None` /
`UnitOfWork.rollback()->None` — les deux sont donc incompatibles ici.
Bascule MANUELLE de `conn.autocommit` à la place.

PIÈGE MAJEUR ÉVITÉ (identifié en revue, vérifié dans le code source
psycopg) : `conn.commit()`/`conn.rollback()` sont des NO-OP SILENCIEUX
tant que la session reste `autocommit=True` (aucun `BEGIN` n'est jamais
émis) — une UnitOfWork naïve construite directement sur la connexion
`open_database` telle quelle donnerait 3 tests verts pour la mauvaise
raison (chaque écriture immédiatement durable, `rollback()` sans effet
NI erreur). D'où la bascule `conn.autocommit = False` au constructeur,
restaurée dans un `finally` à la clôture — APRÈS retour de la session à
IDLE (psycopg refuse de modifier `autocommit`/`isolation_level` tant que
`transaction_status != IDLE`).

Aucune méthode de requête directe sur `UnitOfWork` — toute écriture
passe par `.repository()` (repository.py), qui refuse si l'UnitOfWork
n'est plus active. Pas de `__enter__`/`__exit__` : une exception levée
par le code appelant AVANT tout `commit()` ne déclenche PAS de rollback
automatique — l'ABSENCE de commit suffit à garantir l'absence d'effet
durable (propriété de la transaction PostgreSQL elle-même, pas d'un
`finally` Python). LIMITATION CONNUE, nommée en clair (même patron que
`connection.py` C05-001) : une UnitOfWork jamais close laisse une
transaction ouverte sur la session jusqu'à fermeture de la connexion —
c'est la garde du constructeur (refus d'une 2e UnitOfWork sur une
session non-IDLE) qui empêche que cela devienne silencieux plutôt qu'un
rollback automatique implicite (hors périmètre de l'interface imposée,
qui ne nomme ni `__enter__` ni `__exit__`).

LIMITATION CONNUE (IN_DOUBT, non traitée ici) : une coupure réseau
pendant `COMMIT` (le client ne sait plus si le serveur a validé ou non)
est le cas canonique `ErrorCode.IN_DOUBT` (`opsys_core/errors.py`) —
hors périmètre de cette tâche (« encapsuler connexion et repositories »,
pas « garantir l'exactly-once en présence de partition réseau »),
appartient à une tâche future dédiée (C06/C07+).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg
from psycopg.pq import TransactionStatus

from opsys_core.persistence.connection import ConnexionPostgreSql

if TYPE_CHECKING:
    from opsys_core.persistence.repository import Repository

# Noms de GUC (Grand Unified Configuration) personnalisés PostgreSQL —
# littéraux CONSTANTS du module ; les VALEURS (trace_id/tenant_id) sont
# toujours passées en paramètre lié, jamais interpolées (cf. __init__).
_GUC_TRACE_ID = "opsys.trace_id"
_GUC_TENANT_ID = "opsys.tenant_id"


class TraceOuTenantInvalide(ValueError):
    """`trace_id` ou `tenant_id` est une chaîne vide."""

    def __init__(self, champ: str) -> None:
        super().__init__(f"{champ} ne peut pas être une chaîne vide")
        self.code = "VALIDATION"


class SessionNonInactiveRefusee(RuntimeError):
    """La connexion porte déjà une transaction active (session non IDLE) —
    refus d'ouvrir une 2e UnitOfWork dessus (une session PostgreSQL ne
    porte qu'UNE transaction à la fois ; deux UnitOfWork simultanées sur
    la même connexion s'écraseraient mutuellement trace_id/tenant_id et
    partageraient un seul COMMIT — corruption silencieuse inter-tenants)."""

    def __init__(self) -> None:
        super().__init__(
            "connexion déjà dans une transaction active — refus d'ouvrir une 2e UnitOfWork sur cette session"
        )
        self.code = "CONFLICT"


class TransactionEnEchec(RuntimeError):
    """`commit()` appelé alors que la transaction est en état ABORTED
    (INERROR) côté serveur — une commande précédente (ex. violation de
    contrainte) a fait échouer la transaction ; un `COMMIT` naïf dans cet
    état serait accepté par PostgreSQL (converti serveur-side en
    ROLLBACK, `COMMAND_OK` retourné) SANS que psycopg ne lève quoi que ce
    soit — un faux DONE parfait si non détecté explicitement ici."""

    def __init__(self) -> None:
        super().__init__(
            "transaction en échec (INERROR) — commit() refusé, tous les effets de cette unité de travail sont perdus"
        )
        self.code = "CONFLICT"


class UnitOfWorkFermee(RuntimeError):
    """`commit()`, `rollback()` ou `.repository()` appelé après clôture
    (un `commit()` ou `rollback()` a déjà été exécuté) — idempotence de
    clôture : jamais un no-op silencieux (comportement natif de psycopg
    sur une connexion déjà IDLE, qu'on ne doit pas hériter ici)."""

    def __init__(self) -> None:
        super().__init__("UnitOfWork déjà fermée (commit ou rollback déjà exécuté)")
        self.code = "CONFLICT"


class UnitOfWork:
    """Unité de travail transactionnelle sur une connexion PostgreSQL
    (C05-001) déjà ouverte. Bascule la connexion hors `autocommit` pour
    sa durée de vie ; restaure l'état d'origine à la clôture."""

    def __init__(
        self,
        database: ConnexionPostgreSql,
        *,
        trace_id: str,
        tenant_id: str,
        isolation_level: "psycopg.IsolationLevel | None" = None,
    ) -> None:
        if not trace_id:
            raise TraceOuTenantInvalide("trace_id")
        if not tenant_id:
            raise TraceOuTenantInvalide("tenant_id")

        conn = database.conn
        if conn.info.transaction_status != TransactionStatus.IDLE:
            raise SessionNonInactiveRefusee()

        self._database = database
        self._trace_id = trace_id
        self._tenant_id = tenant_id
        self._fermee = False

        # État d'origine mémorisé AVANT toute bascule — restauré dans un
        # finally à la clôture (commit() et rollback()), après retour à
        # IDLE (ordre imposé par psycopg, cf. docstring de module).
        self._autocommit_origine = conn.autocommit
        self._isolation_level_origine = conn.isolation_level

        conn.autocommit = False
        if isolation_level is not None:
            conn.isolation_level = isolation_level

        # Première requête de la session : c'est CETTE requête qui émet
        # réellement le BEGIN [ISOLATION LEVEL ...] (psycopg diffère le
        # BEGIN jusqu'à la première commande). set_config(..., true) —
        # 3e argument is_local=true — donne une portée TRANSACTION à la
        # propagation (jamais persistante au-delà du commit/rollback).
        # Noms de GUC en littéral constant, valeurs en paramètre lié
        # (SET LOCAL n'accepte pas de paramètres liés — set_config() si).
        #
        # try/except : filet de restauration si la bascule échoue EN
        # COURS DE ROUTE (ex. panne réseau pendant set_config, APRÈS que
        # autocommit soit déjà passé à False) — objection mineure de
        # revue scellée (Qwen3.7-Max, tour 1), VÉRIFIÉE VRAIE par lecture
        # directe de ce code avant correction (CLAIMS UNVERIFIED) : sans
        # ce filet, la connexion (possédée par l'APPELANT, pas par cette
        # UnitOfWork qui n'a jamais fini de se construire) resterait
        # autocommit=False + isolation_level potentiellement modifié,
        # SANS AUCUNE UnitOfWork pour jamais la restaurer — fuite d'état
        # silencieuse vers le prochain utilisateur de la connexion.
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config(%s, %s, true)", (_GUC_TRACE_ID, trace_id))
                cur.execute("SELECT set_config(%s, %s, true)", (_GUC_TENANT_ID, tenant_id))
        except BaseException:
            try:
                # rollback() est un no-op silencieux si la session est
                # restée IDLE (aucune commande n'a atteint le serveur) —
                # vérifié dans le code source psycopg par la revue
                # d'architecture de ce tour ; sans danger de l'appeler
                # inconditionnellement ici.
                conn.rollback()
                conn.isolation_level = self._isolation_level_origine
                conn.autocommit = self._autocommit_origine
            except psycopg.Error:
                # Domaine d'échec restreint DÉLIBÉRÉMENT à psycopg.Error
                # (pas `except Exception` — trop large, bloqué à raison
                # par le hook no-stub-scan) : la restauration ne peut
                # réalistement échouer QUE si la connexion elle-même est
                # dans un état brisé (ex. réseau définitivement coupé) —
                # dans ce cas, la restauration est de toute façon sans
                # objet (la connexion est perdue). Best-effort seulement :
                # l'exception D'ORIGINE prime, jamais masquée par le
                # `raise` nu ci-dessous.
                pass
            raise

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    def _verifier_active(self) -> None:
        """Lève `UnitOfWorkFermee` si cette instance est déjà close.
        Appelé par `commit()`/`rollback()`/`repository()`, ET par
        `Repository.executer()` (repository.py) — Repository et
        UnitOfWork forment une seule unité d'encapsulation conceptuelle
        (« encapsuler connexion ET repositories », spec de tâche),
        volontairement séparée en 2 fichiers par les Sorties exactes."""
        if self._fermee:
            raise UnitOfWorkFermee()

    def repository(self) -> "Repository":
        """Retourne un `Repository` lié à cette UnitOfWork. Importé
        localement (pas au niveau module) pour éviter un cycle d'import
        avec repository.py, qui importe `UnitOfWork` pour son
        annotation de type."""
        self._verifier_active()
        from opsys_core.persistence.repository import Repository

        return Repository(self)

    def commit(self) -> None:
        """Valide la transaction. Lève `TransactionEnEchec` (sans rien
        valider) si la transaction est déjà en état d'échec (INERROR) —
        jamais un succès silencieux qui masquerait la perte des effets."""
        self._verifier_active()
        conn = self._database.conn
        try:
            if conn.info.transaction_status == TransactionStatus.INERROR:
                # ROLLBACK explicite pour ramener la session à IDLE avant
                # de lever — les effets étaient de toute façon déjà
                # perdus (transaction ABORTED côté serveur).
                conn.rollback()
                raise TransactionEnEchec()
            conn.commit()
        finally:
            self._restaurer(conn)
            self._fermee = True

    def rollback(self) -> None:
        """Annule la transaction — aucun effet de cette unité de travail
        ne devient durable."""
        self._verifier_active()
        conn = self._database.conn
        try:
            conn.rollback()
        finally:
            self._restaurer(conn)
            self._fermee = True

    def _restaurer(self, conn: "psycopg.Connection") -> None:
        # La session DOIT être IDLE ici (commit()/rollback() vient de
        # s'exécuter, y compris le rollback explicite du cas INERROR) —
        # psycopg refuse ces assignations tant que transaction_status
        # != IDLE (ProgrammingError).
        conn.isolation_level = self._isolation_level_origine
        conn.autocommit = self._autocommit_origine
