from decimal import Decimal

# PLAN T1.1-d2 : RETOUR (matériel jamais utilisé, réintégré — stocké positif, comme
# RECEPTION) et PERTE/BRIS (matériel sorti sans consommation de chantier — stockés
# négatifs, comme CONSOMMATION) entrent dans le théorique au même titre. Chaque type
# porte déjà le bon signe à l'écriture (materiel.soumettre_materiaux_utilises) : la simple
# somme reste juste, aucun signe spécial à réappliquer ici.
_TYPES_STOCK_THEORIQUE = frozenset({"RECEPTION", "CONSOMMATION", "RETOUR", "PERTE", "BRIS"})


def texte_canonique(valeur: Decimal) -> str:
    """Texte décimal CANONIQUE (`100`, `0.3`, `0` : sans zéros de fin, jamais de notation scientifique) : la même
    quantité s'écrit toujours de la même façon, quelle que soit l'arithmétique qui l'a produite. Un zéro n'a pas de
    signe."""
    if valeur.is_zero():
        return "0"
    return format(valeur.normalize(), "f")


def deriver_stock_articles(materiaux_ids, mouvements) -> dict[str, Decimal]:
    """Stock théorique de chaque article demandé, TOUS lieux confondus (PLAN T1.5-d, M6.15).

    Même règle de somme que `deriver_stock_theorique` (mêmes types de mouvement, `VARIANCE_INVENTAIRE`
    exclue, DA-M6-09), mais sans filtrer par chantier : le seuil de réapprovisionnement est PAR ARTICLE
    (`department.yaml`), pas par chantier. `mouvements` est n'importe quel itérable de maillons (le
    registre durable, une liste). Un article sans aucun mouvement vaut 0 : c'est un stock théorique
    vide, pas une donnée manquante (le seuil, lui, peut manquer, et c'est `reapprovisionnement.py` qui
    le dit). Somme exacte en décimal (`Decimal(str(quantite))`), jamais en flottant : « 150 » ne doit pas
    devenir « 149,99999999999997 » et déclencher un besoin de commande à l'égalité du seuil.

    Ne dit rien de la réservation par chantier (M6.8) ni de l'emplacement (M6.9) : c'est la quantité
    théorique TOUS LIEUX, pas la quantité disponible. `deriver_disponibilite` y retranche ce qui est hors main
    (fournisseur, retour, rebut) et ce qui est réservé.
    """
    demandes = set(materiaux_ids)
    totaux = {materiau_id: Decimal(0) for materiau_id in demandes}
    for mouvement in mouvements:
        materiau_id = mouvement.get("materiau_id")
        if materiau_id in demandes and mouvement.get("type_mouvement") in _TYPES_STOCK_THEORIQUE:
            totaux[materiau_id] += Decimal(str(mouvement["quantite"]))
    return totaux


def deriver_disponibilite(materiaux_ids, mouvements, hors_main, reserve) -> dict[str, dict[str, Decimal]]:
    """Ce que chaque article demandé a en main et de disponible (PLAN T4.14, M6.8 et M6.9) :

        en_main    = stock théorique tous lieux - hors main
        disponible = en_main - réservé

    `hors_main` (`emplacements.hors_main_par_article`) : ce qui est chez le fournisseur, en retour ou au rebut, par
    article ; `reserve` (`reservations.reserve_par_article`) : ce que les réservations ACTIVES mettent de côté. Un
    article absent de l'un ou de l'autre n'a rien hors main, rien de réservé. Chaque valeur est un `Decimal` exact ;
    aucune n'est arrondie ni ramenée à zéro : un en main négatif (donnée à vérifier, jamais une quantité) reste
    négatif, `reapprovisionnement.py` le signale. `mouvements` est n'importe quel itérable de maillons."""
    stocks = deriver_stock_articles(materiaux_ids, mouvements)
    disponibilite = {}
    for materiau_id, total in stocks.items():
        hors = hors_main.get(materiau_id, Decimal(0))
        reserve_article = reserve.get(materiau_id, Decimal(0))
        disponibilite[materiau_id] = {
            "stock_theorique": total,
            "hors_main": hors,
            "en_main": total - hors,
            "reserve": reserve_article,
            "disponible": total - hors - reserve_article,
        }
    return disponibilite


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
