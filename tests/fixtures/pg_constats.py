"""Travailleurs MULTI-PROCESSUS des constats planifiés et du bus (parité SQLite / PostgreSQL), pour
`pg_concurrence.lancer`.

Chaque travailleur est un vrai processus `spawn` : il charge les VRAIS départements, ouvre SA connexion à la base de
l'instance (`OPSYS_BASE_URL`, héritée), attend l'instant de départ commun, puis fait UN geste de production :

- `tour_constats` : un tour du planificateur durable, horloge INJECTÉE (la même pour tous), restreint aux exécuteurs de
  constats demandés ;
- `tour_et_propager` : ce tour, puis la livraison du bus aux consommateurs de M8 (le travail d'une instance
  du serveur) ;
- `propager` : la livraison du bus seule, pour les départements demandés ;
- `tour_puis_mourir` : un tour dont l'outil de constat de M7 tue le processus (SIGKILL) entre ses deux mois ;
- `construire_entrepot` : l'outil `m8_construire_entrepot` de la VRAIE chaîne de capacités.

Données fictives. Aucun réseau.
"""

from __future__ import annotations

import datetime as dt
import os
import signal
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[2]


def _departements() -> dict[str, Any]:
    from m1_front_office import outils as m1
    from m2_revenue_crm import outils as m2
    from m5_financecore import outils as m5

    from opsys.departements import charger_departements

    m1.utiliser_stockage_durable()
    m2.utiliser_stockage_durable()
    m5.utiliser_stockage_durable()
    return charger_departements(RACINE / "departments")


def _ouvrir_connexion() -> None:
    from opsys import stockage

    with stockage.transaction() as cnx:  # connexion ouverte et base joignable AVANT le départ
        cnx.exec_driver_sql("SELECT 1")


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.UTC).isoformat()


def _tour(deps, t: float, noms: tuple[str, ...]) -> dict[str, str]:
    from opsys.connecteurs_planification import constats, planificateur

    planificateur.reinitialiser_arret()
    ports = planificateur.Ports(horloge=lambda: t)
    liste = [e for e in constats.executeurs() if e.nom in noms]
    resume = planificateur.tour(deps, ports=ports, executeurs=liste)
    return {nom: v["statut"] for nom, v in resume["executeurs"].items()}


def tour_constats(t: float, noms: tuple[str, ...], attendre) -> tuple:
    deps = _departements()
    _ouvrir_connexion()
    attendre()
    return ("tour", _tour(deps, t, noms))


def propager(t: float, departements: tuple[str, ...], attendre) -> tuple:
    from opsys import evenements

    deps = _departements()
    _ouvrir_connexion()
    attendre()
    resume = evenements.repartir({d: deps[d] for d in departements}, limite=500, maintenant=_iso(t))
    return ("propage", {k: resume.get(k, 0) for k in ("livres", "traites", "echecs", "quarantaines")})


def tour_et_propager(t: float, noms: tuple[str, ...], departements: tuple[str, ...], attendre) -> tuple:
    from opsys import evenements

    deps = _departements()
    _ouvrir_connexion()
    attendre()
    statuts = _tour(deps, t, noms)
    resume = evenements.repartir({d: deps[d] for d in departements}, limite=500, maintenant=_iso(t))
    return ("tour", statuts, {k: resume.get(k, 0) for k in ("livres", "traites", "echecs", "quarantaines")})


def tour_puis_mourir(t: float, noms: tuple[str, ...], attendre) -> tuple:
    """Mort brutale entre les deux appels de M7 (chaque appel d'outil a sa transaction : le premier mois est
    durable)."""
    from m7_marketing import signaux_outils

    deps = _departements()
    _ouvrir_connexion()
    reel = signaux_outils.constater_performance_signaux
    appels: list[str] = []

    def meurtrier(debut, fin, horodatage):
        appels.append(debut)
        if len(appels) == 2:  # le premier mois a son appel d'outil terminé et VALIDÉ ; le second ne commence pas
            os.kill(os.getpid(), signal.SIGKILL)
        return reel(debut, fin, horodatage)

    signaux_outils.constater_performance_signaux = meurtrier
    attendre()
    _tour(deps, t, noms)
    return ("survecu",)  # inatteignable : le processus est tué


def construire_entrepot(t: float, attendre) -> tuple:
    from opsys import stockage
    from opsys.capacites import Capacites

    deps = _departements()
    _ouvrir_connexion()
    capacites = Capacites(deps, stockage.transaction, filtre={"m08-analytics"}, memoire=False)
    attendre()
    reponse = capacites.appeler("m8_construire_entrepot", {"maintenant": _iso(t)})
    if reponse.get("ok") is not True:
        return ("refus", str(reponse)[:200])
    return ("entrepot", reponse["resultat"]["statut"])


def mourir_directement(t: float, noms: tuple[str, ...]) -> None:
    """Point d'entrée d'un `multiprocessing.Process` (sans file de résultats : le processus ne survit pas)."""
    tour_puis_mourir(t, noms, lambda: None)


def publier_enveloppe(ident: str, type_evenement: str, producteur: str, charge: dict, attendre) -> tuple:
    """Publie `charge` sous `ident` (le geste d'un producteur) ; rend l'issue typée, jamais une exception brute."""
    from opsys import evenements, stockage
    from opsys.evenements.bus import ConflitPublication

    _ouvrir_connexion()
    attendre()
    try:
        with stockage.transaction():
            evenements.publier(type_evenement, producteur, charge, evenement_id=ident)
    except ConflitPublication as exc:
        return ("conflit", str(exc)[:120])
    return ("publie",)


def activer_executeur(executeur: str, mode: str, intervalle_s: int, utilisateur: str, attendre) -> tuple:
    """Un geste d'admin de la console : fixer le mode d'un exécuteur (session serveur, rôle relu en base)."""
    import time

    from opsys import stockage
    from opsys.connecteurs_planification import etat
    from opsys.console.securite import Session

    session = Session(utilisateur=utilisateur, roles=frozenset({"admin", "nathan_owner"}), csrf="c" * 32,
                      expire=int(time.time()) + 3600)
    _ouvrir_connexion()
    attendre()
    try:
        with stockage.transaction() as cnx:
            resultat = etat.appliquer(cnx, session, executeur, mode, motif="course d'admins fictive",
                                      intervalle_s=intervalle_s)
    except etat.RefusOperateur as exc:
        return ("refus", exc.code)
    return ("ok", resultat["mode"], resultat["revision"])
