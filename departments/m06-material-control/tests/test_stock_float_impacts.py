from __future__ import annotations

from dataclasses import replace

from opsys import stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements

M6 = "m06-material-control"


def _cap():
    deps = charger_departements()
    deps[M6] = replace(deps[M6], mode="supervise")
    return Capacites(deps, stockage.transaction, filtre={M6}, appelant=M6, memoire=False)


def _receive(cap, material, project, quantity):
    po = f"PO-float-impact-{material}"
    date = "2026-11-05T12:00:00-04:00"
    return cap.appeler("m6_receptionner_commande", {
        "bon_demande": {
            "po_id": po, "chantier_id": project,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": quantity}],
            "horodatage": date,
        },
        "reception_po": {
            "po_id": po, "chantier_id": project,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": quantity}],
            "horodatage": date,
        },
    })


def test_public_comptage_refuses_lossy_float_projection_before_writing(base):
    material = "mat-float-variance-fictif"
    project = "CH-float-variance-fictif"
    exact = 9_007_199_254_740_993
    cap = _cap()
    receipt = _receive(cap, material, project, exact)
    assert receipt["ok"] and receipt["resultat"]["accepte"] is True, str(receipt)[:500]
    with stockage.transaction():
        before = list(stockage.maillons(M6, "principal"))

    count = cap.appeler("m6_soumettre_comptage", {"comptage": {
        "chantier_id": project, "materiau_id": material,
        "quantite_comptee": exact - 1, "horodatage": "2026-11-05T13:00:00-04:00",
    }})
    assert count["ok"] and count["resultat"]["accepte"] is False, str(count)[:500]
    assert count["resultat"]["verdict"]["code"] == "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"
    with stockage.transaction():
        after = list(stockage.maillons(M6, "principal"))
    assert after == before


def test_po_quantity_calculation_uses_exact_stock_before_float_projection():
    from m6_material_control import bons_commande

    material = "mat-float-po-fictif"
    project = "CH-float-po-fictif"
    exact_stock = 9_007_199_254_740_993

    class Registry:
        def lire(self):
            return [{"type_mouvement": "RECEPTION", "chantier_id": project,
                     "materiau_id": material, "quantite": str(exact_stock)}]

    lines = bons_commande.calculer_lignes_a_commander(
        [{"materiau_id": material, "quantite_estimee": exact_stock + 1, "unite": "unité"}],
        project,
        Registry(),
    )
    assert lines == [{"materiau_id": material, "quantite_nette": 1.0, "unite": "unité"}]
