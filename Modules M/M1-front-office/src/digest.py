"""Produit un digest texte agrégé, déterministe et sans fuite de données sensibles."""

import collections

CANAUX = ["telephone", "courriel", "formulaire", "texte"]
TYPES = ["signal", "transition_phase", "lead_emis", "chiffrage_emis", "alerte"]


def produire_digest(entrees: list[dict], date_reference: str) -> str:
    """Génère un rapport agrégé en français pour la période de référence.

    * Byte-identique pour les mêmes entrées et date_reference.
    * Indépendant de l'ordre des entrées.
    * Ne contient jamais de prix ni de date d'engagement issus des payloads.
    * Pour une liste vide, produit un texte non‑vide signalant l'absence.
    """
    if not entrees:
        return f"Absence d'activité enregistrée pour la période de référence {date_reference}."

    compteur = collections.Counter()
    for entree in entrees:
        canal = entree.get("canal", "")
        type_entree = entree.get("type_entree", "")
        if canal in CANAUX and type_entree in TYPES:
            compteur[(canal, type_entree)] += 1

    lignes = [f"DIGEST - Période de référence : {date_reference}"]
    for canal in CANAUX:
        for type_ in TYPES:
            nb = compteur.get((canal, type_), 0)
            lignes.append(f"- {canal}: {type_}: {nb}")
    return "\n".join(lignes)
