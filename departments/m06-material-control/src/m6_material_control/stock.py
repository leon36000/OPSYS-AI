from decimal import Decimal

# PLAN T1.1-d2 : RETOUR (matériel jamais utilisé, réintégré — stocké positif, comme
# RECEPTION) et PERTE/BRIS (matériel sorti sans consommation de chantier — stockés
# négatifs, comme CONSOMMATION) entrent dans le théorique au même titre. Chaque type
# porte déjà le bon signe à l'écriture (materiel.soumettre_materiaux_utilises) : la simple
# somme reste juste, aucun signe spécial à réappliquer ici.
_TYPES_STOCK_THEORIQUE = frozenset({"RECEPTION", "CONSOMMATION", "RETOUR", "PERTE", "BRIS"})


def deriver_stock_articles(materiaux_ids, mouvements) -> dict[str, Decimal]:
    """Stock théorique de chaque article demandé, TOUS lieux confondus (PLAN T1.5-d, M6.15).

    Même règle de somme que `deriver_stock_theorique` (mêmes types de mouvement, `VARIANCE_INVENTAIRE`
    exclue, DA-M6-09), mais sans filtrer par chantier : le seuil de réapprovisionnement est PAR ARTICLE
    (`department.yaml`), pas par chantier. `mouvements` est n'importe quel itérable de maillons (le
    registre durable, une liste). Un article sans aucun mouvement vaut 0 : c'est un stock théorique
    vide, pas une donnée manquante (le seuil, lui, peut manquer, et c'est `reapprovisionnement.py` qui
    le dit). Somme exacte en décimal (`Decimal(str(quantite))`), jamais en flottant : « 150 » ne doit pas
    devenir « 149,99999999999997 » et déclencher un besoin de commande à l'égalité du seuil.

    Ne dit rien de la réservation par chantier (M6.8) ni de l'emplacement (M6.9), qui n'existent pas
    encore : c'est la quantité théorique en main, pas la quantité disponible.
    """
    demandes = set(materiaux_ids)
    totaux = {materiau_id: Decimal(0) for materiau_id in demandes}
    for mouvement in mouvements:
        materiau_id = mouvement.get("materiau_id")
        if materiau_id in demandes and mouvement.get("type_mouvement") in _TYPES_STOCK_THEORIQUE:
            totaux[materiau_id] += Decimal(str(mouvement["quantite"]))
    return totaux


def deriver_stock_theorique(chantier_id, materiau_id, registre) -> float:
    return sum(
        (
            mouvement["quantite"]
            for mouvement in registre.lire()
            if mouvement.get("type_mouvement") in _TYPES_STOCK_THEORIQUE
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
