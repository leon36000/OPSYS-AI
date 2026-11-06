from __future__ import annotations

from decimal import Decimal, Inexact, Rounded, localcontext
from fractions import Fraction

import pytest
from m6_material_control import seuils_variance


def _config(*, global_pourcentage="0.30", plancher_quantite="0", plancher_dollars="0"):
    return seuils_variance.valider_config({
        "global_pourcentage": global_pourcentage,
        "par_categorie": {},
        "par_materiau": {},
        "categories": {},
        "plancher_quantite": plancher_quantite,
        "plancher_dollars": plancher_dollars,
    })


def _verdict(*, ecart, ratio="0.40"):
    return {
        "materiau_id": "MAT-c7-contexte-fictif",
        "ecart": ecart,
        "ecart_pourcentage": ratio,
    }


@pytest.mark.parametrize("precision", [2, 28, 40])
def test_critique_c7_compare_ecart_et_montant_exacts_sous_tout_contexte(precision):
    config = _config(plancher_quantite="1.22", plancher_dollars="2.46")

    with localcontext() as context:
        context.prec = precision
        resultat = seuils_variance.critique(
            _verdict(ecart="1.23"), config, valeur_unitaire="2.00"
        )

    assert resultat["critique"] is True
    assert resultat["motif"] == "au_dessus_des_seuils"


@pytest.mark.parametrize(("plancher", "critique", "motif"), [
    ("2.50", True, "au_dessus_des_seuils"),
    ("2.51", False, "sous_plancher_dollars"),
])
@pytest.mark.parametrize("precision", [2, 28])
def test_plancher_dollars_conserve_round_half_up_a_mi_cent(
    plancher, critique, motif, precision
):
    # 1,25 × 1,996 = 2,495 ; le contrat arrondit HALF_UP au cent, donc à 2,50.
    config = _config(plancher_quantite="0", plancher_dollars=plancher)

    with localcontext() as context:
        context.prec = precision
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        resultat = seuils_variance.critique(
            _verdict(ecart="1.25"), config, valeur_unitaire="1.996"
        )

    assert resultat["critique"] is critique
    assert resultat["motif"] == motif


@pytest.mark.parametrize("precision", [2, 28, 40])
@pytest.mark.parametrize(("ratio", "critique"), [
    ("0.12345678901234567890123456789012345677", False),
    ("0.12345678901234567890123456789012345678", True),
    ("0.12345678901234567890123456789012345679", True),
])
def test_c7_preserves_long_threshold_lexeme_before_exact_comparison(precision, ratio, critique):
    threshold = "0.12345678901234567890123456789012345678"
    assert len(threshold) <= 40

    with localcontext() as context:
        context.prec = precision
        config = _config(global_pourcentage=threshold)
        resultat = seuils_variance.critique(
            _verdict(ecart="1", ratio=ratio),
            config,
            ratio_exact=Fraction(Decimal(ratio)),
        )

    assert config["global_pourcentage"] == threshold
    assert resultat["critique"] is critique
    if not critique:
        assert resultat["motif"] == "sous_seuil"


def test_c7_keeps_extreme_small_decimal_compact_without_changing_its_value():
    result = _config(plancher_quantite="1e-999999999")

    assert result["plancher_quantite"] == "1E-999999999"
    assert Decimal(result["plancher_quantite"]) == Decimal("1e-999999999")


def test_c7_arrondit_un_mi_cent_selon_half_up_et_non_half_even():
    # 1.25 × 1.988 = 2.485 : HALF_UP donne 2.49, HALF_EVEN donnerait 2.48.
    config = _config(plancher_dollars="2.49")
    resultat = seuils_variance.critique(_verdict(ecart="1.25"), config, valeur_unitaire="1.988")
    assert resultat["critique"] is True
    assert resultat["motif"] == "au_dessus_des_seuils"


def test_c7_montant_exact_ne_depend_pas_des_bornes_emax_emin_de_l_appelant():
    config = _config(plancher_dollars="10000000000")

    with localcontext() as context:
        context.prec = 2
        context.Emax = 9
        context.Emin = -9
        resultat = seuils_variance.critique(
            _verdict(ecart="1e10"), config, valeur_unitaire="1"
        )

    assert resultat["critique"] is True
    assert resultat["motif"] == "au_dessus_des_seuils"
