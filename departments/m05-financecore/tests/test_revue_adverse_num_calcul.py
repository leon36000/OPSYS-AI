"""Revue adverse (num) : les moteurs de calcul rendent un reçu ou un refus typé, jamais une exception.

Deux défauts trouvés par fuzz de `moteur_calcul` :
- un TRI à très forte dérivée (flux qui ne se récupèrent presque pas) levait `ArithmeticError` : la tolérance
  relative de 1e-20 sur la VAN n'est pas atteignable quand la racine, arrondie à 1e-30, tombe là où |VAN'| vaut 1e14 ;
- `mf.au_cent` arrondissait dans le contexte `decimal` de l'APPELANT (28 chiffres) : une VAN de plus de 26 chiffres
  levait `InvalidOperation` (sensibilité d'un projet à 50 ans, croissance de 100 %).
Données fictives, graines fixes.
"""

from __future__ import annotations

import random
from decimal import Decimal, localcontext

import pytest
from m5_financecore import maths_financieres as mf
from m5_financecore import moteur_calcul, verdicts_calcul

FICTIF = True
D = Decimal

# Six décaissements puis 12 $ : la racine de la VAN est à environ -98,65 % par période, où |VAN'| dépasse 1e14.
FLUX_SANS_ISSUE = ["-565.00", "-958.00", "-869.00", "-421.00", "-395.00", "-886.00", "12.00"]


def _rentabilite(flux, taux="0.05"):
    return moteur_calcul.calculer_rentabilite({"objet": "equipement", "flux": flux, "taux_actualisation": taux})


def test_flux_quasi_irrecuperables_rendent_un_tri_unique_et_non_une_exception():
    sortie, verdict = _rentabilite(FLUX_SANS_ISSUE)
    assert verdict is None
    tri = sortie["recu"]["resultat"]["tri"]
    assert tri["statut"] == "UNIQUE"
    assert tri["valeur"].startswith("-0.98653796890655159663")
    rejeu, verdict = moteur_calcul.rejouer(sortie["recu"])
    assert verdict is None and rejeu["identique"] is True


def test_le_tri_unique_est_encadre_a_un_quantum_pres():
    resultat = mf.tri([D(x) for x in FLUX_SANS_ISSUE])
    assert resultat["statut"] == "UNIQUE"
    flux = [D(x) for x in FLUX_SANS_ISSUE]
    with localcontext(mf.CONTEXTE):
        bas, haut = mf.van(resultat["tri"] - mf.QUANTUM_TRI, flux), mf.van(resultat["tri"] + mf.QUANTUM_TRI, flux)
    assert (bas > 0) != (haut > 0) or 0 in (bas, haut)


def test_tri_ne_leve_jamais_sur_des_flux_a_un_changement_de_signe():
    hasard = random.Random(20261101)
    for _ in range(1500):
        n = hasard.randint(2, 10)
        amplitude = hasard.choice([10, 1_000, 100_000, 10**7, 10**9, 10**11])
        flux = [D(hasard.randint(-amplitude, amplitude)).quantize(D("0.01")) for _ in range(n)]
        flux[0] = -abs(flux[0])
        resultat = mf.tri(flux)  # ne lève pas
        if resultat["statut"] == "UNIQUE":
            tolerance = D(resultat["tolerance_van"])
            with localcontext(mf.CONTEXTE):
                residu = abs(mf.van(resultat["tri"], flux))
                encadre = (mf.van(resultat["tri"] - mf.QUANTUM_TRI, flux) > 0) != (
                    mf.van(resultat["tri"] + mf.QUANTUM_TRI, flux) > 0)
            assert residu <= tolerance or encadre


def test_cas_legitimes_du_tri_restent_inchanges():
    sortie, verdict = _rentabilite(["-1000", "300", "400", "500"], "0.08")
    assert verdict is None
    tri = sortie["recu"]["resultat"]["tri"]
    assert tri["statut"] == "UNIQUE" and tri["valeur"].startswith("0.08896339469")  # 8,896 %
    sans_changement, verdict = _rentabilite(["100", "200", "300"])
    assert verdict is None and sans_changement["recu"]["resultat"]["tri"]["statut"] == "AUCUN_CHANGEMENT_DE_SIGNE"


def test_au_cent_ne_depend_pas_du_contexte_de_l_appelant():
    enorme = D("123456789012345678901234567.896")  # 27 chiffres entiers : 30 chiffres une fois au cent
    assert mf.au_cent(enorme) == D("123456789012345678901234567.90")
    with localcontext() as contexte:
        contexte.prec = 6  # un appelant au contexte étroit ne change pas l'arrondi monétaire
        assert mf.au_cent(D("1234.565")) == D("1234.57")


BASE_EXTREME = {"investissement_initial": "999999999999.99", "flux_annuel": "999999999999.99",
                "croissance_annuelle": "1", "duree_annees": 50, "taux_actualisation": "0.05",
                "valeur_residuelle": "1000"}


def test_sensibilite_d_un_projet_extreme_rend_un_recu_ou_un_refus_jamais_une_exception():
    sortie, verdict = moteur_calcul.analyser_sensibilite({
        "objet": "equipement", "base": BASE_EXTREME, "variations": {},
        "scenarios": [{"nom": "s1", "hypotheses": {"flux_annuel": "1000"}}]})
    assert (sortie is None) != (verdict is None)
    if verdict is not None:
        assert verdict["code"] in verdicts_calcul.CODES_CALCUL
    else:
        assert D(sortie["recu"]["resultat"]["base"]["van"]) > 0


def test_sensibilite_ordinaire_inchangee():
    base = {"investissement_initial": "10000", "flux_annuel": "3000", "croissance_annuelle": "0.02",
            "duree_annees": 5, "taux_actualisation": "0.08", "valeur_residuelle": "0"}
    sortie, verdict = moteur_calcul.analyser_sensibilite({
        "objet": "equipement", "base": base,
        "variations": {"flux_annuel": {"bas": "2500", "haut": "3500"}}, "scenarios": []})
    assert verdict is None
    assert [b["hypothese"] for b in sortie["recu"]["resultat"]["tornade"]] == ["flux_annuel"]


@pytest.mark.parametrize("flux", [FLUX_SANS_ISSUE, ["-1000", "300", "400", "500"]])
def test_un_refus_de_precision_est_un_verdict_catalogue(flux, monkeypatch):
    def _echec(_flux):
        raise ArithmeticError("TRI : non convergent (simulé)")

    monkeypatch.setattr(mf, "tri", _echec)
    sortie, verdict = _rentabilite(flux)
    assert sortie is None and verdict["code"] == "REJ-CALC-RESULTAT-HORS-PRECISION"


def test_encadrement_d_une_racine_a_un_quantum_pres():
    racine = D("0.5")

    def droite(x):
        return racine - x

    with localcontext(mf.CONTEXTE):  # 50 chiffres : 0,5 ± 3e-30 est représentable
        assert mf._encadre(droite, racine) is True  # la VAN s'annule exactement
        assert mf._encadre(droite, racine + mf.QUANTUM_TRI) is True  # à un quantum de la racine : encore encadrée
        assert mf._encadre(droite, racine - mf.QUANTUM_TRI) is True
        assert mf._encadre(droite, racine + 3 * mf.QUANTUM_TRI) is False  # à trois quanta : non
        assert mf._encadre(droite, racine - 3 * mf.QUANTUM_TRI) is False
