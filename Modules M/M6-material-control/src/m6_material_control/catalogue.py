def resoudre_prix(materiau_id, catalogue, registre):
    postes = {} if catalogue is None else catalogue.get("postes", {})

    if materiau_id in postes:
        return {
            "verdict_resolution_prix": "PRIX_CATALOGUE",
            "cout_unitaire_resolu": postes[materiau_id]["cout_unitaire"],
        }

    receptions = [
        mouvement
        for mouvement in registre.lire()
        if mouvement.get("type_mouvement") == "RECEPTION"
        and mouvement.get("materiau_id") == materiau_id
        and mouvement.get("cout_unitaire") is not None
    ]

    if receptions:
        mouvement = max(receptions, key=lambda element: element["index"])
        return {
            "verdict_resolution_prix": "PRIX_HISTORIQUE_FALLBACK",
            "cout_unitaire_resolu": mouvement["cout_unitaire"],
        }

    return {
        "verdict_resolution_prix": "INDETERMINE",
        "cout_unitaire_resolu": None,
    }
