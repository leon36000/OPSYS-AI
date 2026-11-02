"""Écritures concurrentes sur PostgreSQL : relecture après conflit et verrous consultatifs de transaction.

POURQUOI. Sous SQLite, `BEGIN IMMEDIATE` ne laisse qu'UN écrivain à la fois : un deuxième écrivain attend, puis LIT
l'état validé par le premier et rend le verdict que ses propres gardes rendent (`REVISION-PERIMEE`, `SOURCE-MODIFIEE`,
rejeu d'une saisie identique…). Sous PostgreSQL (READ COMMITTED), deux écrivains lisent le MÊME état, écrivent tous les
deux, et c'est la contrainte d'unicité (clé primaire d'un registre chaîné, révision d'un classement…) qui départage :
le perdant reçoit `IntegrityError` / `EcritureConcurrente` au lieu du verdict (défaut latent L1 du rapport de
qualification PostgreSQL). Les consoles de saisie ne traduisaient pas ce conflit.

CE QUE FAIT `relire_si_conflit`. Sur PostgreSQL seulement, elle exécute le corps dans un point de sauvegarde ; si une
violation d'unicité (SQLSTATE 23505), une panne de sérialisation (40001) ou un interblocage (40P01) en sort, le point de
sauvegarde est annulé et le corps est REJOUÉ : la relecture voit alors ce que le gagnant a validé (chaque instruction
d'un READ COMMITTED voit un instantané neuf) et rend exactement le verdict de SQLite. Un conflit qui persiste après
`essais` passages remonte tel quel (jamais avalé). Sur SQLite, le corps s'exécute directement : AUCUN changement.

Le corps doit être rejouable : ses seules écritures sont des écritures de base de données dans la transaction courante
(le point de sauvegarde les annule toutes). Aucune écriture hors base, aucun envoi, ne doit s'y trouver.

CE QUE FAIT `verrou_consultatif`. Un verrou de transaction NOMMÉ (`pg_advisory_xact_lock`), pour les chemins « lire puis
écrire » qui ne reposent sur aucune contrainte d'unicité (ex. l'audit d'une publication idempotente). Sur SQLite, rien :
`BEGIN IMMEDIATE` sérialise déjà tous les écrivains. Même exigence que la garde M2 : READ COMMITTED sans autocommit.
"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from .maillons import EcritureConcurrente
from .moteur import connexion_courante

T = TypeVar("T")
SQLSTATE_UNICITE = "23505"
SQLSTATE_SERIALISATION = "40001"
SQLSTATE_INTERBLOCAGE = "40P01"
_REJOUABLES = frozenset({SQLSTATE_UNICITE, SQLSTATE_SERIALISATION, SQLSTATE_INTERBLOCAGE})
ESSAIS_PAR_DEFAUT = 3


def sqlstate(exc: BaseException) -> str | None:
    """SQLSTATE du pilote derrière une erreur SQLAlchemy (psycopg 3), ou `None`."""
    origine = getattr(exc, "orig", None)
    code = getattr(origine, "sqlstate", None) or getattr(getattr(origine, "diag", None), "sqlstate", None)
    return code if isinstance(code, str) else None


def est_conflit_rejouable(exc: BaseException) -> bool:
    """Vrai pour la perte d'une course d'écriture (clé en double, sérialisation, interblocage) ; faux pour toute autre
    erreur d'intégrité (CHECK, clé étrangère, NOT NULL : un défaut, pas une course)."""
    if isinstance(exc, EcritureConcurrente):
        return True
    if isinstance(exc, DBAPIError):
        return sqlstate(exc) in _REJOUABLES
    return False


def relire_si_conflit(corps: Callable[[], T], *, essais: int = ESSAIS_PAR_DEFAUT) -> T:
    """Exécute `corps()` ; sur PostgreSQL, le rejoue après une course d'écriture perdue (voir le module)."""
    cnx = connexion_courante()
    if cnx is None or cnx.dialect.name != "postgresql" or essais <= 1:
        return corps()
    for passage in range(1, essais + 1):
        try:
            with cnx.begin_nested():
                return corps()
        except (DBAPIError, EcritureConcurrente) as exc:
            if passage >= essais or not est_conflit_rejouable(exc):
                raise
    raise AssertionError("inatteignable")  # pragma: no cover — la boucle rend ou lève


def cle_verrou(nom: str) -> int:
    """Clé 64 bits signée, stable, dérivée d'un nom (les verrous consultatifs de PostgreSQL sont numériques)."""
    return int.from_bytes(sha256(("opsys:verrou:" + nom).encode("utf-8")).digest()[:8], "big", signed=True)


def verrou_consultatif(cnx: Any, nom: str, *, partage: bool = False) -> None:
    """Prend le verrou de transaction `nom` (attend s'il est tenu) ; relâché au commit ou au rollback.

    PostgreSQL : exige READ COMMITTED sans autocommit (un instantané plus ancien que l'attente rendrait la relecture
    périmée). SQLite : aucun effet (un seul écrivain à la fois). Tout autre moteur : refus."""
    if connexion_courante() is not cnx:
        raise RuntimeError("le verrou consultatif exige la transaction courante")
    if cnx.dialect.name == "postgresql":
        if (cnx.get_isolation_level() != "READ COMMITTED"
                or getattr(cnx.connection.dbapi_connection, "autocommit", None) is not False):
            raise ValueError("le verrou consultatif exige READ COMMITTED sans autocommit")
        verrou = func.pg_advisory_xact_lock_shared if partage else func.pg_advisory_xact_lock
        cnx.execute(select(verrou(cle_verrou(nom))))
    elif cnx.dialect.name != "sqlite":
        raise ValueError("backend non qualifié pour le verrou consultatif")


def verrou_ecriture_console(cnx: Any) -> None:
    """Sérialise les écritures HUMAINES de la console entre elles (un seul écrivain de console à la fois, comme
    `BEGIN IMMEDIATE` sous SQLite). Pris par `outils.executer_atomique` et par les ports de console qui n'y passent pas,
    avant tout point de sauvegarde. Il ne coopère pas avec les écrivains d'agent (ils ne le prennent pas) : une
    course console / agent se résout par la contrainte d'unicité et `relire_si_conflit`."""
    verrou_consultatif(cnx, "console-ecriture")
