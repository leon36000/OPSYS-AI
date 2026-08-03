def deriver_stock_theorique(chantier_id, materiau_id, registre) -> float:
    return sum(
        (
            mouvement["quantite"]
            for mouvement in registre.lire()
            if mouvement.get("type_mouvement") in {"RECEPTION", "CONSOMMATION"}
            and mouvement.get("chantier_id") == chantier_id
            and mouvement.get("materiau_id") == materiau_id
        ),
        0.0,
    )


def verifier_disponibilite_consommation(
    chantier_id, lignes_consommees, registre
) -> tuple[bool, str | None]:
    if not chantier_id:
        return False, "REJ-STOCK-CHANTIER-MANQUANT"

    quantites_par_materiau = {}
    for ligne in lignes_consommees:
        materiau_id = ligne["materiau_id"]
        quantites_par_materiau[materiau_id] = (
            quantites_par_materiau.get(materiau_id, 0.0)
            + ligne["quantite"]
        )

    for materiau_id, quantite_demandee in quantites_par_materiau.items():
        stock_theorique = deriver_stock_theorique(
            chantier_id,
            materiau_id,
            registre,
        )
        if quantite_demandee > stock_theorique:
            return False, "REJ-STOCK-INSUFFISANT"

    return True, None
