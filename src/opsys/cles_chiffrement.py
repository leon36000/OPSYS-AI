"""Coffre minimal de clés de chiffrement destructibles (PLAN T4.2, ADR-0009 §2 « tout dans la
même base »).

Un registre de département (`opsys.stockage.maillons`) est un journal append-only : sa table
(`registres_maillons`) n'offre qu'INSERT, jamais UPDATE ni DELETE, précisément pour que sa chaîne
de hash reste une preuve d'intégrité. Cette propriété est exactement ce qui rend une donnée
personnelle qu'on y écrit impossible à détruire directement (POLITIQUE-geolocalisation.md §5).

Ce module fait l'inverse : une table où chaque ligne PEUT être vraiment supprimée. Un consommateur
(ex. `m4_field_ops.pointage`, via `retention.chiffrer_position`) chiffre une donnée avant de
l'écrire dans un registre, avec une clé obtenue ici. `detruire` supprime logiquement la clé ;
`demander_effacement` conserve en plus une intention durable de nettoyage des fichiers SQLite
courants après commit. Seul son état `termine` atteste ce nettoyage borné : ni la suppression
logique, ni ce checkpoint ne certifient l'effacement des sauvegardes, snapshots ou supports OS.

`portee` namespace l'usage (ex. ``"m04-field-ops/gps"``) : deux départements, ou deux finalités du
même département, n'entrent jamais en collision même avec le même ``identifiant``. Une seule clé
par ``(portee, identifiant)`` en v1 : aucune rotation, aucun historique de clés — une nouvelle clé
après destruction (``obtenir_ou_creer`` rappelé pour la même portée/identifiant) démarre une
période de rétention neuve, ce qui est le comportement voulu (ex. un employé réembauché).

Bibliothèque standard uniquement (``secrets``), comme le reste du socle (``console.securite``).
"""

from __future__ import annotations

import math
import secrets
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from .stockage.moteur import inserer
from .stockage.schema import CLES_CHIFFREMENT, EFFACEMENTS_CLES

LONGUEUR_CLE_OCTETS = 32

__all__ = ["LONGUEUR_CLE_OCTETS", "obtenir_ou_creer", "lire", "detruire",
           "demander_effacement", "lire_effacement", "finaliser_effacement", "reprendre_effacements"]


def lire(cnx: Connection, portee: str, identifiant: str) -> bytes | None:
    """Clé actuelle, ou ``None`` si elle n'a jamais existé OU si elle a été détruite (crypto-
    shredding, PLAN T4.2) : les deux cas sont indistinguables ici, exactement l'effet recherché —
    une fois détruite, une clé n'est pas différente d'une clé qui n'a jamais existé."""
    valeur = cnx.execute(
        select(CLES_CHIFFREMENT.c.cle).where(
            (CLES_CHIFFREMENT.c.portee == portee) & (CLES_CHIFFREMENT.c.identifiant == identifiant)
        )
    ).scalar_one_or_none()
    return bytes.fromhex(valeur) if valeur is not None else None


def obtenir_ou_creer(cnx: Connection, portee: str, identifiant: str, cree_le: str) -> bytes:
    """Clé existante pour ``(portee, identifiant)``, ou une NOUVELLE clé aléatoire (32 octets,
    ``secrets.token_bytes`` — jamais dans un module pur de département, toujours ici, à la
    frontière impure) si aucune n'existe encore. Idempotent et sûr en écriture concurrente :
    l'INSERT porte ``ON CONFLICT DO NOTHING`` sur la clé primaire, puis une lecture RESTITUE
    toujours la ligne qui a gagné (la nôtre, ou celle d'un autre appelant simultané) — jamais deux
    clés différentes pour la même (portee, identifiant)."""
    nouvelle = secrets.token_bytes(LONGUEUR_CLE_OCTETS)
    insertion = inserer(cnx)(CLES_CHIFFREMENT).values(
        portee=portee, identifiant=identifiant, cle=nouvelle.hex(), cree_le=cree_le,
    )
    cnx.execute(insertion.on_conflict_do_nothing(index_elements=["portee", "identifiant"]))
    cle = lire(cnx, portee, identifiant)
    assert cle is not None, "vient d'être insérée ou existait déjà : ne peut pas être absente ici"
    return cle


def detruire(cnx: Connection, portee: str, identifiant: str) -> bool:
    """DELETE logique réel (PLAN T4.2), sans attestation de nettoyage des fichiers. ``True`` si une
    clé a effectivement été supprimée, ``False`` si elle n'existait déjà plus (purge rejouée sur un
    technicien déjà purgé, ou jamais géolocalisé : idempotent, jamais une erreur)."""
    resultat = cnx.execute(
        delete(CLES_CHIFFREMENT).where(
            (CLES_CHIFFREMENT.c.portee == portee) & (CLES_CHIFFREMENT.c.identifiant == identifiant)
        )
    )
    return resultat.rowcount > 0


def lire_effacement(cnx: Connection, purge_id: str) -> dict | None:
    """État courant distinct de la réponse d'approbation initiale, jamais réécrite."""
    ligne = cnx.execute(select(EFFACEMENTS_CLES).where(EFFACEMENTS_CLES.c.purge_id == purge_id)).mappings().first()
    return dict(ligne) if ligne is not None else None


def demander_effacement(
    cnx: Connection, portee: str, identifiant: str, cree_le: str, *,
    purge_id: str | None = None, demande_id: str | None = None,
) -> dict:
    """DELETE logique + file atomiques. L'appelant conserve son contrôle d'autorité humaine.

    Le retour reste un instantané en_attente ; consulter lire_effacement pour l'issue courante.
    Reprendre une opération existante ne détruit JAMAIS une clé recréée depuis.
    Une transaction externe à stockage.transaction conserve la file pour une reprise explicite.
    """
    from .etat import journaliser
    from .stockage.moteur import apres_validation, connexion_courante

    if not cnx.in_transaction():
        raise ValueError("effacement exige une transaction appelante")
    if any(not isinstance(x, str) or not x.strip() for x in (portee, identifiant, cree_le)):
        raise ValueError("cible et date d'effacement obligatoires")
    ident = uuid.uuid4().hex if purge_id is None else purge_id
    if not isinstance(ident, str) or uuid.UUID(ident).hex != ident:
        raise ValueError("purge_id doit être un UUID hex canonique")
    precedente = lire_effacement(cnx, ident)
    if precedente is not None:
        if (precedente["portee"], precedente["identifiant"], precedente["demande_id"], precedente["cree_le"]) != (
            portee, identifiant, demande_id, cree_le,
        ):
            raise ValueError("purge_id déjà lié à une autre opération")
        return precedente
    sqlite = cnx.dialect.name == "sqlite"
    if sqlite:
        # Le nettoyage du WAL seul ne nettoie pas les cellules supprimées de la base.
        cnx.exec_driver_sql("PRAGMA secure_delete=ON")
        if cnx.exec_driver_sql("PRAGMA secure_delete").scalar_one() != 1:
            raise ValueError("effacement SQLite indisponible avant suppression")
    logique = detruire(cnx, portee, identifiant)
    valeurs = {"purge_id": ident, "portee": portee, "identifiant": identifiant,
               "demande_id": demande_id, "cree_le": cree_le, "cle_detruite": logique,
               "etat_fichiers": "en_attente" if sqlite else "non_qualifie",
               "motif": None if sqlite else "backend_non_qualifie"}
    cnx.execute(inserer(cnx)(EFFACEMENTS_CLES).values(**valeurs))
    journaliser(cnx, "maintenance-coffre", "cles.effacement.demande", ident,
                {"demande_id": demande_id, "cle_detruite": logique, "etat_fichiers": valeurs["etat_fichiers"]})
    if sqlite and connexion_courante() is cnx:
        url = str(cnx.engine.url)
        apres_validation(lambda: finaliser_effacement(ident, url))
    return dict(valeurs)


@dataclass(frozen=True)
class BudgetNettoyage:
    """Bornes de maintenance courante ; le délai SQLite est coopératif, pas un SLA d'IO."""

    max_octets_base: int = 256 * 1024 * 1024
    reserve_octets_disque: int = 64 * 1024 * 1024
    max_secondes: float = 5.0

    def __post_init__(self) -> None:
        if type(self.max_octets_base) is not int or not 0 < self.max_octets_base <= 256 * 1024 * 1024:
            raise ValueError("budget de taille de maintenance invalide")
        if type(self.reserve_octets_disque) is not int or self.reserve_octets_disque < 64 * 1024 * 1024:
            raise ValueError("budget de réserve disque invalide")
        if (isinstance(self.max_secondes, bool) or not isinstance(self.max_secondes, (int, float))
                or not math.isfinite(self.max_secondes) or not 0 < self.max_secondes <= 5):
            raise ValueError("budget de durée de maintenance invalide")


def _nettoyer_fichiers_courants(engine, budget: BudgetNettoyage | None = None) -> tuple[bool, str | None]:
    """Réécrit les pages historiques puis purge le WAL, après commit seulement.

    Le VACUUM répond au résidu legacy dans la freelist : secure_delete au seul DELETE
    courant ne l'efface pas. Gardes avant travail et interruptions => état en attente.
    Sauvegardes, snapshots, blocs OS et PostgreSQL ne sont pas couverts.
    """
    if engine.dialect.name != "sqlite":
        return False, "backend_non_qualifie"
    limites = BudgetNettoyage() if budget is None else budget
    if not isinstance(limites, BudgetNettoyage):
        raise ValueError("budget de maintenance invalide")
    database = engine.url.database
    if not database or database == ":memory:" or engine.url.query:
        return False, "sqlite_sans_fichier"
    chemin = Path(database)
    if not chemin.is_absolute() or chemin.is_symlink() or not chemin.is_file():
        return False, "chemin_non_qualifie"
    debut = time.monotonic()
    deadline = debut + limites.max_secondes
    # Connexion neuve privée : aucun progress_handler d'un utilisateur du pool n'est écrasé.
    dbapi = sqlite3.connect(str(chemin), timeout=0.05, isolation_level=None)
    ancien_delai = None
    try:
        ancien_delai = dbapi.execute("PRAGMA busy_timeout").fetchone()[0]
        dbapi.execute("PRAGMA busy_timeout=50")
        if dbapi.in_transaction:
            return False, "transaction_active"
        if dbapi.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
            return False, "journal_non_qualifie"
        pages = dbapi.execute("PRAGMA page_count").fetchone()[0]
        taille_page = dbapi.execute("PRAGMA page_size").fetchone()[0]
        taille_base = max(chemin.stat().st_size, pages * taille_page)
        wal = Path(str(chemin) + "-wal")
        taille_wal = wal.stat().st_size if wal.exists() else 0
        if taille_base + taille_wal > limites.max_octets_base:
            return False, "budget_taille"
        besoin = 2 * taille_base + taille_wal + limites.reserve_octets_disque
        if shutil.disk_usage(chemin.parent).free < besoin:
            return False, "budget_espace"
        if time.monotonic() >= deadline:
            return False, "budget_duree"
        dbapi.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        avant = tuple(dbapi.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
        if avant[0] != 0:
            return False, "wal_occupe"
        if avant != (0, 0, 0):
            return False, "checkpoint_incomplet"
        dbapi.execute("PRAGMA secure_delete=ON")
        if time.monotonic() >= deadline:
            return False, "budget_duree"
        dbapi.execute("VACUUM")
        if time.monotonic() >= deadline:
            return False, "budget_duree"
        apres = tuple(dbapi.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
        if apres[0] != 0:
            return False, "wal_occupe"
        if apres != (0, 0, 0):
            return False, "checkpoint_incomplet"
        return True, None
    except sqlite3.Error as exc:
        code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
        if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            return False, "wal_occupe"
        if code == sqlite3.SQLITE_INTERRUPT:
            return False, "budget_duree"
        if code == sqlite3.SQLITE_FULL:
            return False, "budget_espace"
        return False, "maintenance_indisponible"
    finally:
        # Handler possédé par cette seule connexion et retiré même en cas d'interruption.
        dbapi.set_progress_handler(None, 0)
        try:
            if ancien_delai is not None:
                dbapi.execute(f"PRAGMA busy_timeout={int(ancien_delai)}")
        finally:
            dbapi.close()


def finaliser_effacement(
    purge_id: str, url: str | None = None, *, budget: BudgetNettoyage | None = None,
) -> dict:
    """Reprise bornée sans DELETE. Aucun succès de stockage avant commit et checkpoint acquis."""
    from .etat import journaliser
    from .stockage.moteur import connexion_courante, moteur

    if connexion_courante() is not None:
        raise RuntimeError("maintenance interdite dans une transaction métier")
    engine = moteur(url)
    with engine.begin() as cnx:
        etat = lire_effacement(cnx, purge_id)
    if etat is None:
        raise KeyError("opération d'effacement inconnue")
    if etat["etat_fichiers"] != "en_attente":
        return etat
    try:
        termine, motif = _nettoyer_fichiers_courants(engine, budget)
    except (SQLAlchemyError, sqlite3.Error, OSError):
        termine, motif = False, "maintenance_indisponible"
    cible = "termine" if termine else "en_attente"
    with engine.begin() as cnx:
        resultat = cnx.execute(update(EFFACEMENTS_CLES).where(
            EFFACEMENTS_CLES.c.purge_id == purge_id, EFFACEMENTS_CLES.c.etat_fichiers == "en_attente",
        ).values(etat_fichiers=cible, motif=motif))
        if resultat.rowcount == 1 and (termine or motif != etat["motif"]):
            journaliser(cnx, "maintenance-coffre", "cles.effacement." + ("termine" if termine else "en_attente"),
                        purge_id, {"etat_fichiers": cible, "motif": motif})
        courant = lire_effacement(cnx, purge_id)
    assert courant is not None
    return courant


def reprendre_effacements(
    url: str | None = None, *, limite: int = 4, budget: BudgetNettoyage | None = None,
) -> list[dict]:
    """Drain explicite borné après redémarrage ; aucune autorisation de nouvelle suppression."""
    from .stockage.moteur import connexion_courante, moteur

    if connexion_courante() is not None:
        raise RuntimeError("reprise interdite dans une transaction métier")
    if not isinstance(limite, int) or isinstance(limite, bool) or not 1 <= limite <= 4:
        raise ValueError("limite de reprise entre 1 et 4")
    with moteur(url).begin() as cnx:
        identifiants = list(cnx.execute(select(EFFACEMENTS_CLES.c.purge_id).where(
            EFFACEMENTS_CLES.c.etat_fichiers == "en_attente",
        ).order_by(EFFACEMENTS_CLES.c.cree_le, EFFACEMENTS_CLES.c.purge_id).limit(limite)).scalars())
    return [finaliser_effacement(ident, url, budget=budget) for ident in identifiants]
