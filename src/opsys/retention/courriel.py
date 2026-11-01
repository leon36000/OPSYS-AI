"""Rétention Loi 25 du courriel d'ingestion : à l'échéance déclarée du compte, le CONTENU devient illisible, les
empreintes restent.

Ce que la synchronisation conserve (docs/architecture/CONNECTEURS-COURRIEL.md §10) et ce que cette purge en fait :

- originaux et résultats d'étapes scellés (`ingestion_documents`, `ingestion_taches`) : `nonce` et `chiffre` à NULL ;
- brouillons de contacts ou de factures non décidés (`ingestion_brouillons`) : contenu vidé, statut `ECARTE` avec la
  décision `retention_loi25` ; les brouillons `VALIDE` sont des données d'affaires déjà confirmées : intacts ;
- brouillons de réponse sortants (`courriel_brouillons`) : contenu vidé, jamais un brouillon en cours d'approbation ou
  d'envoi ;
- archive déposée en clair (`<OPSYS_HOME>/imports/onboarding/courriel-*.zip`) : écrasée puis retirée ;
- lien message -> lot (`courriel_messages.lot_id`) : NULL ; `cle_message` et `empreinte` (hachages) restent : sans eux,
  un nouvel amorçage réingérerait le courriel.

Aucune de ces tables n'est un registre chaîné : rien n'est supprimé d'une chaîne, et le journal du compte
(`courriel_journal`, append-only, sans contenu) consigne la purge. Un lot n'est purgé que lorsque TOUS les messages qui
le référencent sont échus (selon la rétention de LEUR compte). Un document en double (`DOUBLON`) d'un original purgé
n'a pas de copie : il n'y a rien de plus à effacer.

Limites dites : le fichier SQLite peut conserver des pages libérées (`PRAGMA secure_delete=ON` les écrase à la
suppression, mais ce module ne lance pas de `VACUUM` ni ne touche aux sauvegardes déjà faites) ; les données déjà
transmises à M1 (registre chaîné) ont leur propre rétention (`retention.cles`, adresses) ; un brouillon `VALIDE` et les
fiches du CRM qui en découlent sont des dossiers d'affaires, hors de cette purge.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, select, update

from ..courriel_connecteurs import comptes
from ..stockage.schema import (
    COURRIEL_BROUILLONS,
    COURRIEL_COMPTES,
    COURRIEL_MESSAGES,
    INGESTION_BROUILLONS,
    INGESTION_DOCUMENTS,
    INGESTION_LOTS,
    INGESTION_TACHES,
)
from . import echeances

DECISION = json.dumps({"motif": "retention_loi25", "automatique": True}, sort_keys=True)
CODE = "PURGE_RETENTION"
ETATS_SORTANTS_PURGEABLES = ("BROUILLON", "ENVOYE", "ECHEC", "INCERTAIN", "REFUSE")
_ARCHIVE = re.compile(r"^courriel-[0-9a-f]{40}\.zip$")
PLAFOND_PAR_CATEGORIE = 1000


def _coupure(maintenant: int, jours: int) -> str:
    return echeances.instant(maintenant - jours * 86400)


def plan(cnx: Connection, maintenant: int) -> dict[str, Any]:
    """Ce qu'une purge effacerait MAINTENANT : lots échus (avec leur compte), brouillons sortants échus, archives."""
    retention = {c: r for c, r in cnx.execute(select(COURRIEL_COMPTES.c.compte_id, COURRIEL_COMPTES.c.retention_jours))}
    coupures = {c: _coupure(maintenant, r) for c, r in retention.items()}
    par_lot: dict[str, list[tuple[str, str]]] = {}
    for compte_id, lot_id, vu_le in cnx.execute(select(
            COURRIEL_MESSAGES.c.compte_id, COURRIEL_MESSAGES.c.lot_id, COURRIEL_MESSAGES.c.vu_le).where(
            COURRIEL_MESSAGES.c.lot_id.is_not(None))):
        par_lot.setdefault(lot_id, []).append((compte_id, vu_le))
    lots = {lot: sorted({c for c, _ in msgs}) for lot, msgs in par_lot.items()
            if all(vu < coupures[c] for c, vu in msgs)}
    archives = {}
    for lot_id in lots:
        nom = cnx.execute(select(INGESTION_LOTS.c.nom_source).where(INGESTION_LOTS.c.lot_id == lot_id)).scalar()
        if nom and _ARCHIVE.fullmatch(nom):
            archives.setdefault(nom, []).append(lot_id)
    sortants = [(brouillon_id, compte_id) for brouillon_id, compte_id, modifie in cnx.execute(select(
        COURRIEL_BROUILLONS.c.brouillon_id, COURRIEL_BROUILLONS.c.compte_id, COURRIEL_BROUILLONS.c.modifie_le).where(
        COURRIEL_BROUILLONS.c.statut.in_(ETATS_SORTANTS_PURGEABLES), COURRIEL_BROUILLONS.c.chiffre != "")
        .order_by(COURRIEL_BROUILLONS.c.modifie_le, COURRIEL_BROUILLONS.c.brouillon_id))
        if modifie < coupures[compte_id]]
    return {"lots": dict(sorted(lots.items())), "archives": dict(sorted(archives.items())),
            "sortants": sorted(sortants)}


def apercu(cnx: Connection, maintenant: int) -> list[dict[str, Any]]:
    """Les éléments à purger sous forme de références (identifiants, jamais un contenu) : aperçu à blanc."""
    p = plan(cnx, maintenant)
    elements: list[dict[str, Any]] = []
    for lot, comptes_ in list(p["lots"].items())[:PLAFOND_PAR_CATEGORIE]:
        elements.append({"categorie": "lot_ingestion", "ref": lot, "comptes": comptes_})
    for nom in list(p["archives"])[:PLAFOND_PAR_CATEGORIE]:
        elements.append({"categorie": "archive_deposee", "ref": nom})
    for brouillon_id, compte_id in p["sortants"][:PLAFOND_PAR_CATEGORIE]:
        elements.append({"categorie": "brouillon_sortant", "ref": brouillon_id, "comptes": [compte_id]})
    return elements


def _ecraser_et_retirer(chemin: Path) -> bool:
    if not chemin.is_file() or chemin.is_symlink():
        return False
    taille = chemin.stat().st_size
    with chemin.open("r+b") as flux:
        flux.write(b"\0" * taille)
        flux.flush()
        os.fsync(flux.fileno())
    chemin.unlink()
    return True


def _autres_lots_actifs(cnx: Connection, nom: str, exclus: set[str]) -> bool:
    return cnx.execute(select(INGESTION_LOTS.c.lot_id).where(
        INGESTION_LOTS.c.nom_source == nom, INGESTION_LOTS.c.lot_id.not_in(exclus)).limit(1)).first() is not None


def purger(cnx: Connection, maintenant: int, depot: Path, acteur: str, *, limite: int = 200) -> dict[str, int]:
    """Applique la purge (au plus `limite` lots et `limite` brouillons par appel : reprise au passage suivant).
    Idempotent : un lot déjà purgé n'a plus de lien `lot_id` et n'est plus planifié."""
    if cnx.dialect.name == "sqlite":
        cnx.exec_driver_sql("PRAGMA secure_delete=ON")
    p = plan(cnx, maintenant)
    lots = dict(list(p["lots"].items())[:limite])
    quand = comptes.instant()
    resume = dict.fromkeys(("documents", "taches", "brouillons", "archives", "lots", "sortants"), 0)
    par_compte: dict[str, dict[str, int]] = {}
    for lot_id, comptes_ in lots.items():
        r = cnx.execute(update(INGESTION_DOCUMENTS).where(
            INGESTION_DOCUMENTS.c.lot_id == lot_id, INGESTION_DOCUMENTS.c.chiffre.is_not(None)).values(
            nonce=None, chiffre=None, code=CODE, modifie_le=quand))
        resume["documents"] += r.rowcount
        cnx.execute(update(INGESTION_TACHES).where(
            INGESTION_TACHES.c.lot_id == lot_id,
            INGESTION_TACHES.c.statut.in_(("EN_ATTENTE", "BAIL", "ECHEC_REPRENABLE"))).values(
            statut="SAUTEE", porteur=None, bail_expire=None, code=CODE, revision=INGESTION_TACHES.c.revision + 1,
            modifie_le=quand))
        r = cnx.execute(update(INGESTION_TACHES).where(
            INGESTION_TACHES.c.lot_id == lot_id, INGESTION_TACHES.c.chiffre.is_not(None)).values(
            nonce=None, chiffre=None, modifie_le=quand))
        resume["taches"] += r.rowcount
        cnx.execute(update(INGESTION_BROUILLONS).where(
            INGESTION_BROUILLONS.c.lot_id == lot_id, INGESTION_BROUILLONS.c.statut.in_(("PRET", "A_VERIFIER"))).values(
            statut="ECARTE", decision=DECISION, revision=INGESTION_BROUILLONS.c.revision + 1, modifie_le=quand))
        r = cnx.execute(update(INGESTION_BROUILLONS).where(
            INGESTION_BROUILLONS.c.lot_id == lot_id, INGESTION_BROUILLONS.c.statut != "VALIDE",
            INGESTION_BROUILLONS.c.chiffre != "").values(nonce="", chiffre="", modifie_le=quand))
        resume["brouillons"] += r.rowcount
        cnx.execute(update(COURRIEL_MESSAGES).where(COURRIEL_MESSAGES.c.lot_id == lot_id).values(lot_id=None))
        resume["lots"] += 1
        for compte_id in comptes_:
            par_compte.setdefault(compte_id, dict.fromkeys(("purges", "documents", "archives"), 0))["purges"] += 1
    for nom, lots_de_l_archive in p["archives"].items():
        if not set(lots_de_l_archive) <= set(lots) or _autres_lots_actifs(cnx, nom, set(lots_de_l_archive)):
            continue
        if _ecraser_et_retirer(depot / nom):
            resume["archives"] += 1
            for compte_id in {c for lot in lots_de_l_archive for c in lots[lot]}:
                par_compte.setdefault(compte_id, dict.fromkeys(("purges", "documents", "archives"), 0))["archives"] += 1
    for brouillon_id, compte_id in p["sortants"][:limite]:
        r = cnx.execute(update(COURRIEL_BROUILLONS).where(
            COURRIEL_BROUILLONS.c.brouillon_id == brouillon_id, COURRIEL_BROUILLONS.c.chiffre != "",
            COURRIEL_BROUILLONS.c.statut.in_(ETATS_SORTANTS_PURGEABLES)).values(nonce="", chiffre=""))
        resume["sortants"] += r.rowcount
        par_compte.setdefault(compte_id, dict.fromkeys(("purges", "documents", "archives"), 0))["purges"] += r.rowcount
    for compte_id, compteurs in sorted(par_compte.items()):
        comptes.journaliser(cnx, compte_id, "retention.purge", acteur, details=compteurs)
    return resume
