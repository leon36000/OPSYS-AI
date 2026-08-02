"""Digest déterministe, en lecture seule, des estimations M3 enregistrées.

Le digest sélectionne dans une fenêtre fournie les estimations explicitement
bloquées et les alertes explicites de plancher. Il ne consulte ni horloge,
ni hasard, ni réseau et n'écrit jamais dans le registre : deux appels ayant
les mêmes maillons et les mêmes arguments retournent donc les mêmes octets.
Il ne valide pas l'authenticité métier du registre, ne répare aucune entrée
malformée et ne déduit pas une alerte absente ; il restitue uniquement les
signaux présents dans les maillons lisibles fournis par son appelant.
"""

from __future__ import annotations

import re
from typing import Any


_FORMAT_HORODATAGE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T"
    r"(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
    r"(Z|[+-]\d{2}:\d{2})$"
)


def _est_bissextile(annee: int) -> bool:
    return annee % 4 == 0 and (annee % 100 != 0 or annee % 400 == 0)


def _jours_avant_annee(annee: int) -> int:
    precedente = annee - 1
    return 365 * precedente + precedente // 4 - precedente // 100 + precedente // 400


def _instant_utc(valeur: str) -> tuple[int, int]:
    if not isinstance(valeur, str):
        raise ValueError("horodatage invalide : une chaîne ISO-8601 est requise")
    correspondance = _FORMAT_HORODATAGE.fullmatch(valeur)
    if correspondance is None:
        raise ValueError("horodatage invalide : fuseau ISO-8601 obligatoire")

    annee, mois, jour, heure, minute, seconde = (
        int(correspondance.group(index)) for index in range(1, 7)
    )
    fraction = correspondance.group(7) or ""
    fuseau = correspondance.group(8)

    jours_mois = [31, 28 + int(_est_bissextile(annee)), 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if (
        annee < 1
        or mois < 1
        or mois > 12
        or jour < 1
        or jour > jours_mois[mois - 1]
        or heure > 23
        or minute > 59
        or seconde > 59
    ):
        raise ValueError("horodatage invalide : date ou heure hors limites")

    decalage = 0
    if fuseau != "Z":
        signe = 1 if fuseau[0] == "+" else -1
        heures_decalage = int(fuseau[1:3])
        minutes_decalage = int(fuseau[4:6])
        if heures_decalage > 23 or minutes_decalage > 59:
            raise ValueError("horodatage invalide : décalage de fuseau hors limites")
        decalage = signe * (heures_decalage * 3600 + minutes_decalage * 60)

    jours = _jours_avant_annee(annee) + sum(jours_mois[: mois - 1]) + (jour - 1)
    secondes = jours * 86400 + heure * 3600 + minute * 60 + seconde - decalage
    nanosecondes = int((fraction + "000000000")[:9])
    return secondes, nanosecondes


def _dans_fenetre(
    horodatage: str,
    debut: tuple[int, int],
    fin: tuple[int, int],
) -> tuple[int, int]:
    instant = _instant_utc(horodatage)
    if not debut <= instant < fin:
        raise LookupError
    return instant


def _texte_raison(valeur: Any) -> str:
    return "-" if valeur is None else str(valeur)


def produire_digest(
    registre_cible: Any,
    debut_fenetre: str,
    fin_fenetre: str,
    horodatage: str,
) -> str:
    """Produit le digest canonique sans muter le registre fourni."""
    debut = _instant_utc(debut_fenetre)
    fin = _instant_utc(fin_fenetre)
    _instant_utc(horodatage)
    if fin <= debut:
        raise ValueError("fenêtre invalide : la fin doit être strictement postérieure au début")

    bloquees: list[tuple[tuple[int, int], str, str, str]] = []
    alertes: list[tuple[tuple[int, int], str, str]] = []

    maillons = registre_cible.lire()
    for maillon in maillons:
        if not isinstance(maillon, dict):
            continue
        if maillon.get("type_entree") != "estimation_produite":
            continue

        horodatage_entree = maillon.get("horodatage")
        if not isinstance(horodatage_entree, str):
            raise ValueError("estimation_produite sans horodatage ISO-8601")
        try:
            instant = _dans_fenetre(horodatage_entree, debut, fin)
        except LookupError:
            continue

        devis_id = maillon.get("devis_id")
        if not isinstance(devis_id, str):
            raise ValueError("estimation_produite sans devis_id textuel")

        if maillon.get("prix_bloque") is True:
            bloquees.append(
                (
                    instant,
                    devis_id,
                    horodatage_entree,
                    _texte_raison(maillon.get("raison_blocage")),
                )
            )
        if maillon.get("alerte_plancher") is True:
            alertes.append((instant, devis_id, horodatage_entree))

    bloquees.sort(key=lambda entree: (entree[0], entree[1], entree[2], entree[3]))
    alertes.sort(key=lambda entree: (entree[0], entree[1], entree[2]))

    lignes = [
        (
            f"DIGEST debut_fenetre={debut_fenetre} "
            f"fin_fenetre={fin_fenetre} horodatage={horodatage}"
        ),
        "[ESTIMATIONS_BLOQUEES]",
    ]
    for _, devis_id, horodatage_entree, raison in bloquees:
        lignes.append(
            f"  {devis_id} horodatage={horodatage_entree} raison_blocage={raison}"
        )

    lignes.append("[ALERTES_PLANCHER]")
    for _, devis_id, horodatage_entree in alertes:
        lignes.append(f"  {devis_id} horodatage={horodatage_entree}")

    return "\n".join(lignes)
