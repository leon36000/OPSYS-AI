def construire_confirmation_consommation_terrain(
    intervention_id,
    chantier_id,
    lignes_consommees,
    stock_restant,
) -> dict:
    return {
        "intervention_id": intervention_id,
        "chantier_id": chantier_id,
        "materiaux_confirmes": [
            {
                "materiau_id": ligne["materiau_id"],
                "quantite_declaree": ligne["quantite"],
            }
            for ligne in lignes_consommees
        ],
        "stock_restant": stock_restant,
    }


