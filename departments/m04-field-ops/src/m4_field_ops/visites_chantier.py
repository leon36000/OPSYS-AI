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
        if any(a[1] > b[0] for a, b in zip(intervalles, intervalles[1:], strict=False)):
            raise ValueError('pauses chevauchées')
        minutes_pause = sum(_minutes(a, b) for a, b in intervalles)
        visites.append({'visite_id': visite_id, 'intervention_id': intervention,
                        'travail_minutes': presence - minutes_pause,
                        'pause_minutes': minutes_pause, 'deplacement_minutes': deplacement,
                        '_route': route, '_depart': depart})
    visites.sort(key=lambda v: (v['_route'], v['visite_id']))
    if any(a['_depart'] > b['_route'] for a, b in zip(visites, visites[1:], strict=False)):
        raise ValueError('visites chevauchées')
    for v in visites:
        del v['_route'], v['_depart']
    return {'visites': visites, **{cle: sum(v[cle] for v in visites) for cle in
            ('travail_minutes', 'pause_minutes', 'deplacement_minutes')}}


def _anomalie_validee(maillons, point):
    """Une décision de revue doit référencer exactement le pointage concerné."""
    from . import encodage

    indices = {m.get('ligne_id'): i for i, m in enumerate(maillons)}
    demandes = [m for m in maillons if m.get('type_entree') == 'demande_revue'
                and m.get('type_demande') == 'anomalie_pointage'
                and m.get('pointage_ligne_id') == point.get('ligne_id')]
    if len(demandes) != 1:
        return False
    demande = demandes[0]
    did = demande.get('demande_id')
    if (demande.get('intervention_id') != point.get('intervention_id')
            or demande.get('horodatage') != point.get('horodatage')
            or did != encodage.empreinte('demande_revue', point.get('intervention_id'), point.get('horodatage'))
            or demande.get('statut_arbitrage') != 'en_attente'):
        return False
    decisions = [m for m in maillons if m.get('type_entree') == 'resolution_revue'
                 and m.get('demande_id') == did]
    if len(decisions) != 1:
        return False
    resolution = decisions[0]
    rang = indices.get(resolution.get('ligne_id'), -1)
    if (rang < 1 or indices.get(point.get('ligne_id'), -1) >= indices.get(demande.get('ligne_id'), -1)
            or indices.get(demande.get('ligne_id'), -1) >= rang
            or resolution.get('intervention_id') != point.get('intervention_id')
            or resolution.get('decision') != 'validee' or resolution.get('statut_arbitrage') != 'validee'
            or resolution.get('resolution_id') != encodage.empreinte(
                'resolution_revue', did, resolution.get('horodatage'))
            or _instant(resolution.get('horodatage')) < _instant(demande.get('horodatage'))):
        return False
    transition = maillons[rang - 1]
    return (transition.get('type_entree') == 'transition_statut'
            and transition.get('intervention_id') == point.get('intervention_id')
            and transition.get('statut_precedent') == 'en_revue' and transition.get('statut') == 'sur_site'
            and transition.get('horodatage') == resolution.get('horodatage'))


def calculer_faits(registre, intervention_id, *, ignorer_anciens=False, ignorer_visite=None):
    """Lit les faits porteurs d'une identité explicite, sans rétro-attribution.

    Par défaut toute source ancienne non identifiée bloque le total. Le mode interne
    de fermeture ne les attribue pas et ne doit pas servir à établir un total global.
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
        if (ignorer_anciens and ident is None) or (ignorer_visite is not None and ident == ignorer_visite):
            continue
        technicien = m.get('technicien_id')
        if (type(ident) is not str or not ident.strip() or type(technicien) is not str
                or not technicien.strip()):
            raise ValueError('pointage sans identité explicite')
        instant = _instant(m.get('horodatage'))
        if action == 'en_route':
            if ident in sessions or any(a['phase'] != 'fermee' for a in actives.values()):
                raise ValueError('visite dupliquée ou ouverte')
            actives.clear()
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
        if (action in ('arrivee', 'depart') and 'gps_coherent' in m
                and m['gps_coherent'] is not True and not _anomalie_validee(maillons, m)):
            raise ValueError('anomalie GPS non arbitrée')
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
            if (phase not in ('presence', 'fermee') or etat['pause'] is not None
                    or (phase == 'fermee' and (m.get('gps_coherent') is True
                        or not _anomalie_validee(maillons, m)))):
                raise ValueError('départ incohérent')
            sessions[ident]['depart'] = m['horodatage']
            etat['phase'] = 'fermee'
        sources[ident].append(m['ligne_id'])
        etat['dernier'] = instant
    if any(a['phase'] != 'fermee' for a in actives.values()):
        raise ValueError('visite incomplète')
    resultat = calculer_sessions(list(sessions.values()))
    for visite in resultat['visites']:
        visite['sources'] = sources[visite['visite_id']][:]
    return resultat


def ouvrir(principal, visites, visite_id, horodatage, *, provenance=None):
    """Ouvre une visite prévue avec preuve civile courante, sans écrire de pointage.

    Fonction pure : l'adaptateur devra fournir transaction, autorité et rejeu.
    """
    from zoneinfo import ZoneInfo

    from . import annotations_calendrier as notes
    from . import etats, visites_durables

    if principal is visites or type(visite_id) is not str:
        raise ValueError('visite invalide')
    instant = _instant(horodatage)
    tete_principal, tete_visites = principal.tete(), visites.tete()
    try:
        _, lignes, sources, _, _, _ = visites_durables._charger(principal, visites)
        candidats = [m for m in lignes if m['ligne_id'] == visite_id]
        if len(candidats) != 1:
            raise ValueError('prévision inconnue')
        prevision = candidats[0]
        ancre = prevision['ancre']
        intervention = ancre['intervention_id']
        courant = sources[1].get(notes._cle(ancre))
        if (courant is None or courant['validite'] != 'date_confirmee'
                or etats.statut_courant(principal, intervention) != 'planifiee'):
            raise ValueError('prévision remplacée ou état incompatible')
        if (instant < _instant(prevision['horodatage']) or
                instant.astimezone(ZoneInfo('America/Montreal')).date().isoformat()
                != prevision['creneau']['debut'][:10]):
            raise ValueError('jour ou chronologie incohérent')
        if (visite_active(principal, intervention) is not None or any(
                m.get('type_entree') == 'visite_ouverte' and m.get('visite_id') == visite_id
                for m in principal.lire())):
            raise ValueError('visite déjà ouverte ou identité déjà utilisée')
        if principal.tete() != tete_principal or visites.tete() != tete_visites:
            raise ValueError('source modifiée')
        entree = {'type_entree': 'visite_ouverte', 'intervention_id': intervention,
                  'visite_id': visite_id, 'source_calendrier': ancre['source_ligne_id'],
                  'source_application': ancre['source_application_id'],
                  'equipe_id': prevision['creneau']['equipe_id'], 'horodatage': horodatage}
        if provenance is not None:
            entree.update(_provenance(provenance, 'ouvrir', visite_id))
        ligne = principal.ajouter(entree)
        return {'visite_id': visite_id, 'ouverture_id': ligne}
    except notes.Refus as exc:
        raise ValueError('source de visite invalide') from exc


def verifier_ouverture_courante(principal, ouverture):
    """Revalide l'ancre civile au moment du départ, sans utiliser un profil courant."""
    from . import annotations_calendrier as notes

    try:
        sources = notes._sources(principal)
        datee = sources[0][ouverture['source_calendrier']][1]
        ancre = {'intervention_id': ouverture['intervention_id'], 'plan_id': datee['plan_id'],
                 'source_application_id': ouverture['source_application'],
                 'source_ligne_id': ouverture['source_calendrier']}
        creneau = notes._creneau(sources, ancre)
        courante = sources[1].get(notes._cle(ancre))
        if (courante is None or courante['validite'] != 'date_confirmee'
                or creneau['equipe_id'] != ouverture['equipe_id']):
            raise ValueError('prévision remplacée')
    except (notes.Refus, KeyError, TypeError) as exc:
        raise ValueError('ancre de visite invalide') from exc


def visite_active(registre, intervention_id):
    """Identité explicite ouverte ; une chaîne contradictoire échoue fermée."""
    ouverte = None
    for m in registre.lire():
        if m.get('intervention_id') != intervention_id:
            continue
        if m.get('type_entree') == 'visite_ouverte':
            if (ouverte is not None or not isinstance(m.get('visite_id'), str)
                    or not isinstance(m.get('equipe_id'), str) or not m['equipe_id']):
                raise ValueError('ouvertures contradictoires')
            _instant(m.get('horodatage'))
            ouverte = m
        elif m.get('type_entree') == 'visite_fermee':
            if (ouverte is None or m.get('visite_id') != ouverte['visite_id']
                    or m.get('ouverture_id') != ouverte['ligne_id']
                    or _instant(m.get('horodatage')) < _instant(ouverte['horodatage'])):
                raise ValueError('fermeture contradictoire')
            ouverte = None
    return ouverte


def fermer(principal, visites, visite_id, horodatage, *, provenance=None):
    """Ferme une session pointée sans achever le chantier ni émettre de WCT."""
    from . import etats, visites_durables
    from .annotations_calendrier import Refus

    instant = _instant(horodatage)
    tete_principal, tete_visites = principal.tete(), visites.tete()
    try:
        _, lignes, _, _, _, _ = visites_durables._charger(principal, visites)
        previsions = [m for m in lignes if m['ligne_id'] == visite_id]
        if len(previsions) != 1:
            raise ValueError('prévision inconnue')
        prevision = previsions[0]
        iid = prevision['ancre']['intervention_id']
        ouverture = visite_active(principal, iid)
        if (ouverture is None or ouverture['visite_id'] != visite_id
                or ouverture['source_calendrier'] != prevision['ancre']['source_ligne_id']
                or ouverture['source_application'] != prevision['ancre']['source_application_id']
                or ouverture['equipe_id'] != prevision['creneau']['equipe_id']
                or etats.statut_courant(principal, iid) != 'sur_site'):
            raise ValueError('ouverture ou état incompatible')
        resultat = calculer_faits(principal, iid, ignorer_anciens=True)
        sessions = [v for v in resultat['visites'] if v['visite_id'] == visite_id]
        if len(sessions) != 1:
            raise ValueError('session incomplète')
        dernier_id = sessions[0]['sources'][-1]
        dernier = next(m for m in principal.lire() if m.get('ligne_id') == dernier_id)
        if dernier.get('action') != 'depart' or instant < _instant(dernier['horodatage']):
            raise ValueError('départ absent ou chronologie invalide')
        if principal.tete() != tete_principal or visites.tete() != tete_visites:
            raise ValueError('source modifiée')
        entree = {'type_entree': 'visite_fermee', 'intervention_id': iid,
                  'visite_id': visite_id, 'ouverture_id': ouverture['ligne_id'],
                  'source_depart': dernier_id, 'horodatage': horodatage}
        if provenance is not None:
            entree.update(_provenance(provenance, 'fermer', visite_id))
        ligne = principal.ajouter(entree)
        return {'visite_id': visite_id, 'fermeture_id': ligne}
    except Refus as exc:
        raise ValueError('source de visite invalide') from exc


def calculer_faits_certifies(principal, visites, intervention_id, *, ignorer_anciens=False,
                             omettre_ouverte=False):
    """Vérifie les ancres et fermetures explicites avant tout total de chantier.

    Les anomalies GPS exigent une demande et une résolution validée reliées au pointage.
    Le mode interne d'interruption écarte les anciens faits hors session sans les
    attribuer. Le mode de consultation peut omettre la session encore ouverte.
    Dans ces deux modes, le résultat n'est pas un total global certifié pour WCT.
    """
    from zoneinfo import ZoneInfo

    from . import visites_durables
    from .annotations_calendrier import Refus

    tete_principal, tete_visites = principal.tete(), visites.tete()
    try:
        _, lignes, _, _, _, _ = visites_durables._charger(principal, visites)
        previsions = {m['ligne_id']: m for m in lignes}
        from .registre import Registre

        active, utilisees, dernier_depart, technicien_route = None, set(), None, None
        ouverte_courante = visite_active(principal, intervention_id) if omettre_ouverte else None
        maillons = principal.lire()
        for rang, m in enumerate(maillons):
            if m.get('intervention_id') != intervention_id:
                continue
            typ = m.get('type_entree')
            if typ in {'visite_ouverte', 'visite_fermee'} and any(
                    k in m for k in ('auteur', 'mutation', 'source_attendue')):
                _provenance({k: m[k] for k in ('auteur', 'mutation', 'source_attendue')},
                            'ouvrir' if typ == 'visite_ouverte' else 'fermer', m.get('visite_id'))
            action = m.get('action') if typ == 'pointage' else m.get('statut') if typ == 'transition_statut' else None
            if typ == 'visite_ouverte':
                ident = m.get('visite_id')
                prev = previsions.get(ident)
                if active is not None or ident in utilisees or prev is None:
                    raise ValueError('ouverture sans prévision unique')
                ancre, creneau = prev['ancre'], prev['creneau']
                if (ancre['intervention_id'] != intervention_id
                        or m.get('source_calendrier') != ancre['source_ligne_id']
                        or m.get('source_application') != ancre['source_application_id']
                        or m.get('equipe_id') != creneau['equipe_id']
                        or _instant(m['horodatage']) < _instant(prev['horodatage'])
                        or _instant(m['horodatage']).astimezone(ZoneInfo('America/Montreal')).date().isoformat()
                        != creneau['debut'][:10]):
                    raise ValueError('ancre ou ouverture incohérente')
                verifier_ouverture_courante(Registre(maillons[:rang]), m)
                active, dernier_depart, technicien_route = m, None, None
                utilisees.add(ident)
            elif action in {'en_route', 'arrivee', 'depart', 'pause_debut', 'pause_fin'}:
                if ignorer_anciens and m.get('visite_id') is None and active is None:
                    continue
                if (active is None or m.get('visite_id') != active['visite_id']
                        or _instant(m['horodatage']) < _instant(active['horodatage'])):
                    raise ValueError('fait sans ouverture correspondante')
                if action == 'en_route':
                    verifier_ouverture_courante(Registre(maillons[:rang]), active)
                    if technicien_route is not None or not m.get('technicien_id'):
                        raise ValueError('route incohérente')
                    technicien_route = m['technicien_id']
                elif technicien_route is None or m.get('technicien_id') != technicien_route:
                    raise ValueError('pointage sans technicien de route correspondant')
                if (typ == 'pointage' and action in ('arrivee', 'depart')
                        and m.get('gps_coherent') is not True
                        and not (ouverte_courante and m.get('visite_id') == ouverte_courante['visite_id'])
                        and not _anomalie_validee(maillons, m)):
                    raise ValueError('anomalie GPS non arbitrée')
                if action == 'depart':
                    dernier_depart = m
            elif typ == 'visite_fermee':
                if (active is None or m.get('visite_id') != active['visite_id']
                        or m.get('ouverture_id') != active['ligne_id'] or dernier_depart is None
                        or m.get('source_depart') != dernier_depart['ligne_id']
                        or _instant(m['horodatage']) < _instant(dernier_depart['horodatage'])):
                    raise ValueError('fermeture sans départ correspondant')
                active, dernier_depart, technicien_route = None, None, None
        if (active is not None and not omettre_ouverte) or not utilisees:
            raise ValueError('visite ouverte ou absente')
        ouverte_id = active['visite_id'] if active is not None else None
        fermees = utilisees - ({ouverte_id} if ouverte_id is not None else set())
        if not fermees:
            raise ValueError('aucune visite fermée')
        resultat = calculer_faits(principal, intervention_id, ignorer_anciens=ignorer_anciens,
                                   ignorer_visite=ouverte_id)
        if {v['visite_id'] for v in resultat['visites']} != fermees:
            raise ValueError('sessions incohérentes')
        if principal.tete() != tete_principal or visites.tete() != tete_visites:
            raise ValueError('source modifiée')
        return resultat
    except (Refus, KeyError, TypeError, StopIteration) as exc:
        raise ValueError('source de visite invalide') from exc


def _provenance(provenance, operation, visite_id):
    from copy import deepcopy

    from . import annotations_calendrier as notes

    if type(provenance) is not dict or set(provenance) != {'auteur', 'mutation', 'source_attendue'}:
        raise ValueError('provenance invalide')
    try:
        notes._auteur(provenance['auteur'])
        source = provenance['source_attendue']
        if type(source) is not str or notes._HEX.fullmatch(source) is None:
            raise ValueError('source invalide')
        notes._mutation(provenance['mutation'], {'operation': operation, 'visite_id': visite_id,
                                                 'source_attendue': source})
    except notes.Refus as exc:
        raise ValueError('provenance invalide') from exc
    return deepcopy(provenance)
