from decimal import Decimal


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
            # Écart en décimal exact (10,3 − 3,1 = 7,2, pas 7,200000000000001), comme `stock.py`.
            "quantite_suggeree": float(Decimal(str(seuil_quantite)) - Decimal(str(stock_actuel))),
        }

    return None
