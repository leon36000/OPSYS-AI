from __future__ import annotations

import test_review_rebut_consumption_stock_mismatch as fx


def test_public_consumption_rejects_10e28_plus_point1_without_writing(base):
    material = "mat-consommation-decimale-exces-fictif"
    project = "CH-consommation-decimale-exces-fictif"
    receipt = fx._recevoir_quantite(material, project, 10**28, statut="conforme", suffix="stock-exact")
    assert receipt["ok"] is True, receipt
    assert receipt["resultat"]["accepte"] is True, receipt

    wct = fx._wct(project, "w-consommation-decimale-exces-fictif")
    fx._publier_wct(wct)
    before = fx._etat_stock_durable(material)
    response = fx._consommer_legacy(wct, project, [
        {"materiau_id": material, "quantite": 10**28},
        {"materiau_id": material, "quantite": 0.1},
    ])

    after = fx._etat_stock_durable(material)
    assert response.get("ok") is True, response
    assert response.get("resultat", {}).get("accepte") is False, response
    assert response["resultat"]["verdict"]["code"] == "REJ-STOCK-INSUFFISANT"
    assert after == before


def test_public_consumption_records_completed_wct_with_exact_non_float_stock_remaining(base):
    material = "mat-consommation-stock-restant-float-fictif"
    project = "CH-consommation-stock-restant-float-fictif"
    receipt = fx._recevoir_quantite(
        material, project, 9_007_199_254_740_994, statut="conforme", suffix="stock-restant"
    )
    assert receipt["ok"] and receipt["resultat"]["accepte"] is True, receipt

    wct = fx._wct(project, "w-consommation-stock-restant-float-fictif")
    fx._publier_wct(wct)
    before = fx._etat_stock_durable(material)
    response = fx._consommer_legacy(wct, project, [{"materiau_id": material, "quantite": 1}])
    after = fx._etat_stock_durable(material)

    assert response.get("ok") is True, response
    assert response.get("resultat", {}).get("accepte") is True, response
    stock_restant = response["resultat"]["resultat"]["stock_restant"]
    assert stock_restant == [{
        "materiau_id": material,
        "quantite": None,
        "quantite_exacte": "9007199254740993",
        "motif_projection": "precision_float_insuffisante",
    }]
    assert after != before
    mouvements = after[1]
    consommations = [
        mouvement for mouvement in mouvements
        if mouvement.get("type_mouvement") == "CONSOMMATION" and mouvement.get("wct_id") == wct["wct_id"]
    ]
    assert len(consommations) == 1 and consommations[0]["quantite"] == -1

    # Le rejeu du même WCT ne double pas le fait accompli.
    replay = fx._consommer_legacy(wct, project, [{"materiau_id": material, "quantite": 1}])
    assert replay.get("ok") is True and replay["resultat"]["accepte"] is False, replay
    assert replay["resultat"]["verdict"]["code"] == "REJ-DECLARATION-DEJA-SOUMISE"
    assert fx._etat_stock_durable(material) == after
