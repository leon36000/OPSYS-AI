from . import contrats_sortie
from . import stock
from . import validation


def consommer_materiaux(wct, formulaire, registre) -> tuple[dict | None, str | None]:
    ok, code = validation.valider_wct(wct)
    if not ok:
        return None, code

    ok, code = validation.valider_formulaire_consommation(formulaire, wct)
    if not ok:
        return None, code

    stock_restant = []
    for ligne in formulaire["lignes_consommees"]:
        theorique_avant = stock.deriver_stock_theorique(
            formulaire["chantier_id"],
            ligne["materiau_id"],
            registre,
        )
        restant = theorique_avant - ligne["quantite"]
        stock_restant.append(
            {
                "materiau_id": ligne["materiau_id"],
                "quantite": restant,
            }
        )

    return (
        contrats_sortie.construire_confirmation_consommation_terrain(
            formulaire["intervention_id"],
            formulaire["chantier_id"],
            formulaire["lignes_consommees"],
            stock_restant,
        ),
        None,
    )
