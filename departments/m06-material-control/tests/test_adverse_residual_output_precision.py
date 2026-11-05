from __future__ import annotations

from decimal import Decimal

import pytest
from m6_material_control import bons_commande
from m6_material_control.decimal_exact import DecimalIndeterminable
from test_stock_float_impacts import _cap

from opsys import stockage


def test_public_reorder_suggestion_is_silently_rounded_down_after_exact_decision(base):
    material = "mat-adverse-reorder-output-fictif"
    project = "CH-adverse-reorder-output-fictif"
    threshold = 9_007_199_254_740_994  # 2**53 + 2; exactly representable as int/float.
    po = "PO-adverse-reorder-output-fictif"
    date = "2026-11-05T12:00:00-04:00"
    cap = _cap()
    with stockage.transaction():
        before = list(stockage.maillons("m06-material-control", "principal"))
    response = cap.appeler("m6_receptionner_commande", {
        "bon_demande": {"po_id": po, "chantier_id": project,
                        "lignes_demandees": [{"materiau_id": material, "quantite_demandee": 1}],
                        "horodatage": date},
        "reception_po": {"po_id": po, "chantier_id": project,
                         "lignes_recues": [{"materiau_id": material, "quantite_recue": 1}],
                         "horodatage": date},
        "seuils_reorder": [{"chantier_id": project, "materiau_id": material, "seuil_quantite": threshold}],
    })
    with stockage.transaction():
        after = list(stockage.maillons("m06-material-control", "principal"))
    assert response["ok"] and response["resultat"]["accepte"] is False, response
    assert response["resultat"]["verdict"]["code"] == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"
    assert after == before


def test_public_reorder_fields_become_internally_inconsistent_when_stock_float_rounds(base):
    material = "mat-adverse-reorder-fields-fictif"
    project = "CH-adverse-reorder-fields-fictif"
    stock_exact = 9_007_199_254_740_993
    threshold = 9_007_199_254_740_994
    po = "PO-adverse-reorder-fields-fictif"
    date = "2026-11-05T12:00:00-04:00"
    cap = _cap()
    with stockage.transaction():
        before = list(stockage.maillons("m06-material-control", "principal"))
    response = cap.appeler("m6_receptionner_commande", {
        "bon_demande": {"po_id": po, "chantier_id": project,
                        "lignes_demandees": [{"materiau_id": material, "quantite_demandee": stock_exact}],
                        "horodatage": date},
        "reception_po": {"po_id": po, "chantier_id": project,
                         "lignes_recues": [{"materiau_id": material, "quantite_recue": stock_exact}],
                         "horodatage": date},
        "seuils_reorder": [{"chantier_id": project, "materiau_id": material,
                            "seuil_quantite": threshold}],
    })
    with stockage.transaction():
        after = list(stockage.maillons("m06-material-control", "principal"))
    assert response["ok"] and response["resultat"]["accepte"] is False, response
    assert response["resultat"]["verdict"]["code"] == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"
    assert after == before


def test_po_net_quantity_projection_is_silently_rounded_down():
    material = "mat-adverse-po-output-fictif"
    project = "CH-adverse-po-output-fictif"
    estimate = 9_007_199_254_740_994

    class Registry:
        def lire(self):
            return [{"type_mouvement": "RECEPTION", "chantier_id": project,
                     "materiau_id": material, "quantite": "1"}]

    with pytest.raises(DecimalIndeterminable):
        bons_commande.calculer_lignes_a_commander(
            [{"materiau_id": material, "quantite_estimee": estimate, "unite": "u"}], project, Registry())
    assert Decimal(estimate) - Decimal(1) == Decimal(9_007_199_254_740_993)


def test_public_exact_equal_count_is_refused_when_legacy_float_cannot_represent_theory(base):
    material = "mat-adverse-variance-equal-fictif"
    project = "CH-adverse-variance-equal-fictif"
    quantity = 9_007_199_254_740_993
    cap = _cap()
    po = "PO-adverse-variance-equal-fictif"
    date = "2026-11-05T12:00:00-04:00"
    receipt = cap.appeler("m6_receptionner_commande", {
        "bon_demande": {"po_id": po, "chantier_id": project,
                        "lignes_demandees": [{"materiau_id": material, "quantite_demandee": quantity}],
                        "horodatage": date},
        "reception_po": {"po_id": po, "chantier_id": project,
                         "lignes_recues": [{"materiau_id": material, "quantite_recue": quantity}],
                         "horodatage": date},
    })
    assert receipt["ok"] and receipt["resultat"]["accepte"] is True, str(receipt)[:500]
    with stockage.transaction():
        before = list(stockage.maillons("m06-material-control", "principal"))
    count = cap.appeler("m6_soumettre_comptage", {"comptage": {
        "chantier_id": project, "materiau_id": material,
        "quantite_comptee": quantity, "horodatage": "2026-11-05T13:00:00-04:00",
    }})
    print("exact_equal_count_response", count)
    with stockage.transaction():
        after = list(stockage.maillons("m06-material-control", "principal"))
    assert count["ok"] and count["resultat"]["accepte"] is False, str(count)[:500]
    assert count["resultat"]["verdict"]["code"] == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"
    assert after == before


def test_public_po_draft_persists_the_rounded_net_quantity(base):
    material = "mat-adverse-po-public-fictif"
    project = "CH-adverse-po-public-fictif"
    quote = "DEVIS-adverse-po-public-fictif"
    estimate = 9_007_199_254_740_994
    cap = _cap()

    planned = cap.appeler("m6_enregistrer_besoins_prevus", {
        "chantier_id": project, "devis_id": quote,
        "lignes": [{"materiau_id": material, "quantite_estimee": estimate, "unite": "u"}],
    })
    supplier = cap.appeler("m6_enregistrer_fournisseur", {
        "fournisseur_id": "fournisseur-adverse-fictif", "nom": "Fournisseur fictif",
        "horodatage": "2026-11-05T12:00:00-04:00",
    })
    po_stock = "PO-adverse-po-stock-fictif"
    date = "2026-11-05T12:00:00-04:00"
    receipt = cap.appeler("m6_receptionner_commande", {
        "bon_demande": {"po_id": po_stock, "chantier_id": project,
                        "lignes_demandees": [{"materiau_id": material, "quantite_demandee": 1}],
                        "horodatage": date},
        "reception_po": {"po_id": po_stock, "chantier_id": project,
                         "lignes_recues": [{"materiau_id": material, "quantite_recue": 1}],
                         "horodatage": date},
    })
    assert planned["ok"] and planned["resultat"]["accepte"] is True, str(planned)[:500]
    assert supplier["ok"] and supplier["resultat"]["accepte"] is True, str(supplier)[:500]
    assert receipt["ok"] and receipt["resultat"]["accepte"] is True, str(receipt)[:500]

    with stockage.transaction():
        po_before = list(stockage.maillons("m06-material-control", "bons_commande"))
    drafted = cap.appeler("m6_creer_po_brouillon", {
        "po_id": "PO-adverse-po-understated-fictif", "devis_id": quote,
        "fournisseur_id": "fournisseur-adverse-fictif", "horodatage": date,
        "date_requise": "2099-01-01", "mode_livraison": "ramassage",
    })
    with stockage.transaction():
        po_after = list(stockage.maillons("m06-material-control", "bons_commande"))
    assert drafted["ok"] and drafted["resultat"]["accepte"] is False, str(drafted)[:800]
    assert drafted["resultat"]["verdict"]["code"] == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"
    assert po_after == po_before


def test_public_reception_ecart_float_is_inconsistent_with_large_exact_quantities(base):
    material = "mat-adverse-reception-ecart-fictif"
    project = "CH-adverse-reception-ecart-fictif"
    ordered = 9_007_199_254_740_994
    received = 1
    po = "PO-adverse-reception-ecart-fictif"
    date = "2026-11-05T12:00:00-04:00"
    cap = _cap()
    with stockage.transaction():
        before = list(stockage.maillons("m06-material-control", "principal"))
    response = cap.appeler("m6_receptionner_commande", {
        "bon_demande": {"po_id": po, "chantier_id": project,
                        "lignes_demandees": [{"materiau_id": material, "quantite_demandee": ordered}],
                        "horodatage": date},
        "reception_po": {"po_id": po, "chantier_id": project,
                         "lignes_recues": [{"materiau_id": material, "quantite_recue": received}],
                         "horodatage": date},
    })
    with stockage.transaction():
        after = list(stockage.maillons("m06-material-control", "principal"))
    assert response["ok"] and response["resultat"]["accepte"] is False, response
    assert response["resultat"]["verdict"]["code"] == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"
    assert after == before
    assert Decimal(str(received)) - Decimal(str(ordered)) == Decimal(-9_007_199_254_740_993)
