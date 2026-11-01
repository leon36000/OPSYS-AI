"""Revue adverse (num) : `nombres.decimal_lu` borne l'ORDRE DE GRANDEUR des nombres lus.

Défaut trouvé : `decimal_lu` ne refusait que le non-fini. Un `prix_total` de `1E+30` (ou de 32 chiffres) dans UN seul
fait de devis accepté faisait lever `InvalidOperation` à `texte_decimal` (contexte de 28 chiffres) dans la mesure
`m8_carnet_signe_cad`, donc dans `entonnoir.mesurer` et dans tout ce qui lit les mesures (wallboards, vue exécutive,
score de santé) ; `1e999999999` levait `Overflow`. Un seuil de configuration de `1e30` faisait de même, et une borne de
santé de `1e-999999999` se formatait en un milliard de caractères. Un nombre hors de [1e-15, 1e15] en valeur absolue
n'est plus « lisible » : la mesure est non calculable et le dit (jamais un plantage). Données fictives.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from m8_analytics import entonnoir, nombres, sante, wallboards

FICTIF = True
H = "2026-10-01T10:00:00+00:00"


@pytest.mark.parametrize("brut", ["1E+30", "1e999999999", "-1E+16", 1e30, 10**32, "1e-999999999", "1E-16", -1e-30,
                                  12345678901234567890123456789012,
                                  pytest.param(10**5000, id="entier-de-5001-chiffres")])
def test_un_nombre_hors_de_l_ordre_de_grandeur_lisible_est_refuse(brut):
    assert nombres.decimal_lu(brut) is None


@pytest.mark.parametrize(("brut", "attendu"), [
    ("1E+15", Decimal("1E+15")), ("999999999999.99", Decimal("999999999999.99")), ("0.000001", Decimal("0.000001")),
    (1e6, Decimal("1000000.0")), ("-5", Decimal("-5")), (0, Decimal(0)), ("0.00", Decimal("0.00")),
    ("1E-15", Decimal("1E-15")),
])
def test_les_nombres_ordinaires_restent_lus(brut, attendu):
    lu = nombres.decimal_lu(brut)
    assert lu == attendu


@pytest.mark.parametrize("zero", ["0E+999999", "0E-999999999", "-0", "0e5"])
def test_un_zero_a_exposant_demesure_est_un_zero_court(zero):
    lu = nombres.decimal_lu(zero)
    assert lu == 0 and abs(lu.as_tuple().exponent) < 10  # jamais un milliard de zéros à écrire


@pytest.mark.parametrize("prix", ["1E+30", "1e999999999", 12345678901234567890123456789012])
def test_un_prix_demesure_dans_un_fait_rend_la_mesure_non_calculable_pas_un_plantage(prix):
    defs = entonnoir.charger_definitions()
    faits = [{"type_entree": "devis_accepte", "devis_id": "D1", "lead_id": "L1", "prix_total": prix, "horodatage": H}]
    mesures = {m["metric_id"]: m for m in entonnoir.mesurer(faits, [], defs)}  # ne lève pas
    carnet = mesures["m8_carnet_signe_cad"]
    assert carnet["statut"] == entonnoir.STATUT_NON_CALCULABLE and carnet["valeur"] is None
    assert "prix" in carnet["detail"]


def test_un_prix_ordinaire_reste_calcule():
    defs = entonnoir.charger_definitions()
    faits = [{"type_entree": "devis_accepte", "devis_id": "D1", "lead_id": "L1", "prix_total": "25000.50",
              "horodatage": H}]
    mesures = {m["metric_id"]: m for m in entonnoir.mesurer(faits, [], defs)}
    assert mesures["m8_carnet_signe_cad"]["valeur"] == "25000.50"


def test_un_seuil_demesure_est_invalide_jamais_un_plantage():
    assert nombres.seuil_valide({"sens": "au_dessus", "valeur": 1e30}) is None
    assert nombres.seuil_valide({"sens": "au_dessus", "valeur": 1e-30}) is None
    assert nombres.seuil_valide({"sens": "au_dessus", "valeur": 25}) == {"sens": "au_dessus", "valeur": Decimal(25)}
    avec_seuils = {"sens": "au_dessus", "attention": "1e30", "critique": "2e30"}
    with pytest.raises(wallboards.WallboardRefuse):
        wallboards._valider_seuils("tuile", avec_seuils)


def test_une_borne_de_sante_demesuree_est_invalide_et_dite():
    definition = {"composantes": [{"indicateurs": [{"mesure": "m8_taux_acceptation_pct"}]}]}
    lue = sante.lire_configuration(
        {"bornes": {"m8_taux_acceptation_pct": {"pire": "1e-999999999", "cible": "1e999999999"}}}, definition)
    assert lue["bornes"] == {} and [i["metric_id"] for i in lue["invalides"]] == ["m8_taux_acceptation_pct"]
