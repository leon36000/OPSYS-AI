"""Calcul pur de sessions explicites ; l'appelant doit vérifier les sources et l'autorité.

Ne crée aucune association historique et ne constitue ni une présence individuelle,
ni une validation de paie. Les instants sont calculés en UTC, jamais en temps mural.
"""
from datetime import UTC, datetime

MAX_VISITES = 1000
MAX_PAUSES = 100


def _instant(valeur):
    if type(valeur) is not str:
        raise ValueError('instant invalide')
    try:
        instant = datetime.fromisoformat(valeur)
        if instant.utcoffset() is None:
            raise ValueError
        return instant.astimezone(UTC)
    except (ValueError, OverflowError):
        raise ValueError('instant zoné requis') from None


def _minutes(debut, fin):
    secondes = (fin - debut).total_seconds()
    if secondes < 0 or secondes % 60:
        raise ValueError('intervalle invalide ou précision inférieure à la minute')
    return int(secondes // 60)


def calculer_sessions(sessions):
    """Somme des intervalles explicites complets ; refuse toute ambiguïté.

    Les champs de temps ne sont pas des preuves à eux seuls. La validation des
    identités, ancrages et pointages liés appartient au lecteur durable.
    """
    if type(sessions) is not list or not 1 <= len(sessions) <= MAX_VISITES:
        raise ValueError('nombre de visites invalide')
    visites, ids, chantier = [], set(), None
    for session in sessions:
        if type(session) is not dict:
            raise ValueError('visite invalide')
        visite_id, intervention = session.get('visite_id'), session.get('intervention_id')
        if any(type(x) is not str or not x.strip() or len(x) > 256 for x in (visite_id, intervention)):
            raise ValueError('identité invalide')
        if visite_id in ids or (chantier is not None and intervention != chantier):
            raise ValueError('visite dupliquée ou chantier différent')
        ids.add(visite_id)
        chantier = intervention
        route, arrivee, depart = (_instant(session.get(c)) for c in ('en_route', 'arrivee', 'depart'))
        deplacement = _minutes(route, arrivee)
        presence = _minutes(arrivee, depart)
        if presence == 0:
            raise ValueError('visite vide')
        pauses = session.get('pauses')
        if type(pauses) is not list or len(pauses) > MAX_PAUSES:
            raise ValueError('pauses invalides')
        intervalles = []
        for pause in pauses:
            if type(pause) not in (tuple, list) or len(pause) != 2:
                raise ValueError('pause invalide')
            debut, fin = map(_instant, pause)
            if not arrivee <= debut < fin <= depart:
                raise ValueError('pause hors visite')
            _minutes(debut, fin)
            intervalles.append((debut, fin))
        intervalles.sort()
        if any(a[1] > b[0] for a, b in zip(intervalles, intervalles[1:])):
            raise ValueError('pauses chevauchées')
        minutes_pause = sum(_minutes(a, b) for a, b in intervalles)
        visites.append({'visite_id': visite_id, 'intervention_id': intervention,
                        'travail_minutes': presence - minutes_pause,
                        'pause_minutes': minutes_pause, 'deplacement_minutes': deplacement,
                        '_route': route, '_depart': depart})
    visites.sort(key=lambda v: (v['_route'], v['visite_id']))
    if any(a['_depart'] > b['_route'] for a, b in zip(visites, visites[1:])):
        raise ValueError('visites chevauchées')
    for v in visites:
        del v['_route'], v['_depart']
    return {'visites': visites, **{cle: sum(v[cle] for v in visites) for cle in
            ('travail_minutes', 'pause_minutes', 'deplacement_minutes')}}
