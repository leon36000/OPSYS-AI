import math
from decimal import Decimal

from .decimal_exact import (
    DecimalIndeterminable,
    somme_decimaux_exactement,
    soustraire_exactement,
)


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

    quantite_theorique_exacte = stock._deriver_stock_theorique_decimal(
        chantier_id,
        materiau_id,
        registre,
    )
    ecart_exact = soustraire_exactement(Decimal(str(quantite_comptee)), quantite_theorique_exacte)

    if ecart_exact == 0:
        verdict_variance = "AUCUN_ECART"
    elif ecart_exact < 0:
        verdict_variance = "STOCK_INFERIEUR_AU_THEORIQUE"
    else:
        verdict_variance = "STOCK_SUPERIEUR_AU_THEORIQUE"

    quantite_theorique = float(quantite_theorique_exacte)
    ecart = float(ecart_exact)
    if not math.isfinite(quantite_theorique) or not math.isfinite(ecart):
        raise DecimalIndeterminable
    theorie_float_exacte = Decimal(str(quantite_theorique))
    ecart_float_exact = Decimal(str(ecart))
    if theorie_float_exacte != quantite_theorique_exacte:
        raise DecimalIndeterminable
    somme_projection = somme_decimaux_exactement(((theorie_float_exacte, 1), (ecart_float_exact, 1)))
    if somme_projection is None or somme_projection != Decimal(str(quantite_comptee)):
        raise DecimalIndeterminable

    return {
        "chantier_id": chantier_id,
        "materiau_id": materiau_id,
        "verdict_variance": verdict_variance,
        "quantite_theorique": quantite_theorique,
        "quantite_comptee": quantite_comptee,
        "ecart": ecart,
        "note_investigation": None,
    }
