"""Revue adverse (num) : `releve_bancaire.analyser_montant` ne lit un montant à DEUX séparateurs que si les milliers
sont des groupes de trois chiffres séparés par UN seul caractère, l'autre étant le séparateur décimal.

Défaut trouvé : dès que « , » et « . » figuraient tous deux, le dernier était pris pour le séparateur décimal et l'autre
était SUPPRIMÉ, où qu'il soit : « 1.23,45 » devenait 123,45 $, « 1,2,3.45 » 123,45 $ et « 12,34,56.78 »
123 456,78 $, des nombres mal formés lus comme des montants plausibles au lieu d'être refusés comme ambigus (le cas
à un seul séparateur, « 1,234 », l'était déjà). Données fictives.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from m5_financecore import releve_bancaire as rb

FICTIF = True
D = Decimal


@pytest.mark.parametrize("texte", ["1.23,45", "1,2,3.45", "12,34,56.78", "1.2.3,45", "1,23.45", "12.34,5", "1,5.5",
                                   "1234.567,89", "1.234.56,78", "0.5,5", ",1.234,56", "1.,23", "1,.23", "1.234,"])
def test_un_montant_a_deux_separateurs_mal_groupes_est_refuse_comme_ambigu_ou_invalide(texte):
    montant, raison = rb.analyser_montant(texte)
    assert montant is None and raison in ("ambigu", "invalide")


@pytest.mark.parametrize("texte, attendu", [
    ("1,234.56", D("1234.56")), ("1.234,56", D("1234.56")), ("1,234,567.89", D("1234567.89")),
    ("1.234.567,89", D("1234567.89")), ("12,345.6", D("12345.60")), ("999.999,99", D("999999.99")),
    ("(1 234,56)", D("-1234.56")), ("1 234,56", D("1234.56")), ("-1,234.56", D("-1234.56")),
    ("1.234,56-", D("-1234.56")),
    ("1234,56", D("1234.56")), ("1234.56", D("1234.56")), ("$1,234.56", D("1234.56")), ("12,5", D("12.50")),
    ("0,5", D("0.50")), ("100", D("100.00")), ("-0", D("0.00")),
])
def test_les_montants_bien_formes_restent_lus(texte, attendu):
    assert rb.analyser_montant(texte) == (attendu, None)


def test_l_ancien_comportement_a_un_seul_separateur_est_inchange():
    assert rb.analyser_montant("1,234") == (None, "ambigu")
    assert rb.analyser_montant("1,234,567") == (None, "ambigu")
    assert rb.analyser_montant("12,3") == (D("12.30"), None)
    assert rb.analyser_montant("1.234") == (None, "invalide")
