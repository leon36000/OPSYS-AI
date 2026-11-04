"""Frontières techniques des dates du calcul M5, sur des données fictives."""

from m5_financecore import prevision_longue


def _calculer_fin_2999(mois):
    scenario = {
        "nom": "base",
        "croissance_revenus_mensuelle": "0",
        "croissance_charges_mensuelle": "0",
        "saisonnalite": ["1"] * 12,
        "delai_encaissement_jours": 0,
        "delai_paiement_jours": 0,
    }
    # Les six mois précédents restent dans la plage de dates technique.
    historique = [
        {"mois": f"2999-{m:02d}", "produits": "100.00", "charges": "50.00", "ecritures": 1, "brouillons": 0}
        for m in range(mois - 6, mois)
    ]
    return prevision_longue.calculer(
        aujourd_hui=f"2999-{mois:02d}-01",
        horizon_mois=6,
        solde_initial="100.00",
        historique=historique,
        budget=[],
        carnet=[],
        configuration={"mois_historique": 6, "scenarios": [scenario]},
    )


def test_horizon_qui_depasse_la_plage_des_mois_est_refuse_sans_exception():
    resultat, verdict = _calculer_fin_2999(12)
    assert resultat is None
    assert verdict["code"] == "REJ-PREVISION-LONGUE-DATE-INVALIDE"


def test_dernier_mois_projete_en_decembre_2999_reste_admis():
    # Juin est couvert avec un historique fictif de décembre 2998 à mai 2999.
    scenario = {
        "nom": "base", "croissance_revenus_mensuelle": "0", "croissance_charges_mensuelle": "0",
        "saisonnalite": ["1"] * 12, "delai_encaissement_jours": 0, "delai_paiement_jours": 0,
    }
    historique = [
        {"mois": mois, "produits": "100.00", "charges": "50.00", "ecritures": 1, "brouillons": 0}
        for mois in ["2998-12", "2999-01", "2999-02", "2999-03", "2999-04", "2999-05"]
    ]
    resultat, verdict = prevision_longue.calculer(
        aujourd_hui="2999-06-01", horizon_mois=6, solde_initial="100.00", historique=historique,
        budget=[], carnet=[], configuration={"mois_historique": 6, "scenarios": [scenario]},
    )
    assert verdict is None
    assert resultat["dernier_mois"] == "2999-12"


def test_premier_mois_historique_en_janvier_1900_est_admis_mais_pas_avant():
    scenario = {
        "nom": "base", "croissance_revenus_mensuelle": "0", "croissance_charges_mensuelle": "0",
        "saisonnalite": ["1"] * 12, "delai_encaissement_jours": 0, "delai_paiement_jours": 0,
    }
    historique = [
        {"mois": f"1900-{mois:02d}", "produits": "100.00", "charges": "50.00", "ecritures": 1, "brouillons": 0}
        for mois in range(1, 7)
    ]
    arguments = {
        "horizon_mois": 6, "solde_initial": "100.00", "historique": historique,
        "budget": [], "carnet": [], "configuration": {"mois_historique": 6, "scenarios": [scenario]},
    }
    resultat, verdict = prevision_longue.calculer(aujourd_hui="1900-07-01", **arguments)
    assert verdict is None
    assert resultat["premier_mois"] == "1900-08"
    resultat, verdict = prevision_longue.calculer(aujourd_hui="1900-06-01", **arguments)
    assert resultat is None
    assert verdict["code"] == "REJ-PREVISION-LONGUE-DATE-INVALIDE"
