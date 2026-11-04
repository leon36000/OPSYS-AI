"""Assertions publiques, entrées entièrement fictives, contre survivants M5 ciblés."""
from m5_financecore import prevision_longue

AUJOURD_HUI = "2026-09-29"
HIST = [
    {"mois": f"2026-{m:02d}", "produits": "1000.00", "charges": "800.00", "ecritures": 1, "brouillons": 0}
    for m in range(3, 9)
]
SCENARIO = {
    "nom": "base", "croissance_revenus_mensuelle": "0", "croissance_charges_mensuelle": "0",
    "saisonnalite": ["1"] * 12, "delai_encaissement_jours": 0, "delai_paiement_jours": 0,
}

def calcul(horizon=6, scenarios=None, budget=(), carnet=()):
    conf = {"mois_historique": 6, "scenarios": [dict(SCENARIO)] if scenarios is None else scenarios}
    return prevision_longue.calculer(aujourd_hui=AUJOURD_HUI, horizon_mois=horizon,
        solde_initial="5000.00", historique=HIST, budget=list(budget), carnet=list(carnet), configuration=conf)

def test_configuration_accepte_quatre_et_refuse_un_cinquieme_scenario():
    quatre = [dict(SCENARIO, nom=f"s{i}") for i in range(4)]
    complet, refus = calcul(scenarios=quatre)
    assert refus is None and len(complet["scenarios"]) == 4
    cinq = [dict(SCENARIO, nom=f"s{i}") for i in range(5)]
    complet, refus = calcul(scenarios=cinq)
    assert complet is None
    assert refus["code"] == "REJ-PREVISION-LONGUE-CONFIGURATION-INVALIDE"

def test_vue_par_defaut_commence_a_zero_et_page_de_douze():
    complet, refus = calcul(horizon=24)
    assert refus is None
    page, refus = prevision_longue.vue(complet, scenario="base")
    assert refus is None
    assert [x["mois"] for x in page["scenario"]["lignes"]] == [
        "2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03",
        "2027-04", "2027-05", "2027-06", "2027-07", "2027-08", "2027-09",
    ]
    assert page["scenario"]["lignes_total"] == 24
    assert page["scenario"]["prochain_depart"] == 12

def test_page_exactement_au_bout_de_l_horizon_n_annonce_pas_de_suite():
    complet, refus = calcul(horizon=12)
    assert refus is None
    page, refus = prevision_longue.vue(complet, scenario="base", depart=0, limite=12)
    assert refus is None
    assert len(page["scenario"]["lignes"]) == 12
    assert page["scenario"]["prochain_depart"] is None

def test_budget_partiel_inverse_reste_une_source_de_charges_connue():
    complet, refus = calcul(budget=[{"mois":"2026-10", "produits":None, "charges":"900.00"}])
    assert refus is None
    octobre = complet["scenarios"][0]["lignes"][0]
    assert octobre["charges"] == "900.00"
    assert octobre["sources_charges"] == ["budget"]
    assert octobre["revenus"] == "1000.00"
    assert octobre["sources_produits"] == ["historique"]
    assert complet["recu"]["entrees"]["budget"][0]["produits"] is None
    assert prevision_longue.rejouer(complet["recu"]) == (True, "")

def test_echeance_carnet_alimente_le_mois_calendaire_de_sa_date():
    carnet = [{"date": "2026-10-15", "montant": "500.00", "contrat_id": "FICT-1", "echeance": "1"}]
    complet, refus = calcul(carnet=carnet)
    assert refus is None
    octobre = complet["scenarios"][0]["lignes"][0]
    assert octobre["mois"] == "2026-10"
    assert octobre["contrats"] == "500.00"
    assert octobre["revenus"] == "500.00"
    assert octobre["sources_produits"] == ["carnet"]


def test_couverture_identifie_exactement_le_mois_avec_echeance_carnet():
    carnet = [{"date": "2026-10-15", "montant": "500.00", "contrat_id": "FICT-1", "echeance": "1"}]
    complet, refus = calcul(carnet=carnet)
    assert refus is None
    assert complet["couverture"]["mois_carnet"] == ["2026-10"]


def test_recu_conserve_trois_limites_principales_puis_sa_note():
    complet, refus = calcul()
    assert refus is None
    avertissements = complet["recu"]["avertissements"]
    assert avertissements[:3] == complet["limites"][:3]
    assert len(avertissements) == 4
    assert "trois principales" in avertissements[3]


def test_resume_omet_les_lignes_et_detail_ne_rend_que_la_page_demandee():
    complet, refus = calcul(horizon=6)
    assert refus is None
    resume, refus = prevision_longue.vue(complet)
    assert refus is None
    assert all("lignes" not in scenario for scenario in resume["scenarios"])
    page, refus = prevision_longue.vue(complet, scenario="base", depart=2, limite=2)
    assert refus is None
    assert [ligne["mois"] for ligne in page["scenario"]["lignes"]] == ["2026-12", "2027-01"]
    assert page["scenario"]["lignes_total"] == 6
    assert page["scenario"]["prochain_depart"] == 4
    assert page["scenario"]["nom"] == "base"
    assert "hypotheses" in page["scenario"]
