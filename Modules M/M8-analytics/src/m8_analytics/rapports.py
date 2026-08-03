from . import encodage


def construire_rapport(metriques, signaux, role=None, metric_ids_autorises=None):
    if metric_ids_autorises is None:
        metriques_visibles = list(metriques)
        signaux_visibles = list(signaux)
    else:
        autorises = set(metric_ids_autorises)
        metriques_visibles = [m for m in metriques if m["metric_id"] in autorises]
        signaux_visibles = [s for s in signaux if s["metric_id"] in autorises]

    type_rapport = "RAPPORT_ANALYTIQUE"
    snapshot_id = encodage.empreinte(
        type_rapport, role, metriques_visibles, signaux_visibles
    )

    return {
        "type": type_rapport,
        "role": role,
        "metriques": metriques_visibles,
        "signaux": signaux_visibles,
        "snapshot_id": snapshot_id,
    }
