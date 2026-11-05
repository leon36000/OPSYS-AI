from decimal import Decimal

from .decimal_exact import (
    AccumulateurDecimalExact,
    DecimalIndeterminable,
    somme_decimaux_exactement,
    soustraire_exactement,
    texte_ou_refus,
)

# PLAN T1.1-d2 : RETOUR (matériel jamais utilisé, réintégré — stocké positif, comme
# RECEPTION) et PERTE/BRIS (matériel sorti sans consommation de chantier — stockés
# négatifs, comme CONSOMMATION) entrent dans le théorique au même titre. Chaque type
# porte déjà le bon signe à l'écriture (materiel.soumettre_materiaux_utilises) : la simple
# somme reste juste, aucun signe spécial à réappliquer ici.
_TYPES_STOCK_THEORIQUE = frozenset({"RECEPTION", "CONSOMMATION", "RETOUR", "PERTE", "BRIS", "AJUSTEMENT"})


def texte_canonique(valeur: Decimal) -> str:
    """Texte décimal CANONIQUE (`100`, `0.3`, `0` : sans zéros de fin, jamais de notation scientifique) : la même
    quantité s'écrit toujours de la même façon, quelle que soit l'arithmétique qui l'a produite. Un zéro n'a pas de
    signe."""
    return texte_ou_refus(valeur)


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
    accumulateurs = {materiau_id: AccumulateurDecimalExact() for materiau_id in demandes}
    for mouvement in mouvements:
        materiau_id = mouvement.get("materiau_id")
        if (
            materiau_id in demandes
            and mouvement.get("type_mouvement") in _TYPES_STOCK_THEORIQUE
            and not accumulateurs[materiau_id].ajouter(mouvement["quantite"], 1)
        ):
            raise DecimalIndeterminable
    totaux = {}
    for materiau_id, accumulateur in accumulateurs.items():
        total = accumulateur.resultat()
        if total is None:
            raise DecimalIndeterminable
        totaux[materiau_id] = total
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
            "en_main": soustraire_exactement(total, hors),
            "reserve": reserve_article,
            "disponible": soustraire_exactement(soustraire_exactement(total, hors), reserve_article),
        }
    return disponibilite


def _deriver_stock_theorique_decimal(chantier_id, materiau_id, registre) -> Decimal:
    total = somme_decimaux_exactement(
        (Decimal(str(mouvement["quantite"])), 1)
        for mouvement in registre.lire()
        if mouvement.get("type_mouvement") in _TYPES_STOCK_THEORIQUE
        and mouvement.get("chantier_id") == chantier_id
        and mouvement.get("materiau_id") == materiau_id
    )
    if total is None:
        raise DecimalIndeterminable
    return total


def deriver_stock_theorique(chantier_id, materiau_id, registre) -> float:
    """Somme décimale des mouvements ; conserve le nombre JSON du contrat historique."""
    return float(_deriver_stock_theorique_decimal(chantier_id, materiau_id, registre))


def verifier_disponibilite_consommation(
    chantier_id, lignes_consommees, registre, en_main_global=None
) -> tuple[bool, str | None]:
    if not chantier_id:
        return False, "REJ-STOCK-CHANTIER-MANQUANT"

    accumulateurs = {}
    for ligne in lignes_consommees:
        materiau_id = ligne["materiau_id"]
        accumulateur = accumulateurs.setdefault(materiau_id, AccumulateurDecimalExact())
        if not accumulateur.ajouter(ligne["quantite"], 1):
            return False, "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"

    quantites_par_materiau = {}
    for materiau_id, accumulateur in accumulateurs.items():
        quantite = accumulateur.resultat()
        if quantite is None:
            return False, "REJ-M6-ARITHMETIQUE-DECIMALE-INDETERMINABLE"
        quantites_par_materiau[materiau_id] = quantite

    for materiau_id, quantite_demandee in quantites_par_materiau.items():
        stock_theorique = _deriver_stock_theorique_decimal(
            chantier_id,
            materiau_id,
            registre,
        )
        if quantite_demandee > stock_theorique:
            return False, "REJ-STOCK-INSUFFISANT"

        # L'ancien contrat n'est permis que si le registre d'emplacements prouve aussi que la
        # quantité existe en main à l'échelle globale. `en_main_global` est absent pour les
        # appelants historiques en mémoire et n'est transmis par l'outil public qu'après
        # validation de la chaîne durable d'emplacements. Ce contrôle ne répartit jamais le
        # disponible d'un autre chantier vers celui-ci. C'est seulement une borne globale
        # nécessaire : elle ne prouve pas que le stock soit au chantier demandé. Le contrat
        # historique ne reconstruit pas cette attribution physique.
        if (
            en_main_global is not None
            and materiau_id in en_main_global
            and quantite_demandee > en_main_global[materiau_id]
        ):
            return False, "REJ-STOCK-INSUFFISANT"

    return True, None
