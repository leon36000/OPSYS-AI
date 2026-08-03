def evaluer_reorder(chantier_id, materiau_id, seuils, registre):
    seuil_trouve = None

    for seuil in seuils:
        if (
            seuil["chantier_id"] == chantier_id
            and seuil["materiau_id"] == materiau_id
        ):
            seuil_trouve = seuil
            break

    if seuil_trouve is None:
        return None

    from . import stock

    stock_actuel = stock.deriver_stock_theorique(
        chantier_id,
        materiau_id,
        registre,
    )
    seuil_quantite = seuil_trouve["seuil_quantite"]

    if stock_actuel < seuil_quantite:
        return {
            "chantier_id": chantier_id,
            "materiau_id": materiau_id,
            "stock_actuel": stock_actuel,
            "seuil_quantite": seuil_quantite,
            "quantite_suggeree": seuil_quantite - stock_actuel,
        }

    return None
