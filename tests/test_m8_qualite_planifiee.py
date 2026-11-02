"""C4, de bout en bout : un connecteur envoie une donnée aberrante, la mesure est BLOQUÉE, la tuile le dit, le copilote
refuse, le score de santé est indéterminé, M10 mémorise l'échec, puis tout se rétablit quand la source est corrigée.

Le défaut (base ea631e4bc) : la qualité des données n'était pas branchée sur le catalogue ; un échec de qualité ne
bloquait ni une tuile ni une réponse du copilote. Ici, les vrais départements, le vrai bus, le VRAI planificateur à
horloge INJECTÉE, des données FICTIVES ; la donnée aberrante entre par la voie que prendrait un connecteur (un relevé de
moteur de recherche dont les clics dépassent les impressions, rangé dans le registre des signaux de M7 ; un constat du
cash libre incohérent publié sur le bus) ; M8 lit par ses vrais outils (`Capacites`) et la vraie console (client HTTP de
test). Limites dites : SQLite seulement, horloge injectée, aucun service externe ; le bus n'authentifie pas le
producteur d'un événement (limite connue du socle), ce que l'on prouve ici est ce que M8 en fait.
"""

from __future__ import annotations

import json
import re

import planif_m8_monde as pm
import pytest
from fastapi.testclient import TestClient
from m8_analytics import outils as m8_outils

from opsys import evenements, stockage
from opsys.console import application, wallboards_ui
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.outils import executer_atomique

FICTIF = True
MDP = "mot-de-passe-fictif-12345"
JOUR = 86400
BORNES = {"sante": {"bornes": {"m8_cash_libre_cad": {"pire": "0", "cible": "50000"}}}}
RECHERCHE = ("m8_clics_recherche", "m8_impressions_recherche")


@pytest.fixture
def monde(tmp_path, monkeypatch, declarer_services):
    m = pm.monter(tmp_path, monkeypatch, declarer_services)
    pm.semer_tout(m, pm.lire_yaml(pm.RACINE / "departments/m01-front-office/fixtures/plaintes/plaintes.v1.yaml"))
    yield m
    pm.demonter()


@pytest.fixture
def monde_cash(tmp_path, monkeypatch, declarer_services):
    m = pm.monter(tmp_path, monkeypatch, declarer_services)
    m.attendu = pm.semer_m5_tresorerie(m, tmp_path, monkeypatch)
    reel = m8_outils._configuration
    monkeypatch.setattr(m8_outils, "_configuration", lambda: {**reel(), **BORNES})
    yield m
    pm.demonter()


def _console(monde, monkeypatch):
    monkeypatch.setattr(wallboards_ui, "_maintenant", lambda: monde.maintenant())
    app = application.creer_application(Configuration("secret-qualite-fictif-" + "x" * 40, cookie_securise=False,
                                                      prefixe="/opsys"), charger_departements(), stockage.transaction)
    client = TestClient(app, base_url="https://testserver/opsys")
    client.__enter__()
    reponse = client.post("/connexion", data={"identifiant": "nathan", "mot_de_passe": MDP}, follow_redirects=False)
    assert reponse.status_code == 303
    return client


@pytest.fixture
def console(monde, monkeypatch):
    client = _console(monde, monkeypatch)
    yield client
    client.__exit__(None, None, None)


def _signal(clics: str, impressions: str):
    """Un relevé journalier de moteur de recherche, tel qu'un connecteur de M7 le range (révision si la valeur
    change)."""
    from m7_marketing.signaux import modele, registre

    provenance = {"fournisseur": "fictif", "point_acces": "fictif", "version_api": "v1", "mode": "api_lecture",
                  "empreinte_reponse": "b" * 64, "page": 0}
    fait = modele.brouillon_fait(
        source="search_console", compte_ref="site-principal", nature="performance_recherche_jour", portee_type="site",
        portee_ref="propriete", debut="2026-10-25", fin="2026-10-25",
        mesures={"clics": clics, "impressions": impressions}, observe_le="2026-11-12T04:00:00+00:00", fictif=False,
        provenance=provenance, echantillon={"nature": "complet", "n": None})
    with stockage.transaction():
        registre.enregistrer(stockage.maillons(*registre.REGISTRE), [fait], "2026-11-12T04:00:00+00:00")


def _passage(monde, avance: float = 12 * 3600) -> None:
    resume = monde.tour(avance)
    assert {v["statut"] for v in resume.values() if "statut" in v} <= {"ok", "pas_echu"}, resume
    livraison = monde.propager()
    assert livraison["echecs"] == 0 and livraison["quarantaines"] == 0, livraison


def _sante(monde) -> dict:
    par_nom = {o.nom: o for o in monde.bus.departements[pm.M8].charger_outils()}
    reponse = executer_atomique(par_nom["m8_lire_sante_entreprise"], {"maintenant": monde.maintenant()})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _consolider(monde) -> dict:
    publication = monde.m8("m8_publier_faits_consolides", maintenant=monde.maintenant())
    monde.propager(pm.M9, pm.M10)
    return publication


# ===================================================================================== A. un relevé aberrant de M7
def test_un_releve_aberrant_bloque_la_mesure_la_tuile_le_copilote_le_rapport_et_m10_puis_tout_se_retablit(
    monde, console
):
    monde.activer("actif")
    _passage(monde, 1)

    # -- état sain : calculé, contrôlé et conforme, tuile à jour, le copilote répond
    # ------------------------------------
    saines = monde.mesures()
    assert (saines["m8_clics_recherche"]["valeur"], saines["m8_impressions_recherche"]["valeur"]) == ("250", "5000")
    assert saines["m8_clics_recherche"]["qualite"] == "ok"
    assert saines["m8_clics_recherche"]["pastille"] != "QUALITY_FAIL"
    tuiles = {t["id"]: t for t in console.get("/api/wallboards/acquisition").json()["tuiles"]}
    assert tuiles["clics-recherche"]["valeur"] == "250" and tuiles["clics-recherche"]["qualite_en_echec"] is False
    assert monde.m8("m8_repondre_question", question="Combien de clics de recherche ?",
                    maintenant=monde.maintenant())["statut"] == "repondu"
    rapport = monde.m8("m8_lire_rapport_qualite", maintenant=monde.maintenant())
    assert rapport["comptes"]["echec"] == 0 and rapport["lignes"] == []
    _consolider(monde)

    # -- un connecteur envoie un relevé aberrant : 99 999 clics pour 50 impressions
    # --------------------------------------
    _signal("99999", "50")
    _passage(monde)  # le prochain passage du constat de M7 publie le nouveau résumé

    # 1. la MESURE est bloquée : non calculable, aucune valeur, la raison nommée, et le reste n'a pas bougé
    bloquees = monde.mesures()
    for metric_id in RECHERCHE:
        m = bloquees[metric_id]
        assert (m["statut"], m["valeur"], m["qualite"]) == ("non_calculable", None, "echec")
        assert m["pastille"] == "QUALITY_FAIL"
        assert m["fraicheur"] == "manquant" and m["a_jour"] is False
    assert bloquees["m8_visites_site"]["valeur"] == saines["m8_visites_site"]["valeur"] == "600"
    assert bloquees["m8_factures_emises"]["valeur"] == saines["m8_factures_emises"]["valeur"]
    autres = {i for i, m in bloquees.items() if m["qualite"] == "echec"}
    assert autres == set(RECHERCHE)

    # 2. la TUILE : pastille QUALITY_FAIL dite en toutes lettres, aucune valeur, bannière qui le dit
    api = console.get("/api/wallboards/acquisition").json()
    tuiles = {t["id"]: t for t in api["tuiles"]}
    for tuile_id in ("clics-recherche", "impressions-recherche"):
        tuile = tuiles[tuile_id]
        assert tuile["pastille"] == "QUALITY_FAIL" and tuile["libelle_fraicheur"] == "QUALITÉ EN ÉCHEC"
        assert tuile["valeur_affichee"] == "non calculable" and tuile["valeur"] is None
    assert tuiles["visites-site"]["pastille"] != "QUALITY_FAIL" and tuiles["visites-site"]["valeur"] == "600"
    assert api["banniere"]["niveau"] in ("attention", "critique")
    assert any("contrôle de qualité" in m for m in api["banniere"]["messages"])
    page = console.get("/wallboards/acquisition").text
    assert "QUALITY_FAIL" in page and "Qualité en échec" in page and "99999" not in page and "99 999" not in page

    # 3. le COPILOTE refuse, avec une explication, jamais un chiffre douteux
    reponse = monde.m8("m8_repondre_question", question="Combien de clics de recherche ?",
                       maintenant=monde.maintenant())
    assert reponse["statut"] == "refuse" and reponse["refus"]["code"] == "REJ-COPILOTE-QUALITE-ECHEC"
    assert "contrôle de qualité" in reponse["texte"] and reponse["chiffres"] == []
    assert not re.search(r"99\s?999|250", reponse["texte"]) and reponse["mesures"][0]["valeur"] is None
    mixte = monde.m8("m8_repondre_question", question="Combien de clics de recherche et de visites du site ?",
                     maintenant=monde.maintenant())
    par_id = {m["metric_id"]: m for m in mixte["mesures"]}
    assert mixte["statut"] == "repondu" and par_id["m8_visites_site"]["valeur"] == "600"
    assert par_id["m8_clics_recherche"]["valeur"] is None and "BLOQUÉE" in mixte["texte"]

    # 4. le RAPPORT de qualité nomme le département source, la règle et le geste de correction, sans la valeur
    rapport = monde.m8("m8_lire_rapport_qualite", maintenant=monde.maintenant())
    assert rapport["comptes"]["echec"] == 2
    assert {(ligne["departement"], ligne["regle"]) for ligne in rapport["lignes"]} == {
        ("m07-marketing", "Q-CLICS-AU-PLUS-IMPRESSIONS")}
    assert all(ligne["correction"] and "99999" not in json.dumps(ligne) for ligne in rapport["lignes"])
    collecte = {ligne["metric_id"]: ligne for ligne in monde.pages(
        "m8_lire_etat_collecte", "mesures", maintenant=monde.maintenant(), vue="mesures", seulement_a_corriger=True)}
    assert collecte["m8_clics_recherche"]["etat_collecte"] == "qualite_en_echec"

    # 5. M10 MÉMORISE l'échec (et ne reçoit aucune valeur douteuse) ; M9 reçoit la consolidation
    publication = _consolider(monde)
    assert {(a["metric_id"], a["type"]) for a in publication["anomalies"]} >= {(i, "echec_qualite") for i in RECHERCHE}
    memoire = monde.bus.registre(pm.M10, "faits_analytiques")
    assert len(memoire) == 2
    dernier = memoire[-1]
    assert {(a["metric_id"], a["type"]) for a in dernier["anomalies"]} >= {(i, "echec_qualite") for i in RECHERCHE}
    memorisees = {m["metric_id"]: m for m in dernier["mesures"]}
    assert memorisees["m8_clics_recherche"]["valeur"] is None and memorisees["m8_clics_recherche"]["statut"] == (
        "non_calculable")
    assert "99999" not in json.dumps(dernier)
    assert monde.bus.quarantaines() == [] and monde.bus.ecritures_hors_propriete() == []

    # -- la source est corrigée : le connecteur renvoie un relevé cohérent, tout se rétablit SANS autre geste
    # ------------
    _signal("10", "200")
    _passage(monde, JOUR)
    retablies = monde.mesures()
    for metric_id in RECHERCHE:
        assert retablies[metric_id]["statut"] == "calculee" and retablies[metric_id]["qualite"] == "ok"
        assert retablies[metric_id]["pastille"] != "QUALITY_FAIL"
    # le relevé révisé remplace l'aberrant (même jour, 25 octobre) : 250 clics + 10, 5 000 impressions + 200
    clics, impressions = retablies["m8_clics_recherche"], retablies["m8_impressions_recherche"]
    assert (clics["valeur"], impressions["valeur"]) == ("260", "5200")
    tuiles = {t["id"]: t for t in console.get("/api/wallboards/acquisition").json()["tuiles"]}
    assert tuiles["clics-recherche"]["valeur"] == "260" and tuiles["clics-recherche"]["qualite_en_echec"] is False
    assert monde.m8("m8_repondre_question", question="Combien de clics de recherche ?",
                    maintenant=monde.maintenant())["statut"] == "repondu"
    assert monde.m8("m8_lire_rapport_qualite", maintenant=monde.maintenant())["comptes"]["echec"] == 0
    apres = _consolider(monde)
    assert not any(a["type"] == "echec_qualite" for a in apres["anomalies"])


# ===================================================================================== B. un constat de cash libre
# incohérent
def _constat_forge(monde, *, sequence: int, en_deficit: bool) -> None:
    """Un connecteur publie un constat de cash libre dont le drapeau de déficit contredit le montant (schéma valide)."""
    dernier = monde.publies("m5.cash_libre_constate")[-1]["charge"]
    charge = {**dernier, "sequence": sequence, "en_deficit": en_deficit,
              "evenement_id": f"m5-cash-libre-{sequence}-{dernier['date_reference']}-{'ab' * 8}"}
    evenements.publier("m5.cash_libre_constate", pm.M5, charge, evenement_id=charge["evenement_id"])
    monde.propager()


def test_un_constat_de_cash_libre_incoherent_bloque_les_quatre_mesures_et_rend_la_composante_finance_indeterminee(
    monde_cash,
):
    monde = monde_cash
    monde.activer("actif", noms=("m5.constat.cash-libre",))
    monde.tour(1)
    monde.propager()
    quatre = ("m8_cash_libre_cad", "m8_solde_tresorerie_cad", "m8_comptes_a_payer_cad", "m8_taxes_a_remettre_cad")
    sain = monde.mesures()
    assert sain["m8_cash_libre_cad"]["valeur"] == "27861.98" and sain["m8_cash_libre_cad"]["qualite"] == "ok"
    sante = _sante(monde)
    assert next(c for c in sante["composantes"] if c["id"] == "finance")["statut"] == "determine"

    _constat_forge(monde, sequence=2, en_deficit=True)  # le montant (27 861,98 $) est positif
    bloquees = monde.mesures()
    for metric_id in quatre:
        assert (bloquees[metric_id]["valeur"], bloquees[metric_id]["pastille"]) == (None, "QUALITY_FAIL"), metric_id
    sante = _sante(monde)
    finance = next(c for c in sante["composantes"] if c["id"] == "finance")
    assert finance["statut"] == "indetermine" and finance["score"] is None
    assert finance["indicateurs"][0]["raison"] == "qualite_echec" and finance["indicateurs"][0]["valeur"] is None
    assert sante["statut"] == "indetermine" and sante["score"] is None
    reponse = monde.m8("m8_repondre_question", question="Quel est le cash libre ?", maintenant=monde.maintenant())
    assert reponse["statut"] == "refuse" and reponse["refus"]["code"] == "REJ-COPILOTE-QUALITE-ECHEC"
    assert "27861" not in json.dumps(reponse) and "27 861" not in json.dumps(reponse)
    sante_copilote = monde.m8("m8_repondre_question", question="Quel est le score de santé de l'entreprise ?",
                              maintenant=monde.maintenant())
    assert "INDÉTERMINÉ" in sante_copilote["texte"]

    # -- la source corrige son constat (rang suivant, drapeau cohérent) : la mesure et le score reviennent
    # ---------------
    _constat_forge(monde, sequence=3, en_deficit=False)
    retablies = monde.mesures()
    assert retablies["m8_cash_libre_cad"]["valeur"] == "27861.98" and retablies["m8_cash_libre_cad"]["qualite"] == "ok"
    sante = _sante(monde)
    assert next(c for c in sante["composantes"] if c["id"] == "finance")["statut"] == "determine"
    assert monde.m8("m8_repondre_question", question="Quel est le cash libre ?",
                    maintenant=monde.maintenant())["statut"] == "repondu"


def test_un_deficit_reel_et_coherent_n_est_pas_une_erreur_de_qualite(monde_cash):
    """Négatif de ce test : bloquer un déficit réel serait cacher la pire nouvelle. Un constat dont le montant est
    négatif ET
    le drapeau vrai passe le contrôle."""
    monde = monde_cash
    monde.activer("actif", noms=("m5.constat.cash-libre",))
    monde.tour(1)
    monde.propager()
    dernier = monde.publies("m5.cash_libre_constate")[-1]["charge"]
    charge = {**dernier, "sequence": 2, "cash_libre_cad": "-1250.00", "en_deficit": True,
              "evenement_id": f"m5-cash-libre-2-{dernier['date_reference']}-{'cd' * 8}"}
    evenements.publier("m5.cash_libre_constate", pm.M5, charge, evenement_id=charge["evenement_id"])
    monde.propager()
    m = monde.mesures()["m8_cash_libre_cad"]
    assert (m["valeur"], m["qualite"]) == ("-1250.00", "ok")
