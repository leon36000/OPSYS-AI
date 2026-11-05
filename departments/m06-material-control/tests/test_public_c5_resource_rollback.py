from __future__ import annotations

from dataclasses import replace

from m6_material_control import registre as registre_module

from opsys import stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements

M6 = "m06-material-control"


def test_c5_numeric_bound_refusal_rolls_back_primary_and_location_ledgers(base):
    material = "mat-c5-calcul-borne-fictif"
    project = "CH-c5-calcul-borne-fictif"
    deps = charger_departements()
    deps[M6] = replace(deps[M6], mode="supervise")
    cap = Capacites(deps, stockage.transaction, filtre={M6}, appelant=M6, memoire=False)
    with stockage.transaction():
        registre = registre_module.Registre(maillons=stockage.maillons(M6, "principal"))
        _, error = registre.ajouter({
            "type_mouvement": "RECEPTION",
            "chantier_id": project,
            "materiau_id": material,
            "quantite": "9" * 5000,
            "cout_unitaire": 5.0,
        })
        assert error is None

    def snapshot():
        with stockage.transaction():
            return {
                nom: list(stockage.maillons(M6, nom))
                for nom in ("principal", "emplacements", "bons_commande", "reservations")
            }

    before = snapshot()
    date = "2026-11-05T12:00:00-04:00"
    po = "PO-c5-calcul-borne-fictif"
    response = cap.appeler("m6_receptionner_commande", {
        "bon_demande": {
            "po_id": po, "chantier_id": project,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": 0.1}],
            "horodatage": date,
        },
        "reception_po": {
            "po_id": po, "chantier_id": project,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": 0.1}],
            "horodatage": date,
        },
        "catalogue_materiaux": {
            "version": "v1", "unite_monetaire": "CAD",
            "postes": {material: {"cout_unitaire": 5.0, "libelle": "Article fictif"}},
        },
        "details_reception": [{"materiau_id": material, "statut_ligne": "conforme"}],
        "lieu_livraison": {"type": "depot"},
    })

    assert response == {
        "ok": False,
        "erreur": "refus_metier",
        "details": "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE",
    }
    after = snapshot()
    assert after == before
