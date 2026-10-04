from __future__ import annotations

import json
from decimal import Decimal, localcontext

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import decision_capital, registre

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique

FICTIF = True
D = Decimal
ADMIN = contexte.IdentiteAppelante(personne="admin.capital.fictif", role="admin")


@pytest.fixture
def outil_capital(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-capital-scenario.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "admin.capital.fictif", "Admin Capital Fictif", "mot-de-passe-capital-123", ["admin"]
        )
        registre.enregistrer_mouvement(
            {
                "montant": D("1000.00"),
                "type_mouvement": "ENCAISSEMENT",
                "horodatage": "2026-10-01T09:00:00-04:00",
                "classe_retention": "STANDARD",
                "source": "relevé fictif Q-0",
            },
            m5_outils._registre_mouvements(None),
        )
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(
        yaml.safe_dump(
            {
                "configuration": {
                    "fiscal": {
                        "frequence_tps_tvq": "trimestrielle",
                        "mois_fin_exercice": 12,
                        "taxes_remises_jusqu_au": "2026-09-30",
                    },
                    "obligations_declarees": {
                        "paies": {"montant": "200.00", "source": "paie fictive P-1", "au": "2026-10-01"},
                        "das": {"montant": "0.00", "source": "déclaration fictive D-1", "au": "2026-10-01"},
                        "dettes": {"montant": "0.00", "source": "relevé fictif D-2", "au": "2026-10-01"},
                        "reserves": {"montant": "100.00", "source": "décision fictive R-1", "au": "2026-10-01"},
                    },
                    "prevision": {
                        "horizon_semaines": 2,
                        "seuil_alerte": {"montant": "0.00", "source": "test fictif", "au": "2026-10-01"},
                        "echeances_obligations": {
                            "paies": "2026-10-08",
                            "das": "2026-10-08",
                            "dettes": "2026-10-08",
                        },
                    },
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    yield {o.nom: o for o in m5_outils.outils()}
    stockage.liberer()


def _appeler(outils, arguments):
    with contexte.appele_par_appareil(ADMIN):
        return executer_atomique(outils["m5_preparer_decision_capital"], arguments)


def test_outil_capital_projette_depuis_solde_registre_sans_retirer_cash_libre_deux_fois(outil_capital):
    arguments = {
        "actif": "équipement fictif E-1",
        "prix": "700.00",
        "source_prix": "soumission fictive Q-1",
        "prix_valide_jusqua": "2026-10-30",
        "aujourd_hui": "2026-10-01",
        "offre_financement": {
            "source": "offre de prêt fictive P-1",
            "mise_de_fonds": "100.00",
            "paiement_mensuel": "80.00",
            "mois": 2,
        },
        "offre_location": {
            "source": "offre de location fictive L-1",
            "mise_de_fonds": "50.00",
            "paiement_mensuel": "40.00",
            "mois": 2,
        },
        "echeanciers_hypothetiques": {
            "achat_comptant": {"couvre_jusquau": "2026-10-14", "flux_sorties": [{
                    "type_sortie": "prix",
                    "montant": "700.00",
                    "date": "2026-10-01",
                    "source": "soumission Q-1",
                    "hypothese": "prix payable à la livraison",
                }]},
            "financement": {"couvre_jusquau": "2026-10-14", "flux_sorties": [{
                    "type_sortie": "mise_de_fonds",
                    "montant": "100.00",
                    "date": "2026-10-01",
                    "source": "offre P-1",
                    "hypothese": "mise de fonds selon offre",
                },
                {
                    "type_sortie": "paiement_mensuel",
                    "montant": "80.00",
                    "date": "2026-10-08",
                    "source": "offre P-1",
                    "hypothese": "premier paiement selon offre",
                }]},
            "location": {"couvre_jusquau": "2026-10-14", "flux_sorties": [{
                    "type_sortie": "mise_de_fonds",
                    "montant": "50.00",
                    "date": "2026-10-01",
                    "source": "offre L-1",
                    "hypothese": "mise de fonds selon offre",
                },
                {
                    "type_sortie": "paiement_mensuel",
                    "montant": "40.00",
                    "date": "2026-10-08",
                    "source": "offre L-1",
                    "hypothese": "premier loyer selon offre",
                }]},
        },
    }

    reponse = _appeler(outil_capital, arguments)

    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]["resultat"]
    assert len(json.dumps(reponse["resultat"], ensure_ascii=False)) <= m5_outils.BUDGET_SORTIE
    assert resultat["contexte_financier"]["cash_libre"]["cash_libre"] == "700.00"
    projections = resultat["projections_scenarios"]
    assert projections["statut"] == "CALCULE" and projections["horizon_semaines"] == 2
    assert next(flux for flux in projections["flux_connus_inclus"] if flux["id"] == "obligation:paies") == {
        "id": "obligation:paies",
        "source": "déclaration du propriétaire (configuration.obligations_declarees.paies) : paie fictive P-1",
        "date": "2026-10-08",
        "montant": "200.00",
        "manque": [],
    }
    assert projections["options"] == {
        "achat_comptant": {
            "statut": "CALCULE",
            "solde_fin": "100.00",
            "plus_bas": {"semaine": 2, "solde": "100.00"},
            "manque": [],
            "flux_scenario": [
                {
                    "source": "soumission Q-1",
                    "date": "2026-10-01",
                    "montant": "700.00",
                    "hypothese": "prix payable à la livraison",
                }
            ],
            "statut_provenance": "REFERENCE_MANUELLE_NON_VERIFIEE",
            "couverture_saisie_jusquau": "2026-10-14",
            "sorties_hors_horizon": {"nombre": 0, "total": "0.00", "non_chiffres": 0},
        },
        "financement": {
            "statut": "CALCULE",
            "solde_fin": "620.00",
            "plus_bas": {"semaine": 2, "solde": "620.00"},
            "manque": [],
            "flux_scenario": [
                {
                    "source": "offre P-1",
                    "date": "2026-10-01",
                    "montant": "100.00",
                    "hypothese": "mise de fonds selon offre",
                },
                {
                    "source": "offre P-1",
                    "date": "2026-10-08",
                    "montant": "80.00",
                    "hypothese": "premier paiement selon offre",
                },
            ],
            "statut_provenance": "REFERENCE_MANUELLE_NON_VERIFIEE",
            "couverture_saisie_jusquau": "2026-10-14",
            "sorties_hors_horizon": {"nombre": 0, "total": "0.00", "non_chiffres": 0},
        },
        "location": {
            "statut": "CALCULE",
            "solde_fin": "710.00",
            "plus_bas": {"semaine": 2, "solde": "710.00"},
            "manque": [],
            "flux_scenario": [
                {
                    "source": "offre L-1",
                    "date": "2026-10-01",
                    "montant": "50.00",
                    "hypothese": "mise de fonds selon offre",
                },
                {
                    "source": "offre L-1",
                    "date": "2026-10-08",
                    "montant": "40.00",
                    "hypothese": "premier loyer selon offre",
                },
            ],
            "statut_provenance": "REFERENCE_MANUELLE_NON_VERIFIEE",
            "couverture_saisie_jusquau": "2026-10-14",
            "sorties_hors_horizon": {"nombre": 0, "total": "0.00", "non_chiffres": 0},
        },
    }


def test_scenario_sans_echeancier_est_incomplet_sans_deviner_zero_ou_date(outil_capital):
    arguments = {
        "actif": "camion fictif C-1",
        "prix": "700.00",
        "source_prix": "soumission fictive Q-2",
        "prix_valide_jusqua": "2026-10-30",
        "aujourd_hui": "2026-10-01",
        "offre_financement": {
            "source": "offre de prêt fictive P-2",
            "mise_de_fonds": "0.00",
            "paiement_mensuel": "80.00",
            "mois": 2,
        },
        "offre_location": {
            "source": "offre de location fictive L-2",
            "mise_de_fonds": "0.00",
            "paiement_mensuel": "40.00",
            "mois": 2,
        },
        "echeanciers_hypothetiques": {
            "achat_comptant": {"couvre_jusquau": "2026-10-14", "flux_sorties": [{
                    "type_sortie": "prix",
                    "montant": "700.00",
                    "date": "2026-10-01",
                    "source": "soumission Q-2",
                    "hypothese": "prix à la livraison",
                }]}
        },
    }

    reponse = _appeler(outil_capital, arguments)

    assert reponse["ok"] is True, reponse
    projections = reponse["resultat"]["resultat"]["projections_scenarios"]
    assert projections["statut"] == "PARTIEL"
    assert projections["options"]["achat_comptant"]["statut"] == "CALCULE"
    for nom in ("financement", "location"):
        option = projections["options"][nom]
        assert option["statut"] == "INCOMPLET" and option["solde_fin"] is None
        assert option["manque"] == ["échéancier absent, non rapproché ou couverture déclarée insuffisante"]


def test_echeancier_a_couverture_trop_courte_est_incomplet(outil_capital):
    arguments = {
        "actif": "camion fictif C-3",
        "prix": "700.00",
        "source_prix": "soumission fictive Q-5",
        "prix_valide_jusqua": "2026-10-30",
        "aujourd_hui": "2026-10-01",
        "offre_financement": {
            "source": "offre de prêt fictive P-5", "mise_de_fonds": "0.00", "paiement_mensuel": "80.00", "mois": 2,
        },
        "offre_location": {
            "source": "offre de location fictive L-5", "mise_de_fonds": "0.00", "paiement_mensuel": "40.00", "mois": 2,
        },
        "echeanciers_hypothetiques": {
            "achat_comptant": {
                "couvre_jusquau": "2026-10-02",
                "flux_sorties": [{
                    "type_sortie": "prix", "montant": "700.00", "date": "2026-10-01",
                    "source": "soumission Q-5", "hypothese": "prix à la livraison",
                }],
            }
        },
    }

    reponse = _appeler(outil_capital, arguments)

    assert reponse["ok"] is True, reponse
    projections = reponse["resultat"]["resultat"]["projections_scenarios"]
    option = projections["options"]["achat_comptant"]
    assert option["statut"] == "INCOMPLET" and option["solde_fin"] is None
    assert "couverture" in option["manque"][0]


def test_montant_echeancier_non_rapproche_du_prix_ne_produit_pas_de_prevision(outil_capital):
    arguments = {
        "actif": "camion fictif C-4",
        "prix": "700.00",
        "source_prix": "soumission fictive Q-6",
        "prix_valide_jusqua": "2026-10-30",
        "aujourd_hui": "2026-10-01",
        "offre_financement": {
            "source": "offre de prêt fictive P-6", "mise_de_fonds": "0.00", "paiement_mensuel": "80.00", "mois": 2,
        },
        "offre_location": {
            "source": "offre de location fictive L-6", "mise_de_fonds": "0.00", "paiement_mensuel": "40.00", "mois": 2,
        },
        "echeanciers_hypothetiques": {
            "achat_comptant": {
                "couvre_jusquau": "2026-10-14",
                "flux_sorties": [{
                    "type_sortie": "prix", "montant": "0.00", "date": "2026-10-01",
                    "source": "soumission Q-6", "hypothese": "écart volontaire pour tester le rapprochement",
                }],
            }
        },
    }

    reponse = _appeler(outil_capital, arguments)

    assert reponse["ok"] is True, reponse
    projections = reponse["resultat"]["resultat"]["projections_scenarios"]
    option = projections["options"]["achat_comptant"]
    assert option["statut"] == "INCOMPLET" and option["solde_fin"] is None
    assert "non rapproché" in option["manque"][0]


def test_echeancier_avec_montant_illisible_est_refuse_par_nom(outil_capital):
    arguments = {
        "actif": "équipement fictif E-2",
        "prix": "700.00",
        "source_prix": "soumission fictive Q-3",
        "prix_valide_jusqua": "2026-10-30",
        "aujourd_hui": "2026-10-01",
        "offre_financement": {
            "source": "offre de prêt fictive P-3",
            "mise_de_fonds": "0.00",
            "paiement_mensuel": "80.00",
            "mois": 2,
        },
        "offre_location": {
            "source": "offre de location fictive L-3",
            "mise_de_fonds": "0.00",
            "paiement_mensuel": "40.00",
            "mois": 2,
        },
        "echeanciers_hypothetiques": {
            "achat_comptant": {"couvre_jusquau": "2026-10-14", "flux_sorties": [
                {
                    "type_sortie": "prix",
                    "montant": "NaN",
                    "date": "2026-10-01",
                    "source": "soumission Q-3",
                    "hypothese": "prix à la livraison",
                }
            ]}
        },
    }

    reponse = _appeler(outil_capital, arguments)

    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-CAPITAL-ECHEANCIER-INVALIDE"


def test_provenance_surdimensionnee_garde_les_soldes_inconnus_sous_budget(outil_capital):
    echeancier = [
        {
            "type_sortie": "autre",
            "montant": "10.00",
            "date": "2026-10-01",
            "source": "Q" * 80,
            "hypothese": "H" * 80,
        }
        for _ in range(7)
    ]
    arguments = {
        "actif": "camion fictif C-2",
        "prix": "700.00",
        "source_prix": "soumission fictive Q-4",
        "prix_valide_jusqua": "2026-10-30",
        "aujourd_hui": "2026-10-01",
        "offre_financement": {
            "source": "offre de prêt fictive P-4", "mise_de_fonds": "0.00", "paiement_mensuel": "80.00", "mois": 2,
        },
        "offre_location": {
            "source": "offre de location fictive L-4", "mise_de_fonds": "0.00", "paiement_mensuel": "40.00", "mois": 2,
        },
        "echeanciers_hypothetiques": {
            "achat_comptant": {"couvre_jusquau": "2026-10-14", "flux_sorties": [{
                "type_sortie": "prix", "montant": "700.00", "date": "2026-10-01", "source": "Q", "hypothese": "prix"
            }, *echeancier]},
            "financement": {"couvre_jusquau": "2026-10-14", "flux_sorties": [
                {
                    "type_sortie": "mise_de_fonds", "montant": "0.00", "date": "2026-10-01",
                    "source": "P", "hypothese": "mise nulle",
                },
                {
                    "type_sortie": "paiement_mensuel", "montant": "80.00", "date": "2026-10-08",
                    "source": "P", "hypothese": "paiement",
                },
                *echeancier[:6],
            ]},
            "location": {"couvre_jusquau": "2026-10-14", "flux_sorties": [
                {
                    "type_sortie": "mise_de_fonds", "montant": "0.00", "date": "2026-10-01",
                    "source": "L", "hypothese": "mise nulle",
                },
                {
                    "type_sortie": "paiement_mensuel", "montant": "40.00", "date": "2026-10-08",
                    "source": "L", "hypothese": "paiement",
                },
                *echeancier[:6],
            ]},
        },
    }

    reponse = _appeler(outil_capital, arguments)

    assert reponse["ok"] is True, reponse
    assert len(json.dumps(reponse["resultat"], ensure_ascii=False)) <= m5_outils.BUDGET_SORTIE
    projections = reponse["resultat"]["resultat"]["projections_scenarios"]
    assert projections["statut"] == "NON_CALCULABLE"
    assert "budget" in projections["manque"][0]
    assert all(
        option["statut"] == "NON_CALCULABLE" and option["solde_fin"] is None
        for option in projections["options"].values()
    )


def test_rapprochement_decimal_independant_de_la_precision_appelante():
    offres = {
        "source": "offre fictive",
        "mise_de_fonds": "0.00",
        "paiement_mensuel": "1.00",
        "mois": 1,
    }
    echeanciers = {
        "achat_comptant": {
            "couvre_jusquau": "2026-10-14",
            "flux_sorties": [
                {"type_sortie": "prix", "montant": "1234567.88", "date": "2026-10-01", "source": "Q", "hypothese": "H"},
                {"type_sortie": "prix", "montant": "0.01", "date": "2026-10-02", "source": "Q", "hypothese": "H"},
            ],
        }
    }
    with localcontext() as contexte_decimal:
        contexte_decimal.prec = 2
        normalises, verdict = decision_capital.normaliser_echeanciers(echeanciers, "1234567.89", offres, offres)

    assert verdict is None
    assert normalises is not None
    assert sum((flux["montant"] for flux in normalises["achat_comptant"]), Decimal("0")) == Decimal("1234567.89")


def test_reponse_trop_grosse_apres_repli_budgetaire_est_refusee(outil_capital, monkeypatch):
    arguments = {
        "actif": "camion fictif budget",
        "prix": "700.00",
        "source_prix": "soumission fictive Q-budget",
        "prix_valide_jusqua": "2026-10-30",
        "aujourd_hui": "2026-10-01",
        "offre_financement": {"source": "offre P", "mise_de_fonds": "0.00", "paiement_mensuel": "80.00", "mois": 2},
        "offre_location": {"source": "offre L", "mise_de_fonds": "0.00", "paiement_mensuel": "40.00", "mois": 2},
        "echeanciers_hypothetiques": {},
    }
    monkeypatch.setattr(m5_outils, "BUDGET_SORTIE", 100)

    reponse = _appeler(outil_capital, arguments)

    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-PREVISION-REPONSE-TROP-GROSSE"
