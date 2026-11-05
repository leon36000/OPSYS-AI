from __future__ import annotations

from decimal import Decimal

import pytest
from m6_material_control import (
    bons_commande,
    fournisseurs,
    materiel,
    registre,
    reorder,
    stock,
)
from m6_material_control.decimal_exact import (
    DecimalIndeterminable,
    float_projection_exacte_ou_refus,
)
from test_stock_float_impacts import M6, _cap

from opsys import stockage


class _Registry:
    def __init__(self, maillons):
        self._maillons = list(maillons)

    def lire(self):
        return list(self._maillons)


def _creer_po_avec_ligne(ligne):
    registre_fournisseurs = []
    _, refus = fournisseurs.enregistrer_fournisseur(
        "fournisseur-po-projection-fictif", "Fournisseur fictif", "2026-11-05T12:00:00Z",
        registre_fournisseurs,
    )
    assert refus is None
    return bons_commande.creer_brouillon(
        "PO-projection-fictif", "CH-projection-fictif", "fournisseur-po-projection-fictif",
        [ligne], "2026-11-05T12:00:00Z", [], [], registre_fournisseurs,
        conditions={"date_requise": "2026-11-06", "mode_livraison": "ramassage"},
    )


def test_float_projection_preserves_short_decimal_but_refuses_lost_integer_unit_and_overflow():
    assert float_projection_exacte_ou_refus(Decimal("0.1")) == 0.1
    assert float_projection_exacte_ou_refus(Decimal("1.25")) == 1.25
    with pytest.raises(DecimalIndeterminable):
        float_projection_exacte_ou_refus(Decimal(9_007_199_254_740_993))
    with pytest.raises(DecimalIndeterminable):
        float_projection_exacte_ou_refus(Decimal("1e400"))


def test_po_refuses_factor_1e_minus_18_instead_of_rounding_its_demanded_quantity():
    po, verdict = _creer_po_avec_ligne({
        "materiau_id": "MAT-1", "quantite_nette": 5.0, "unite": "boite",
        "facteur_perte": "0." + "0" * 17 + "1",
    })
    assert po is None
    assert verdict["code"] == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"
    # 5 * (1 + 1e-18) est exact, mais son projection float serait silencieusement 5.0.


def test_po_float_overflow_keeps_legacy_invalid_line_verdict():
    po, verdict = _creer_po_avec_ligne({
        "materiau_id": "MAT-1", "quantite_nette": 1.7e308, "unite": "boite",
        "facteur_perte": "0.5",
    })
    assert po is None
    assert verdict["code"] == "REJ-PO-LIGNE-INVALIDE"
    assert "hors domaine" in verdict["detail"]


def test_po_net_refuses_exact_difference_that_float_would_round_down():
    material = "mat-po-float-refus-fictif"
    project = "CH-po-float-refus-fictif"
    registry = _Registry([{
        "type_mouvement": "RECEPTION", "chantier_id": project,
        "materiau_id": material, "quantite": "1",
    }])
    with pytest.raises(DecimalIndeterminable):
        bons_commande.calculer_lignes_a_commander(
            [{"materiau_id": material, "quantite_estimee": 9_007_199_254_740_994, "unite": "u"}],
            project,
            registry,
        )


@pytest.mark.parametrize(
    ("stock_exact", "threshold"),
    [
        ("1", Decimal(9_007_199_254_740_994)),  # suggestion is 2**53 + 1
        ("9007199254740993", Decimal(9_007_199_254_740_994)),  # stock field loses one
        ("0", Decimal("1e400")),  # finite Decimal cannot project to finite float
    ],
)
def test_reorder_refuses_inexact_stock_or_suggestion_projection(stock_exact, threshold):
    material = "mat-reorder-float-refus-fictif"
    project = "CH-reorder-float-refus-fictif"
    registry = _Registry([{
        "type_mouvement": "RECEPTION", "chantier_id": project,
        "materiau_id": material, "quantite": stock_exact,
    }] if Decimal(stock_exact) else [])
    seuils = [{
        "chantier_id": project, "materiau_id": material, "seuil_quantite": threshold,
    }]
    with pytest.raises(DecimalIndeterminable):
        reorder.evaluer_reorder(project, material, seuils, registry)


def test_public_po_draft_refuses_before_persisting_rounded_quantity(base):
    material = "mat-po-e2e-float-fictif"
    project = "CH-po-e2e-float-fictif"
    quote = "DEVIS-po-e2e-float-fictif"
    estimate = 9_007_199_254_740_994
    cap = _cap()
    date = "2026-11-05T12:00:00-04:00"

    planned = cap.appeler("m6_enregistrer_besoins_prevus", {
        "chantier_id": project, "devis_id": quote,
        "lignes": [{"materiau_id": material, "quantite_estimee": estimate, "unite": "u"}],
    })
    supplier = cap.appeler("m6_enregistrer_fournisseur", {
        "fournisseur_id": "fournisseur-po-e2e-float-fictif", "nom": "Fournisseur fictif",
        "horodatage": date,
    })
    receipt = cap.appeler("m6_receptionner_commande", {
        "bon_demande": {
            "po_id": "PO-po-e2e-stock-float-fictif", "chantier_id": project,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": 1}],
            "horodatage": date,
        },
        "reception_po": {
            "po_id": "PO-po-e2e-stock-float-fictif", "chantier_id": project,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": 1}],
            "horodatage": date,
        },
    })
    assert planned["ok"] and planned["resultat"]["accepte"] is True, str(planned)[:500]
    assert supplier["ok"] and supplier["resultat"]["accepte"] is True, str(supplier)[:500]
    assert receipt["ok"] and receipt["resultat"]["accepte"] is True, str(receipt)[:500]

    with stockage.transaction():
        before = list(stockage.maillons(M6, "bons_commande"))
    drafted = cap.appeler("m6_creer_po_brouillon", {
        "po_id": "PO-po-e2e-rounded-fictif", "devis_id": quote,
        "fournisseur_id": "fournisseur-po-e2e-float-fictif", "horodatage": date,
        "date_requise": "2099-01-01", "mode_livraison": "ramassage",
    })
    with stockage.transaction():
        after = list(stockage.maillons(M6, "bons_commande"))
    assert drafted["ok"] and drafted["resultat"]["accepte"] is False, str(drafted)[:700]
    assert drafted["resultat"]["verdict"]["code"] == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"
    assert after == before


def test_public_reception_refuses_unrepresentable_ecart_before_stock_write(base):
    material = "mat-reception-float-ecart-fictif"
    project = "CH-reception-float-ecart-fictif"
    po = "PO-reception-float-ecart-fictif"
    cap = _cap()
    with stockage.transaction():
        before = list(stockage.maillons(M6, "principal"))
    response = cap.appeler("m6_receptionner_commande", {
        "bon_demande": {
            "po_id": po, "chantier_id": project,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": 9_007_199_254_740_994}],
            "horodatage": "2026-11-05T12:00:00-04:00",
        },
        "reception_po": {
            "po_id": po, "chantier_id": project,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": 1}],
            "horodatage": "2026-11-05T12:00:00-04:00",
        },
    })
    with stockage.transaction():
        after = list(stockage.maillons(M6, "principal"))
    assert response["ok"] and response["resultat"]["accepte"] is False, str(response)[:700]
    assert response["resultat"]["verdict"]["code"] == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"
    assert after == before


@pytest.mark.parametrize(
    ("received", "threshold"),
    [
        (1, 9_007_199_254_740_994),
        (9_007_199_254_740_993, 9_007_199_254_740_994),
    ],
)
def test_public_c5_refuses_lossy_reorder_fields_before_stock_write(base, received, threshold):
    material = f"mat-reorder-public-float-{received}-fictif"
    project = f"CH-reorder-public-float-{received}-fictif"
    po = f"PO-reorder-public-float-{received}-fictif"
    cap = _cap()
    with stockage.transaction():
        before = list(stockage.maillons(M6, "principal"))
    response = cap.appeler("m6_receptionner_commande", {
        "bon_demande": {
            "po_id": po, "chantier_id": project,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": received}],
            "horodatage": "2026-11-05T12:00:00-04:00",
        },
        "reception_po": {
            "po_id": po, "chantier_id": project,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": received}],
            "horodatage": "2026-11-05T12:00:00-04:00",
        },
        "seuils_reorder": [{
            "chantier_id": project, "materiau_id": material, "seuil_quantite": threshold,
        }],
    })
    with stockage.transaction():
        after = list(stockage.maillons(M6, "principal"))
    assert response["ok"] and response["resultat"]["accepte"] is False, str(response)[:700]
    assert response["resultat"]["verdict"]["code"] == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"
    assert after == before


def test_stock_read_and_reception_stream_more_than_4096_historical_movements():
    material = "mat-stock-flux-4097-fictif"
    project = "CH-stock-flux-4097-fictif"
    history = [{
        "type_mouvement": "RECEPTION", "chantier_id": project,
        "materiau_id": material, "quantite": "1", "cout_unitaire": None,
    } for _ in range(4097)]
    registry = registre.Registre()
    _, error = registry.ajouter_lot(history)
    assert error is None
    assert stock._deriver_stock_theorique_decimal(project, material, registry) == Decimal(4097)

    response, code = materiel.enregistrer_reception(
        {
            "po_id": "PO-stock-flux-4097-fictif", "chantier_id": project,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": 1}],
            "horodatage": "2026-11-05T12:00:00-04:00",
        },
        {
            "po_id": "PO-stock-flux-4097-fictif", "chantier_id": project,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": 1}],
            "horodatage": "2026-11-05T12:00:00-04:00",
        },
        {"version": "v1", "unite_monetaire": "CAD", "postes": {}},
        registry,
    )
    assert code is None, code
    assert response["accuse_reception"]["lignes"][0]["ecart"] == 0.0
    assert stock._deriver_stock_theorique_decimal(project, material, registry) == Decimal(4098)


def test_stock_aggregate_consumes_single_pass_generator_without_history_list():
    material = "mat-stock-generateur-fictif"
    project = "CH-stock-generateur-fictif"

    class OneShotRegistry:
        def __init__(self):
            self.calls = 0

        def lire(self):
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("le registre one-shot a été relu")
            return ({
                "type_mouvement": "RECEPTION", "chantier_id": project,
                "materiau_id": material, "quantite": "1",
            } for _ in range(5000))

    registry = OneShotRegistry()
    assert stock._deriver_stock_theorique_decimal(project, material, registry) == Decimal(5000)
    assert registry.calls == 1
