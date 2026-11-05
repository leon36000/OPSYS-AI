from __future__ import annotations

from dataclasses import replace

from opsys import stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements

M6 = "m06-material-control"


def test_public_reception_equality_to_threshold_does_not_emit_reorder(base):
    material = "mat-float-boundary-fictif"
    project = "CH-float-boundary-fictif"
    quantity = 9_007_199_254_740_993
    deps = charger_departements()
    deps[M6] = replace(deps[M6], mode="supervise")
    cap = Capacites(deps, stockage.transaction, filtre={M6}, appelant=M6, memoire=False)

    response = cap.appeler("m6_receptionner_commande", {
        "bon_demande": {
            "po_id": "PO-float-boundary-fictif",
            "chantier_id": project,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": quantity}],
            "horodatage": "2026-11-05T12:00:00-04:00",
        },
        "reception_po": {
            "po_id": "PO-float-boundary-fictif",
            "chantier_id": project,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": quantity}],
            "horodatage": "2026-11-05T12:00:00-04:00",
        },
        "seuils_reorder": [{"chantier_id": project, "materiau_id": material, "seuil_quantite": quantity}],
    })
    assert response["ok"] and response["resultat"]["accepte"] is True, str(response)[:800]
    assert response["resultat"]["resultat"]["signaux_reorder"] == []


def test_public_reorder_keeps_one_unit_shortage_above_binary_float_exactness(base):
    material = "mat-float-shortage-fictif"
    project = "CH-float-shortage-fictif"
    quantity = 9_007_199_254_740_995
    deps = charger_departements()
    deps[M6] = replace(deps[M6], mode="supervise")
    cap = Capacites(deps, stockage.transaction, filtre={M6}, appelant=M6, memoire=False)

    with stockage.transaction():
        before = list(stockage.maillons(M6, "principal"))
    response = cap.appeler("m6_receptionner_commande", {
        "bon_demande": {
            "po_id": "PO-float-shortage-fictif", "chantier_id": project,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": quantity}],
            "horodatage": "2026-11-05T12:00:00-04:00",
        },
        "reception_po": {
            "po_id": "PO-float-shortage-fictif", "chantier_id": project,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": quantity}],
            "horodatage": "2026-11-05T12:00:00-04:00",
        },
        "seuils_reorder": [{
            "chantier_id": project, "materiau_id": material, "seuil_quantite": quantity + 1,
        }],
    })
    with stockage.transaction():
        after = list(stockage.maillons(M6, "principal"))
    assert response["ok"] and response["resultat"]["accepte"] is False, str(response)[:800]
    assert response["resultat"]["verdict"]["code"] == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"
    assert after == before
