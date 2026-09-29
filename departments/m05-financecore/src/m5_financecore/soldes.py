from __future__ import annotations

from datetime import datetime
from decimal import Decimal

_TYPES_SOLDE = ("ENCAISSEMENT", "DECAISSEMENT", "AJUSTEMENT", "AUTRE")


def calculer_solde(registre_cible):
    total = Decimal("0")
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") != "mouvement_enregistre":
            continue
        if maillon["type_mouvement"] in _TYPES_SOLDE:
            total += maillon["montant"]
    return total


def calculer_provisions(registre_cible):
    """`(total, nombre, derniere_piece)` des mouvements `PROVISION` du registre : ce qui est mis de côté sans sortir
    du solde.

    Lecture pure (T4.16) : la même somme que celle que `calculer_argent_disponible` retranche, exposée pour que le
    cash libre puisse dire d'où vient sa composante « réserves ». `nombre` distingue « aucune réserve posée » (jamais
    un zéro qui passerait pour une décision) de « des réserves totalisant zéro » ; `derniere_piece` est l'horodatage
    de la plus récente (`None` s'il n'y en a aucune)."""
    total = Decimal("0")
    nombre = 0
    plus_recente = None
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") != "mouvement_enregistre":
            continue
        if maillon["type_mouvement"] == "PROVISION":
            total += maillon["montant"]
            nombre += 1
            instant = datetime.fromisoformat(maillon["horodatage"])
            if plus_recente is None or instant > datetime.fromisoformat(plus_recente):
                plus_recente = maillon["horodatage"]
    return total, nombre, plus_recente


def calculer_argent_disponible(registre_cible):
    solde = calculer_solde(registre_cible)
    total_provisions, _, _ = calculer_provisions(registre_cible)
    return solde - total_provisions


def decrire_mouvements(registre_cible):
    """Ce qui porte le solde, pour en dire la source et la fraîcheur (T4.16) : le nombre de mouvements du registre,
    l'horodatage du plus récent (à l'instant, pas à l'ordre d'écriture : l'horodatage est fourni par l'appelant) et la
    tête de la chaîne. Lecture pure ; `derniere_piece` est `None` si le registre ne porte aucun mouvement."""
    maillons = registre_cible.lire()
    mouvements = [m for m in maillons if m.get("type_entree") == "mouvement_enregistre"]
    plus_recent = max(mouvements, key=lambda m: datetime.fromisoformat(m["horodatage"]), default=None)
    return {
        "nombre": len(mouvements),
        "derniere_piece": plus_recent["horodatage"] if plus_recent is not None else None,
        "taille_registre": len(maillons),
        "tete": maillons[-1]["ligne_id"] if maillons else None,
    }
