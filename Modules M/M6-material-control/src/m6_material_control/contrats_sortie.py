CLES_MONETAIRES_INTERDITES = frozenset({
    "cout_unitaire",
    "cout",
    "prix",
    "montant",
    "devise",
    "unite_monetaire",
    "montant_total_estime",
})


def _verifier_absence_cles_monetaires(valeur) -> None:
    if isinstance(valeur, dict):
        for cle, sous_valeur in valeur.items():
            if cle in CLES_MONETAIRES_INTERDITES:
                raise ValueError(f"Clé monétaire interdite détectée : {cle}")
            _verifier_absence_cles_monetaires(sous_valeur)
    elif isinstance(valeur, list):
        for element in valeur:
            _verifier_absence_cles_monetaires(element)


def construire_confirmation_consommation_terrain(
    intervention_id,
    chantier_id,
    lignes_consommees,
    stock_restant,
) -> dict:
    confirmation = {
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

    _verifier_absence_cles_monetaires(confirmation)
    return confirmation

