from __future__ import annotations

_TYPES_SOLDE = ("ENCAISSEMENT", "DECAISSEMENT", "AJUSTEMENT", "AUTRE")


def calculer_solde(registre_cible):
    total = 0.0
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") != "mouvement_enregistre":
            continue
        if maillon["type_mouvement"] in _TYPES_SOLDE:
            total += maillon["montant"]
    return total


def calculer_argent_disponible(registre_cible):
    solde = calculer_solde(registre_cible)
    total_provisions = 0.0
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") != "mouvement_enregistre":
            continue
        if maillon["type_mouvement"] == "PROVISION":
            total_provisions += maillon["montant"]
    return solde - total_provisions
