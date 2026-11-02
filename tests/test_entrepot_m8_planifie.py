"""Entrepôt de M8 : les constats de la phase 2 sont DÉCLENCHÉS PAR LE PLANIFICATEUR, de bout en bout.

La phase 2 avait livré sept outils de constat (T1/N2) que personne ne lançait : sans geste d'agent, les mesures de
M8 étaient non calculables puis périmées. Ici, des données FICTIVES vivent dans M1, M2, M4, M5, M6 et M7 (semées par
leurs vrais outils et registres) ; le VRAI planificateur durable, avec une horloge INJECTÉE (aucun sleep), appelle
les VRAIS outils de constat ; leurs événements circulent sur le VRAI bus et le VRAI répartiteur jusqu'aux
consommateurs réels de M8, M9 et M10 ; puis les mesures se lisent par le moteur, les wallboards de la VRAIE console,
le copilote et la mémoire.

Prouvé en plus : rien ne part par défaut ni en ombre ; une valeur exacte pour chaque mesure, recoupée avec la propre
lecture du département ; l'idempotence (même créneau, deuxième instance, redémarrage au milieu d'un cycle) par
l'identifiant déterministe du constat ; une avance de plusieurs cadences ne rattrape pas en rafale ; la panne d'un
département n'arrête pas les autres, rend sa mesure périmée à la cadence prévue puis se rétablit ; aucune donnée
personnelle dans les charges ni le journal. Limites dites : SQLite seulement, horloge injectée, aucun service externe.
"""

from __future__ import annotations

import json

import planif_m8_monde as pm
import planif_qa as pq
import pytest
from fastapi.testclient import TestClient
from m8_analytics import entrepot_stockage

from opsys import contexte, stockage
from opsys.connecteurs_planification import bail, constats, etat, journal, planificateur
from opsys.console import application, wallboards_ui
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage.schema import PLANIFICATEUR_EXECUTEURS

FICTIF = True
MDP = "mot-de-passe-fictif-12345"
INTERVALLE = 43200  # la cadence PAR DÉFAUT dérivée du catalogue (mesures à fenêtre de 24 h, deux passages par fenêtre)
JOUR = 86400

# Chaque mesure alimentée par un constat planifié, avec la valeur que les données semées doivent produire.
ATTENDU = {
    "m8_depense_pub_comptabilisee_cad": "200.00",  # 125,40 $ + 74,60 $ validés ; 75,40 $ attendent une personne
    "m8_ecart_depense_pub_comptabilisee_cad": "75.40",  # relevés 275,40 $ moins comptabilisé 200,00 $
    "m8_factures_emises": "2",  # F-1 (payée) et F-2 (envoyée) ; F-3 est un brouillon
    "m8_facturation_emise_cad": "1200.00",
    "m8_clics_recherche": "250",  # octobre 20 j x 10 + novembre 10 j x 5
    "m8_impressions_recherche": "5000",
    "m8_visites_site": "600",
    "m8_capacite_heures_disponibles": "18.00",
    "m8_capacite_heures_planifiees": "12.67",
    "m8_charge_planifiee_pct": "70.39",
    "m8_pipeline_leads_ouverts": "4",  # 26 leads : 13 convertis, 9 perdus, 4 ouverts
    "m8_taux_conversion_resolus_pct": "59.09",  # 13 convertis sur 22 résolus
    "m8_articles_en_rupture": "1",
    "m8_articles_sur_reserves": "0",
    "m8_reservations_incompletes": "1",
    "m8_plaintes_periode": "2",
}
# Les mesures de la phase 2 qu'aucun constat n'alimente sans autre déclaration (valeur déclarée, canaux du
# propriétaire).
SANS_VALEUR = ("m8_valeur_ponderee_pipeline_cad",)
# Le nombre d'événements que le premier tour publie, par type (M5 : une facture par état courant ; M7 : deux mois x
# deux sources).
PREMIER_TOUR = {
    "m1.plaintes_constatees": 1, "m2.pipeline_constate": 1, "m2.filet_anti_perte_constate": 1,
    "m4.capacite_equipe_constatee": 1,
    "m5.cash_libre_constate": 1,  # sans mouvement ni déclaration : « non calculable », publié tel quel (jamais un zéro)
    "m5.depense_publicitaire_constatee": 1, "m5.facture_emise_constatee": 2, "m5.preaudit_constate": 1,
    "m6.disponibilite_constatee": 1,
    "m7.performance_signaux_constatee": 4,
}


@pytest.fixture
def monde(tmp_path, monkeypatch, declarer_services):
    m = pm.monter(tmp_path, monkeypatch, declarer_services)
    pm.semer_tout(m, pm.lire_yaml(pm.RACINE / "departments/m01-front-office/fixtures/plaintes/plaintes.v1.yaml"))
    yield m
    pm.demonter()


@pytest.fixture
def console(monde, monkeypatch):
    monkeypatch.setattr(wallboards_ui, "_maintenant", lambda: monde.maintenant())
    app = application.creer_application(Configuration("secret-planif-m8-fictif-" + "x" * 40, cookie_securise=False,
                                                      prefixe="/opsys"), charger_departements(), stockage.transaction)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        reponse = client.post("/connexion", data={"identifiant": "nathan", "mot_de_passe": MDP},
                              follow_redirects=False)
        assert reponse.status_code == 303
        yield client


def _publies_par_id(monde) -> dict[str, str]:
    return {e["evenement_id"]: e["type_evenement"] for e in monde.bus.sortants() if e["type_evenement"] in
            pm.CONSTATS.values()}


def _etat_mesures(monde, ids=ATTENDU) -> dict[str, tuple]:
    mesures = monde.mesures()
    return {i: (mesures[i]["statut"], mesures[i]["valeur"], mesures[i]["fraicheur"]) for i in ids}


def _journal(nom):
    with stockage.transaction() as cnx:
        return journal.lire(cnx, nom, limite=500)


def _rejouer_creneau() -> None:
    """Rend tous les créneaux échus tout de suite SANS toucher à l'horloge : ce qui arriverait si une deuxième instance
    (ou un redémarrage qui a perdu la réservation) laissait un exécuteur repasser dans le MÊME créneau."""
    with stockage.transaction() as cnx:
        cnx.execute(PLANIFICATEUR_EXECUTEURS.update().values(prochain_passage=0))


# ===================================================================================================== rien par défaut
def test_rien_ne_part_par_defaut_et_les_mesures_restent_non_calculables(monde):
    resume = monde.tour(1)
    assert {v["statut"] for v in resume.values()} == {"inactif"} and set(resume) == set(pm.CONSTATS)
    assert monde.nombre_publie() == {}
    monde.propager()
    mesures = monde.mesures()
    for metric_id in ATTENDU:
        assert mesures[metric_id]["statut"] == "non_calculable", metric_id


def test_l_ombre_calcule_le_plan_le_journalise_et_ne_publie_rien(monde):
    monde.activer("ombre")
    resume = monde.tour(1)
    assert {v["statut"] for v in resume.values()} == {"ombre"} and set(resume) == set(pm.CONSTATS)
    assert resume["m7.constat.performance-signaux"]["ressources"] == 1
    assert monde.nombre_publie() == {}  # l'outil publie au bus : l'ombre n'appelle donc aucun outil
    for nom in pm.CONSTATS:
        aurait = [j for j in _journal(nom) if j["evenement"] == "aurait"]
        assert aurait and aurait[0]["mode"] == "ombre"
    journal_m7 = _journal("m7.constat.performance-signaux")
    aurait_m7 = [j["details"]["aurait"] for j in journal_m7 if j["evenement"] == "aurait"]
    assert aurait_m7 == [2]
    monde.propager()
    assert all(m["statut"] == "non_calculable" for k, m in monde.mesures().items() if k in ATTENDU)


# =========================================================================================== de bout en bout (actif)
def test_du_planificateur_aux_outils_reels_au_bus_aux_mesures_au_wallboard_au_copilote_et_a_la_memoire(monde, console):
    monde.activer("actif")
    resume = monde.tour(1)
    assert {n: v["statut"] for n, v in resume.items()} == dict.fromkeys(pm.CONSTATS, "ok"), resume
    assert monde.nombre_publie() == PREMIER_TOUR

    # les identifiants portent les bornes calculées sur le créneau (jour local, mois civils, lundi), jamais l'horloge
    # brute
    ids = set(_publies_par_id(monde))
    for prefixe in ("m1-plaintes-2026-11-12-", "m2-pipeline-2026-11-12-", "m6-disponibilite-2026-11-12-",
                    "m4-capacite-2026-11-09-journees_datees_seulement-", "m5-depense-pub-1-2026-11-01-2026-11-12-",
                    "m7-perf-search_console-site-principal-2026-10-01-2026-10-31-",
                    "m7-perf-search_console-site-principal-2026-11-01-2026-11-30-",
                    "m7-perf-umami-site-principal-2026-10-01-2026-10-31-",
                    "m7-perf-umami-site-principal-2026-11-01-2026-11-30-"):
        assert any(i.startswith(prefixe) for i in ids), prefixe

    livraison = monde.propager()
    assert livraison["echecs"] == 0 and livraison["quarantaines"] == 0, livraison
    assert monde.bus.quarantaines() == [] and monde.bus.ecritures_hors_propriete() == []

    # -- les mesures de M8 : valeur exacte, calculée, à jour (le constat est de cette heure) -------------------------
    mesures = monde.mesures()
    for metric_id, valeur in ATTENDU.items():
        assert (mesures[metric_id]["statut"], mesures[metric_id]["valeur"]) == ("calculee", valeur), metric_id
    for metric_id in ("m8_depense_pub_comptabilisee_cad", "m8_factures_emises", "m8_facturation_emise_cad",
                      "m8_clics_recherche", "m8_impressions_recherche", "m8_visites_site",
                      "m8_capacite_heures_disponibles", "m8_pipeline_leads_ouverts", "m8_articles_en_rupture",
                      "m8_plaintes_periode"):
        assert mesures[metric_id]["fraicheur"] == "a_jour", metric_id
    assert mesures["m8_valeur_ponderee_pipeline_cad"]["statut"] == "non_calculable"  # aucune valeur déclarée : dit
    # le cash libre de ce monde n'a ni mouvement ni déclaration : M5 le constate « non calculable » et M8 le dit
    # (la preuve avec un trésorier fictif complet est `test_cash_libre_planifie_m8.py`)
    for metric_id in ("m8_cash_libre_cad", "m8_solde_tresorerie_cad"):
        assert mesures[metric_id]["statut"] == "non_calculable" and mesures[metric_id]["valeur"] is None, metric_id

    # -- recoupement avec la PROPRE lecture de chaque département (une autre voie que le constat) ----------------------
    _recouper_avec_les_departements(monde)

    # -- l'entrepôt, les wallboards de la VRAIE console, le copilote --------------------------------------------------
    construction = monde.m8("m8_construire_entrepot", maintenant=monde.maintenant())
    assert construction["statut"] == "construit"
    with stockage.transaction() as cnx:
        lignes = {ligne["metric_id"]: ligne for ligne in entrepot_stockage.lire_mesures_courantes(cnx)}
    for metric_id, valeur in ATTENDU.items():
        assert lignes[metric_id]["valeur"] == valeur and lignes[metric_id]["statut"] == "calculee", metric_id
    ventes = console.get("/api/wallboards/ventes-clientele").json()
    tuiles = {t["id"]: t for t in ventes["tuiles"]}
    assert tuiles["leads-ouverts"]["valeur"] == "4" and tuiles["factures-emises"]["valeur"] == "2"
    assert tuiles["plaintes"]["valeur"] == "2" and tuiles["facturation"]["valeur"] == "1200.00"
    equipes = {t["id"]: t for t in console.get("/api/wallboards/equipes-materiel").json()["tuiles"]}
    assert equipes["charge-planifiee"]["valeur"] == "70.39" and equipes["ruptures"]["valeur"] == "1"
    page = console.get("/wallboards/ventes-clientele").text
    assert page.count("PÉRIMÉE") == 0 and "Factures émises" in page and "Plaintes reçues" in page
    acquisition = {t["id"]: t for t in console.get("/api/wallboards/acquisition").json()["tuiles"]}
    assert acquisition["clics-recherche"]["valeur"] == "250"
    assert acquisition["depense-comptabilisee"]["valeur"] == "200.00"

    reponse = monde.m8("m8_repondre_question", question="Combien de factures émises ?", maintenant=monde.maintenant())
    assert reponse["statut"] == "repondu" and reponse["mesures"][0]["metric_id"] == "m8_factures_emises"
    assert reponse["mesures"][0]["valeur"] == "2"
    reponse = monde.m8("m8_repondre_question", question="Quelle est la facturation émise avant taxes ?",
                       maintenant=monde.maintenant())
    assert reponse["mesures"][0]["metric_id"] == "m8_facturation_emise_cad"
    assert reponse["mesures"][0]["valeur"] == "1200.00"
    assert "CPA" in reponse["mention"]  # une mesure financière porte la mention professionnelle
    reponse = monde.m8("m8_repondre_question", question="Quelles sont nos ruptures de stock ?",
                       maintenant=monde.maintenant())
    assert reponse["mesures"][0]["metric_id"] == "m8_articles_en_rupture" and reponse["mesures"][0]["valeur"] == "1"

    # -- M10 (mémoire) et M9 (direction) voient le fait consolidé ------------------------------------------------------
    publication = monde.m8("m8_publier_faits_consolides", maintenant=monde.maintenant())
    assert publication["nouvelle"] is True
    monde.propager(pm.M9, pm.M10)
    (fait,) = monde.bus.registre(pm.M10, "faits_analytiques")
    memorisees = {m["metric_id"]: m for m in fait["mesures"]}
    for metric_id, valeur in ATTENDU.items():
        assert memorisees[metric_id]["valeur"] == valeur, metric_id
    consolides = [e for e in monde.bus.sortants("m8.fait_consolide")]
    assert len(consolides) == 1 and monde.bus.statut(consolides[0]["evenement_id"], pm.M9) == "traite"
    assert monde.bus.statut(consolides[0]["evenement_id"], pm.M10) == "traite"
    assert monde.bus.quarantaines() == [] and monde.bus.ecritures_hors_propriete() == []

    # -- aucune donnée personnelle ni nominative dans une charge publiée, ni dans le journal du planificateur ----------
    for e in monde.publies():
        if e["type_evenement"] in pm.CONSTATS.values():
            texte = json.dumps(e["charge"], ensure_ascii=False)
            for interdit in pm.PERSONNEL:
                assert interdit not in texte, (e["type_evenement"], interdit)
    for nom in pm.CONSTATS:
        texte = json.dumps(_journal(nom), ensure_ascii=False)
        for interdit in ("example", "@", "Client", "client-fictif", "+1514"):
            assert interdit not in texte, (nom, interdit)


def _recouper_avec_les_departements(monde) -> None:
    """La valeur de M8 égale ce que le département lit LUI-MÊME (l'outil de lecture, pas le constat)."""
    from m1_front_office.outils import lire_plaintes_structurees
    from m2_revenue_crm import outils as m2_outils
    from m4_field_ops.outils import outils as m4_outils
    from m6_material_control import outils as m6_outils

    mesures = monde.mesures()
    plaintes = lire_plaintes_structurees("2026-11-12")["resultat"]
    assert plaintes["comptes"]["declarees"] == int(mesures["m8_plaintes_periode"]["valeur"]) == 2
    m2 = {o.nom: o for o in m2_outils.outils()}
    with contexte.appele_par_appareil(pm.ADMIN):
        from opsys.outils import executer_atomique

        analyse = executer_atomique(m2["m2_analyser_pipeline"], {"horodatage": monde.maintenant()})
    assert analyse["resultat"]["accepte"] is True
    assert str(analyse["resultat"]["resultat"]["pipeline"]["ouverts"]) == mesures["m8_pipeline_leads_ouverts"]["valeur"]
    aide4 = monde.aide4
    par_nom = {o.nom: o for o in m4_outils()}
    capacite = aide4._resultat(aide4._appeler(par_nom, "m4_lire_capacite_equipe", {
        "debut_semaine": pm.LUNDI, "horodatage_reference": monde.maintenant()}, aide4.ADMIN))
    assert f"{float(capacite['heures_disponibles']):.2f}" == mesures["m8_capacite_heures_disponibles"]["valeur"]
    assert f"{float(capacite['heures_planifiees']):.2f}" == mesures["m8_capacite_heures_planifiees"]["valeur"]
    aide6 = monde.aide6
    m6 = {o.nom: o for o in m6_outils.outils()}
    lecture = aide6._outil(m6, "m6_lire_disponibilite", {"materiau_ids": None})["resultat"]
    rupture = sum(1 for a in lecture["articles"] if float(a["disponible"]) <= 0)
    assert rupture == int(mesures["m8_articles_en_rupture"]["valeur"]) == 1


# ================================================================================================== idempotence
def test_un_creneau_deja_pris_ne_republie_rien_et_le_prochain_est_reserve_a_une_cadence(monde):
    monde.activer("actif")
    monde.tour(1)
    avant = _publies_par_id(monde)
    # le créneau est réservé : rien ne repasse
    assert monde.tour(0) == dict.fromkeys(pm.CONSTATS, {"statut": "pas_echu"})
    assert _publies_par_id(monde) == avant
    with stockage.transaction() as cnx:
        for nom in pm.CONSTATS:
            ligne = etat.ligne(cnx, nom)
            assert ligne["prochain_passage"] == int(monde.horloge()) + ligne["intervalle_s"]


def test_une_deuxieme_instance_dans_le_meme_creneau_ne_publie_pas_deux_fois_meme_sans_la_reservation(monde):
    """Pire cas : la réservation du créneau est perdue (deuxième instance, redémarrage). Les arguments sont ceux du
    CRÉNEAU, donc les identifiants d'événement sont les mêmes : le bus absorbe, rien n'est publié deux fois."""
    monde.activer("actif")
    monde.tour(1)
    avant = _publies_par_id(monde)
    for _ in range(3):
        _rejouer_creneau()
        resume = monde.tour(60)  # une minute plus tard : même créneau de 12 h
        assert {v["statut"] for v in resume.values()} == {"ok"}
    assert _publies_par_id(monde) == avant
    assert len(avant) == sum(PREMIER_TOUR.values()) == len(set(avant))
    monde.propager()
    assert _etat_mesures(monde)["m8_pipeline_leads_ouverts"] == ("calculee", "4", "a_jour")


def test_un_bail_tenu_par_une_autre_instance_empeche_le_constat_sans_rien_publier(monde):
    monde.activer("actif", noms=("m6.constat.disponibilite",))
    pris = bail.acquerir("m6.constat.disponibilite:instance", "autre-instance", 600, horloge=monde.horloge)
    assert pris is not None
    resume = monde.tour(1)
    assert resume["m6.constat.disponibilite"]["ignores"] == 1 and monde.nombre_publie() == {}
    bail.liberer(pris)


def test_un_redemarrage_au_milieu_d_un_cycle_reprend_sans_doublon(monde, monkeypatch):
    """Le processus s'arrête (exception hors `Exception`) entre les deux appels de M7 : le premier mois est publié, le
    second non. À la reprise, le constat est refait en entier : le premier mois est absorbé, le second est publié."""
    from m7_marketing import signaux_outils

    monde.activer("actif", noms=("m7.constat.performance-signaux",))

    class Coupure(BaseException):
        pass

    reel = signaux_outils.constater_performance_signaux
    appels: list[str] = []

    def coupe_au_second(debut, fin, horodatage):
        appels.append(debut)
        if len(appels) == 2:
            raise Coupure
        return reel(debut, fin, horodatage)

    monkeypatch.setattr(signaux_outils, "constater_performance_signaux", coupe_au_second)
    with pytest.raises(Coupure):
        monde.tour(1)
    assert appels == ["2026-10-01", "2026-11-01"]
    # le premier mois est durable (une transaction par outil) ; le second n'a rien publié
    assert monde.nombre_publie() == {"m7.performance_signaux_constatee": 2}
    monkeypatch.setattr(signaux_outils, "constater_performance_signaux", reel)
    _rejouer_creneau()
    resume = monde.tour(30)
    assert resume["m7.constat.performance-signaux"]["statut"] == "ok"
    assert monde.nombre_publie() == {"m7.performance_signaux_constatee": 4}
    monde.propager()
    assert monde.mesures()["m8_clics_recherche"]["valeur"] == "250"  # deux mois, jamais comptés deux fois


# =========================================================================================== horloge : pas de rafale
def test_une_avance_de_plusieurs_cadences_ne_rattrape_pas_les_creneaux_manques(monde):
    monde.activer("actif")
    monde.tour(1)
    avant = monde.nombre_publie()
    passages_avant = {n: len([j for j in _journal(n) if j["evenement"] == "passage"]) for n in pm.CONSTATS}
    resume = monde.tour(5 * JOUR)  # cinq jours sans tour (arrêt du serveur) : dix créneaux manqués
    assert {v["statut"] for v in resume.values()} == {"ok"}
    passages = {n: len([j for j in _journal(n) if j["evenement"] == "passage"]) - passages_avant[n]
                for n in pm.CONSTATS}
    assert passages == dict.fromkeys(pm.CONSTATS, 1)  # UN passage chacun, pas dix
    apres = monde.nombre_publie()
    for type_evenement, nombre in apres.items():
        assert nombre - avant.get(type_evenement, 0) <= 2, type_evenement  # au plus les deux mois de M7
    # le suivant est dans une cadence, pas dans la minute qui suit
    with stockage.transaction() as cnx:
        for nom in pm.CONSTATS:
            ligne = etat.ligne(cnx, nom)
            assert ligne["prochain_passage"] == int(monde.horloge()) + ligne["intervalle_s"]
    suite = monde.tour(60)
    assert {v["statut"] for v in suite.values()} == {"pas_echu"}


def test_les_cadences_par_defaut_viennent_du_catalogue_et_la_capacite_passe_chaque_jour(monde):
    with stockage.transaction() as cnx:
        vue = {v["executeur"]: v for v in etat.vue(cnx)}
    assert {n: vue[n]["intervalle_s"] for n in pm.CONSTATS} == {
        "m1.constat.plaintes": INTERVALLE, "m2.constat.pipeline": INTERVALLE, "m2.constat.filet": INTERVALLE,
        "m4.constat.capacite-equipe": JOUR,  # fenêtre hebdomadaire (cadence 7 j du catalogue) : borné à un jour
        "m5.constat.cash-libre": INTERVALLE,  # fenêtre de 24 h des quatre mesures du cash libre, deux passages
        "m5.constat.depense-publicitaire": INTERVALLE, "m5.constat.factures-emises": INTERVALLE,
        "m5.constat.preaudit": INTERVALLE,
        "m6.constat.disponibilite": INTERVALLE, "m7.constat.performance-signaux": INTERVALLE}


# ============================================================================================ panne et reprise
def _tuile_m6(monde):
    return _etat_mesures(monde, ("m8_articles_en_rupture", "m8_pipeline_leads_ouverts"))


@pytest.mark.parametrize("panne", ["defaut_de_l_outil", "departement_indisponible"])
def test_la_panne_d_un_departement_n_arrete_pas_les_autres_perime_sa_mesure_puis_se_retablit(
        monde, monkeypatch, console, panne):
    """Le constat de M6 échoue à deux passages de suite : après UN passage manqué la mesure est encore à jour (le
    constat passe deux fois par fenêtre : c'est la marge), après DEUX elle est périmée, à la cadence prévue ; les six
    autres constats continuent ; la reprise la remet à jour."""
    from m6_material_control import outils as m6_outils

    retire = None
    monde.activer("actif")
    monde.tour(1)
    monde.propager()
    assert _tuile_m6(monde) == {"m8_articles_en_rupture": ("calculee", "1", "a_jour"),
                                "m8_pipeline_leads_ouverts": ("calculee", "4", "a_jour")}

    reel = m6_outils.constater_disponibilite
    if panne == "defaut_de_l_outil":
        def casse(horodatage):
            raise RuntimeError("panne simulée de M6")

        monkeypatch.setattr(m6_outils, "constater_disponibilite", casse)
        attendu = ("erreur", "REJ-PLAN-DEFAUT-EXECUTEUR")
    else:
        retire = monde.plan.departements.pop(pm.M6)  # M6 n'est plus servi : le planificateur le dit
        attendu = ("refus", "REJ-PLAN-DEPARTEMENT-ABSENT")

    resume = monde.tour(INTERVALLE)  # premier passage manqué
    assert (resume["m6.constat.disponibilite"]["statut"], resume["m6.constat.disponibilite"]["code"]) == attendu
    assert resume["m2.constat.pipeline"]["statut"] == "ok"
    assert resume["m7.constat.performance-signaux"]["statut"] == "ok"
    assert all(v["statut"] in ("ok", "pas_echu") for n, v in resume.items() if n != "m6.constat.disponibilite"), resume
    monde.propager()
    assert _tuile_m6(monde)["m8_articles_en_rupture"] == ("calculee", "1", "a_jour")  # la marge de sécurité tient

    resume = monde.tour(INTERVALLE)  # deuxième passage manqué : 24 h et 31 s depuis le dernier constat
    assert (resume["m6.constat.disponibilite"]["statut"], resume["m6.constat.disponibilite"]["code"]) == attendu
    assert resume["m2.constat.pipeline"]["statut"] == "ok"
    monde.propager()
    etat_mesures = _tuile_m6(monde)
    assert etat_mesures["m8_articles_en_rupture"] == ("calculee", "1", "perime")
    assert etat_mesures["m8_pipeline_leads_ouverts"] == ("calculee", "4", "a_jour")  # les autres continuent

    # visible au tableau de santé du planificateur ET à la console, avec le code typé
    with stockage.transaction() as cnx:
        vue = {v["executeur"]: v for v in etat.vue(cnx)}
    assert vue["m6.constat.disponibilite"]["dernier_statut"] == attendu[0]
    assert vue["m6.constat.disponibilite"]["dernier_code"] == attendu[1]
    assert vue["m6.constat.disponibilite"]["echecs_24h"] == 2
    assert vue["m2.constat.pipeline"]["dernier_statut"] == "ok" and vue["m2.constat.pipeline"]["echecs_24h"] == 0
    page = console.get("/plateforme/connecteurs").text
    assert attendu[1] in page and "m6.constat.disponibilite" in page
    assert "PÉRIMÉE" in console.get("/wallboards/equipes-materiel").text  # la tuile des ruptures le dit, avec son âge

    # reprise : l'outil revient, le prochain créneau republie, la mesure redevient à jour
    if panne == "defaut_de_l_outil":
        monkeypatch.setattr(m6_outils, "constater_disponibilite", reel)
    else:
        monde.plan.departements[pm.M6] = retire
    resume = monde.tour(INTERVALLE)
    assert resume["m6.constat.disponibilite"]["statut"] == "ok"
    monde.propager()
    assert _tuile_m6(monde)["m8_articles_en_rupture"] == ("calculee", "1", "a_jour")
    with stockage.transaction() as cnx:
        vue = {v["executeur"]: v for v in etat.vue(cnx)}
    assert vue["m6.constat.disponibilite"]["dernier_statut"] == "ok"


def test_une_panne_de_m8_n_empeche_pas_la_publication_et_les_constats_attendent_au_bus(monde):
    """Le producteur publie même si M8 est en panne (le bus garde) ; à la reprise de M8 les mesures se calculent."""
    monde.activer("actif")
    monde.tour(1)
    monde.propager(pm.M9)  # M8 n'est pas servi : rien n'est livré à M8
    assert monde.mesures()["m8_factures_emises"]["statut"] == "non_calculable"
    monde.propager(pm.M8)
    assert monde.mesures()["m8_factures_emises"]["valeur"] == "2"


# ============================================================================================ garde-fous et arrêt
def test_le_coupe_circuit_l_arret_propre_et_l_expiration_arretent_les_constats(monde, monkeypatch):
    monde.activer("actif")
    monkeypatch.setenv(etat.ENV_PLANIFICATEUR, "0")
    assert monde.tour(1) == {"_raison": "desactive"}
    assert monde.nombre_publie() == {}
    monkeypatch.delenv(etat.ENV_PLANIFICATEUR)
    planificateur.demander_arret()
    try:
        resume = monde.tour(1)
    finally:
        planificateur.reinitialiser_arret()
    assert monde.nombre_publie() == {} and resume.get("_raison") == "arret"
    resume = monde.tour(91 * JOUR)  # l'activation (90 jours) a expiré : fail-closed
    assert {v["statut"] for v in resume.values()} == {"inactif"} and monde.nombre_publie() == {}


def test_un_outil_de_niveau_n3_ou_plus_n_est_jamais_appele_par_un_constat(monde):
    """Même déclaré par un manifeste, un outil N3+ (ici la clôture d'une période de M5, N4) n'est pas appelé : le
    contrôle de niveau précède l'appel, et le contrôle de cohérence le refuse à la déclaration."""
    from opsys import departements as modele

    declaration = constats.Declaration(pm.M5, "M5", modele.ConstatPlanifie(
        nom="hostile", outil="m5_clore_periode_comptable", mesures=("m8_factures_emises",),
        appels=((("periode", "valeur", "2026-10"), ("horodatage", "calcul", "instant")),)))
    executeur = constats.ExecuteurConstat(declaration)
    ctx = planificateur.Contexte(monde.plan.ports, None, "essai", monde.plan.departements, monde.horloge())
    with pytest.raises(planificateur.NiveauInterdit) as refus:
        executeur.traiter("instance", ctx, None)
    assert refus.value.code == "REJ-PLAN-NIVEAU-INTERDIT"
    with pytest.raises(planificateur.NiveauInterdit):
        executeur.constater("instance", ctx)
    deps = {pm.M5: _avec_constat(monde.bus.departements[pm.M5], declaration.constat)}
    assert any("niveau" in p for p in constats.problemes(deps))


def _avec_constat(departement, constat):
    import dataclasses

    return dataclasses.replace(departement._departement, constats_planifies=(constat,))


# ====================================================================================== un jeu d'appels qui échoue
def test_un_jeu_d_appels_qui_echoue_n_empeche_pas_les_suivants_et_dit_son_code(monde, monkeypatch):
    """M7 fait deux appels (le mois précédent, puis le mois en cours). Le premier REFUSE (verdict rendu, pas
    exception) : le second est tout de même fait, le tour est en erreur et dit le code du refus."""
    from m7_marketing import signaux_outils

    monde.activer("actif", noms=("m7.constat.performance-signaux",))
    reel = signaux_outils.constater_performance_signaux

    def refuse_le_premier(debut, fin, horodatage):
        if debut.startswith("2026-10"):
            return {"accepte": False, "verdict": {"code": "REJ-SIGNAUX-ESSAI", "detail": "refus d'essai"}}
        return reel(debut, fin, horodatage)

    monkeypatch.setattr(signaux_outils, "constater_performance_signaux", refuse_le_premier)
    resume = monde.tour(1)["m7.constat.performance-signaux"]
    assert resume["statut"] == "erreur" and resume["code"] == "REJ-SIGNAUX-ESSAI" and resume["erreurs"] == 1
    assert resume["etapes"] == 1  # le second appel a été fait
    assert monde.nombre_publie() == {"m7.performance_signaux_constatee": 2}  # novembre seulement (deux sources)
    assert all("2026-10" not in i for i in _publies_par_id(monde))


def test_un_refus_rendu_par_un_outil_est_une_erreur_visible_pas_un_succes(monde, monkeypatch):
    from m6_material_control import outils as m6_outils

    monkeypatch.setattr(m6_outils, "constater_disponibilite",
                        lambda horodatage: {"accepte": False, "verdict": {"code": "REJ-M6-ESSAI"}})
    monde.activer("actif", noms=("m6.constat.disponibilite",))
    resume = monde.tour(1)["m6.constat.disponibilite"]
    assert (resume["statut"], resume["code"], resume["erreurs"]) == ("erreur", "REJ-M6-ESSAI", 1)
    assert monde.nombre_publie() == {}


def test_l_intervalle_regle_par_l_admin_commande_le_creneau(monde):
    """À l'heure : un constat de M6 par heure (un événement de plus par créneau), contre deux par jour par défaut."""
    monde.activer("actif", noms=("m6.constat.disponibilite",), intervalle_s=3600)
    for heure in range(3):
        assert monde.tour(1 if heure == 0 else 3600)["m6.constat.disponibilite"]["statut"] == "ok"
    assert monde.nombre_publie() == {"m6.disponibilite_constatee": 3}
    suite = monde.tour(60)
    assert suite["m6.constat.disponibilite"]["statut"] == "pas_echu"
    assert monde.nombre_publie()["m6.disponibilite_constatee"] == 3


def test_le_cycle_de_m5_et_les_constats_dedies_se_recouvrent_sans_doublon(monde):
    """`m5.cycle` lançait déjà les deux constats de M5 (étape 6). Les deux chemins donnent la même période, la même
    version et la même `sequence` : rien n'est publié deux fois, et l'ordre de passage n'y change rien."""
    monde.activer("actif", noms=("m5.constat.depense-publicitaire", "m5.constat.factures-emises"))
    monde.tour(1)
    avant = _publies_par_id(monde)
    assert len(avant) == 3  # un constat de dépense, deux factures émises
    with stockage.transaction() as cnx:
        etat.appliquer(cnx, pq.session_admin(), "m5.cycle", "actif", motif="preuve fictive",
                       maintenant=monde.horloge(), intervalle_s=15)
    resume = monde.plan.tour(avance=30)["executeurs"]["m5.cycle"]
    assert resume["statut"] == "ok", resume
    assert _publies_par_id(monde) == avant


def test_un_arret_propre_au_milieu_d_un_passage_libere_le_bail_et_laisse_le_jeu_suivant(monde, monkeypatch):
    """L'arrêt est lu entre deux jeux d'appels : le mois précédent est publié, le mois en cours attend le prochain
    créneau ; le bail est libéré (une autre instance peut reprendre tout de suite)."""
    from m7_marketing import signaux_outils

    monde.activer("actif", noms=("m7.constat.performance-signaux",))
    reel = signaux_outils.constater_performance_signaux

    def arrete_apres_le_premier(debut, fin, horodatage):
        resultat = reel(debut, fin, horodatage)
        planificateur.demander_arret()
        return resultat

    monkeypatch.setattr(signaux_outils, "constater_performance_signaux", arrete_apres_le_premier)
    try:
        resume = monde.tour(1)["m7.constat.performance-signaux"]
    finally:
        planificateur.reinitialiser_arret()
    assert resume["code"] == "REJ-COURRIEL-ARRET-DEMANDE" and resume["statut"] == "ok" and resume["ignores"] == 1
    assert monde.nombre_publie() == {"m7.performance_signaux_constatee": 2}  # octobre seulement
    reprise = bail.acquerir("m7.constat.performance-signaux:instance", "autre-instance", 60, horloge=monde.horloge)
    assert reprise is not None  # le bail avait été libéré
    bail.liberer(reprise)
