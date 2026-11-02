"""M2-C1 : le filet anti-perte alimente M8 par le PLANIFICATEUR, de bout en bout.

Un carnet de douze leads FICTIFS aux défauts variés (`departments/m02-revenue-crm/tests/filet_carnet.py`) vit dans M2,
semé
par ses vrais outils. Le VRAI planificateur durable, avec une horloge INJECTÉE (aucun sleep), appelle le VRAI outil
`m2_constater_filet` (constat déclaré au manifeste, exécuteur `m2.constat.filet`) ; l'événement
`m2.filet_anti_perte_constate`
circule sur le VRAI bus et le VRAI répartiteur jusqu'au consommateur réel de M8 ; les deux mesures du catalogue
(`m8_violations_sla_commercial`, `m8_anomalies_integrite_crm`) se lisent par le moteur et au wallboard de la VRAIE
console.

Prouvé : rien ne part par défaut ni en ombre (l'ombre dit « aurait » sans rien écrire dans M2 ni sur le bus) ; en actif,
une
valeur exacte pour chaque mesure, recoupée avec la propre lecture du département ; sans délai déclaré la mesure des
violations est non calculable (jamais zéro) alors que l'audit, qui n'a besoin d'aucun seuil, se lit ; des délais
déclarés en
partie donnent une couverture partielle dite ; un même créneau (deuxième instance, réservation perdue) ne publie rien de
plus ; aucune donnée personnelle dans la charge ni dans le journal du planificateur. Limites dites : SQLite, horloge
injectée, données fictives, aucun service externe.
"""

from __future__ import annotations

import datetime as dt
import json
import sys

import planif_m8_monde as pm
import pytest
from fastapi.testclient import TestClient

from opsys import stockage
from opsys.connecteurs_planification import constats, journal
from opsys.console import application, wallboards_ui
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage.schema import PLANIFICATEUR_EXECUTEURS

sys.path.insert(0, str(pm.RACINE / "departments" / "m02-revenue-crm" / "tests"))
import filet_carnet as fc  # noqa: E402
import ventes_aide  # noqa: E402

FICTIF = True
MDP = "mot-de-passe-fictif-12345"
EXECUTEUR = "m2.constat.filet"
TYPE = "m2.filet_anti_perte_constate"
# Le créneau de 12 h qui contient le premier tour : minuit local (05:00 UTC en novembre) du jour de `pm.DEBUT`.
CRENEAU = dt.datetime(2026, 11, 12, 5, 0, tzinfo=dt.UTC)
PERSONNEL = ("Client L", "Injoignable", "example", "418-555", "@", "L0", "L1", "vendeur", "devis-L", "fichier-")


@pytest.fixture
def monde(tmp_path, monkeypatch, declarer_services):
    m = pm.monter(tmp_path, monkeypatch, declarer_services)
    monkeypatch.setattr(fc, "MAINT_UTC", CRENEAU)
    m2 = ventes_aide.Monde(tmp_path, monkeypatch)
    fc.semer(m2)
    m.m2 = m2
    yield m
    pm.demonter()


@pytest.fixture
def console(monde, monkeypatch):
    monkeypatch.setattr(wallboards_ui, "_maintenant", lambda: monde.maintenant())
    app = application.creer_application(
        Configuration("secret-planif-filet-fictif-" + "x" * 40, cookie_securise=False, prefixe="/opsys"),
        charger_departements(),
        stockage.transaction,
    )
    with TestClient(app, base_url="https://testserver/opsys") as client:
        reponse = client.post("/connexion", data={"identifiant": "nathan", "mot_de_passe": MDP}, follow_redirects=False)
        assert reponse.status_code == 303
        yield client


def _publies(monde):
    return monde.publies(TYPE)


def _journal(nom=EXECUTEUR):
    with stockage.transaction() as cnx:
        return journal.lire(cnx, nom, limite=500)


def _tour(monde, avance=1):
    return monde.tour(avance)[EXECUTEUR]


def _mesure(monde, metric_id):
    return monde.mesures()[metric_id]


def _ligne_entrepot(monde, metric_id):
    from m8_analytics import entrepot_stockage

    assert monde.m8("m8_construire_entrepot", maintenant=monde.maintenant())["statut"] in ("construit", "inchange")
    with stockage.transaction() as cnx:
        return {ligne["metric_id"]: ligne for ligne in entrepot_stockage.lire_mesures_courantes(cnx)}[metric_id]


# ================================================================================================ rien par défaut
def test_le_constat_est_declare_par_le_manifeste_inactif_par_defaut_et_en_n2():
    (declaration,) = [d for d, _ in constats.declarees() if d.nom == EXECUTEUR]
    assert declaration.constat.outil == "m2_constater_filet"
    assert declaration.constat.mesures == ("m8_violations_sla_commercial", "m8_anomalies_integrite_crm")
    (definition,) = [x for _, x in constats.declarees() if x.nom == EXECUTEUR]
    assert definition.niveau == "N2" and definition.famille == "constats"
    assert 15 <= definition.intervalle_defaut_s <= 86400


def test_rien_ne_part_par_defaut_et_les_mesures_restent_non_calculables(monde):
    resume = monde.tour(1)
    assert resume[EXECUTEUR]["statut"] == "inactif" and _publies(monde) == []
    monde.propager()
    for metric_id in ("m8_violations_sla_commercial", "m8_anomalies_integrite_crm"):
        assert _mesure(monde, metric_id)["statut"] == "non_calculable", metric_id


def test_l_ombre_dit_aurait_ne_publie_rien_et_n_ecrit_rien_dans_m2(monde):
    avant = monde.m2.instantane()
    monde.activer("ombre", noms=(EXECUTEUR,))
    resume = _tour(monde)
    assert resume["statut"] == "ombre" and _publies(monde) == []
    aurait = [j for j in _journal() if j["evenement"] == "aurait"]
    assert aurait and aurait[0]["mode"] == "ombre" and aurait[0]["details"] == {"aurait": 1}
    apres = monde.m2.instantane()
    changees = {t for t in apres if apres[t] != avant[t]}
    assert changees <= {"planificateur_executeurs", "planificateur_journal"}, changees
    monde.propager()
    assert _mesure(monde, "m8_violations_sla_commercial")["statut"] == "non_calculable"


# ================================================================================================ de bout en bout
def test_du_planificateur_au_bus_aux_mesures_au_wallboard_et_au_copilote(monde, console):
    monde.activer("actif", noms=(EXECUTEUR,))
    resume = _tour(monde)
    assert resume["statut"] == "ok", resume
    (evenement,) = _publies(monde)
    charge = evenement["charge"]
    assert charge["date_reference"] == "2026-11-12" and charge["constate_le"] == CRENEAU.isoformat()
    assert charge["violations_total"] == 10 and charge["anomalies_total"] == 5 and charge["leads_examines"] == 12
    assert charge["violations_par_regle"] == {
        "prochaine_action_obligatoire": 2,
        "lead_chaud_non_contacte": 1,
        "photos_non_recues": 1,
        "soumission_non_relancee": 1,
        "plainte_non_escaladee": 1,
        "lead_sans_proprietaire": 2,
        "tache_en_retard": 2,
    }
    assert charge["anomalies_par_controle"] == {
        "lead_sans_statut": 0,
        "client_sans_contact": 1,
        "tache_sans_proprietaire": 0,
        "soumission_orpheline": 1,
        "activite_sans_lead": 1,
        "lead_sans_client": 0,
        "pipeline_incoherent": 2,
        "doublon_probable": 0,
    }
    assert charge["regles_non_evaluees"] == [] and charge["regles_partielles"] == []

    livraison = monde.propager()
    assert livraison["echecs"] == 0 and livraison["quarantaines"] == 0, livraison
    assert monde.bus.quarantaines() == [] and monde.bus.ecritures_hors_propriete() == []

    violations = _mesure(monde, "m8_violations_sla_commercial")
    anomalies = _mesure(monde, "m8_anomalies_integrite_crm")
    assert (violations["statut"], violations["valeur"]) == ("calculee", "10")
    assert (anomalies["statut"], anomalies["valeur"]) == ("calculee", "5")
    assert violations["fraicheur"] == anomalies["fraicheur"] == "a_jour"
    for metric_id in ("m8_violations_sla_commercial", "m8_anomalies_integrite_crm"):
        assert _ligne_entrepot(monde, metric_id)["proprietaire"] == "m02-revenue-crm"
    assert violations["couverture"] == anomalies["couverture"] == "complete"

    # -- le wallboard de la VRAIE console ------------------------------------------------------------------------------
    tuiles = {t["id"]: t for t in console.get("/api/wallboards/ventes-clientele").json()["tuiles"]}
    assert tuiles["violations-sla"]["valeur"] == "10" and tuiles["anomalies-integrite"]["valeur"] == "5"
    page = console.get("/wallboards/ventes-clientele").text
    assert "Violations du SLA commercial" in page and "intégrité du CRM" in page
    assert "PÉRIMÉE" not in page

    # -- le copilote retrouve la mesure par ses synonymes
    # ---------------------------------------------------------------
    reponse = monde.m8(
        "m8_repondre_question", question="Combien de violations du SLA commercial ?", maintenant=monde.maintenant()
    )
    assert reponse["statut"] == "repondu" and reponse["mesures"][0]["metric_id"] == "m8_violations_sla_commercial"
    assert reponse["mesures"][0]["valeur"] == "10"


def test_la_valeur_de_m8_egale_ce_que_les_outils_de_m2_lisent_eux_memes(monde):
    monde.activer("actif", noms=(EXECUTEUR,))
    _tour(monde)
    monde.propager()
    scan = monde.m2.accepte(monde.m2.appeler("m2_scanner_sla", {"horodatage": CRENEAU.isoformat(), "limite": 1}))
    audit = monde.m2.accepte(monde.m2.appeler("m2_auditer_integrite", {"horodatage": CRENEAU.isoformat(), "limite": 1}))
    assert str(scan["total"]) == _mesure(monde, "m8_violations_sla_commercial")["valeur"]
    assert str(audit["total"]) == _mesure(monde, "m8_anomalies_integrite_crm")["valeur"]


# ================================================================================================ sans délai déclaré
def test_sans_delai_declare_la_mesure_des_violations_est_non_calculable_l_audit_se_lit_quand_meme(monde):
    monde.m2.configurer()  # le vrai manifeste est vide : aucun délai déclaré
    monde.activer("actif", noms=(EXECUTEUR,))
    _tour(monde)
    (evenement,) = _publies(monde)
    charge = evenement["charge"]
    assert len(charge["regles_non_evaluees"]) == 5 and charge["violations_par_regle"]["lead_chaud_non_contacte"] is None
    assert charge["regles_partielles"] == ["prochaine_action_obligatoire", "lead_sans_proprietaire"]
    monde.propager()
    violations = _mesure(monde, "m8_violations_sla_commercial")
    assert violations["statut"] == "non_calculable" and violations["valeur"] is None, "ce n'est pas zéro violation"
    assert violations["manque"] == ["regles_sla"]
    ligne = _ligne_entrepot(monde, "m8_violations_sla_commercial")
    assert ligne["valeur"] is None and "aucune règle SLA n'est évaluée en entier" in ligne["detail"]
    anomalies = _mesure(monde, "m8_anomalies_integrite_crm")
    assert (anomalies["statut"], anomalies["valeur"]) == ("calculee", "5"), "l'audit n'a besoin d'aucun seuil"


def test_des_delais_declares_en_partie_donnent_une_couverture_partielle_dite(monde):
    monde.m2.configurer(sla={"heures_lead_chaud": 4, "heures_assignation": 24, "heures_retard_tolerance": 6})
    monde.activer("actif", noms=(EXECUTEUR,))
    _tour(monde)
    monde.propager()
    violations = _mesure(monde, "m8_violations_sla_commercial")
    assert violations["statut"] == "calculee"
    # chaud 1 (L06) + sans propriétaire 2 (L05, L11) + retard 2 (L08, L09) + la partie sans délai de la règle de
    # première
    # action (L11 : lead qualifié sans action, immédiat) = 6
    assert violations["valeur"] == "6"
    assert violations["couverture"] == "partielle"
    detail = _ligne_entrepot(monde, "m8_violations_sla_commercial")["detail"]
    assert detail.startswith("couverture partielle") and "photos_non_recues" in detail and "non évaluée" in detail
    assert "prochaine_action_obligatoire" in detail and "pour leur seule partie sans délai" in detail


# ================================================================================================ idempotence
def test_un_meme_creneau_deux_instances_ou_un_redemarrage_ne_publient_rien_de_plus(monde):
    monde.activer("actif", noms=(EXECUTEUR,))
    _tour(monde)
    (premier,) = _publies(monde)
    assert monde.tour(0)[EXECUTEUR] == {"statut": "pas_echu"}
    for _ in range(3):  # la réservation du créneau est perdue (deuxième instance, redémarrage) : mêmes arguments
        with stockage.transaction() as cnx:
            cnx.execute(PLANIFICATEUR_EXECUTEURS.update().values(prochain_passage=0))
        assert monde.tour(60)[EXECUTEUR]["statut"] == "ok"
    assert [e["evenement_id"] for e in _publies(monde)] == [premier["evenement_id"]]
    monde.propager()
    assert _mesure(monde, "m8_violations_sla_commercial")["valeur"] == "10"


def test_le_creneau_suivant_est_un_constat_de_plus_et_une_donnee_changee_une_version_de_plus(monde):
    monde.activer("actif", noms=(EXECUTEUR,))
    _tour(monde)
    (premier,) = _publies(monde)
    monde.m2.configurer(sla={**fc.FICTIF_SLA, "heures_lead_chaud": 100000})  # le propriétaire assouplit un délai
    resume = monde.tour(43200 + 5)[EXECUTEUR]  # le créneau de 12 h suivant
    assert resume["statut"] == "ok"
    deux = _publies(monde)
    assert len(deux) == 2 and deux[0]["evenement_id"] != deux[1]["evenement_id"]
    assert deux[1]["charge"]["version_donnees"] != premier["charge"]["version_donnees"]
    assert deux[1]["charge"]["violations_par_regle"]["lead_chaud_non_contacte"] == 0
    monde.propager()
    assert _mesure(monde, "m8_violations_sla_commercial")["valeur"] == "9", "le dernier constat publié fait foi"


def test_la_panne_de_m2_n_arrete_rien_d_autre_et_le_constat_se_refait_au_creneau_suivant(monde, monkeypatch):
    from m2_revenue_crm import outils_integrite

    monde.activer("actif", noms=(EXECUTEUR, "m6.constat.disponibilite"))
    reel = outils_integrite._lire_registres

    def panne():
        raise RuntimeError("registre illisible (panne simulée)")

    monkeypatch.setattr(outils_integrite, "_lire_registres", panne)
    resume = monde.tour(1)
    assert resume[EXECUTEUR]["statut"] in ("erreur", "echec") and _publies(monde) == []
    assert resume["m6.constat.disponibilite"]["statut"] == "ok", "un autre département n'est pas touché"
    monkeypatch.setattr(outils_integrite, "_lire_registres", reel)
    assert monde.tour(43200 + 5)[EXECUTEUR]["statut"] == "ok" and len(_publies(monde)) == 1


# ================================================================================================ confidentialité
def test_aucune_donnee_personnelle_dans_la_charge_ni_dans_le_journal_du_planificateur(monde):
    monde.activer("actif", noms=(EXECUTEUR,))
    _tour(monde)
    for e in _publies(monde):
        texte = json.dumps(e["charge"], ensure_ascii=False)
        for interdit in PERSONNEL:
            assert interdit not in texte, interdit
    texte = json.dumps(_journal(), ensure_ascii=False)
    for interdit in PERSONNEL:
        assert interdit not in texte, interdit


def test_le_constat_n_ecrit_dans_m2_que_ce_que_le_planificateur_et_le_bus_ecrivent(monde):
    registres = (
        "principal",
        "relances_preparees",
        "consentements_contact",
        "profils_propriete",
        "satisfactions_recues",
        "devis_envoyes_recus",
        "relances_devis_recues",
    )
    avant = {n: monde.m2.registre(n) for n in registres}
    tables_avant = monde.m2.instantane()
    monde.activer("actif", noms=(EXECUTEUR,))
    _tour(monde)
    assert {n: monde.m2.registre(n) for n in registres} == avant, "aucun registre de M2 n'est écrit"
    tables_apres = monde.m2.instantane()
    changees = {t for t in tables_apres if tables_apres[t] != tables_avant[t]}
    assert {t for t in changees if not t.startswith("planificateur")} <= {"evenements_sortants"}, changees
