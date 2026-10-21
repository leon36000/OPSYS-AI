from datetime import date
from decimal import Decimal

from m5_financecore import prevision


def _flux(identifiant: str, sens: str, montant: str, jour: date, source: str) -> dict[str, object]:
    flux = {
        "id": identifiant,
        "sens": sens,
        "nature": "obligation" if identifiant.startswith("obligation:") else "scenario_capital",
        "montant": Decimal(montant),
        "date": jour,
        "regle_de_date": "date déclarée dans la source fictive",
        "source": source,
        "hypothese": "hypothèse fictive de date",
        "manque": [],
        "reserves": [],
    }
    if identifiant.startswith("capital:"):
        flux["couvre_jusquau"] = date(2026, 10, 14)
    return flux


def test_projection_capital_reutilise_obligation_une_fois_pour_les_trois_options():
    aujourd_hui = date(2026, 10, 1)
    solde = {
        "id": "solde",
        "montant": Decimal("1000.00"),
        "manque": [],
        "source": {"description": "registre fictif", "registres": []},
        "fraicheur": {"derniere_piece": "2026-10-01", "pieces": 1},
    }
    obligations_connues = [
        _flux("obligation:paie-fictive", prevision.SORTIE, "200.00", date(2026, 10, 8), "déclaration fictive")
    ]
    sorties = {
        "achat_comptant": [_flux("capital:cash:0", prevision.SORTIE, "700.00", aujourd_hui, "offre fictive Q-1")],
        "financement": [
            _flux("capital:pret:0", prevision.SORTIE, "100.00", aujourd_hui, "offre fictive P-1"),
            _flux("capital:pret:1", prevision.SORTIE, "80.00", date(2026, 10, 8), "échéance citée P-1"),
        ],
        "location": [
            _flux("capital:bail:0", prevision.SORTIE, "50.00", aujourd_hui, "offre fictive L-1"),
            _flux("capital:bail:1", prevision.SORTIE, "40.00", date(2026, 10, 8), "échéance citée L-1"),
        ],
    }

    resultat = prevision.projeter_scenarios(aujourd_hui, 2, solde, obligations_connues, sorties)
    projections = resultat["options"]

    assert resultat["flux_connus_inclus"] == [
        {
            "id": "obligation:paie-fictive",
            "source": "déclaration fictive",
            "date": "2026-10-08",
            "montant": "200.00",
            "manque": [],
        }
    ]

    assert {nom: (projection["solde_fin"], projection["plus_bas"]) for nom, projection in projections.items()} == {
        "achat_comptant": ("100.00", {"semaine": 2, "solde": "100.00"}),
        "financement": ("620.00", {"semaine": 2, "solde": "620.00"}),
        "location": ("710.00", {"semaine": 2, "solde": "710.00"}),
    }
    assert projections["achat_comptant"]["flux_scenario"] == [
        {
            "source": "offre fictive Q-1",
            "date": "2026-10-01",
            "montant": "700.00",
            "hypothese": "hypothèse fictive de date",
        }
    ]
    assert projections["financement"]["statut_provenance"] == "REFERENCE_MANUELLE_NON_VERIFIEE"
