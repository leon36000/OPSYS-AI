from __future__ import annotations

from decimal import localcontext

import pytest
from m6_material_control.outils import outils
from m6_material_control.registre import Registre

from opsys import stockage
from opsys.outils import executer, executer_atomique

M6 = "m06-material-control"
MATERIAL = "MAT-variance-precision-fictif"
PROJECT = "CH-variance-precision-fictif"


def _tool():
    return next(item for item in outils() if item.nom == "m6_evaluer_variance_chantier")


def _args(estimated, actual, threshold=0.1):
    return {
        "chantier_id": PROJECT,
        "besoins_estimes": [{
            "materiau_id": MATERIAL,
            "quantite_estimee": estimated,
            "unite": "unite-fictive",
        }],
        "lignes_declarees": [{
            "type_ligne": "prevu",
            "materiau_id": MATERIAL,
            "quantite": actual,
            "quantite_estimee": estimated,
            "unite": "unite-fictive",
        }],
        "seuil_pourcentage": threshold,
    }


def _code_refus(response):
    assert response["ok"] is True, response
    assert response["resultat"]["accepte"] is False, response
    return response["resultat"]["verdict"]["code"]


def test_public_variance_refuses_equal_integer_quantities_not_representable_as_float():
    quantity = 9_007_199_254_740_993  # 2**53 + 1; exact JSON integer
    response = executer(_tool(), _args(quantity, quantity))
    assert _code_refus(response) == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"


@pytest.mark.parametrize("precision", [2, 28, 40])
def test_public_variance_compares_decimal_boundary_exactly_in_reduced_and_normal_contexts(precision):
    with localcontext() as context:
        context.prec = precision
        under = executer(_tool(), _args(3, 3.299999999999999))
        at = executer(_tool(), _args(3, 3.3))
        over = executer(_tool(), _args(3, 3.300000000000001))

    assert under["ok"] and under["resultat"]["accepte"] is True, under
    assert under["resultat"]["resultat"]["signal_variance_critique"] is None
    assert at["ok"] and at["resultat"]["accepte"] is True, at
    assert at["resultat"]["resultat"]["signal_variance_critique"] is not None
    assert over["ok"] and over["resultat"]["accepte"] is True, over
    assert over["resultat"]["resultat"]["signal_variance_critique"] is not None


@pytest.mark.parametrize("precision", [28, 40])
def test_public_variance_exact_accumulation_is_context_independent(precision):
    quantity = 10**28 + 1
    args = _args(quantity, quantity)
    args["lignes_declarees"] = [
        {
            "type_ligne": "prevu", "materiau_id": MATERIAL, "quantite": 10**28,
            "quantite_estimee": 10**28, "unite": "unite-fictive",
        },
        {
            "type_ligne": "prevu", "materiau_id": MATERIAL, "quantite": 1,
            "quantite_estimee": 1, "unite": "unite-fictive",
        },
    ]
    with localcontext() as context:
        context.prec = precision
        response = executer(_tool(), args)
    assert _code_refus(response) == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"


def test_public_variance_preserves_representable_one_unit_difference():
    estimated = 9_007_199_254_740_991  # 2**53 - 1
    actual = 9_007_199_254_740_992  # 2**53; both integers are exactly representable
    response = executer(_tool(), _args(estimated, actual, threshold=1e-16))
    assert response["ok"] and response["resultat"]["accepte"] is True, response
    verdict = response["resultat"]["resultat"]["verdicts_materiaux"][0]
    assert verdict["quantite_estimee"] == estimated
    assert verdict["quantite_reelle"] == float(actual)
    assert verdict["ecart"] == 1.0
    assert verdict["verdict_variance"] == "ECART_REEL_SUPERIEUR"
    assert verdict["classification_requise"] is True
    assert response["resultat"]["resultat"]["signal_variance_critique"] is not None


def test_public_variance_from_durable_register_refuses_lossy_real_projection(base):
    quantity = 9_007_199_254_740_993
    material = "MAT-variance-registre-precision-fictif"
    project = "CH-variance-registre-precision-fictif"
    wct_id = "WCT-variance-registre-precision-fictif"
    with stockage.transaction():
        register = Registre(maillons=stockage.maillons(M6, "principal"))
        _, error = register.ajouter({
            "type_mouvement": "CONSOMMATION",
            "chantier_id": project,
            "materiau_id": material,
            "quantite": -quantity,
            "cout_unitaire": 1.0,
            "wct_id": wct_id,
            "unite": "unite-fictive",
        })
        assert error is None
        before = list(stockage.maillons(M6, "principal"))

    tool = _tool()
    response = executer_atomique(tool, {
        "chantier_id": project,
        "wct_id": wct_id,
        "besoins_estimes": [{
            "materiau_id": material,
            "quantite_estimee": quantity,
            "unite": "unite-fictive",
        }],
        "seuil_pourcentage": 0.1,
    })
    assert _code_refus(response) == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"
    with stockage.transaction():
        after = list(stockage.maillons(M6, "principal"))
    assert after == before
