from . import contrats


def valider_snapshot(snapshot, dictionnaire):
    if not isinstance(snapshot, dict):
        return False, "REJ-SNAPSHOT-STRUCTURE-INVALIDE"
    if set(snapshot.keys()) != contrats.CHAMPS_SNAPSHOT_MODULE:
        return False, "REJ-SNAPSHOT-STRUCTURE-INVALIDE"
    if not isinstance(snapshot["valeurs"], dict):
        return False, "REJ-SNAPSHOT-STRUCTURE-INVALIDE"

    module_source = snapshot["module_source"]
    if module_source not in dictionnaire:
        return False, "REJ-SNAPSHOT-MODULE-INCONNU"

    metriques_module = dictionnaire[module_source]
    for metric_id in snapshot["valeurs"]:
        if metric_id not in metriques_module:
            return False, "REJ-SNAPSHOT-METRIC-ID-INCONNU"

    # PRD §5.2 (SnapshotModule) : chaque valeur est un fait rapporté par le
    # module source, TOUJOURS du texte — la conversion numérique n'a lieu QUE
    # dans la couche sémantique (semantique.py::deriver_metrique), jamais
    # avant (un nombre, un booléen ou tout autre type n'est pas du texte).
    for valeur in snapshot["valeurs"].values():
        if not isinstance(valeur, str):
            return False, "REJ-SNAPSHOT-VALEUR-NON-TEXTE"

    return True, None
