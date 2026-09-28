from . import catalogue


def traiter_reception(bon_demande, reception_po, catalogue_fourni, registre):
    bareme_version = (
        catalogue_fourni["version"] if catalogue_fourni is not None else None
    )

    resultat_indetermine = {
        "po_id": bon_demande["po_id"],
        "chantier_id": bon_demande["chantier_id"],
        "verdict_reception": "INDETERMINE",
        "lignes": [],
        "montant_total_estime": None,
        "bareme_version": bareme_version,
    }

    if (
        reception_po["po_id"] != bon_demande["po_id"]
        or reception_po["chantier_id"] != bon_demande["chantier_id"]
    ):
        return resultat_indetermine

    recues_par_materiau = {
        ligne["materiau_id"]: ligne["quantite_recue"]
        for ligne in reception_po["lignes_recues"]
    }

    lignes = []
    for ligne_demandee in bon_demande["lignes_demandees"]:
        materiau_id = ligne_demandee["materiau_id"]

        if materiau_id not in recues_par_materiau:
            return resultat_indetermine

        quantite_demandee = ligne_demandee["quantite_demandee"]
        quantite_recue = recues_par_materiau[materiau_id]
        ecart = quantite_recue - quantite_demandee
        resolution_prix = catalogue.resoudre_prix(
            materiau_id, catalogue_fourni, registre
        )
        cout_unitaire_resolu = resolution_prix["cout_unitaire_resolu"]
        montant_ligne = (
            cout_unitaire_resolu * quantite_recue
            if cout_unitaire_resolu is not None
            else None
        )

        lignes.append(
            {
                "materiau_id": materiau_id,
                "quantite_demandee": quantite_demandee,
                "quantite_recue": quantite_recue,
                "ecart": ecart,
                "verdict_resolution_prix": resolution_prix[
                    "verdict_resolution_prix"
                ],
                "cout_unitaire_resolu": cout_unitaire_resolu,
                "montant_ligne": montant_ligne,
            }
        )

    ecarts = [ligne["ecart"] for ligne in lignes]
    contient_ecart_inferieur = any(ecart < 0 for ecart in ecarts)
    contient_ecart_superieur = any(ecart > 0 for ecart in ecarts)

    if contient_ecart_inferieur and contient_ecart_superieur:
        verdict_reception = "RECEPTION_MIXTE"
    elif contient_ecart_inferieur:
        verdict_reception = "RECEPTION_INFERIEURE"
    elif contient_ecart_superieur:
        verdict_reception = "RECEPTION_SUPERIEURE"
    else:
        verdict_reception = "CONFORME"

    montant_total_estime = (
        sum(ligne["montant_ligne"] for ligne in lignes)
        if all(ligne["montant_ligne"] is not None for ligne in lignes)
        else None
    )

    return {
        "po_id": bon_demande["po_id"],
        "chantier_id": bon_demande["chantier_id"],
        "verdict_reception": verdict_reception,
        "lignes": lignes,
        "montant_total_estime": montant_total_estime,
        "bareme_version": bareme_version,
    }
