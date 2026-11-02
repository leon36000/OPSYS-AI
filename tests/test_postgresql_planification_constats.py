"""Constats planifiés, de bout en bout et en VRAIS PROCESSUS, sur SQLite ET sur PostgreSQL 17 réel.

Le monde est celui de `test_entrepot_m8_planifie` (dix départements réels, vrais outils de constat, vrai bus, vrai
planificateur durable, données fictives semées par les vrais outils de M1, M2, M4, M5, M6 et M7) ; la différence est la
CONCURRENCE : plusieurs processus `spawn` (chacun avec sa connexion et son pool) font le travail d'une instance du
serveur au même instant, avec une horloge INJECTÉE commune.

Prouvé ici (aucun de ces gestes n'avait tourné sur PostgreSQL) :

- créneau : N processus se disputent le tour, chaque constat passe UNE fois (réservation par comparaison-échange) ;
- bail et idempotence : la réservation du créneau est perdue (deuxième instance, redémarrage) et les N processus
  repassent tous : rien n'est publié deux fois (identifiant déterministe absorbé par le bus), M8 compte une fois ;
- bus : chaque processus livre aux consommateurs de M8 pendant que les autres publient : aucun échec, aucune
  quarantaine, aucun doublon dans `faits_operations`, aucune « contradiction » fantôme, mesures EXACTES ;
- mort brutale (SIGKILL) au milieu d'un constat de M7 : le premier mois est durable, un autre processus reprend sans
  doublon après l'expiration du bail ;
- entrepôt M8 : N processus construisent en même temps ; une seule construction gagne, les autres disent `inchange` ou
  `concurrent`, jamais une exception ni un entrepôt à moitié bâti.
"""

from __future__ import annotations

import json
import multiprocessing
import signal
from collections import Counter

import planif_m8_monde as pm
import pytest
from m8_analytics import entrepot_stockage
from pg_concurrence import lancer
from pg_constats import (
    construire_entrepot,
    mourir_directement,
    tour_constats,
    tour_et_propager,
)
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from pg_rejeu import _charger
from sqlalchemy import select

from opsys import stockage
from opsys.connecteurs_planification import bail, etat, journal
from opsys.stockage.schema import PLANIFICATEUR_BAUX, PLANIFICATEUR_EXECUTEURS

FICTIF = True
N = 4
_ENTREPOT = _charger("test_entrepot_m8_planifie.py")
ATTENDU, PREMIER_TOUR = _ENTREPOT.ATTENDU, _ENTREPOT.PREMIER_TOUR
NOMS = tuple(pm.CONSTATS)
M8 = (pm.M8,)


@pytest.fixture
def monde(url_base, tmp_path, monkeypatch, declarer_services):  # noqa: F811
    m = pm.monter(tmp_path, monkeypatch, declarer_services, url=url_base)
    _semer(m, pm.lire_yaml(pm.RACINE / "departments/m01-front-office/fixtures/plaintes/plaintes.v1.yaml"))
    yield m
    pm.demonter()


def _semer(monde, corpus) -> None:
    """Comme `pm.semer_tout`, mais les plaintes de M1 vont dans le registre DURABLE : `pm.semer_m1` le remplace par un
    registre en mémoire (`reinitialiser_registre`), que les processus fils ne verraient pas."""
    import datetime as dt

    from m1_front_office.outils import recevoir_message_canal

    from opsys import taxonomie

    monde.aide4, monde.aide6 = pm.aide_m4(), pm.aide_m6()
    pm.semer_m2()
    pm.semer_m6(monde)
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    taxonomie.enregistrer_signaux_plainte(corpus["signaux_plainte"])
    fuseau = dt.timezone(dt.timedelta(hours=-5))
    for rang, (texte, jour) in enumerate((
            ("Je suis très déçu : vos gars ont abîmé ma propriété.", dt.datetime(2026, 11, 10, 9, 0, tzinfo=fuseau)),
            ("Danger : un fil électrique pend, j'ai peur.", dt.datetime(2026, 11, 11, 9, 0, tzinfo=fuseau)))):
        assert recevoir_message_canal(canal="sms", expediteur=f"+1514555{rang:04d}", message_id=f"SM-{rang}",
                                      recu_le=jour.isoformat(), texte=texte) is not None
    pm.semer_m5_factures()
    pm.semer_m7_releves_et_comptabilite(monde)
    pm.semer_m7_signaux()
    pm.semer_m4(monde)


def _sans_panne(issues) -> None:
    assert [i for i in issues if i[0] == "PANNE"] == [], issues


def _passages(nom: str) -> int:
    with stockage.transaction() as cnx:
        return len([j for j in journal.lire(cnx, nom, limite=500) if j["evenement"] == "passage"])


def _publies(monde) -> dict[str, str]:
    return {e["evenement_id"]: e["type_evenement"] for e in monde.bus.sortants() if e["type_evenement"] in
            pm.CONSTATS.values()}


def _mesures_exactes(monde) -> None:
    mesures = monde.mesures()
    for metric_id, valeur in ATTENDU.items():
        assert (mesures[metric_id]["statut"], mesures[metric_id]["valeur"]) == ("calculee", valeur), metric_id


def _faits_sans_doublon(monde) -> None:
    """`faits_operations` ne porte aucune clé de contenu en double ; aucun constat n'est dit « contradictoire »."""
    from m8_analytics import operations_recues

    faits = monde.bus.registre(pm.M8, "faits_operations")
    cles = [(f["type_entree"], *(json.dumps(f.get(c), sort_keys=True) for c in operations_recues.cles_unicite(
        f["type_entree"]))) for f in faits]
    assert len(cles) == len(set(cles)), Counter(cles).most_common(3)
    assert monde.bus.registre(pm.M8, "constats_contradictoires") == []


# =================================================================================================== le créneau
def test_n_processus_se_disputent_le_tour_chaque_constat_passe_une_seule_fois(monde):
    monde.activer("actif")
    t = monde.horloge() + 1
    issues = lancer(tour_constats, [(t, NOMS)] * N, delai_s=300)
    _sans_panne(issues)
    for nom in NOMS:
        statuts = [i[1][nom] for i in issues if nom in i[1]]
        assert statuts.count("ok") == 1, (nom, statuts)
        assert set(statuts) <= {"ok", "deja_pris", "pas_echu"}, (nom, statuts)
        assert _passages(nom) == 1, nom
    assert Counter(_publies(monde).values()) == PREMIER_TOUR
    with stockage.transaction() as cnx:
        for nom in NOMS:
            ligne = etat.ligne(cnx, nom)
            assert ligne["prochain_passage"] == int(t) + ligne["intervalle_s"]  # réservé UNE fois, pas N


def test_n_processus_tour_et_livraison_en_meme_temps_donnent_des_mesures_exactes_sans_doublon(monde):
    monde.activer("actif")
    t = monde.horloge() + 1
    issues = lancer(tour_et_propager, [(t, NOMS, M8)] * N, delai_s=600)
    _sans_panne(issues)
    for _, _, livraison in issues:
        assert livraison["echecs"] == 0 and livraison["quarantaines"] == 0, issues
    for nom in NOMS:
        assert sum(1 for i in issues if i[1].get(nom) == "ok") == 1, nom
    assert Counter(_publies(monde).values()) == PREMIER_TOUR
    reste = monde.propager()  # ce qu'aucun processus n'avait encore vu
    assert reste["echecs"] == 0 and reste["quarantaines"] == 0
    assert monde.bus.quarantaines() == [] and monde.bus.recus(statut="echec") == []
    _faits_sans_doublon(monde)
    _mesures_exactes(monde)


def test_la_reservation_du_creneau_perdue_les_n_processus_repassent_et_rien_n_est_publie_deux_fois(monde):
    """Pire cas : une deuxième instance, un redémarrage qui a perdu la réservation. Tous les processus REPASSENT (les
    arguments sont ceux du créneau) : l'identifiant d'événement est le même, le bus absorbe, M8 compte une fois."""
    monde.activer("actif")
    t = monde.horloge() + 1
    _sans_panne(lancer(tour_et_propager, [(t, NOMS, M8)] * 2, delai_s=600))
    avant = _publies(monde)
    assert Counter(avant.values()) == PREMIER_TOUR
    with stockage.transaction() as cnx:
        cnx.execute(PLANIFICATEUR_EXECUTEURS.update().values(prochain_passage=0))
    issues = lancer(tour_et_propager, [(t + 60, NOMS, M8)] * N, delai_s=600)
    _sans_panne(issues)
    assert all(i[1][nom] == "ok" or i[1][nom] in {"deja_pris", "pas_echu"} for i in issues for nom in NOMS)
    assert _publies(monde) == avant  # mêmes identifiants, mêmes types : rien de plus
    monde.propager()
    assert monde.bus.quarantaines() == []
    _faits_sans_doublon(monde)
    _mesures_exactes(monde)


def test_un_bail_tenu_par_une_autre_instance_arrete_les_n_processus_sans_rien_publier(monde):
    nom = "m6.constat.disponibilite"
    monde.activer("actif", noms=(nom,))
    pris = bail.acquerir(nom + ":instance", "autre-instance", 600, horloge=monde.horloge)
    assert pris is not None
    issues = lancer(tour_constats, [(monde.horloge() + 1, (nom,))] * N, delai_s=300)
    _sans_panne(issues)
    assert monde.nombre_publie() == {}
    with stockage.transaction() as cnx:
        refus = [j for j in journal.lire(cnx, nom, limite=100) if j["evenement"] == "bail_refuse"]
        jeton = cnx.execute(select(PLANIFICATEUR_BAUX.c.jeton).where(
            PLANIFICATEUR_BAUX.c.ressource == nom + ":instance")).scalar_one()
    assert len(refus) == 1 and jeton == 1  # un seul processus a gagné le créneau et s'est heurté au bail
    bail.liberer(pris)


# =================================================================================================== mort brutale
def test_un_processus_tue_net_au_milieu_du_constat_m7_un_autre_reprend_sans_doublon(monde):
    nom = "m7.constat.performance-signaux"
    monde.activer("actif", noms=(nom,))
    t = monde.horloge() + 1
    processus = multiprocessing.get_context("spawn").Process(target=mourir_directement, args=(t, (nom,)))
    processus.start()
    processus.join(300)
    assert processus.exitcode == -signal.SIGKILL, processus.exitcode  # tué net, au milieu du constat
    assert monde.nombre_publie() == {"m7.performance_signaux_constatee": 2}, "le premier mois est durable, seul"
    with stockage.transaction() as cnx:
        mort_bail = cnx.execute(select(PLANIFICATEUR_BAUX)).mappings().one()
    assert mort_bail["porteur"] != "" and mort_bail["jeton"] == 1  # le bail du mort n'a jamais été libéré
    assert bail.acquerir(mort_bail["ressource"], "autre", 60, horloge=lambda: t + 10) is None  # pas encore expiré
    with stockage.transaction() as cnx:
        cnx.execute(PLANIFICATEUR_EXECUTEURS.update().values(prochain_passage=0))
    issues = lancer(tour_et_propager, [(t + 300, (nom,), M8)] * 2, delai_s=600)  # bail (120 s) expiré
    _sans_panne(issues)
    assert sorted(i[1][nom] for i in issues if nom in i[1])[0] in {"ok", "deja_pris", "pas_echu"}
    assert monde.nombre_publie() == {"m7.performance_signaux_constatee": 4}  # 2 mois x 2 sources, jamais 6
    monde.propager()
    assert monde.mesures()["m8_clics_recherche"]["valeur"] == "250"  # deux mois, jamais comptés deux fois
    _faits_sans_doublon(monde)
    with stockage.transaction() as cnx:
        reprise = cnx.execute(select(PLANIFICATEUR_BAUX.c.jeton, PLANIFICATEUR_BAUX.c.porteur)).one()
    assert reprise[0] >= 2 and reprise[1] == ""  # jeton de fencing plus grand, bail libéré par le repreneur


# =================================================================================================== l'entrepôt M8
def test_n_processus_construisent_l_entrepot_en_meme_temps_une_seule_construction_gagne(monde):
    monde.activer("actif")
    _sans_panne(lancer(tour_et_propager, [(monde.horloge() + 1, NOMS, M8)], delai_s=600))
    monde.propager()
    t = monde.horloge() + 5
    issues = lancer(construire_entrepot, [(t,)] * N, delai_s=600)
    _sans_panne(issues)
    statuts = [i[1] for i in issues]
    assert all(i[0] == "entrepot" for i in issues), issues
    assert statuts.count("construit") == 1 and set(statuts) <= {"construit", "inchange", "concurrent"}, statuts
    with stockage.transaction() as cnx:
        derniere = entrepot_stockage.derniere_construction(cnx)
        assert derniere["rang"] == 1  # une seule construction a laissé une trace
        courantes = {ligne["metric_id"]: ligne for ligne in entrepot_stockage.lire_mesures_courantes(cnx)}
        nb = cnx.exec_driver_sql("SELECT COUNT(*) FROM m8_ent_constructions").scalar_one()
    assert nb == 1 and derniere["nb_mesures"] == len(courantes)
    for metric_id, valeur in ATTENDU.items():
        assert courantes[metric_id]["valeur"] == valeur and courantes[metric_id]["statut"] == "calculee", metric_id
    # une reconstruction sur le même état ne change rien, ensuite
    (suite,) = lancer(construire_entrepot, [(t + 1,)], delai_s=300)
    assert suite == ("entrepot", "inchange")
