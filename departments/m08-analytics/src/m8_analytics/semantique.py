import math
from datetime import datetime

from . import encodage


def _analyser_horodatage(horodatage):
    """Parse un horodatage ISO-8601, y compris le suffixe 'Z'.

    datetime.fromisoformat() ne comprend 'Z' que depuis Python 3.11 ; le job CI
    n'épingle pas de version Python explicite, donc on normalise nous-mêmes
    plutôt que de dépendre d'un comportement récent du parseur stdlib.
    """
    if horodatage.endswith("Z"):
        horodatage = horodatage[:-1] + "+00:00"
    return datetime.fromisoformat(horodatage)


def deriver_metrique(
    module_source,
    metric_id,
    definition,
    registre_cible,
    horodatage_reference,
):
    candidats = []
    valeurs_invalides = 0
    derniere_valeur_invalide = False
    for maillon in registre_cible.lire():
        if maillon["module_source"] != module_source:
            continue
        if metric_id not in maillon["valeurs"]:
            continue
        valeur_brute = maillon["valeurs"][metric_id]
        if not isinstance(valeur_brute, str):
            valeurs_invalides += 1
            derniere_valeur_invalide = True
            continue
        try:
            valeur = float(valeur_brute)
        except (TypeError, ValueError):
            valeurs_invalides += 1
            derniere_valeur_invalide = True
            continue
        derniere_valeur_invalide = not math.isfinite(valeur)
        if not math.isfinite(valeur):
            valeurs_invalides += 1
            continue
        candidats.append((maillon["index"], maillon["horodatage"], valeur))

    version_definition = encodage.empreinte(definition)
    n = len(candidats)

    if n == 0:
        resultat = {
            "metric_id": metric_id,
            "valeur": None,
            "version_definition": version_definition,
            "fraicheur": None,
            "n": 0,
        }
        if valeurs_invalides:
            resultat["valeurs_invalides"] = valeurs_invalides
        if derniere_valeur_invalide:
            resultat["derniere_valeur_invalide"] = True
        return resultat

    _, horodatage_choisi, valeur_choisie = max(candidats, key=lambda t: t[0])
    fraicheur = (
        _analyser_horodatage(horodatage_reference)
        - _analyser_horodatage(horodatage_choisi)
    ).total_seconds() / 86400

    resultat = {
        "metric_id": metric_id,
        "valeur": valeur_choisie,
        "version_definition": version_definition,
        "fraicheur": fraicheur,
        "n": n,
    }
    if valeurs_invalides:
        resultat["valeurs_invalides"] = valeurs_invalides
    if derniere_valeur_invalide:
        resultat["derniere_valeur_invalide"] = True
    return resultat
