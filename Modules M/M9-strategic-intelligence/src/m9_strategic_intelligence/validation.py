from . import contrats


def valider_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return False, "REJ-SNAPSHOT-STRUCTURE-INVALIDE"

    if set(snapshot.keys()) != contrats.CHAMPS_SNAPSHOT_MODULE:
        return False, "REJ-SNAPSHOT-STRUCTURE-INVALIDE"

    if not isinstance(snapshot["valeurs"], dict):
        return False, "REJ-SNAPSHOT-STRUCTURE-INVALIDE"

    if (
        not isinstance(snapshot["module_source"], str)
        or not snapshot["module_source"]
        or not isinstance(snapshot["horodatage"], str)
        or not snapshot["horodatage"]
    ):
        return False, "REJ-SNAPSHOT-CHAMP-TEXTE-INVALIDE"

    if any(not isinstance(valeur, str) for valeur in snapshot["valeurs"].values()):
        return False, "REJ-SNAPSHOT-VALEUR-NON-TEXTE"

    return True, None
