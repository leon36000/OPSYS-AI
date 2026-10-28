"""Données fictives : calcul explicite par visite, sans inférence des liens anciens."""
from copy import deepcopy

import pytest

from m4_field_ops import visites_chantier as visites


def session(ident, route, arrivee, depart, pauses=()):
    return {'visite_id': ident, 'intervention_id': 'chantier-fictif',
            'en_route': route, 'arrivee': arrivee, 'depart': depart,
            'pauses': list(pauses), 'fictif': True}


def scenario():
    return [session('visite-lundi', '2026-11-02T08:30:00-05:00',
                    '2026-11-02T09:00:00-05:00', '2026-11-02T12:00:00-05:00',
                    [('2026-11-02T10:00:00-05:00', '2026-11-02T10:30:00-05:00')]),
            session('visite-vendredi', '2026-11-06T13:40:00+00:00',
                    '2026-11-06T14:00:00+00:00', '2026-11-06T18:00:00+00:00')]


def test_temps_par_visite_et_trous_exclus():
    original = scenario()
    donnees = deepcopy(original)
    r = visites.calculer_sessions(donnees)
    assert r['travail_minutes'] == 390
    assert r['pause_minutes'] == 30
    assert r['deplacement_minutes'] == 50
    assert [v['travail_minutes'] for v in r['visites']] == [150, 240]
    assert donnees == original


def test_refuse_chevauchement_et_repetitions():
    deux = scenario()
    deux[1]['en_route'] = '2026-11-02T11:00:00-05:00'
    deux[1]['arrivee'] = '2026-11-02T11:30:00-05:00'
    deux[1]['depart'] = '2026-11-02T13:00:00-05:00'
    with pytest.raises(ValueError):
        visites.calculer_sessions(deux)
    deux = scenario()
    deux[1]['visite_id'] = deux[0]['visite_id']
    with pytest.raises(ValueError):
        visites.calculer_sessions(deux)


@pytest.mark.parametrize('pauses', [
    [('2026-11-02T08:59:00-05:00', '2026-11-02T09:10:00-05:00')],
    [('2026-11-02T11:59:00-05:00', '2026-11-02T12:01:00-05:00')],
    [('2026-11-02T10:00:00-05:00', '2026-11-02T10:30:00-05:00'),
     ('2026-11-02T10:15:00-05:00', '2026-11-02T10:45:00-05:00')],
])
def test_refuse_pauses_hors_visite_ou_chevauchees(pauses):
    s = scenario()
    s[0]['pauses'] = pauses
    with pytest.raises(ValueError):
        visites.calculer_sessions(s)


def test_instants_zones_et_precision_exacte_requis():
    for champ, instant in [('arrivee', '2026-11-02T09:00:00'),
                           ('depart', '2026-11-02T12:00:01-05:00')]:
        s = scenario()
        s[0][champ] = instant
        with pytest.raises(ValueError):
            visites.calculer_sessions(s)


def test_changement_heure_calcule_en_utc():
    s = [session('nuit-fictive', '2026-11-01T00:00:00-04:00',
                 '2026-11-01T00:30:00-04:00', '2026-11-01T02:30:00-05:00')]
    assert visites.calculer_sessions(s)['travail_minutes'] == 180


def test_aucune_session_complete_inventee():
    for valeur in ([], [dict(scenario()[0], depart=None)],
                   [dict(scenario()[0], intervention_id='')],
                   [scenario()[0], dict(scenario()[1], intervention_id='autre-fictif')]):
        with pytest.raises(ValueError):
            visites.calculer_sessions(valeur)


def test_ordre_sans_mutation_et_limites():
    sessions = list(reversed(scenario()))
    avant = deepcopy(sessions)
    resultat = visites.calculer_sessions(sessions)
    assert [v['visite_id'] for v in resultat['visites']] == ['visite-lundi', 'visite-vendredi']
    assert sessions == avant
    with pytest.raises(ValueError):
        visites.calculer_sessions([scenario()[0]] * (visites.MAX_VISITES + 1))
