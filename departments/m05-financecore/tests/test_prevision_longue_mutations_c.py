"""Régressions publiques M5-PREV-2 pour les survivants mutkit #69/#108/#112/#135/#136/#146/#153/#219.

Fixtures synthétiques uniquement. Le fichier reste hors du worktree M5 afin de ne pas interférer avec les agents.
Exécution depuis le worktree M5 :
  PYTHONPATH=departments/m05-financecore/src .venv/bin/pytest -q /path/to/test_m5_mutation_regressions.py
"""

from __future__ import annotations

from datetime import date

import pytest
from m5_financecore import prevision_longue

AUJOURD_HUI = "2026-09-30"
HORIZON = 6
SOLDE = "5000.00"


def _mois_precedents(aujourd_hui: str, nombre: int) -> list[str]:
    """Génère indépendamment les N mois complets précédant le mois courant."""
    jour = date.fromisoformat(aujourd_hui)
    index = jour.year * 12 + jour.month - 1
    mois = []
    for decalage in range(nombre, 0, -1):
        annee, mois_zero = divmod(index - decalage, 12)
        mois.append(f"{annee:04d}-{mois_zero + 1:02d}")
    return mois


def _historique(aujourd_hui: str = AUJOURD_HUI, nombre: int = 3):
    return [
        {"mois": mois, "produits": "1000.00", "charges": "800.00", "ecritures": 1, "brouillons": 0}
        for mois in _mois_precedents(aujourd_hui, nombre)
    ]


def _scenario(*, nom="base", coefficient_octobre="1"):
    saisonnalite = ["1"] * 12
    saisonnalite[9] = coefficient_octobre  # la première ligne projetée est octobre 2026
    return {
        "nom": nom,
        "croissance_revenus_mensuelle": "0",
        "croissance_charges_mensuelle": "0",
        "saisonnalite": saisonnalite,
        "delai_encaissement_jours": 0,
        "delai_paiement_jours": 0,
    }


def _configuration(*, mois_historique=3, nombre_scenarios=1, coefficient_octobre="1"):
    return {
        "mois_historique": mois_historique,
        "scenarios": [
            _scenario(nom=f"s{i}", coefficient_octobre=coefficient_octobre)
            for i in range(nombre_scenarios)
        ],
    }


def _calculer(
    *,
    aujourd_hui=AUJOURD_HUI,
    horizon=HORIZON,
    mois_historique=3,
    nombre_scenarios=1,
    coefficient_octobre="1",
    historique=None,
    budget=(),
    carnet=(),
):
    return prevision_longue.calculer(
        aujourd_hui=aujourd_hui,
        horizon_mois=horizon,
        solde_initial=SOLDE,
        historique=(
            _historique(aujourd_hui, mois_historique) if historique is None else historique
        ),
        budget=list(budget),
        carnet=list(carnet),
        configuration=_configuration(
            mois_historique=mois_historique,
            nombre_scenarios=nombre_scenarios,
            coefficient_octobre=coefficient_octobre,
        ),
    )


def test_borne_haute_2999_refuse_sans_exception():
    """Le premier mois projeté qui tomberait en 3000 doit être refusé proprement."""
    resultat, verdict = _calculer(aujourd_hui="2999-07-15")

    assert resultat is None
    assert verdict is not None
    assert verdict["code"] == "REJ-PREVISION-LONGUE-DATE-INVALIDE"


def test_echeance_positive_de_un_dollar_est_incluse():
    resultat, verdict = _calculer(
        carnet=[{"date": "2026-10-15", "montant": "1.00", "contrat_id": "C-1", "echeance": "1"}]
    )

    assert verdict is None
    assert resultat is not None
    octobre = resultat["scenarios"][0]["lignes"][0]
    assert octobre["contrats"] == "1.00"
    assert octobre["revenus"] == "1.00"
    assert octobre["solde_projete"] == "4201.00"


@pytest.mark.parametrize(
    ("coefficient", "solde_octobre"),
    [("0", "4200.00"), ("3", "7200.00")],
)
def test_bornes_saisonnieres_zero_et_trois_sont_inclusives(coefficient, solde_octobre):
    resultat, verdict = _calculer(coefficient_octobre=coefficient)

    assert verdict is None
    assert resultat is not None
    assert resultat["scenarios"][0]["lignes"][0]["solde_projete"] == solde_octobre


def test_24_mois_historique_est_la_borne_haute_valide():
    resultat, verdict = _calculer(mois_historique=24)

    assert verdict is None
    assert resultat is not None
    assert len(resultat["recu"]["entrees"]["historique"]) == 24
    assert len(resultat["scenarios"][0]["lignes"]) == HORIZON


def test_quatre_scenarios_sont_acceptes():
    resultat, verdict = _calculer(nombre_scenarios=4)

    assert verdict is None
    assert resultat is not None
    assert [s["nom"] for s in resultat["scenarios"]] == ["s0", "s1", "s2", "s3"]


@pytest.mark.parametrize(
    ("historique", "code"),
    [
        (42, "REJ-PREVISION-LONGUE-HISTORIQUE-INCOMPLET"),
        ([None, None, None], "REJ-PREVISION-LONGUE-HISTORIQUE-INVALIDE"),
    ],
)
def test_historique_malforme_rend_un_verdict_plutot_qu_une_exception(historique, code):
    resultat, verdict = _calculer(historique=historique)

    assert resultat is None
    assert verdict is not None
    assert verdict["code"] == code
