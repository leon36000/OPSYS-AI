"""Aides des tests de concurrence MULTI-PROCESSUS (parité SQLite / PostgreSQL).

Chaque travailleur est un vrai processus (`spawn` : interpréteur neuf, pool de connexions à lui, aucun état partagé
avec le test). Tous s'importent et ouvrent leur connexion, puis attendent le même instant de départ avant le geste
disputé : la fenêtre de course est réelle, pas simulée par des fils d'un même processus.

Les travailleurs sont des fonctions de CE module (importables par le processus fils). La base est désignée par
`OPSYS_BASE_URL`, héritée de l'environnement du test.
"""

from __future__ import annotations

import multiprocessing
import os
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

DELAI_DEPART_S = 4.0
ENV_MARQUEUR = "OPSYS_QUALIF_MARQUEUR"


def lancer(cible: Callable[..., Any], arguments: Sequence[tuple], *, delai_s: float = 90.0) -> list[Any]:
    """Un processus par `arguments[i]` ; rend, dans l'ordre, les valeurs de `cible(*arguments[i], attendre)`.

    `attendre()` bloque jusqu'à l'instant de départ commun. Une exception du travailleur est rendue comme
    `("PANNE", type, message)` : le test la voit, elle n'est jamais avalée."""
    ctx = multiprocessing.get_context("spawn")
    file = ctx.Queue()
    depart = time.time() + DELAI_DEPART_S
    processus = [ctx.Process(target=_enveloppe, args=(cible, a, depart, file, i)) for i, a in enumerate(arguments)]
    for p in processus:
        p.start()
    issues: dict[int, Any] = {}
    limite = time.monotonic() + delai_s
    try:
        while len(issues) < len(processus):
            restant = limite - time.monotonic()
            if restant <= 0:
                raise TimeoutError(f"travailleurs sans réponse après {delai_s} s ({len(issues)}/{len(processus)})")
            indice, valeur = file.get(timeout=restant)
            issues[indice] = valeur
    finally:
        for p in processus:
            p.join(10)
            if p.is_alive():
                p.kill()
    return [issues[i] for i in range(len(processus))]


def _enveloppe(cible, arguments, depart, file, indice):
    def attendre() -> None:
        reste = depart - time.time()
        if reste > 0:
            time.sleep(reste)

    try:
        valeur = cible(*arguments, attendre)
    except BaseException as exc:  # noqa: BLE001 — transmis au test, jamais avalé
        valeur = ("PANNE", type(exc).__name__, str(exc)[:300])
    file.put((indice, valeur))


def marqueur() -> Path:
    return Path(os.environ[ENV_MARQUEUR])


# -- 1. deux (ou N) processus décident la même approbation --------------------------------------------------------
def _outil_compte(x: int) -> dict:
    """Outil de test : consigne SON exécution dans un fichier partagé (un ajout atomique par appel, tous processus)."""
    with open(marqueur(), "a", encoding="utf-8") as f:
        f.write(f"{os.getpid()}:{x}\n")
    time.sleep(0.4)  # élargit la fenêtre : l'autre décision arrive pendant que celle-ci exécute
    return {"x": x}


def decider(ident: str, attendre) -> tuple:
    from opsys import approbations, stockage
    from opsys.outils import Autonomie, Outil

    outils = {"m9_compte": Outil("m9_compte", "Outil qui consigne son exécution.",
                                 {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
                                 _outil_compte, Autonomie.T2)}
    with stockage.transaction() as cnx:  # connexion ouverte et migrée avant le départ
        cnx.exec_driver_sql("SELECT 1")
    attendre()
    try:
        with stockage.transaction() as cnx:
            reponse = approbations.decider(cnx, ident, True, "nathan", outils, {})
    except ValueError as exc:
        return ("refus", str(exc)[:80])
    return ("ok", reponse["statut"])


# -- 2. N processus se disputent le bail d'une ressource --------------------------------------------------------
def acquerir_bail(ressource: str, porteur: str, decalage_s: int, attendre) -> tuple:
    from opsys import stockage
    from opsys.connecteurs_planification import bail

    with stockage.transaction() as cnx:
        cnx.exec_driver_sql("SELECT 1")
    attendre()
    obtenu = bail.acquerir(ressource, porteur, 30, horloge=lambda: time.time() + decalage_s)
    return ("bail", obtenu.jeton, obtenu.porteur) if obtenu is not None else ("occupe",)


# -- 3. N processus réservent le même créneau de planificateur --------------------------------------------------
def reserver_creneau(executeur: str, maintenant: float, attendre) -> tuple:
    from opsys import stockage
    from opsys.connecteurs_planification import planificateur

    with stockage.transaction() as cnx:
        cnx.exec_driver_sql("SELECT 1")
    attendre()
    mode, intervalle = planificateur._reserver_creneau(executeur, maintenant)
    return (mode, intervalle)


# -- 4. N processus réservent l'envoi du même brouillon approuvé --------------------------------------------------
def reserver_envoi(brouillon_id: str, fournisseur: str, attendre) -> tuple:
    from opsys import stockage
    from opsys.courriel_connecteurs import envoi
    from opsys.courriel_connecteurs.erreurs import ErreurCourriel

    with stockage.transaction() as cnx:
        ligne = envoi._ligne(cnx, brouillon_id)
        brouillon = envoi._ouvrir(ligne)
    jeton = envoi.JetonApprobation(ligne["demande_id"], ligne["empreinte"])
    attendre()
    try:
        envoi.GardeEnvoiSas(stockage.transaction).reserver(brouillon, jeton, fournisseur)
    except ErreurCourriel as exc:
        return ("refus", exc.code)
    return ("reserve",)


# -- 5. N processus rejouent la même clé d'idempotence d'appareil ------------------------------------------------
def reclamer_cle(cle: str, attendre) -> tuple:
    import datetime as dt

    from opsys import idempotence, stockage

    meta = idempotence.Meta(cle=cle, appareil="appareil-fictif", horodatage_appareil="2026-11-01T12:00:00+00:00")
    arguments = {"x": 1}
    with stockage.transaction() as cnx:
        cnx.exec_driver_sql("SELECT 1")
    attendre()
    with stockage.transaction() as cnx:
        reclamation = idempotence.reclamer(cnx, meta, "m9_outil_fictif", arguments, dt.datetime.now(dt.UTC))
        if reclamation.rejouee:
            return ("rejoue", reclamation.reponse)
        with open(marqueur(), "a", encoding="utf-8") as f:  # l'exécution fraîche, une ligne par exécution réelle
            f.write(f"{os.getpid()}\n")
        time.sleep(0.4)
        idempotence.finaliser(cnx, meta, {"ok": True, "resultat": {"x": 1}})
    return ("frais",)


# -- 6. N processus de console écrivent la MÊME révision d'une fiche matériau M6 --------------------------------------
def ecrire_materiau_console(cle: str, revision_attendue: int, nom: str, attendre) -> tuple:
    """Un écrivain HUMAIN de la console (chemin de production : `console.metier.executer` -> `executer_atomique`)."""
    from opsys import stockage
    from opsys.console import metier
    from opsys.console.securite import Session
    from opsys.departements import charger_departements

    deps = charger_departements()
    session = Session("admin.fictif", frozenset({"admin"}), "csrf-fictif", 4102444800)
    arguments = dict(materiau_id="mat-fictif", nom=nom, unite="pi", actif=True, raison="Fiche FICTIVE",
                     revision_attendue=revision_attendue)
    with stockage.transaction() as cnx:
        cnx.exec_driver_sql("SELECT 1")
    attendre()
    with stockage.transaction() as cnx:
        reponse = metier.executer(cnx, deps, session, "m6_enregistrer_materiau_console", arguments, mutation_id=cle)
    resultat = reponse["resultat"]
    return ("accepte",) if resultat["accepte"] else ("refus", resultat["raison"])


# -- 7. relire_si_conflit : N processus lisent « registre vide ? » puis écrivent, sans verrou -------------------------
def ajouter_si_vide(registre: str, i: int, attendre) -> tuple:
    """Lire-puis-écrire sans verrou : SQLite l'exclut (écrivain unique), PostgreSQL le départage par la clé du rang ;
    `relire_si_conflit` rejoue la perdante, qui relit alors le registre non vide et ne l'écrit pas."""
    from opsys import stockage
    from opsys.stockage.concurrence import relire_si_conflit

    def corps():
        journal = stockage.maillons("m09-demo", registre)
        if len(journal) == 0:
            time.sleep(0.5)  # élargit la fenêtre : tous les processus ont lu « vide » avant la première écriture
            journal.append({"i": i})
            return "ecrit"
        return "relu"

    with stockage.transaction() as cnx:
        cnx.exec_driver_sql("SELECT 1")
    attendre()
    with stockage.transaction():
        return (relire_si_conflit(corps),)


# -- 8. verrou_consultatif : N processus font « si absent, écrire + auditer » ------------------------------------------
def auditer_une_fois(nom: str, attendre) -> tuple:
    """Le motif de L10 : lire l'état, puis écrire et auditer. Sans verrou, PostgreSQL audite autant de fois qu'il y a
    de processus ; avec le verrou nommé (pris AVANT la lecture), une seule fois."""
    from sqlalchemy import func, select

    from opsys import stockage
    from opsys.etat import journaliser
    from opsys.stockage.concurrence import verrou_consultatif
    from opsys.stockage.schema import JOURNAL

    with stockage.transaction() as cnx:
        cnx.exec_driver_sql("SELECT 1")
    attendre()
    with stockage.transaction() as cnx:
        verrou_consultatif(cnx, "essai-" + nom)
        deja = cnx.execute(select(func.count()).select_from(JOURNAL).where(
            JOURNAL.c.action == "essai.verrou", JOURNAL.c.cible == nom)).scalar_one()
        if deja:
            return ("relu",)
        time.sleep(0.5)
        journaliser(cnx, "essai", "essai.verrou", nom, {})
    return ("ecrit",)
