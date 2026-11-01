"""Exclusion d'écriture d'instance des services M4 (recalcul certifié, relecture courante, historique, capacités) et
identité de la base, sur SQLite ET sur PostgreSQL.

CE QUE L'ANCIEN CODE EXIGEAIT. Les services de la famille « capacité M4 » (`service_capability`,
`service_lecture_m4`, `service_recalcul_m4`, le moteur de recalcul, `service_history_m4`, `service_politiques`)
vérifiaient, à chaque pas de leur portée, (1) que l'écouteur `begin` du moteur engage `BEGIN IMMEDIATE` (aucun
autre écrivain ne peut valider tant que la transaction vit), (2) que la connexion `sqlite3` est bien dans une
transaction, (3) l'identité du FICHIER de base (chemin, périphérique, inode) pour qu'une capacité ne puisse pas
être rejouée contre une autre base.

CE QUE PROPOSE CE MODULE POUR POSTGRESQL.
- Exclusion : un verrou consultatif de transaction `ecriture-instance-m4` (`stockage.concurrence`), pris à
  l'ouverture de la portée et VÉRIFIÉ à chaque pas dans `pg_locks` pour CETTE session (un `ROLLBACK TO SAVEPOINT`
  antérieur à la prise du verrou le relâcherait : le contrôle le détecte). Il sérialise entre elles les portées de
  la famille (deux recalculs, une relecture et un recalcul, la révocation d'une politique…). Il N'EXCLUT PAS les
  écrivains métier M3/M4/M5 ordinaires (ils ne le prennent pas) : sous SQLite, `BEGIN IMMEDIATE` les excluait
  tous.
- Pourquoi cela suffit : le protocole des services est optimiste. Ils relisent leurs sources (projection M4, devis
  M3, reçus et traces M5, politiques, événement du bus) AVANT et APRÈS chaque écriture et comparent le contenu
  relu au contenu premier (`_final`, `verifier_projection`, `_politiques`) ; un registre append-only relu
  identique au début et à la fin n'a pas bougé entre-temps (aucun ABA possible). Toute dérive donne
  `RefusAutorite` (« source modifiée ») et la portée est annulée. Ce qui est publié correspond donc aux sources
  telles qu'elles étaient à l'instant de la dernière vérification, avant la validation : le même énoncé que sous
  SQLite, moins l'interdiction faite aux autres écrivains de valider entre la dernière vérification et le commit
  (fenêtre de quelques millisecondes, identique à celle de toute lecture suivie d'une écriture ; une nouvelle
  exécution du recalcul rend `rien_a_faire` ou recalcule).
- Unicité : les intentions, attestations et résultats portent des clés uniques (`intention_id`) : une double
  exécution simultanée donne `IntegrityError` -> `INTENTION_EN_CONFLIT`, sur les deux moteurs.
- Identité : (nom de la base, OID de la base, identifiant de système du serveur). Une capacité forgée contre une
  autre base ou un autre serveur ne passe pas la comparaison.

NON PROUVÉ (dit sans détour) : l'équivalence n'est pas démontrée pour un écrivain M3/M4/M5 qui valide EXACTEMENT
entre la dernière vérification et le commit ; aucune charge, aucun interblocage mesuré ; un pooler en mode
transaction (PgBouncer) n'est pas qualifié (le verrou et `pg_backend_pid()` supposent une connexion stable pour la
transaction)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event as sqla_event
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from .concurrence import cle_verrou, verrou_consultatif
from .moteur import _debuter_sqlite

NOM_VERROU_ECRITURE = "ecriture-instance-m4"


def engager(cnx: Any) -> None:
    """Ouvre l'exclusion d'écriture de la portée. SQLite : rien à faire (l'écouteur `begin` a déjà engagé `BEGIN
    IMMEDIATE`) ; PostgreSQL : prend le verrou consultatif d'instance (attend s'il est tenu par une autre portée)."""
    if cnx.dialect.name == "postgresql":
        verrou_consultatif(cnx, NOM_VERROU_ECRITURE)


def transaction_driver_ouverte(cnx: Any) -> bool:
    """La connexion du pilote est réellement dans une transaction (et pas seulement l'objet SQLAlchemy)."""
    pilote = cnx.connection.driver_connection
    if cnx.dialect.name == "sqlite":
        return bool(pilote.in_transaction)
    if cnx.dialect.name == "postgresql":
        from psycopg.pq import TransactionStatus

        return pilote.info.transaction_status == TransactionStatus.INTRANS
    return False


def exclusion_engagee(cnx: Any) -> bool:
    """L'exclusion d'écriture est engagée MAINTENANT pour cette transaction (vérifiée, jamais supposée)."""
    if cnx.dialect.name == "sqlite":
        return sqla_event.contains(cnx.engine, "begin", _debuter_sqlite) and transaction_driver_ouverte(cnx)
    if cnx.dialect.name == "postgresql":
        cle = cle_verrou(NOM_VERROU_ECRITURE)
        haut, bas = (cle >> 32) & 0xFFFFFFFF, cle & 0xFFFFFFFF
        return bool(cnx.execute(text(
            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted AND objsubid = 1 "
            "AND pid = pg_backend_pid() AND classid::bigint = :haut AND objid::bigint = :bas)"),
            {"haut": haut, "bas": bas}).scalar_one()) and transaction_driver_ouverte(cnx)
    return False


def identite_base(cnx: Any) -> tuple:
    """Identité stable de la base de la connexion. SQLite : (chemin réel, périphérique, inode) du fichier, refus si la
    base n'est pas un fichier durable. PostgreSQL : (« postgresql », nom, OID de la base, identifiant de système)."""
    import os
    import stat

    if cnx.dialect.name == "sqlite":
        lignes = cnx.exec_driver_sql("PRAGMA database_list").all()
        chemins = [ligne[2] for ligne in lignes if ligne[1] == "main"]
        if len(chemins) != 1 or not chemins[0]:
            raise ValueError("base SQLite non durable")
        chemin = os.path.realpath(chemins[0])
        info = os.stat(chemin, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("base SQLite non régulière")
        return chemin, info.st_dev, info.st_ino
    if cnx.dialect.name == "postgresql":
        nom, oid = cnx.execute(text(
            "SELECT current_database(), "
            "(SELECT oid::bigint FROM pg_database WHERE datname = current_database())")).one()
        if not nom or oid is None:
            raise ValueError("identité de base PostgreSQL indisponible")
        systeme = None
        try:
            with cnx.begin_nested():
                systeme = cnx.execute(select(text("system_identifier")).select_from(
                    text("pg_control_system()"))).scalar_one_or_none()
        except DBAPIError:
            systeme = None  # fonction non accordée à ce compte : le nom et l'OID de la base restent liés
        return "postgresql", nom, int(oid), None if systeme is None else int(systeme)
    raise ValueError("moteur non qualifié")
