"""Statistiques déterministes en Decimal : comparées à des oracles INDÉPENDANTS (stdlib flottante, valeurs publiées)."""

from __future__ import annotations

import math
import statistics
from decimal import Decimal as D

import pytest
from m7_marketing.mesure import statistiques as st


@pytest.mark.parametrize("z", ["-8", "-3.1", "-1", "0", "0.5", "1.96", "3", "7.9"])
def test_phi_suit_la_loi_normale_de_la_stdlib(z):
    attendu = statistics.NormalDist().cdf(float(z))
    assert abs(float(st.phi(D(z))) - attendu) < 1e-12


def test_phi_au_dela_de_8_3_vaut_zero_ou_un_et_refuse_ce_qui_n_est_pas_decimal():
    assert st.phi(D("9")) == 1 and st.phi(D("-9")) == 0
    with pytest.raises(ValueError):
        st.phi(1.96)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        st.phi(D("NaN"))


@pytest.mark.parametrize("p", ["0.5", "0.8", "0.9", "0.975", "0.995", "0.001"])
def test_quantile_inverse_de_phi(p):
    z = st.quantile(D(p))
    assert abs(float(z) - statistics.NormalDist().inv_cdf(float(p))) < 1e-9
    assert abs(float(st.phi(z)) - float(p)) < 1e-11


@pytest.mark.parametrize("p", ["0", "1", "-0.1", "1.2"])
def test_quantile_refuse_hors_de_0_1(p):
    with pytest.raises(ValueError):
        st.quantile(D(p))


def test_z_des_niveaux_usuels_valeurs_publiees():
    assert st.texte(st.z_pour_niveau(D("0.95"))) == "1.959964"
    assert st.texte(st.z_pour_niveau(D("0.99"))) == "2.575829"
    assert st.texte(st.z_pour_niveau(D("0.90"))) == "1.644854"
    with pytest.raises(ValueError):
        st.z_pour_niveau(D("0.97"))


def _wilson_oracle(k, n, z=1.959964):
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    demi = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - demi, centre + demi


@pytest.mark.parametrize("k,n", [(5, 20), (0, 10), (10, 10), (1, 3), (300, 1000), (37, 41)])
def test_wilson_contre_la_formule_a_la_main(k, n):
    bas, haut = st.wilson(k, n)
    obt_bas, obt_haut = _wilson_oracle(k, n)
    assert abs(float(bas) - max(0.0, obt_bas)) < 1e-6 and abs(float(haut) - min(1.0, obt_haut)) < 1e-6


def test_wilson_valeur_connue_5_sur_20():
    # Valeur publiée de l'intervalle de Wilson 95 % pour 5/20 : [0,1119 ; 0,4687]
    bas, haut = st.wilson(5, 20)
    assert st.texte(bas, D("0.0001")) == "0.1119" and st.texte(haut, D("0.0001")) == "0.4687"


@pytest.mark.parametrize("k,n", [(-1, 5), (6, 5), (1, 0), (True, 5), (1.0, 5)])
def test_wilson_refuse_les_comptes_impossibles(k, n):
    with pytest.raises(ValueError):
        st.wilson(k, n)


def test_wilson_les_bornes_encadrent_la_proportion_et_se_resserrent_avec_n():
    petit = st.wilson(3, 10)
    grand = st.wilson(300, 1000)
    assert petit[0] < D("0.3") < petit[1]
    assert (grand[1] - grand[0]) < (petit[1] - petit[0])


def test_ecart_de_proportions_newcombe_contient_l_ecart_et_exclut_zero_quand_il_est_net():
    d, bas, haut = st.ecart_proportions(300, 1000, 200, 1000)
    assert d == D("0.1") and bas < d < haut and bas > 0
    d0, bas0, haut0 = st.ecart_proportions(20, 100, 20, 100)
    assert d0 == 0 and bas0 < 0 < haut0
    assert abs(float(bas) - 0.0637) < 0.002 and abs(float(haut) - 0.1359) < 0.002  # calcul à la main (Newcombe)


def test_texte_arrondit_au_demi_superieur_et_n_ecrit_jamais_moins_zero():
    assert st.texte(D("0.0000005")) == "0.000001"
    assert st.texte(D("-0.0000001")) == "0"
    assert st.texte(D("2.500000")) == "2.5"
