"""Produit un digest texte agrégé, déterministe et sans fuite de données sensibles."""

import collections

CANAUX = ["telephone", "courriel", "formulaire", "texte"]
TYPES = ["signal", "transition_phase", "lead_emis", "chiffrage_emis", "alerte"]


def _canal_de(entree: dict) -> str:
    """Canal d'une entrée : premier niveau prioritaire, replié sur payload.canal.

    Correctif d'audit : les entrées réellement écrites par le pipeline (ex. les
    transitions de phase composées par le tool layer) ne portent pas toujours le
    canal au premier niveau. S'en tenir au seul premier niveau les classait
    systématiquement en « non classées », même quand l'information existait.
    """
    canal = entree.get("canal")
    if not canal:
        payload = entree.get("payload")
        if isinstance(payload, dict):
            canal = payload.get("canal")
    return canal or ""


def _correspond_a_la_date(entree: dict, date_reference: str) -> bool:
    """Vrai si l'entrée compte pour cette date_reference.

    Correctif d'audit : date_reference ne servait qu'à l'en-tête du digest, sans
    jamais filtrer les entrées — un registre contenant plusieurs jours voyait
    tout compté dans n'importe quel digest, quelle que soit la date demandée.
    Une entrée SANS horodatage n'est jamais exclue (compatibilité avec les
    appelants historiques qui n'en fournissent pas) ; une entrée horodatée un
    autre jour que date_reference est exclue, car c'est précisément le filtre
    que la date de référence est censée appliquer.
    """
    horodatage = entree.get("horodatage")
    if not isinstance(horodatage, str) or not horodatage:
        return True
    return horodatage[:10] == date_reference


def produire_digest(entrees: list[dict], date_reference: str) -> str:
    """Génère un rapport agrégé en français pour la période de référence.

    * Byte-identique pour les mêmes entrées et date_reference.
    * Indépendant de l'ordre des entrées.
    * Ne contient jamais de prix ni de date d'engagement issus des payloads.
    * Pour une liste vide, produit un texte non‑vide signalant l'absence.
    * Une entrée horodatée un autre jour que date_reference n'est comptée
      dans aucune case : date_reference filtre réellement la période.
    * Les entrées dont le canal ou le type_entree ne sont pas reconnus sont
      comptabilisées séparément sous la rubrique "entrées non classées".
    """
    if not entrees:
        return f"Absence d'activité enregistrée pour la période de référence {date_reference}."

    compteur = collections.Counter()
    non_classes = 0
    for entree in entrees:
        if not _correspond_a_la_date(entree, date_reference):
            continue
        canal = _canal_de(entree)
        type_entree = entree.get("type_entree", "")
        if canal in CANAUX and type_entree in TYPES:
            compteur[(canal, type_entree)] += 1
        else:
            non_classes += 1

    lignes = [f"DIGEST - Période de référence : {date_reference}"]
    for canal in CANAUX:
        for type_ in TYPES:
            nb = compteur.get((canal, type_), 0)
            lignes.append(f"- {canal}: {type_}: {nb}")
    lignes.append(f"- entrées non classées : {non_classes}")
    return "\n".join(lignes)
