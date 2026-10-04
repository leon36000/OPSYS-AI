from decimal import Decimal

from m5_financecore import decision_capital, outils

FICTIF = True


def test_contrat_agent_financement_location_est_ferme_et_utilise_des_montants_texte():
    outil = next(o for o in outils.outils() if o.nom == "m5_preparer_decision_capital")
    for cle in ("offre_financement", "offre_location"):
        schema = outil.parametres["properties"][cle]
        assert schema["required"] == ["source", "mise_de_fonds", "paiement_mensuel", "mois"]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["mise_de_fonds"]["type"] == "string"
        assert schema["properties"]["paiement_mensuel"]["type"] == "string"
        assert schema["properties"]["mois"]["minimum"] == 1
    outil = next(o for o in outils.outils() if o.nom == "m5_preparer_decision_capital")
    schema_echeanciers = outil.parametres["properties"]["echeanciers_hypothetiques"]
    assert "echeanciers_hypothetiques" not in outil.parametres["required"]
    assert schema_echeanciers["additionalProperties"] is False
    financement = schema_echeanciers["properties"]["financement"]
    assert financement["required"] == ["couvre_jusquau", "flux_sorties"]
    assert financement["properties"]["flux_sorties"]["maxItems"] == 8
    assert financement["properties"]["flux_sorties"]["items"]["required"] == [
        "type_sortie",
        "montant",
        "date",
        "source",
        "hypothese",
    ]


def test_refuse_cash_libre_absent_ou_non_calculable():
    sortie = decision_capital.preparer(
        "CAMION",
        "95000.00",
        "Offre concessionnaire 44",
        "2026-10-30",
        "2026-09-30",
        {"calculable": False, "manque": ["paies", "taxes"]},
        {"source": "Banque", "mise_de_fonds": "5000.00", "paiement_mensuel": "1600.00", "mois": 60},
        {"source": "Bailleur", "mise_de_fonds": "3000.00", "paiement_mensuel": "1800.00", "mois": 48},
    )
    assert sortie["accepte"] is False
    assert sortie["verdict"]["code"] == "REJ-CAPITAL-CASH-LIBRE-NON-CALCULABLE"
    assert sortie["verdict"]["manque"] == ["paies", "taxes"]


def test_compare_cash_finance_location_et_sources_sans_recommander_achat():
    sortie = decision_capital.preparer(
        "Équipement",
        "50000.00",
        "Soumission fournisseur Q-52",
        "2026-10-30",
        "2026-09-30",
        {"calculable": True, "cash_libre": Decimal("72000.00"), "sources": ["grand-livre", "paies", "TPS/TVQ"]},
        {"source": "Offre de prêt P-8", "mise_de_fonds": "8000.00", "paiement_mensuel": "950.00", "mois": 60},
        {"source": "Offre de location L-2", "mise_de_fonds": "2500.00", "paiement_mensuel": "1100.00", "mois": 48},
    )
    assert sortie["accepte"] is True
    result = sortie["resultat"]
    assert result["scenarios"]["achat_comptant"]["cash_libre_apres"] == "22000.00"
    assert result["scenarios"]["financement"]["total_paiements_cites"] == "65000.00"
    assert result["scenarios"]["location"]["total_paiements_cites"] == "55300.00"
    assert result["action_proposee"] == "DEMANDER_APPROBATION_HUMAINE"
    assert "acheter" not in result["action_proposee"].lower()


def test_refuse_offre_fournisseur_expiree():
    sortie = decision_capital.preparer(
        "Camion",
        "95000.00",
        "Offre expirée",
        "2026-09-29",
        "2026-09-30",
        {"calculable": True, "cash_libre": Decimal("150000.00"), "sources": ["grand-livre"]},
        {"source": "Prêt", "mise_de_fonds": "5000.00", "paiement_mensuel": "1600.00", "mois": 60},
        {"source": "Location", "mise_de_fonds": "3000.00", "paiement_mensuel": "1800.00", "mois": 48},
    )
    assert sortie["accepte"] is False
    assert sortie["verdict"]["code"] == "REJ-CAPITAL-SOUMISSION-EXPIREE"


def test_cash_libre_deficitaire_est_rendu_comme_deficit_dans_le_scenario_comptant():
    sortie = decision_capital.preparer(
        "Camion",
        "95000.00",
        "Référence d'offre fictive C-9",
        "2026-10-30",
        "2026-09-30",
        {"calculable": True, "cash_libre": Decimal("-12000.00"), "sources": ["registre principal"]},
        {"source": "Offre de prêt fictive P-9", "mise_de_fonds": "5000.00", "paiement_mensuel": "1600.00", "mois": 60},
        {
            "source": "Offre de location fictive L-9",
            "mise_de_fonds": "3000.00",
            "paiement_mensuel": "1800.00",
            "mois": 48,
        },
    )

    assert sortie["accepte"] is True
    assert sortie["resultat"]["cash_libre_actuel"] == "-12000.00"
    assert sortie["resultat"]["scenarios"]["achat_comptant"]["cash_libre_apres"] == "-107000.00"
