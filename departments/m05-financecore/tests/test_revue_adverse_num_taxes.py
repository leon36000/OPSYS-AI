"""Revue adverse (num) : `taxes.calculer_taxes` n'accepte qu'un montant au CENT.

Défaut trouvé : un montant avant taxes de `100.005` (ou `0.001`, `-12.345`) était accepté ; les taxes étaient calculées
et arrondies, mais le montant et le TOTAL APRÈS TAXES gardaient leurs trois décimales (114,985 $ pour
`m5_calculer_taxes_tps_tvq`, l'outil de calcul que les agents appellent). Aucun montant de facture n'a de fraction de
cent ; arrondir en silence serait choisir un arrondi à la place de l'appelant. Données fictives.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import outils as outils_m5
from m5_financecore import taux_fiscaux, taxes

FICTIF = True
D = Decimal
_M5 = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dictionnaire():
    taux, erreurs = taux_fiscaux.charger_taux_fiscaux(_M5 / "contracts" / "taux_fiscaux.v1.yaml")
    assert erreurs == []
    return taux


@pytest.mark.parametrize("montant", ["100.005", "0.001", "-12.345", "99999999999.999", "1E-9999999", "0.0100001"])
def test_un_montant_sous_le_cent_est_refuse(dictionnaire, montant):
    resultat, verdict = taxes.calculer_taxes(D(montant), dictionnaire)
    assert resultat is None and verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"
    assert "cent" in verdict["detail"]


@pytest.mark.parametrize("montant, tps, tvq", [
    ("100.00", "5.00", "9.98"), ("100", "5.00", "9.98"), ("0.00", "0.00", "0.00"), ("0.10", "0.01", "0.01"),
    ("-100.00", "-5.00", "-9.98"), ("1E+2", "5.00", "9.98"), ("999999999999.99", "50000000000.00", "99750000000.00"),
    ("1.10", "0.06", "0.11"),  # TPS 0,055 -> 0,06 (demi-cent vers le haut) ; TVQ 0,109725 -> 0,11
])
def test_les_montants_au_cent_gardent_leurs_taxes(dictionnaire, montant, tps, tvq):
    resultat, verdict = taxes.calculer_taxes(D(montant), dictionnaire)
    assert verdict is None
    par_id = {t["id"]: t["montant"] for t in resultat["taxes"]}
    assert (par_id["tps_federale"], par_id["tvq_quebec"]) == (D(tps), D(tvq))
    assert resultat["montant_apres_taxes"] == D(montant) + D(tps) + D(tvq)


def test_l_outil_agent_refuse_un_montant_sous_le_cent():
    reponse = outils_m5.calculer_taxes_tps_tvq("100.005")
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"
    ok = outils_m5.calculer_taxes_tps_tvq("100.00")
    assert ok["accepte"] is True and ok["resultat"]["montant_apres_taxes"] == D("114.98")
