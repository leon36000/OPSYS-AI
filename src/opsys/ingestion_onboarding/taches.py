"""Table de tâches DURABLE de l'ingestion d'onboarding : phase SQLite, interface prête pour DBOS sur PostgreSQL.

Un LOT (un dépôt) porte des DOCUMENTS ; chaque document porte SEPT tâches, une par étape (`ETAPES`), créées d'un coup
au dépôt et identifiées par leur clé d'idempotence `(document, étape)` (contrainte unique) : une reprise ne crée jamais
une seconde tâche. Les états :

    EN_ATTENTE ──réserver──► BAIL ──terminer──► TERMINEE
         ▲                    │  └──échouer (temporaire)──► ECHEC_REPRENABLE ──(délai écoulé) réserver──► BAIL …
         │                    │  └──échouer (définitif) / tentatives épuisées──► FILE_MORTE
         └── bail expiré : la tâche redevient réservable (même ligne, tentative suivante)
    toute étape suivante d'une étape refusée, sautée ou en file morte ──► SAUTEE

- BAIL : réserver une tâche pose un porteur et une échéance (`bail_expire`, en secondes epoch de l'horloge injectée).
  Un travail interrompu (processus tué, exception) laisse la tâche en BAIL ; à l'échéance, elle redevient réservable.
- Exactement une fois : `terminer` et `echouer` sont des CAS sur (statut BAIL, porteur, révision). Le porteur d'un bail
  repris par un autre ne peut plus rien écrire ; ses effets (brouillons) sont écrits dans la MÊME transaction que le
  CAS, donc annulés avec lui. Les étapes sont des fonctions déterministes de leurs entrées : refaire une étape
  interrompue produit le même résultat.
- Ordre : une tâche n'est réservable que si l'étape précédente du même document est TERMINEE.
- Quotas : lots en cours, documents et octets par lot et au total, tentatives par tâche (`QUOTAS`).

`PortTaches` est le contrat que le service utilise ; `TachesSQLite` l'implémente sur SQLAlchemy Core (SQLite, et la
même requête tourne sur PostgreSQL). Un adaptateur DBOS Transact remplacera `TachesSQLite` à la bascule PostgreSQL :
l'identifiant de workflow DBOS sera la clé `(document, étape)`, le bail son verrou d'exécution ; il n'est PAS
implémenté ici (docs/architecture/INGESTION-ONBOARDING.md, « Ce qui n'est pas fait »).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import Connection, and_, func, insert, or_, select, update

from ..stockage.schema import (
    INGESTION_BROUILLONS,
    INGESTION_DOCUMENTS,
    INGESTION_JOURNAL,
    INGESTION_LOTS,
    INGESTION_TACHES,
)

ETAPES: tuple[str, ...] = ("empreinte", "type", "texte", "classement", "extraction", "validation", "proposition")
RANG = {etape: rang for rang, etape in enumerate(ETAPES, 1)}
STATUTS_ACTIFS = ("EN_ATTENTE", "BAIL", "ECHEC_REPRENABLE")
QUOTAS: dict[str, int] = {
    "lots_en_cours": 8,
    "documents_par_lot": 500,
    "octets_par_lot": 64 * 1024 * 1024,
    "documents_total": 20_000,
    "octets_total": 2 * 1024 * 1024 * 1024,
    "tentatives": 3,
    "bail_secondes": 120,
    "delai_reprise_secondes": 30,
}


def instant_texte() -> str:
    return datetime.now(UTC).isoformat()


def nouvel_identifiant() -> str:
    return uuid.uuid4().hex


class PortTaches(Protocol):
    """Contrat de la file durable (SQLite aujourd'hui, DBOS sur PostgreSQL ensuite)."""

    def creer_lot(self, ligne: Mapping[str, Any]) -> None: ...
    def lot(self, lot_id: str) -> dict[str, Any] | None: ...
    def lot_par_mutation(self, acteur: str, mutation_id: str) -> dict[str, Any] | None: ...
    def lots_en_cours(self) -> int: ...
    def totaux_stockes(self) -> tuple[int, int]: ...
    def original(self, sha256: str) -> dict[str, Any] | None: ...
    def ajouter_document(self, ligne: Mapping[str, Any]) -> None: ...
    def planifier(self, lot_id: str, document_id: str) -> None: ...
    def reserver(self, lot_id: str, porteur: str) -> dict[str, Any] | None: ...
    def terminer(self, tache: Mapping[str, Any], porteur: str, *, nonce: str | None, chiffre: str | None,
                 empreinte: str | None, code: str | None = None) -> bool: ...
    def echouer(self, tache: Mapping[str, Any], porteur: str, code: str, *, reprenable: bool) -> str | None: ...
    def sauter_suivantes(self, document_id: str, apres_rang: int, code: str) -> int: ...
    def resultat(self, document_id: str, etape: str) -> dict[str, Any] | None: ...
    def journaliser(self, lot_id: str, acteur: str, evenement: str, *, document_id: str | None = None,
                    tache_id: str | None = None, code: str | None = None,
                    details: Mapping[str, Any] | None = None) -> None: ...
    def rafraichir_lot(self, lot_id: str) -> str: ...


class TachesSQLite:
    """`PortTaches` sur la connexion de la transaction courante. `maintenant` : horloge en secondes epoch (injectée
    par les tests pour simuler l'expiration d'un bail sans attendre)."""

    def __init__(self, cnx: Connection, *, maintenant: Callable[[], int]) -> None:
        self.cnx = cnx
        self.maintenant = maintenant

    # -- lots et documents --------------------------------------------------------------------------------------
    def creer_lot(self, ligne: Mapping[str, Any]) -> None:
        self.cnx.execute(insert(INGESTION_LOTS).values(**ligne))

    def lot(self, lot_id: str) -> dict[str, Any] | None:
        ligne = self.cnx.execute(select(INGESTION_LOTS).where(INGESTION_LOTS.c.lot_id == lot_id)).mappings().first()
        return dict(ligne) if ligne is not None else None

    def lot_par_mutation(self, acteur: str, mutation_id: str) -> dict[str, Any] | None:
        ligne = self.cnx.execute(select(INGESTION_LOTS).where(
            (INGESTION_LOTS.c.acteur == acteur) & (INGESTION_LOTS.c.mutation_id == mutation_id))).mappings().first()
        return dict(ligne) if ligne is not None else None

    def lots_en_cours(self) -> int:
        return self.cnx.execute(select(func.count()).select_from(INGESTION_LOTS).where(
            INGESTION_LOTS.c.statut == "EN_COURS")).scalar_one()

    def totaux_stockes(self) -> tuple[int, int]:
        nombre, octets = self.cnx.execute(select(func.count(), func.coalesce(func.sum(INGESTION_DOCUMENTS.c.taille), 0))
                                          .where(INGESTION_DOCUMENTS.c.chiffre.is_not(None))).one()
        return int(nombre), int(octets)

    def original(self, sha256: str) -> dict[str, Any] | None:
        ligne = self.cnx.execute(select(INGESTION_DOCUMENTS).where(
            (INGESTION_DOCUMENTS.c.sha256 == sha256) & INGESTION_DOCUMENTS.c.chiffre.is_not(None))).mappings().first()
        return dict(ligne) if ligne is not None else None

    def ajouter_document(self, ligne: Mapping[str, Any]) -> None:
        self.cnx.execute(insert(INGESTION_DOCUMENTS).values(**ligne))

    def planifier(self, lot_id: str, document_id: str) -> None:
        quand = instant_texte()
        self.cnx.execute(insert(INGESTION_TACHES), [
            {"tache_id": nouvel_identifiant(), "document_id": document_id, "lot_id": lot_id, "etape": etape,
             "rang_etape": RANG[etape], "statut": "EN_ATTENTE", "tentatives": 0, "porteur": None, "bail_expire": None,
             "disponible_des": 0, "code": None, "nonce": None, "chiffre": None, "empreinte_resultat": None,
             "revision": 1, "cree_le": quand, "modifie_le": quand}
            for etape in ETAPES
        ])

    def maj_document(self, document_id: str, **valeurs: Any) -> None:
        self.cnx.execute(update(INGESTION_DOCUMENTS).where(INGESTION_DOCUMENTS.c.document_id == document_id)
                         .values(**valeurs, modifie_le=instant_texte()))

    def document(self, document_id: str) -> dict[str, Any] | None:
        ligne = self.cnx.execute(select(INGESTION_DOCUMENTS).where(
            INGESTION_DOCUMENTS.c.document_id == document_id)).mappings().first()
        return dict(ligne) if ligne is not None else None

    # -- tâches ---------------------------------------------------------------------------------------------------
    def _candidates(self, lot_id: str, maintenant: int) -> list[dict[str, Any]]:
        t = INGESTION_TACHES
        reservable = or_(
            t.c.statut == "EN_ATTENTE",
            and_(t.c.statut == "ECHEC_REPRENABLE", t.c.disponible_des <= maintenant),
            and_(t.c.statut == "BAIL", t.c.bail_expire <= maintenant),
        )
        precedente = INGESTION_TACHES.alias("precedente")
        prete = or_(t.c.rang_etape == 1, select(precedente.c.statut).where(
            (precedente.c.document_id == t.c.document_id) & (precedente.c.rang_etape == t.c.rang_etape - 1)
        ).scalar_subquery() == "TERMINEE")
        requete = (select(t, INGESTION_DOCUMENTS.c.rang.label("rang_document"))
                   .join(INGESTION_DOCUMENTS, INGESTION_DOCUMENTS.c.document_id == t.c.document_id)
                   .where((t.c.lot_id == lot_id) & reservable & prete)
                   .order_by(INGESTION_DOCUMENTS.c.rang, t.c.rang_etape).limit(8))
        return [dict(ligne) for ligne in self.cnx.execute(requete).mappings()]

    def reserver(self, lot_id: str, porteur: str) -> dict[str, Any] | None:
        """La prochaine tâche réservable du lot, mise en BAIL pour `porteur` (tentative + 1) ; `None` s'il n'y en a pas
        (tout est terminé, ou ce qui reste attend un bail actif ou un délai de reprise). Une tâche dont les tentatives
        sont épuisées passe en FILE_MORTE au lieu d'être réservée."""
        maintenant = self.maintenant()
        for _ in range(64):
            candidates = self._candidates(lot_id, maintenant)
            if not candidates:
                return None
            tache = candidates[0]
            if tache["tentatives"] >= QUOTAS["tentatives"]:
                self._file_morte(tache, porteur, "REJ-ING-FILE-MORTE")
                continue
            resultat = self.cnx.execute(update(INGESTION_TACHES).where(
                (INGESTION_TACHES.c.tache_id == tache["tache_id"])
                & (INGESTION_TACHES.c.revision == tache["revision"])
            ).values(statut="BAIL", porteur=porteur, bail_expire=maintenant + QUOTAS["bail_secondes"],
                     tentatives=tache["tentatives"] + 1, revision=tache["revision"] + 1, modifie_le=instant_texte()))
            if resultat.rowcount != 1:
                continue
            repris = tache["statut"] == "BAIL"
            self.journaliser(tache["lot_id"], porteur, "tache.reprise_bail_expire" if repris else "tache.reservee",
                             document_id=tache["document_id"], tache_id=tache["tache_id"],
                             details={"etape": tache["etape"], "tentative": tache["tentatives"] + 1})
            if tache["etape"] == ETAPES[0]:
                self.maj_document(tache["document_id"], statut="EN_COURS")
            return {**tache, "statut": "BAIL", "porteur": porteur, "tentatives": tache["tentatives"] + 1,
                    "revision": tache["revision"] + 1}
        return None

    def _cas(self, tache: Mapping[str, Any], porteur: str):
        return ((INGESTION_TACHES.c.tache_id == tache["tache_id"]) & (INGESTION_TACHES.c.statut == "BAIL")
                & (INGESTION_TACHES.c.porteur == porteur) & (INGESTION_TACHES.c.revision == tache["revision"]))

    def terminer(self, tache: Mapping[str, Any], porteur: str, *, nonce: str | None, chiffre: str | None,
                 empreinte: str | None, code: str | None = None) -> bool:
        """CAS : la tâche tenue par `porteur` à cette révision devient TERMINEE avec son résultat chiffré. `code` : la
        tâche a abouti à un VERDICT sur le document (refus, classe non peuplée…) ; l'appelant saute alors la suite."""
        resultat = self.cnx.execute(update(INGESTION_TACHES).where(self._cas(tache, porteur)).values(
            statut="TERMINEE", porteur=None, bail_expire=None, nonce=nonce, chiffre=chiffre,
            empreinte_resultat=empreinte, code=code, revision=tache["revision"] + 1, modifie_le=instant_texte()))
        if resultat.rowcount != 1:
            return False
        self.journaliser(tache["lot_id"], porteur, "tache.terminee", document_id=tache["document_id"],
                         tache_id=tache["tache_id"], code=code, details={"etape": tache["etape"]})
        return True

    def _file_morte(self, tache: Mapping[str, Any], acteur: str, code: str) -> None:
        self.cnx.execute(update(INGESTION_TACHES).where(INGESTION_TACHES.c.tache_id == tache["tache_id"]).values(
            statut="FILE_MORTE", porteur=None, bail_expire=None, code=code, revision=tache["revision"] + 1,
            modifie_le=instant_texte()))
        self.sauter_suivantes(tache["document_id"], tache["rang_etape"], code)
        self.maj_document(tache["document_id"], statut="NON_TRAITE", code=code)
        self.journaliser(tache["lot_id"], acteur, "tache.file_morte", document_id=tache["document_id"],
                         tache_id=tache["tache_id"], code=code, details={"etape": tache["etape"],
                                                                          "tentatives": tache["tentatives"]})

    def echouer(self, tache: Mapping[str, Any], porteur: str, code: str, *, reprenable: bool) -> str | None:
        """Échec d'une tâche tenue : `ECHEC_REPRENABLE` (délai croissant avant la tentative suivante) si l'échec est
        temporaire et qu'il reste des tentatives, `FILE_MORTE` sinon. `None` si le bail n'est plus le sien."""
        if not self.cnx.execute(select(INGESTION_TACHES.c.tache_id).where(self._cas(tache, porteur))).first():
            return None
        if reprenable and tache["tentatives"] < QUOTAS["tentatives"]:
            delai = QUOTAS["delai_reprise_secondes"] * 2 ** (tache["tentatives"] - 1)
            self.cnx.execute(update(INGESTION_TACHES).where(self._cas(tache, porteur)).values(
                statut="ECHEC_REPRENABLE", porteur=None, bail_expire=None, code=code,
                disponible_des=self.maintenant() + delai, revision=tache["revision"] + 1, modifie_le=instant_texte()))
            self.journaliser(tache["lot_id"], porteur, "tache.echec_reprenable", document_id=tache["document_id"],
                             tache_id=tache["tache_id"], code=code, details={"etape": tache["etape"],
                                                                              "delai_s": delai})
            return "ECHEC_REPRENABLE"
        self._file_morte(tache, porteur, code)
        return "FILE_MORTE"

    def sauter_suivantes(self, document_id: str, apres_rang: int, code: str) -> int:
        resultat = self.cnx.execute(update(INGESTION_TACHES).where(
            (INGESTION_TACHES.c.document_id == document_id) & (INGESTION_TACHES.c.rang_etape > apres_rang)
            & INGESTION_TACHES.c.statut.in_(STATUTS_ACTIFS)
        ).values(statut="SAUTEE", porteur=None, bail_expire=None, code=code,
                 revision=INGESTION_TACHES.c.revision + 1, modifie_le=instant_texte()))
        return resultat.rowcount

    def resultat(self, document_id: str, etape: str) -> dict[str, Any] | None:
        ligne = self.cnx.execute(select(INGESTION_TACHES).where(
            (INGESTION_TACHES.c.document_id == document_id) & (INGESTION_TACHES.c.etape == etape))).mappings().first()
        return dict(ligne) if ligne is not None else None

    # -- journal et lot -------------------------------------------------------------------------------------------
    def journaliser(self, lot_id: str, acteur: str, evenement: str, *, document_id: str | None = None,
                    tache_id: str | None = None, code: str | None = None,
                    details: Mapping[str, Any] | None = None) -> None:
        self.cnx.execute(insert(INGESTION_JOURNAL).values(
            quand=instant_texte(), lot_id=lot_id, document_id=document_id, tache_id=tache_id, acteur=acteur[:200],
            evenement=evenement, code=code, details=json.dumps(dict(details or {}), ensure_ascii=False,
                                                               sort_keys=True)))

    def compter(self, lot_id: str) -> dict[str, dict[str, int]]:
        taches = dict(self.cnx.execute(select(INGESTION_TACHES.c.statut, func.count()).where(
            INGESTION_TACHES.c.lot_id == lot_id).group_by(INGESTION_TACHES.c.statut)).all())
        documents = dict(self.cnx.execute(select(INGESTION_DOCUMENTS.c.statut, func.count()).where(
            INGESTION_DOCUMENTS.c.lot_id == lot_id).group_by(INGESTION_DOCUMENTS.c.statut)).all())
        brouillons = dict(self.cnx.execute(select(INGESTION_BROUILLONS.c.statut, func.count()).where(
            INGESTION_BROUILLONS.c.lot_id == lot_id).group_by(INGESTION_BROUILLONS.c.statut)).all())
        return {"taches": taches, "documents": documents, "brouillons": brouillons}

    def rafraichir_lot(self, lot_id: str) -> str:
        restantes = self.cnx.execute(select(func.count()).select_from(INGESTION_TACHES).where(
            (INGESTION_TACHES.c.lot_id == lot_id) & INGESTION_TACHES.c.statut.in_(STATUTS_ACTIFS))).scalar_one()
        statut = "EN_COURS" if restantes else "TERMINE"
        self.cnx.execute(update(INGESTION_LOTS).where(INGESTION_LOTS.c.lot_id == lot_id).values(
            statut=statut, modifie_le=instant_texte()))
        return statut


__all__ = ["ETAPES", "PortTaches", "QUOTAS", "RANG", "TachesSQLite", "instant_texte", "nouvel_identifiant"]
