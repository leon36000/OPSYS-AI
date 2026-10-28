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


def calculer_faits(registre, intervention_id):
    """Lit les faits porteurs d'une identité explicite, sans rétro-attribution.

    Toute source ancienne non identifiée bloque le total. Ce lecteur reste privé :
    les writers et l'authenticité des identités de visite doivent encore être raccordés.
    """
    from .registre import Registre, VerificationError

    if type(intervention_id) is not str or not intervention_id.strip():
        raise ValueError('intervention invalide')
    if registre.taille() > 10000:
        raise ValueError('source trop volumineuse')
    maillons = registre.lire()
    try:
        Registre(maillons).assert_chaine()
    except VerificationError:
        raise ValueError('chaîne invalide') from None
    sessions, sources, actives = {}, {}, {}
    for m in maillons:
        if m.get('intervention_id') != intervention_id:
            continue
        action = (m.get('statut') if m.get('type_entree') == 'transition_statut'
                  else m.get('action') if m.get('type_entree') == 'pointage' else None)
        if action not in {'en_route', 'arrivee', 'depart', 'pause_debut', 'pause_fin'}:
            continue
        ident = m.get('visite_id')
        technicien = m.get('technicien_id')
        if (type(ident) is not str or not ident.strip() or type(technicien) is not str
                or not technicien.strip()):
            raise ValueError('pointage sans identité explicite')
        instant = _instant(m.get('horodatage'))
        if action == 'en_route':
            if ident in sessions or actives:
                raise ValueError('visite dupliquée ou ouverte')
            sessions[ident] = {'visite_id': ident, 'intervention_id': intervention_id,
                               'en_route': m['horodatage'], 'pauses': []}
            sources[ident] = []
            actives[ident] = {'phase': 'route', 'technicien': technicien, 'dernier': instant, 'pause': None}
        elif ident not in actives:
            raise ValueError('pointage sans visite ouverte')
        etat = actives[ident]
        if technicien != etat['technicien'] or instant < etat['dernier']:
            raise ValueError('équipe ou chronologie incohérente')
        phase = etat['phase']
        if action == 'arrivee':
            if phase != 'route':
                raise ValueError('arrivée incohérente')
            sessions[ident]['arrivee'] = m['horodatage']
            etat['phase'] = 'presence'
        elif action == 'pause_debut':
            if phase != 'presence' or etat['pause'] is not None:
                raise ValueError('pause incohérente')
            etat['pause'] = m['horodatage']
        elif action == 'pause_fin':
            if phase != 'presence' or etat['pause'] is None:
                raise ValueError('pause incohérente')
            sessions[ident]['pauses'].append((etat['pause'], m['horodatage']))
            etat['pause'] = None
        elif action == 'depart':
            if phase != 'presence' or etat['pause'] is not None:
                raise ValueError('départ incohérent')
            sessions[ident]['depart'] = m['horodatage']
        sources[ident].append(m['ligne_id'])
        etat['dernier'] = instant
        if action == 'depart':
            del actives[ident]
    if actives:
        raise ValueError('visite incomplète')
    resultat = calculer_sessions(list(sessions.values()))
    for visite in resultat['visites']:
        visite['sources'] = sources[visite['visite_id']][:]
    return resultat
