"""Réconciliateur du coût certifié M4 → M5 (E5 mode ombre, E8 mode actif ; CONCEPTION-ROUTAGE-COUT-CERTIFIE §3 opt. 3).

Boucle PILOTÉE PAR L'ÉTAT, appelée à la fin de chaque `repartiteur.repartir` (donc juste après la livraison qui
rend un certifié périmé, `REJ-COUT-CERTIFIE-A-RECALCULER`, et périodiquement par la boucle du serveur) :

1. lecture seule : les deux politiques `m4.recalculer_v3` et `m4.verifier_v3` doivent être actives (octroi par un
   admin, D1) ; sinon rien n'est lu au-delà ;
2. M5 dit quels devis ont un coût certifié `perime_recalcul_en_attente` ou `inconnu`
   (`m5_financecore.port_service_m4.candidats_cout_certifie`), dans un ordre déterministe, les périmés d'abord ;
3. pour chaque candidat (au plus `limite` par appel), dans SA PROPRE transaction (BEGIN IMMEDIATE : deux
   exécutions concurrentes sont sérialisées), l'état est RELU sous le verrou ; s'il est à jour, rien ; sinon le
   moteur qualifié (`moteur_recalcul_m4.recalculer`) est appelé par l'acteur système `opsys-systeme` (D2) avec une
   intention DÉTERMINISTE (même état → même intention → `deja_executee` / `rien_a_faire`, jamais deux écritures).

Modes (`OPSYS_COUT_CERTIFIE_RECONCILIATEUR`) :

- `ombre` (défaut, E5) : le moteur s'exécute réellement puis la transaction est ANNULÉE ; seul le journal Python
  dit « aurait publié / refuserait pour tel code » : l'empreinte des tables est identique avant et après ;
- `actif` (E8) : la publication est conservée et chaque exécution est journalisée (`cout_certifie_reconciliations`,
  un refus identique n'est journalisé qu'une fois) ;
- `inactif` : rien ; une valeur inconnue vaut `inactif` (fail-closed).

Convergence : un état certifié à jour n'appelle pas le moteur ; un état inchangé (signature des registres M4/M5/M6,
des politiques et des reçus) ne relance ni le balayage ni un refus déjà constaté ; un balayage complet est refait
au plus tard toutes les `_REVUE_PERIODIQUE_S`. Un échec ne touche jamais la facture ni la facturation : rien ne
tourne dans une livraison, et tout refus annule sa propre transaction. SQLite seulement (D5) : PostgreSQL ne lance
rien.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, insert, select

from ..stockage import transaction
from ..stockage.schema import (
    COUT_CERTIFIE_RECONCILIATIONS,
    EVENEMENTS_RECUS,
    OPSYS_INSTANCE,
    REGISTRES,
    SERVICE_POLITIQUES,
)

__all__ = ["ENV_MODE", "MODES", "mode", "reconcilier", "reinitialiser", "derniere_execution"]

ENV_MODE = "OPSYS_COUT_CERTIFIE_RECONCILIATEUR"
MODES = ("inactif", "ombre", "actif")
MODE_DEFAUT = "ombre"
LOT_DEFAUT = 5
_REVUE_PERIODIQUE_S = 3600
_DEPARTEMENTS_SIGNATURE = ("m04-field-ops", "m05-financecore", "m06-material-control")
_M5 = "m05-financecore"
_LOG = logging.getLogger("opsys.reconciliateur_cout_certifie")

_VERROU = threading.Lock()
_MEMOIRE: dict[str, Any] = {"signature": None, "epoch": 0.0, "refus": {}, "derniere": None}


class _Ombre(Exception):
    """Annule la transaction du candidat en mode ombre (zéro écriture), en portant le résultat observé."""

    def __init__(self, resultat):
        super().__init__("ombre")
        self.resultat = resultat


def mode() -> str:
    valeur = os.environ.get(ENV_MODE, MODE_DEFAUT).strip().lower()
    if valeur not in MODES:
        _LOG.warning("mode du réconciliateur inconnu (%r) : inactif", valeur)
        return "inactif"
    return valeur


def reinitialiser() -> None:
    """Oublie la mémoire de convergence (tests, redémarrage)."""
    with _VERROU:
        _MEMOIRE.update(signature=None, epoch=0.0, refus={}, derniere=None)


def derniere_execution() -> dict[str, Any] | None:
    """Résumé du dernier appel (observabilité), sans montant ni donnée métier."""
    with _VERROU:
        return None if _MEMOIRE["derniere"] is None else dict(_MEMOIRE["derniere"])


def _politiques_actives(cnx, instance) -> bool:
    from .. import service_politiques

    return all(
        service_politiques.statut(service_politiques.derniere(cnx, instance, operation)) == "active"
        for operation in ("m4.recalculer_v3", "m4.verifier_v3")
    )


def _signature(cnx) -> str:
    """Empreinte bon marché de tout ce qui peut changer le verdict : registres M4/M5/M6, politiques, reçus M5."""
    h = hashlib.sha256()
    for ligne in cnx.execute(
        select(REGISTRES.c.departement, REGISTRES.c.registre, func.count(), func.max(REGISTRES.c.rang))
        .where(REGISTRES.c.departement.in_(_DEPARTEMENTS_SIGNATURE))
        .group_by(REGISTRES.c.departement, REGISTRES.c.registre)
        .order_by(REGISTRES.c.departement, REGISTRES.c.registre)
    ).all():
        h.update(repr(tuple(ligne)).encode())
    h.update(repr(tuple(cnx.execute(select(func.count(), func.max(SERVICE_POLITIQUES.c.revision))).one())).encode())
    h.update(repr(tuple(cnx.execute(
        select(func.count()).where(EVENEMENTS_RECUS.c.consommateur == _M5, EVENEMENTS_RECUS.c.statut == "traite")
    ).one())).encode())
    return h.hexdigest()


def intention_pour(etat: Mapping[str, Any]) -> str:
    """Intention déterministe : fonction de l'état M5 relu (WCT, devis, version des entrées, tarifs, nombre de
    traces) ; jamais de l'horloge ni d'un compteur."""
    return hashlib.sha256(("opsys.reconciliateur.intention.v1\0" + etat["empreinte_etat"]).encode()).hexdigest()


def _recu_traite(cnx, wct_id) -> bool:
    return cnx.execute(
        select(EVENEMENTS_RECUS.c.statut).where(
            EVENEMENTS_RECUS.c.evenement_id == wct_id, EVENEMENTS_RECUS.c.consommateur == _M5)
    ).scalar_one_or_none() == "traite"


def _journaliser(cnx, instance, acteur, etat, intention, statut, code, epoch) -> bool:
    """Mode actif : une ligne par publication ; un même (intention, statut, code) n'est écrit qu'une fois."""
    if statut != "publiee":
        existe = cnx.execute(
            select(COUT_CERTIFIE_RECONCILIATIONS.c.id).where(
                COUT_CERTIFIE_RECONCILIATIONS.c.intention_id == intention,
                COUT_CERTIFIE_RECONCILIATIONS.c.statut == statut,
                (COUT_CERTIFIE_RECONCILIATIONS.c.code == code) if code is not None
                else COUT_CERTIFIE_RECONCILIATIONS.c.code.is_(None),
            ).limit(1)
        ).first()
        if existe is not None:
            return False
    cnx.execute(insert(COUT_CERTIFIE_RECONCILIATIONS).values(
        instance_id=instance, acteur=acteur, wct_id=etat["wct_id"], devis_id=etat["devis_id"],
        intention_id=intention, statut=statut, code=code, epoch=max(1, int(epoch))))
    return True


def _traiter(acteur, devis_id, mode_courant, epoch) -> dict[str, Any]:
    """Un candidat, dans sa propre transaction : relecture sous verrou, moteur, journal (actif) ou annulation
    (ombre). Ne lève que pour un défaut de code (rattrapé par l'appelant)."""
    from m5_financecore import port_service_m4 as port

    from .. import moteur_recalcul_m4 as moteur
    from .. import service_acteur_systeme as systeme

    try:
        with transaction() as cnx:
            etat = port.etat_cout_certifie(devis_id)
            if etat["statut"] not in ("perime_recalcul_en_attente", "inconnu"):
                return {"statut": "a_jour" if etat["statut"] == "a_jour" else "ignore", "devis_id": devis_id}
            if not _recu_traite(cnx, etat["wct_id"]):
                return {"statut": "ignore", "devis_id": devis_id}
            intention = intention_pour(etat)
            try:
                reponse = moteur.recalculer(cnx, acteur, acteur=systeme.IDENTIFIANT, wct_id=etat["wct_id"],
                                            devis_id=devis_id, intention_id=intention)
                statut, code = reponse["statut"], None
            except moteur.RefusRecalculM4 as exc:
                statut, code = "refus", exc.code
            resultat = {"statut": statut, "code": code, "devis_id": devis_id, "wct_id": etat["wct_id"],
                        "intention_id": intention, "etat_avant": etat["statut"]}
            if mode_courant == "ombre":
                raise _Ombre(resultat)
            instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one()
            resultat["journalise"] = _journaliser(cnx, instance, systeme.IDENTIFIANT, etat, intention, statut, code,
                                                  epoch)
            return resultat
    except _Ombre as ombre:
        return {**ombre.resultat, "ombre": True}


def reconcilier(departements: Mapping[str, Any] | None = None, *, limite: int = LOT_DEFAUT,
                maintenant: float | None = None, mode_force: str | None = None) -> dict[str, Any]:
    """Un tour borné. Rend un résumé (comptes par issue) ; ne lève jamais vers le répartiteur pour un refus."""
    mode_courant = mode() if mode_force is None else mode_force
    if mode_courant not in MODES:
        raise ValueError("mode inconnu")
    resume: dict[str, Any] = {"mode": mode_courant, "candidats": 0, "traites": 0, "publiees": 0, "refus": 0,
                              "deja_executees": 0, "rien_a_faire": 0, "a_jour": 0, "erreurs": 0, "reportes": 0}
    if mode_courant == "inactif" or (departements is not None and _M5 not in departements):
        resume["raison"] = "inactif" if mode_courant == "inactif" else "m5_absent"
        return resume
    if type(limite) is not int or limite < 0:
        raise ValueError("limite doit être un entier positif ou nul")
    epoch = time.time() if maintenant is None else maintenant
    try:
        from m5_financecore import port_service_m4 as port
    except ImportError:
        resume["raison"] = "m5_indisponible"
        return resume
    with transaction() as cnx:
        if cnx.engine.dialect.name != "sqlite":
            resume["raison"] = "backend_non_sqlite"
            return resume
        instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)
                               ).scalar_one_or_none()
        if not instance or not _politiques_actives(cnx, instance):
            resume["raison"] = "politiques_inactives"
            return resume
        signature = _signature(cnx)
        with _VERROU:
            if _MEMOIRE["signature"] == signature and epoch - _MEMOIRE["epoch"] < _REVUE_PERIODIQUE_S:
                resume["raison"] = "etat_inchange"
                return resume
            refus_connus = dict(_MEMOIRE["refus"]) if _MEMOIRE["signature"] == signature else {}
        candidats = port.candidats_cout_certifie()
    resume["candidats"] = len(candidats)
    from .. import service_acteur_systeme as systeme

    complet = True
    for etat in candidats:
        cle = (etat["devis_id"], intention_pour(etat))
        if cle in refus_connus:
            resume["reportes"] += 1
            continue
        if resume["traites"] >= limite:
            complet = False
            break
        resume["traites"] += 1
        try:
            with systeme.contexte_reconciliateur() as acteur:
                resultat = _traiter(acteur, etat["devis_id"], mode_courant, epoch)
        except Exception:  # noqa: BLE001 — un défaut ne doit jamais arrêter le répartiteur ni la facturation
            resume["erreurs"] += 1
            _LOG.exception("réconciliateur : défaut sur un candidat (aucune écriture conservée)")
            continue
        statut = resultat["statut"]
        cle_resume = {"publiee": "publiees", "refus": "refus", "deja_executee": "deja_executees",
                      "rien_a_faire": "rien_a_faire", "a_jour": "a_jour"}.get(statut)
        if cle_resume:
            resume[cle_resume] += 1
        if statut == "refus":
            refus_connus[cle] = resultat["code"]
        _LOG.info(
            "réconciliateur %s : acteur=%s devis=%s wct=%s intention=%s -> %s%s%s", mode_courant,
            systeme.IDENTIFIANT, resultat.get("devis_id"), resultat.get("wct_id"), resultat.get("intention_id"),
            "aurait " if resultat.get("ombre") and statut == "publiee" else "", statut,
            f" ({resultat['code']})" if resultat.get("code") else "",
        )
    with _VERROU:
        # La signature n'est mémorisée qu'après un balayage COMPLET, et seulement si rien n'a été publié dans ce tour
        # (une publication change les registres : le tour suivant le constate et converge, sans moteur).
        if complet and (mode_courant == "ombre" or resume["publiees"] == 0):
            _MEMOIRE.update(signature=signature, epoch=epoch, refus=refus_connus)
        elif _MEMOIRE["signature"] == signature:
            _MEMOIRE["refus"] = refus_connus
        _MEMOIRE["derniere"] = dict(resume)
    return resume
