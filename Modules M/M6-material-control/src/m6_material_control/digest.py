"""Digest matériel en lecture seule et déterministe.

Les variances proviennent du registre, les reorders du recalcul stock/seuils.
Aucune entrée n'est normalisée ni réparée.
"""


def produire_digest_quotidien(registre, seuils) -> dict:
    variances_significatives = []

    for mouvement in registre.lire():
        if mouvement["type_mouvement"] != "VARIANCE_INVENTAIRE":
            continue

        ecart = mouvement["quantite"]
        if ecart == 0:
            verdict_variance = "AUCUN_ECART"
        elif ecart < 0:
            verdict_variance = "STOCK_INFERIEUR_AU_THEORIQUE"
        else:
            verdict_variance = "STOCK_SUPERIEUR_AU_THEORIQUE"

        variances_significatives.append(
            {
                "chantier_id": mouvement["chantier_id"],
                "materiau_id": mouvement["materiau_id"],
                "verdict_variance": verdict_variance,
                "ecart": ecart,
            }
        )

    from . import reorder

    reorders = []
    for seuil in seuils:
        signal = reorder.evaluer_reorder(
            seuil["chantier_id"],
            seuil["materiau_id"],
            seuils,
            registre,
        )
        if signal is not None:
            reorders.append(
                {
                    "chantier_id": signal["chantier_id"],
                    "materiau_id": signal["materiau_id"],
                    "quantite_suggeree": signal["quantite_suggeree"],
                }
            )

    nb_variances_stock = len(variances_significatives)
    nb_reorders_suggeres = len(reorders)
    type_digest = "DIGEST_MATERIEL"

    from . import encodage

    hash_digest = encodage.empreinte(
        type_digest,
        nb_variances_stock,
        nb_reorders_suggeres,
        variances_significatives,
        reorders,
    )

    return {
        "type": type_digest,
        "nb_variances_stock": nb_variances_stock,
        "nb_reorders_suggeres": nb_reorders_suggeres,
        "variances_significatives": variances_significatives,
        "reorders": reorders,
        "hash_digest": hash_digest,
    }
