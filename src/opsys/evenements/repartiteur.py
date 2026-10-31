"""Répartiteur du bus d'événements (ADR-0009 §3) : livraison idempotente, réessais, quarantaine.

`repartir` traite chaque paire (événement, consommateur) éligible dans SA PROPRE transaction
(`stockage.transaction()` : point de sauvegarde si `repartir` est déjà appelée depuis une
transaction ouverte, sinon une transaction neuve). Ce découpage — plutôt qu'une seule grosse
transaction pour tout l'appel — donne les deux garanties du plan :
- un consommateur qui échoue n'annule que SES écritures (point de sauvegarde autour de son appel) ;
  le reçu, lui, garde l'échec, les tentatives et le backoff dans la même transaction que ce
  consommateur, donc il survit même si l'écriture du consommateur est annulée ;
- un consommateur en échec, ou un appel à `repartir` interrompu en cours de route (panne), ne
  bloque jamais les autres événements ni les autres consommateurs : ce qui est déjà livré ailleurs
  reste acquis (chaque paire commite indépendamment).

La réclamation d'une paire (insertion pour un premier essai, mise à jour conditionnelle pour un
réessai) utilise le même patron que `approbations.decider` (une écriture sous condition, dont le
nombre de lignes touchées dit si la course a été gagnée) : portable SQLite/PostgreSQL, sans verrou
applicatif supplémentaire.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import Connection, and_, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from ..departements import Departement
from ..service_capability import _livraison
from ..stockage import codec, transaction
from ..stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS
from . import attente_wct
from .schemas import types_connus

__all__ = ["etat", "repartir", "verifier_coherence"]

_BASE_BACKOFF_S = 2
_MAX_TENTATIVES = 5
_STATUTS_CLOS = ("traite", "quarantaine")
_CLE_PAIRES_EN_VOL = "_opsys_evenements_paires_en_vol"


def _consommateurs_par_type(departements: Mapping[str, Departement]) -> dict[str, list[tuple[str, Callable]]]:
    """`{type_evenement: [(departement_id, fonction), ...]}`, à partir des manifestes."""
    index: dict[str, list[tuple[str, Callable]]] = {}
    for dep in departements.values():
        if not dep.evenements_consomme:
            continue
        fonctions = dep.charger_consommateurs()
        for type_evenement in dep.evenements_consomme:
            fonction = fonctions.get(type_evenement)
            if fonction is None:
                continue  # déclaration incohérente : signalée par verifier_coherence, jamais bloquante ici
            index.setdefault(type_evenement, []).append((dep.id, fonction))
    return index


def _candidats(
    par_type: Mapping[str, list[tuple[str, Callable]]], maintenant_dt: dt.datetime, limite: int
) -> list[tuple[Mapping[str, Any], str, Callable]]:
    """Paires dues dans l'ordre publié, sans charger l'historique complet en mémoire.

    Les reçus clos sont exclus par paire en SQL. Les autres échéances restent
    comparées en Python : leurs offsets ISO ne s'ordonnent pas comme du texte.
    Le curseur borne chaque lecture à 100 événements ; un historique futur peut
    encore demander plusieurs pages, sans gonfler la liste des paramètres SQL.
    """
    ouverts_par_type = []
    consommateurs = set()
    for type_evenement, abonnes in par_type.items():
        ouverts = []
        for consommateur, _ in abonnes:
            consommateurs.add(consommateur)
            recu_clos = (
                select(1)
                .where(
                    (EVENEMENTS_RECUS.c.evenement_id == EVENEMENTS_SORTANTS.c.evenement_id)
                    & (EVENEMENTS_RECUS.c.consommateur == consommateur)
                    & EVENEMENTS_RECUS.c.statut.in_(_STATUTS_CLOS)
                )
                .correlate(EVENEMENTS_SORTANTS)
                .exists()
            )
            attente_suspendue = (
                select(1)
                .where(
                    (attente_wct.ATTENTES.c.evenement_id == EVENEMENTS_SORTANTS.c.evenement_id)
                    & (attente_wct.ATTENTES.c.consommateur == consommateur)
                    & (attente_wct.ATTENTES.c.etat != "prete")
                )
                .correlate(EVENEMENTS_SORTANTS)
                .exists()
            )
            ouverts.append(~recu_clos & ~attente_suspendue)
        if ouverts:
            ouverts_par_type.append(and_(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement, or_(*ouverts)))
    if not ouverts_par_type:
        return []
    candidats: list[tuple[Mapping[str, Any], str, Callable]] = []
    curseur: tuple[str, str] | None = None
    with transaction() as cnx:
        while True:
            requete = select(EVENEMENTS_SORTANTS).where(or_(*ouverts_par_type))
            if curseur is not None:
                cree_le, ident = curseur
                requete = requete.where(
                    or_(
                        EVENEMENTS_SORTANTS.c.cree_le > cree_le,
                        and_(EVENEMENTS_SORTANTS.c.cree_le == cree_le, EVENEMENTS_SORTANTS.c.evenement_id > ident),
                    )
                )
            evenements = (
                cnx.execute(
                    requete.order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id).limit(100)
                )
                .mappings()
                .all()
            )
            if not evenements:
                return candidats
            ids = [ligne["evenement_id"] for ligne in evenements]
            recus = (
                cnx.execute(
                    select(EVENEMENTS_RECUS).where(
                        EVENEMENTS_RECUS.c.evenement_id.in_(ids)
                        & EVENEMENTS_RECUS.c.consommateur.in_(sorted(consommateurs))
                    )
                )
                .mappings()
                .all()
            )
            recus_index = {(r["evenement_id"], r["consommateur"]): r for r in recus}
            suspendues = set(
                cnx.execute(
                    select(attente_wct.ATTENTES.c.evenement_id, attente_wct.ATTENTES.c.consommateur).where(
                        attente_wct.ATTENTES.c.evenement_id.in_(ids), attente_wct.ATTENTES.c.etat != "prete"
                    )
                ).all()
            )
            for evenement in evenements:
                for consommateur, fonction in par_type.get(evenement["type_evenement"], ()):
                    if (evenement["evenement_id"], consommateur) in suspendues:
                        continue
                    recu = recus_index.get((evenement["evenement_id"], consommateur))
                    if recu is not None:
                        if recu["statut"] in _STATUTS_CLOS:
                            continue
                        prochaine = recu["prochaine_tentative"]
                        if prochaine and dt.datetime.fromisoformat(prochaine) > maintenant_dt:
                            continue
                    candidats.append((evenement, consommateur, fonction))
                    if len(candidats) >= limite:
                        return candidats
            dernier = evenements[-1]
            curseur = (dernier["cree_le"], dernier["evenement_id"])


def _backoff(tentatives: int, depuis: dt.datetime) -> str:
    return (depuis + dt.timedelta(seconds=_BASE_BACKOFF_S**tentatives)).isoformat()


def _livrer_une_paire(
    evenement: Mapping[str, Any], consommateur: str, fonction: Callable[[dict], Any], maintenant_dt: dt.datetime
) -> str | None:
    """Livre un événement à un consommateur ; renvoie le statut final, ou `None` si la course est perdue."""
    evenement_id = evenement["evenement_id"]
    cible = (EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == consommateur)
    garde = None
    try:
        with transaction() as cnx:
            # Même connexion native et même paire seulement ; les autres livraisons restent possibles.
            par_connexion: dict[Connection, set[tuple[str, str]]] = cnx.info.setdefault(_CLE_PAIRES_EN_VOL, {})
            paire = (evenement_id, consommateur)
            actives = par_connexion.get(cnx)
            if actives is None:
                actives = set()
            if paire in actives:
                return None
            garde = (par_connexion, cnx, actives, paire)
            par_connexion[cnx] = actives
            actives.add(paire)
            charge = codec.decoder(evenement["charge"])
            if not attente_wct.peut_livrer(cnx, evenement_id, consommateur, maintenant_dt):
                return None
            existant = cnx.execute(
                select(
                    EVENEMENTS_RECUS.c.tentatives, EVENEMENTS_RECUS.c.statut, EVENEMENTS_RECUS.c.prochaine_tentative
                ).where(cible)
            ).fetchone()
            if existant is None:
                try:
                    with cnx.begin_nested():
                        cnx.execute(
                            insert(EVENEMENTS_RECUS).values(
                                evenement_id=evenement_id,
                                consommateur=consommateur,
                                statut="echec",
                                tentatives=0,
                                prochaine_tentative=None,
                                resultat=None,
                                derniere_erreur=None,
                            )
                        )
                except IntegrityError:
                    return None  # réclamée entre-temps par un autre appel concurrent
                tentatives_avant = 0
            else:
                prochaine = existant.prochaine_tentative
                if existant.statut != "echec" or (prochaine and dt.datetime.fromisoformat(prochaine) > maintenant_dt):
                    return None  # le reçu a changé depuis la sélection ; respecter son backoff courant
                # Le temps est comparé en Python (les offsets ISO ne se comparent pas comme du texte).
                # La réclamation lie ensuite atomiquement le statut, le compteur et l'échéance lus :
                # un autre essai entre SELECT et UPDATE invalide aussi ce candidat ancien.
                meme_echeance = (
                    EVENEMENTS_RECUS.c.prochaine_tentative.is_(None)
                    if prochaine is None
                    else EVENEMENTS_RECUS.c.prochaine_tentative == prochaine
                )
                reclamation = cnx.execute(
                    update(EVENEMENTS_RECUS)
                    .where(
                        cible
                        & (EVENEMENTS_RECUS.c.statut == "echec")
                        & (EVENEMENTS_RECUS.c.tentatives == existant.tentatives)
                        & meme_echeance
                    )
                    .values(statut="echec")
                )
                if reclamation.rowcount != 1:
                    return None  # déjà traité, mis en quarantaine, ou repris ailleurs entre la sélection et ici
                tentatives_avant = existant.tentatives

            try:
                with cnx.begin_nested():
                    reprise_attente = attente_wct.terminer(cnx, evenement_id, consommateur, maintenant_dt)
                    if reprise_attente:
                        attente_wct.revalider_terminee(cnx, evenement_id, consommateur, maintenant_dt)
                    with _livraison(cnx, evenement, consommateur, tentatives_avant):
                        resultat_fonction = fonction(dict(charge))
                        if reprise_attente and resultat_fonction.get("service_m4") not in ("publiee", "deja_tracee"):
                            raise ValueError("reprise sans publication M4 qualifiée")
                        attendre = attente_wct.inscrire(cnx, evenement, consommateur, resultat_fonction, maintenant_dt)
                        if reprise_attente:
                            attente_wct.revalider_terminee(cnx, evenement_id, consommateur, maintenant_dt)
                        if attendre in ("quota", "horodatage_invalide"):
                            resultat_fonction = {**resultat_fonction, "attente_non_creee": attendre}
                        # L'encodage reste dans le même savepoint que le consommateur.
                        resultat_encode = codec.encoder(dict(resultat_fonction))
            except Exception as exc:  # noqa: BLE001 — un consommateur ne doit jamais arrêter le répartiteur
                tentatives = tentatives_avant + 1
                en_quarantaine = tentatives >= _MAX_TENTATIVES
                cnx.execute(
                    update(EVENEMENTS_RECUS)
                    .where(cible)
                    .values(
                        statut="quarantaine" if en_quarantaine else "echec",
                        tentatives=tentatives,
                        prochaine_tentative=None if en_quarantaine else _backoff(tentatives, maintenant_dt),
                        derniere_erreur=f"{type(exc).__name__}: {exc}",
                    )
                )
                if en_quarantaine:
                    attente_wct.quarantaine(cnx, evenement_id, consommateur, maintenant_dt)
                return "quarantaine" if en_quarantaine else "echec"

            if attendre == "attente":
                cnx.execute(
                    update(EVENEMENTS_RECUS)
                    .where(cible)
                    .values(
                        statut="echec",
                        tentatives=tentatives_avant,
                        prochaine_tentative=None,
                        resultat=resultat_encode,
                        derniere_erreur=None,
                    )
                )
                return "attente"
            cnx.execute(
                update(EVENEMENTS_RECUS)
                .where(cible)
                .values(
                    statut="traite",
                    tentatives=tentatives_avant + 1,
                    prochaine_tentative=None,
                    resultat=resultat_encode,
                    derniere_erreur=None,
                )
            )
            return "traite"
    finally:
        # Après commit/rollback aussi : aucun état en vol ne survit à la sortie de cette livraison.
        if garde is not None:
            par_connexion, cnx, actives, paire = garde
            actives.discard(paire)
            if not actives and par_connexion.get(cnx) is actives:
                par_connexion.pop(cnx)


def repartir(
    departements: Mapping[str, Departement], *, limite: int = 100, maintenant: str | None = None
) -> dict[str, int]:
    """Livre les événements en attente à leurs consommateurs abonnés (ADR-0009 §3).

    `departements` : le manifeste courant (`opsys.departements.charger_departements()`), pour
    savoir qui consomme quoi. `limite` borne le nombre de paires (événement, consommateur) livrées
    à cet appel. `maintenant` (texte ISO) est injectable pour les tests, sans horloge cachée : les
    réessais dus sont ceux dont `prochaine_tentative <= maintenant`.
    `limite` est un entier positif ou nul : zéro n'accède ni aux consommateurs ni à la base.
    """
    if type(limite) is not int or limite < 0:
        raise ValueError("limite doit être un entier positif ou nul")
    resume = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    if limite == 0:
        return resume
    maintenant_dt = dt.datetime.fromisoformat(maintenant) if maintenant else dt.datetime.now(dt.UTC)
    with transaction() as cnx:
        attente_wct.reconcilier(cnx, maintenant_dt)
    par_type = _consommateurs_par_type(departements)
    if not par_type:
        return resume
    for evenement, consommateur, fonction in _candidats(par_type, maintenant_dt, limite):
        resultat = _livrer_une_paire(evenement, consommateur, fonction, maintenant_dt)
        if resultat is None:
            resume["ignores"] += 1
            continue
        resume["livres"] += 1
        if resultat == "attente":
            resume["attentes"] = resume.get("attentes", 0) + 1
        else:
            resume[{"traite": "traites", "echec": "echecs", "quarantaine": "quarantaines"}[resultat]] += 1
    return resume


def etat() -> dict[str, Any]:
    """Comptes des reçus par statut et liste de quarantaine (`opsys-metier evenements etat`)."""
    with transaction() as cnx:
        comptes = dict(
            cnx.execute(select(EVENEMENTS_RECUS.c.statut, func.count()).group_by(EVENEMENTS_RECUS.c.statut)).all()
        )
        # L'inbox utilise la réclamation existante `echec`, mais une attente
        # métier ouverte n'est pas un échec de livraison pour l'observateur.
        suspendues = cnx.execute(
            select(attente_wct.ATTENTES.c.etat, func.count())
            .select_from(
                attente_wct.ATTENTES.join(
                    EVENEMENTS_RECUS,
                    and_(
                        EVENEMENTS_RECUS.c.evenement_id == attente_wct.ATTENTES.c.evenement_id,
                        EVENEMENTS_RECUS.c.consommateur == attente_wct.ATTENTES.c.consommateur,
                    ),
                )
            )
            .where(attente_wct.ATTENTES.c.etat.in_(("attente", "prete")), EVENEMENTS_RECUS.c.statut == "echec")
            .group_by(attente_wct.ATTENTES.c.etat)
        ).all()
        for etat_attente, nombre in suspendues:
            comptes["echec"] = comptes.get("echec", 0) - nombre
            if comptes["echec"] == 0:
                comptes.pop("echec")
            comptes["attente_piece" if etat_attente == "attente" else "reprise_prete"] = nombre
        quarantaine = (
            cnx.execute(
                select(
                    EVENEMENTS_RECUS.c.evenement_id,
                    EVENEMENTS_RECUS.c.consommateur,
                    EVENEMENTS_RECUS.c.tentatives,
                    EVENEMENTS_RECUS.c.derniere_erreur,
                    EVENEMENTS_SORTANTS.c.type_evenement,
                    EVENEMENTS_SORTANTS.c.producteur,
                )
                .join(EVENEMENTS_SORTANTS, EVENEMENTS_SORTANTS.c.evenement_id == EVENEMENTS_RECUS.c.evenement_id)
                .where(EVENEMENTS_RECUS.c.statut == "quarantaine")
                .order_by(EVENEMENTS_SORTANTS.c.cree_le)
            )
            .mappings()
            .all()
        )
    return {
        "comptes": comptes,
        "quarantaine": [dict(ligne) for ligne in quarantaine],
    }


def verifier_coherence(departements: Mapping[str, Departement]) -> list[str]:
    """Cohérence des déclarations `department.yaml/evenements` (`opsys-metier verifier`) :

    - chaque type publié ou consommé existe au catalogue ;
    - chaque type consommé a sa fonction dans `consommateurs()` ;
    - aucune fonction de `consommateurs()` n'est orpheline (absente de `evenements.consomme`).

    Rend la liste des problèmes trouvés (vide : cohérent). Ne lève jamais pour un département dont
    le module est cassé : le problème est décrit dans la liste, pour que la CLI l'affiche.
    """
    catalogue = types_connus()
    problemes: list[str] = []
    for dep in departements.values():
        for type_evenement in (*dep.evenements_publie, *dep.evenements_consomme):
            if type_evenement not in catalogue:
                problemes.append(f"{dep.id} : type d'événement {type_evenement!r} absent du catalogue")
        if not dep.evenements_publie and not dep.evenements_consomme:
            continue  # département hors du bus d'événements : pas de module à importer pour lui
        try:
            fonctions = dep.charger_consommateurs()
        except Exception as exc:  # noqa: BLE001 — signalé, jamais une panne de `opsys-metier verifier`
            problemes.append(f"{dep.id} : consommateurs() illisible ({type(exc).__name__}: {exc})")
            continue
        for type_evenement in dep.evenements_consomme:
            if type_evenement not in fonctions:
                problemes.append(f"{dep.id} : type consommé {type_evenement!r} sans fonction dans consommateurs()")
        # Orpheline : présente dans consommateurs() mais absente de evenements.consomme — y compris
        # quand ce dernier est entièrement vide (un département qui ne déclare rien mais publie).
        for orpheline in sorted(set(fonctions) - set(dep.evenements_consomme)):
            problemes.append(f"{dep.id} : consommateurs()[{orpheline!r}] orpheline (absente de evenements.consomme)")
    return problemes
