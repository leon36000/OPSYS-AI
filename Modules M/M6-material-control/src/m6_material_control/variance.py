def evaluer_variance(chantier_id, materiau_id, quantite_comptee, registre) -> dict:
    mouvement_existant = any(
        mouvement.get("type_mouvement") in {"RECEPTION", "CONSOMMATION"}
        and mouvement.get("chantier_id") == chantier_id
        and mouvement.get("materiau_id") == materiau_id
        for mouvement in registre.lire()
    )

    if not mouvement_existant:
        return {
            "chantier_id": chantier_id,
            "materiau_id": materiau_id,
            "verdict_variance": "INDETERMINE",
            "quantite_theorique": 0.0,
            "quantite_comptee": quantite_comptee,
            "ecart": 0.0,
            "note_investigation": None,
        }

    from . import stock

    quantite_theorique = stock.deriver_stock_theorique(
        chantier_id,
        materiau_id,
        registre,
    )
    ecart = quantite_comptee - quantite_theorique

    if ecart == 0:
        verdict_variance = "AUCUN_ECART"
    elif ecart < 0:
        verdict_variance = "STOCK_INFERIEUR_AU_THEORIQUE"
    else:
        verdict_variance = "STOCK_SUPERIEUR_AU_THEORIQUE"

    return {
        "chantier_id": chantier_id,
        "materiau_id": materiau_id,
        "verdict_variance": verdict_variance,
        "quantite_theorique": quantite_theorique,
        "quantite_comptee": quantite_comptee,
        "ecart": ecart,
        "note_investigation": None,
    }
