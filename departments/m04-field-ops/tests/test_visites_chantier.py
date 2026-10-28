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


def registre_sessions():
    from m4_field_ops.registre import Registre
    reg = Registre()
    for visite_id, action, instant in [
        ('v1', 'en_route', '2026-11-02T08:30:00-05:00'),
        ('v1', 'arrivee', '2026-11-02T09:00:00-05:00'),
        ('v1', 'pause_debut', '2026-11-02T10:00:00-05:00'),
        ('v1', 'pause_fin', '2026-11-02T10:30:00-05:00'),
        ('v1', 'depart', '2026-11-02T12:00:00-05:00'),
        ('v2', 'en_route', '2026-11-06T13:40:00+00:00'),
        ('v2', 'arrivee', '2026-11-06T14:00:00+00:00'),
        ('v2', 'depart', '2026-11-06T18:00:00+00:00'),
    ]:
        entree = {'type_entree': 'transition_statut' if action == 'en_route' else 'pointage',
                  'intervention_id': 'chantier-fictif', 'visite_id': visite_id,
                  'horodatage': instant, 'technicien_id': 'equipe-fictive', 'fictif': True}
        entree['statut' if action == 'en_route' else 'action'] = action
        reg.ajouter(entree)
    return reg


def test_projections_utilisent_les_faits_explicitement_identifies():
    reg = registre_sessions()
    resultat = visites.calculer_faits(reg, 'chantier-fictif')
    assert resultat['travail_minutes'] == 390
    assert resultat['pause_minutes'] == 30
    assert resultat['deplacement_minutes'] == 50
    assert len(resultat['visites'][0]['sources']) == 5
    assert len(resultat['visites'][1]['sources']) == 3


def test_refuse_fait_historique_non_identifie_sans_rattachement_invente():
    reg = registre_sessions()
    reg.ajouter({'type_entree': 'pointage', 'intervention_id': 'chantier-fictif',
                 'action': 'depart', 'horodatage': '2026-11-06T18:01:00+00:00', 'fictif': True})
    with pytest.raises(ValueError):
        visites.calculer_faits(reg, 'chantier-fictif')


def test_refuse_fait_incomplet_incoherent_et_chaine_alteree():
    from m4_field_ops.registre import Registre
    reg = registre_sessions()
    maillons = reg.lire()
    with pytest.raises(ValueError):
        visites.calculer_faits(Registre(maillons[:-1]), 'chantier-fictif')
    corrompu = deepcopy(maillons)
    corrompu[1]['horodatage'] = '2026-11-02T10:00:00-05:00'
    with pytest.raises(ValueError):
        visites.calculer_faits(Registre(corrompu), 'chantier-fictif')
    # Même si un support extérieur rechaîne les données, une autre équipe n'est pas acceptée.
    corrompu = deepcopy(maillons)
    corrompu[1]['technicien_id'] = 'autre-equipe-fictive'
    rechaine = Registre()
    for m in corrompu:
        rechaine.ajouter({k: v for k, v in m.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
    with pytest.raises(ValueError):
        visites.calculer_faits(rechaine, 'chantier-fictif')
