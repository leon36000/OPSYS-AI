"""M5-PREV-2 : la prévision longue (6, 12, 24 mois) est un calcul pur, déterministe et fermé.

Ce fichier exerce le NOYAU `prevision_longue.py` sans base ni registre : chaque cas est calculé à la main, au cent, dans
le docstring ou le commentaire du test. Les données sont fictives (AGENTS.md). Aucune valeur d'affaires réelle n'est
écrite ici : la croissance, la saisonnalité et les délais sont des HYPOTHÈSES déclarées par la direction, jamais des
défauts.

Rappel de la règle d'or : le code calcule, le modèle orchestre. Un montant, une date ou une quantité ne vient jamais
d'un modèle ; la prévision ne fait que multiplier des moyennes du grand livre et un budget déclaré par des hypothèses
déclarées, puis décaler des encaissements et des décaissements de délais déclarés.
"""

from __future__ import annotations

from copy import deepcopy

from m5_financecore import prevision_longue

AUJOURD_HUI = "2026-09-29"
MOIS_HISTORIQUE = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
SCENARIO = {
    "nom": "base",
    "croissance_revenus_mensuelle": "0",
    "croissance_charges_mensuelle": "0",
    "saisonnalite": ["1"] * 12,
    "delai_encaissement_jours": 0,
    "delai_paiement_jours": 0,
}


def _historique(produits="1000.00", charges="800.00", *, ecritures=1, mois=None):
    return [
        {"mois": m, "produits": produits, "charges": charges, "ecritures": ecritures, "brouillons": 0}
        for m in (MOIS_HISTORIQUE if mois is None else mois)
    ]


def _config(*scenarios, mois_historique=6):
    return {"mois_historique": mois_historique, "scenarios": list(scenarios) or [dict(SCENARIO)]}


def _calculer(*, config=None, historique=None, budget=(), carnet=(), horizon=6, solde="5000.00"):
    return prevision_longue.calculer(
        aujourd_hui=AUJOURD_HUI,
        horizon_mois=horizon,
        solde_initial=solde,
        historique=_historique() if historique is None else historique,
        budget=list(budget),
        carnet=list(carnet),
        configuration=_config() if config is None else config,
    )


def _scenario(resultat, nom="base"):
    return next(s for s in resultat["scenarios"] if s["nom"] == nom)


def _solde(resultat, nom="base"):
    return [ligne["solde_projete"] for ligne in _scenario(resultat, nom)["lignes"]]


def _code(verdict):
    assert verdict is not None and verdict["code"].startswith("REJ-PREVISION-LONGUE-")
    return verdict["code"]


# ============================================================================================ 1. le calcul exact
def test_six_mois_sans_hypothese_de_croissance_donnent_deux_cents_par_mois():
    """5000 + 6 × (1000 − 800) = 6200.00 ; la moyenne du grand livre est reprise telle quelle (aucune croissance)."""
    resultat, verdict = _calculer()

    assert verdict is None, verdict
    assert _solde(resultat) == ["5200.00", "5400.00", "5600.00", "5800.00", "6000.00", "6200.00"]
    assert _scenario(resultat)["solde_final"] == "6200.00"
    assert _scenario(resultat)["solde_minimal"] == "5000.00"
    assert _scenario(resultat)["total_revenus"] == "6000.00"
    assert _scenario(resultat)["total_charges"] == "4800.00"
    assert _scenario(resultat)["mois_sous_zero"] == []
    assert resultat["premier_mois"] == "2026-10" and resultat["dernier_mois"] == "2027-03"


def test_le_budget_declare_prime_sur_l_historique_pour_le_mois_qu_il_couvre():
    """Octobre : 1200 − 900 = 300 (budget), puis 5 × 200 : 5300, 5500, 5700, 5900, 6100, 6300."""
    budget = [{"mois": "2026-10", "produits": "1200.00", "charges": "900.00"}]
    resultat, verdict = _calculer(budget=budget)

    assert verdict is None, verdict
    assert _solde(resultat) == ["5300.00", "5500.00", "5700.00", "5900.00", "6100.00", "6300.00"]
    octobre = _scenario(resultat)["lignes"][0]
    assert octobre["sources_produits"] == ["budget"] and octobre["sources_charges"] == ["budget"]
    assert resultat["couverture"]["mois_budget"] == ["2026-10"]


def test_un_budget_a_zero_est_un_zero_connu_jamais_un_repli_sur_l_historique():
    """Un zéro DÉCLARÉ ne doit pas être remplacé par la moyenne : octobre vaut 0, les autres mois 200."""
    budget = [{"mois": "2026-10", "produits": "0.00", "charges": "0.00"}]
    resultat, verdict = _calculer(budget=budget)

    assert verdict is None, verdict
    assert _solde(resultat) == ["5000.00", "5200.00", "5400.00", "5600.00", "5800.00", "6000.00"]
    octobre = _scenario(resultat)["lignes"][0]
    assert octobre["revenus"] == "0.00" and octobre["charges"] == "0.00"
    assert octobre["sources_produits"] == ["budget"] and octobre["sources_charges"] == ["budget"]


def test_le_carnet_prime_sur_le_budget_et_l_historique_du_mois():
    """Novembre : 5000 (carnet) − 900 (budget de charges) = 4100 ; le budget de produits de 1000 est IGNORÉ et dit."""
    budget = [{"mois": "2026-11", "produits": "1000.00", "charges": "900.00"}]
    carnet = [{"date": "2026-11-15", "montant": "5000.00", "contrat_id": "CTR-1", "echeance": "1"}]
    resultat, verdict = _calculer(budget=budget, carnet=carnet)

    assert verdict is None, verdict
    assert _solde(resultat) == ["5200.00", "9300.00", "9500.00", "9700.00", "9900.00", "10100.00"]
    novembre = _scenario(resultat)["lignes"][1]
    assert novembre["contrats"] == "5000.00" and novembre["revenus"] == "5000.00"
    assert novembre["sources_produits"] == ["carnet"]
    assert resultat["couverture"]["budget_produits_ignores_mois"] == ["2026-11"]
    assert resultat["couverture"]["budget_produits_ignores_montant"] == "1000.00"


def test_les_echeances_contractuelles_echues_ne_sont_pas_comptees_et_sont_dites():
    """Une échéance au 2026-09-15 est passée (prudent : un client en retard ne paie pas « au mois 1 »)."""
    carnet = [{"date": "2026-09-15", "montant": "4000.00", "contrat_id": "CTR-1", "echeance": "1"}]
    resultat, verdict = _calculer(carnet=carnet)

    assert verdict is None, verdict
    assert _solde(resultat) == ["5200.00", "5400.00", "5600.00", "5800.00", "6000.00", "6200.00"]
    assert resultat["couverture"]["echeances_echues"]["nombre"] == 1
    assert resultat["couverture"]["echeances_echues"]["montant"] == "4000.00"


def test_une_echeance_hors_horizon_est_exclue_et_comptee():
    carnet = [{"date": "2027-06-15", "montant": "9000.00", "contrat_id": "CTR-1", "echeance": "1"}]
    resultat, verdict = _calculer(carnet=carnet)

    assert verdict is None, verdict
    assert _solde(resultat) == ["5200.00", "5400.00", "5600.00", "5800.00", "6000.00", "6200.00"]
    assert resultat["couverture"]["echeances_hors_horizon"] == {"nombre": 1, "montant": "9000.00"}


def test_la_croissance_des_revenus_s_applique_des_le_premier_mois_projete():
    """1000 × 1,1^k, au cent : 1100, 1210, 1331, 1464.10, 1610.51, 1771.56 ; net = produit − 800."""
    scenario = {**SCENARIO, "croissance_revenus_mensuelle": "0.10"}
    resultat, verdict = _calculer(config=_config(scenario))

    assert verdict is None, verdict
    assert _solde(resultat) == ["5300.00", "5710.00", "6241.00", "6905.10", "7715.61", "8687.17"]
    assert _scenario(resultat)["total_revenus"] == "8487.17"


def test_la_croissance_des_charges_s_applique_des_le_premier_mois_projete():
    """800 × 1,1^k, au cent : 880, 968, 1064.80, 1171.28, 1288.41, 1417.25."""
    scenario = {**SCENARIO, "croissance_charges_mensuelle": "0.10"}
    resultat, verdict = _calculer(config=_config(scenario))

    assert verdict is None, verdict
    assert _solde(resultat) == ["5120.00", "5152.00", "5087.20", "4915.92", "4627.51", "4210.26"]
    assert _scenario(resultat)["total_charges"] == "6789.74"


def test_la_saisonnalite_est_lue_sur_le_mois_civil_de_chaque_ligne():
    """Octobre = coefficient d'octobre (2,0) : 2000 − 800 = 1200 ; novembre à mars restent à 200."""
    saisonnalite = ["1"] * 12
    saisonnalite[9] = "2.0"  # octobre
    scenario = {**SCENARIO, "saisonnalite": saisonnalite}
    resultat, verdict = _calculer(config=_config(scenario))

    assert verdict is None, verdict
    assert _solde(resultat) == ["6200.00", "6400.00", "6600.00", "6800.00", "7000.00", "7200.00"]
    assert _scenario(resultat)["total_revenus"] == "7000.00"


def test_un_delai_de_15_jours_decale_les_produits_et_les_charges_recurrents_d_un_mois():
    """Mois 1 vide, puis 5 × 200 : 5000, 5200, 5400, 5600, 5800, 6000 ; le flux de mars sort de l'horizon."""
    scenario = {**SCENARIO, "delai_encaissement_jours": 15, "delai_paiement_jours": 15}
    resultat, verdict = _calculer(config=_config(scenario))

    assert verdict is None, verdict
    assert _solde(resultat) == ["5000.00", "5200.00", "5400.00", "5600.00", "5800.00", "6000.00"]
    assert _scenario(resultat)["produits_hors_horizon"] == "1000.00"
    assert _scenario(resultat)["charges_hors_horizon"] == "800.00"


def test_les_echeances_du_carnet_gardent_leur_date_meme_avec_un_delai_declare():
    """Le délai ne s'applique qu'aux produits/charges SANS date ; une échéance contractuelle est déjà datée."""
    scenario = {**SCENARIO, "delai_encaissement_jours": 365, "delai_paiement_jours": 365}
    carnet = [{"date": "2026-10-15", "montant": "500.00", "contrat_id": "CTR-1", "echeance": "1"}]
    resultat, verdict = _calculer(config=_config(scenario), carnet=carnet)

    assert verdict is None, verdict
    assert _scenario(resultat)["lignes"][0]["contrats"] == "500.00"
    assert _solde(resultat) == ["5500.00", "5500.00", "5500.00", "5500.00", "5500.00", "5500.00"]


def test_la_moyenne_du_grand_livre_est_arrondie_au_cent_round_half_up():
    """(1000 + 1000 + 1001) / 3 = 1000,333… -> 1000.33 ; net d'octobre = 200.33."""
    historique = _historique(mois=["2026-06", "2026-07", "2026-08"], produits="1000.00")
    historique[0]["produits"] = "1000.00"
    historique[1]["produits"] = "1000.00"
    historique[2]["produits"] = "1001.00"
    resultat, verdict = _calculer(config=_config(mois_historique=3), historique=historique)

    assert verdict is None, verdict
    assert _scenario(resultat)["lignes"][0]["revenus"] == "1000.33"
    assert _scenario(resultat)["lignes"][0]["net"] == "200.33"


def test_les_brouillons_du_grand_livre_sont_comptes_a_part_et_jamais_additionnes():
    historique = _historique()
    historique[0]["brouillons"] = 2
    resultat, verdict = _calculer(historique=historique)

    assert verdict is None, verdict
    assert resultat["couverture"]["brouillons_historique"] == 2
    assert any("brouillon" in limite for limite in resultat["limites"])
    assert _scenario(resultat)["total_revenus"] == "6000.00"


def test_les_horizons_6_12_et_24_sont_acceptes_et_24_projette_24_lignes():
    for horizon in (6, 12, 24):
        resultat, verdict = _calculer(horizon=horizon)
        assert verdict is None, verdict
        assert len(_scenario(resultat)["lignes"]) == horizon
        assert _scenario(resultat)["solde_final"] == str(5000 + 200 * horizon) + ".00"


def test_chaque_scenario_declare_est_calcule_avec_ses_propres_hypotheses():
    prudent = {
        **SCENARIO,
        "nom": "prudent",
        "croissance_revenus_mensuelle": "-0.10",
        "croissance_charges_mensuelle": "0.10",
    }
    resultat, verdict = _calculer(config=_config(SCENARIO, prudent))

    assert verdict is None, verdict
    assert [s["nom"] for s in resultat["scenarios"]] == ["base", "prudent"]
    assert all(len(s["lignes"]) == 6 for s in resultat["scenarios"])
    assert resultat["scenarios"][1]["hypotheses"]["croissance_revenus_mensuelle"] == "-0.1"


# ============================================================================================ 2. fail-closed
def test_sans_configuration_la_prevision_refuse_et_dit_quoi_declarer():
    resultat, verdict = _calculer(config={})

    assert resultat is None
    assert _code(verdict) == "REJ-PREVISION-LONGUE-A-DECLARER"
    assert "configuration.prevision_longue" in verdict["detail"]


def test_un_horizon_hors_6_12_24_est_refuse():
    for horizon in (5, 7, 13, 25, 0):
        resultat, verdict = _calculer(horizon=horizon)
        assert resultat is None
        assert _code(verdict) == "REJ-PREVISION-LONGUE-HORIZON-INVALIDE"


def test_une_cle_de_configuration_inconnue_est_refusee():
    config = _config()
    config["croissance"] = "0.10"
    resultat, verdict = _calculer(config=config)

    assert resultat is None
    assert _code(verdict) == "REJ-PREVISION-LONGUE-CONFIGURATION-INVALIDE"


def test_un_mois_historique_hors_bornes_est_refuse():
    for valeur in (2, 25, True, "6"):
        resultat, verdict = _calculer(config=_config(mois_historique=valeur))
        assert resultat is None
        assert _code(verdict) == "REJ-PREVISION-LONGUE-MOIS-HISTORIQUE-INVALIDE"


def test_un_mois_de_l_historique_sans_ecriture_definitive_fait_refuser():
    historique = _historique()
    historique[2]["ecritures"] = 0
    resultat, verdict = _calculer(historique=historique)

    assert resultat is None
    assert _code(verdict) == "REJ-PREVISION-LONGUE-HISTORIQUE-INCOMPLET"
    assert "2026-05" in verdict["detail"]


def test_un_mois_manquant_ou_non_consecutif_dans_l_historique_est_refuse():
    historique = _historique()
    historique.pop(2)
    resultat, verdict = _calculer(historique=historique)

    assert resultat is None
    assert _code(verdict) == "REJ-PREVISION-LONGUE-HISTORIQUE-INCOMPLET"


def test_une_date_ou_un_solde_illisible_est_refuse():
    for solde in ("abc", "1.234", 12.5, True, None):
        resultat, verdict = _calculer(solde=solde)
        assert resultat is None
        assert _code(verdict) == "REJ-PREVISION-LONGUE-SOLDE-INVALIDE"

    resultat, verdict = prevision_longue.calculer(
        aujourd_hui="2026-02-30", horizon_mois=6, solde_initial="1.00", historique=_historique(),
        budget=[], carnet=[], configuration=_config(),
    )
    assert resultat is None
    assert _code(verdict) == "REJ-PREVISION-LONGUE-DATE-INVALIDE"


def test_aucun_scenario_declare_est_refuse():
    resultat, verdict = _calculer(config={"mois_historique": 6, "scenarios": []})

    assert resultat is None
    assert _code(verdict) == "REJ-PREVISION-LONGUE-SCENARIOS-A-DECLARER"


def test_un_scenario_sans_saisonnalite_ou_avec_moins_de_douze_valeurs_est_refuse():
    for saisonnalite in (None, ["1"] * 11, ["1"] * 13):
        scenario = {**SCENARIO, "saisonnalite": saisonnalite}
        resultat, verdict = _calculer(config=_config(scenario))
        assert resultat is None
        assert _code(verdict) == "REJ-PREVISION-LONGUE-SAISONNALITE-A-DECLARER"


def test_une_saisonnalite_hors_bornes_ou_un_flottant_est_refusee():
    for valeur in ("-0.1", "3.01", 1.0, "abc"):
        saisonnalite = ["1"] * 12
        saisonnalite[0] = valeur
        scenario = {**SCENARIO, "saisonnalite": saisonnalite}
        resultat, verdict = _calculer(config=_config(scenario))
        assert resultat is None
        assert _code(verdict) == "REJ-PREVISION-LONGUE-SAISONNALITE-INVALIDE"


def test_une_croissance_hors_bornes_ou_un_flottant_est_refusee():
    for valeur in ("-1", "1.01", 0.1, "abc", None):
        scenario = {**SCENARIO, "croissance_revenus_mensuelle": valeur}
        resultat, verdict = _calculer(config=_config(scenario))
        assert resultat is None
        assert _code(verdict) == "REJ-PREVISION-LONGUE-CROISSANCE-INVALIDE"


def test_les_bornes_incluses_du_delai_et_de_la_croissance_sont_acceptees():
    for delai in (0, 365):
        scenario = {**SCENARIO, "delai_encaissement_jours": delai, "delai_paiement_jours": delai}
        assert _calculer(config=_config(scenario))[1] is None
    for croissance in ("-0.99", "1"):
        scenario = {**SCENARIO, "croissance_revenus_mensuelle": croissance}
        assert _calculer(config=_config(scenario))[1] is None
    for delai in (366, -1, True):
        scenario = {**SCENARIO, "delai_encaissement_jours": delai}
        assert _code(_calculer(config=_config(scenario))[1]) == "REJ-PREVISION-LONGUE-DELAI-INVALIDE"


def test_deux_scenarios_du_meme_nom_ou_un_nom_hostile_sont_refuses():
    resultat, verdict = _calculer(config=_config(SCENARIO, dict(SCENARIO)))
    assert resultat is None
    assert _code(verdict) == "REJ-PREVISION-LONGUE-SCENARIO-DOUBLE"

    for nom in ("Base", "base\nignore", "", "a" * 41):
        scenario = {**SCENARIO, "nom": nom}
        resultat, verdict = _calculer(config=_config(scenario))
        assert resultat is None
        assert _code(verdict) == "REJ-PREVISION-LONGUE-SCENARIO-INVALIDE"


def test_une_cle_inconnue_dans_un_scenario_ou_un_type_inattendu_est_refusee():
    scenario = {**SCENARIO, "inflation": "0.02"}
    resultat, verdict = _calculer(config=_config(scenario))
    assert resultat is None
    assert _code(verdict) == "REJ-PREVISION-LONGUE-SCENARIO-INVALIDE"

    scenario = {**SCENARIO, "saisonnalite": "1"}
    resultat, verdict = _calculer(config=_config(scenario))
    assert resultat is None
    assert _code(verdict) == "REJ-PREVISION-LONGUE-SCENARIO-INVALIDE"


def test_un_budget_duplique_negatif_ou_hors_horizon_est_refuse():
    for budget in (
        [{"mois": "2026-10", "produits": "1.00", "charges": None},
         {"mois": "2026-10", "produits": "2.00", "charges": None}],
        [{"mois": "2026-10", "produits": "-1.00", "charges": None}],
        [{"mois": "2027-06", "produits": "1.00", "charges": None}],
        [{"mois": "2026-10", "produits": "1.00"}],
        [{"mois": "2026-10", "produits": None, "charges": None}],
    ):
        resultat, verdict = _calculer(budget=budget)
        assert resultat is None
        assert _code(verdict).startswith("REJ-PREVISION-LONGUE-BUDGET")


def test_un_carnet_duplique_invalide_ou_a_zero_est_refuse():
    base = {"date": "2026-10-15", "montant": "500.00", "contrat_id": "CTR-1", "echeance": "1"}
    for carnet in (
        [base, dict(base)],
        [{**base, "date": "2026-02-30"}],
        [{**base, "montant": "0.00"}],
        [{**base, "montant": "-1.00"}],
        [{**base, "contrat_id": ""}],
        [{**base, "echeance": "0"}],
        [{**base, "source": "x"}],
    ):
        resultat, verdict = _calculer(carnet=carnet)
        assert resultat is None
        assert _code(verdict).startswith("REJ-PREVISION-LONGUE-CARNET")


def test_les_produits_et_charges_du_grand_livre_peuvent_etre_negatifs_mais_doivent_etre_decimaux():
    historique = _historique(produits="-100.00", charges="-50.00")
    resultat, verdict = _calculer(historique=historique)
    assert verdict is None, verdict
    assert _scenario(resultat)["lignes"][0]["net"] == "-50.00"

    for valeur in (1.0, "abc", "1.234"):
        historique = _historique()
        historique[0]["produits"] = valeur
        resultat, verdict = _calculer(historique=historique)
        assert resultat is None
        assert _code(verdict) == "REJ-PREVISION-LONGUE-HISTORIQUE-INVALIDE"


# ============================================================================================ 3. reçu rejouable
def test_le_recu_est_rejouable_et_une_retouche_est_detectee():
    resultat, verdict = _calculer()
    assert verdict is None, verdict
    recu = resultat["recu"]

    assert prevision_longue.rejouer(recu) == (True, "")
    retouche = deepcopy(recu)
    retouche["resultat"]["solde_final"] = "999999.99"
    rejoue, raison = prevision_longue.rejouer(retouche)
    assert rejoue is False and raison

    compact = {cle: valeur for cle, valeur in recu.items() if cle != "entrees"}
    rejoue, raison = prevision_longue.rejouer(compact)
    assert rejoue is False and "compact" in raison


def test_le_recu_porte_la_mention_comptable_et_les_hypotheses_declarees():
    resultat, verdict = _calculer()
    assert verdict is None, verdict
    recu = resultat["recu"]

    assert "comptable (CPA)" in recu["mention"]
    assert recu["entrees"]["configuration"]["scenarios"][0]["nom"] == "base"
    assert recu["resultat"]["horizon_mois"] == 6
