"""Arithmétique décimale partagée (`nombres.py`, PLAN T1.5-d et T4.19) : lire un nombre, l'écrire en texte, lire
un seuil. Les mesures d'un chantier et l'entonnoir s'en servent : une seule règle d'arrondi, une seule lecture d'un
seuil. Les valeurs sont fictives."""

from __future__ import annotations

from decimal import Decimal

import pytest
from m8_analytics import mesures_chantier, nombres


@pytest.mark.parametrize(("brut", "attendu"), [
    ("12.50", Decimal("12.50")),
    ("  7 ", Decimal("7")),
    (3, Decimal("3")),
    (0.5, Decimal("0.5")),
    ("-1234.567", Decimal("-1234.567")),
])
def test_decimal_lu_lit_un_nombre_ou_un_texte_decimal(brut, attendu):
    lu = nombres.decimal_lu(brut)
    assert lu == attendu and isinstance(lu, Decimal)


@pytest.mark.parametrize(
    "brut", [None, True, False, "", "abc", "12,50 $", "NaN", "Infinity", "-Infinity", float("nan")]
)
def test_decimal_lu_refuse_tout_ce_qui_n_est_pas_un_nombre_fini_sans_valeur_par_defaut(brut):
    assert nombres.decimal_lu(brut) is None


@pytest.mark.parametrize(("valeur", "attendu"), [
    (Decimal("2"), "2.00"),
    (Decimal("1.005"), "1.01"),  # ROUND_HALF_UP : un demi monte, jamais l'arrondi au pair de Python
    (Decimal("1.004"), "1.00"),
    (Decimal("-1.005"), "-1.01"),
    (Decimal("-0.001"), "0.00"),  # jamais « -0.00 »
    (Decimal("1234567.891"), "1234567.89"),  # jamais une notation scientifique
    (Decimal("1E+3"), "1000.00"),
])
def test_texte_decimal_ecrit_deux_decimales_au_demi_superieur(valeur, attendu):
    assert nombres.texte_decimal(valeur) == attendu


def test_seuil_valide_lit_un_sens_connu_et_une_valeur_numerique():
    assert nombres.seuil_valide({"sens": "au_dessus", "valeur": 30}) == {"sens": "au_dessus", "valeur": Decimal("30")}
    assert nombres.seuil_valide({"sens": "au_dessous", "valeur": 12.5}) == {
        "sens": "au_dessous", "valeur": Decimal("12.5"),
    }


@pytest.mark.parametrize("brut", [
    None, "au_dessus", [], {},
    {"sens": "au_dessus"},  # valeur absente
    {"valeur": 3},  # sens absent
    {"sens": "au-dessus", "valeur": 3},  # sens inconnu
    {"sens": "au_dessus", "valeur": True},  # un booléen n'est pas un nombre
    {"sens": "au_dessus", "valeur": "30"},  # un texte non plus : le YAML doit porter un nombre
    {"sens": "au_dessus", "valeur": float("nan")},
    {"sens": "au_dessus", "valeur": 3, "unite": "%"},  # une clé de plus est une faute de frappe
])
def test_seuil_valide_refuse_toute_autre_forme(brut):
    assert nombres.seuil_valide(brut) is None


def test_les_sens_de_seuil_d_un_chantier_sont_ceux_de_nombres():
    """Une seule définition des sens : `mesures_chantier` la reprend, elle ne la copie pas."""
    assert mesures_chantier.SENS_AU_DESSUS is nombres.SENS_AU_DESSUS
    assert mesures_chantier.SENS_AU_DESSOUS is nombres.SENS_AU_DESSOUS
