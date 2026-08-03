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
    for maillon in registre_cible.lire():
        if maillon["module_source"] != module_source:
            continue
        if metric_id not in maillon["valeurs"]:
            continue
        try:
            valeur = float(maillon["valeurs"][metric_id])
        except (TypeError, ValueError):
            continue
        candidats.append((maillon["index"], maillon["horodatage"], valeur))

    version_definition = encodage.empreinte(definition)
    n = len(candidats)

    if n == 0:
        return {
            "metric_id": metric_id,
            "valeur": None,
            "version_definition": version_definition,
            "fraicheur": None,
            "n": 0,
        }

    _, horodatage_choisi, valeur_choisie = max(candidats, key=lambda t: t[0])
    fraicheur = (
        _analyser_horodatage(horodatage_reference)
        - _analyser_horodatage(horodatage_choisi)
    ).total_seconds() / 86400

    return {
        "metric_id": metric_id,
        "valeur": valeur_choisie,
        "version_definition": version_definition,
        "fraicheur": fraicheur,
        "n": n,
    }
