"""fictif: true — décisions d'assignation historiques, sans présence ni équipe observée."""
import importlib.util
import json
from pathlib import Path

import pytest
from m4_field_ops import etats, journal_quotidien
from m4_field_ops.registre import Registre

spec = importlib.util.spec_from_file_location('journal_assignations_fixture',
    Path(__file__).with_name('test_journal_quotidien.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
FICTIF = True
D, SUIVANT = f.D, f.REPRISE


def test_assignations_successives_reelles_ne_reecrivent_pas_le_jour_passe():
    reg, ids, _ = f.f.monde_date()
    iid = next(iter(ids.values()))
    f.f._reussi(etats.assigner_technicien(iid, 'T1-fictif', reg, D + 'T08:00:00-04:00'))
    f.f._reussi(etats.transitionner(iid, 'reportee', reg, D + 'T09:00:00-04:00', motif='meteo'))
    f.f._reussi(etats.transitionner(iid, 'planifiee', reg, SUIVANT + 'T07:00:00-04:00'))
    f.f._reussi(etats.assigner_technicien(iid, 'T2-fictif', reg, SUIVANT + 'T08:00:00-04:00'))
    f.f._reussi(etats.transitionner(iid, 'en_route', reg, SUIVANT + 'T08:30:00-04:00',
        assignation={'intervention_id': iid, 'technicien_id': 'T2-fictif'}))
    avant = reg.lire()
    ancien, courant = journal_quotidien.lire(reg, D), journal_quotidien.lire(reg, SUIVANT)
    decision = [x for x in ancien['lignes'] if x['type'] == 'assignation']
    assert len(decision) == 1 and decision[0]['technicien_assigne'] == 'T1-fictif'
    suivants = [x for x in courant['lignes'] if x.get('technicien_assigne')]
    assert [x['type'] for x in suivants] == ['assignation', 'etat']
    assert all(x['technicien_assigne'] == 'T2-fictif' and x['ancre_visite'] is None for x in suivants)
    assert all('technicien_id' not in x and 'equipe_planifiee' not in x for x in decision + suivants)
    assert all(set(x) <= {'type', 'source_ligne_id', 'intervention_id', 'instant', 'origine_heure',
        'ancre_visite', 'technicien_assigne', 'statut'} for x in decision + suivants)
    pages, debut = [], 0
    while debut is not None:
        page = journal_quotidien.lire(reg, SUIVANT, debut=debut, limite=1, source_attendue=courant['source'])
        pages.extend(page['lignes'])
        debut = page['suivant']
    assert pages == courant['lignes']
    decision[0]['technicien_assigne'] = 'mutation-fictive'
    assert 'mutation-fictive' not in json.dumps(journal_quotidien.lire(reg, D))
    assert reg.lire() == avant


def rechaine(maillons):
    reg = Registre()
    for m in maillons:
        reg.ajouter({k: v for k, v in m.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
    return reg


@pytest.mark.parametrize('alteration', ['vide', 'non_texte', 'orpheline', 'future', 'double', 'terminal'])
def test_assignation_incoherente_ne_devient_pas_un_fait(alteration):
    reg, ids, _ = f.f.monde_date()
    iid = next(iter(ids.values()))
    f.f._reussi(etats.assigner_technicien(iid, 'T-fictif', reg, D + 'T08:00:00-04:00'))
    lignes = reg.lire()
    cible = lignes[-1]
    if alteration == 'vide':
        cible['technicien_id'] = ''
    elif alteration == 'non_texte':
        cible['technicien_id'] = ['T-fictif']
    elif alteration == 'orpheline':
        cible['intervention_id'] = 'orpheline'
    elif alteration == 'future':
        lignes.insert(0, lignes.pop())
    elif alteration == 'double':
        inscription = next(x for x in lignes if x['type_entree'] == etats.TYPE_INSCRIPTION
                           and x['intervention_id'] == iid)
        lignes.insert(0, dict(inscription))
    else:
        lignes.insert(-1, {'type_entree': etats.TYPE_TRANSITION, 'intervention_id': iid,
            'statut_precedent': 'planifiee', 'statut': 'annulee', 'horodatage': D + 'T07:00:00-04:00'})
    corrompu = rechaine(lignes)
    avant = corrompu.lire()
    with pytest.raises(ValueError):
        journal_quotidien.lire(corrompu, D)
    assert corrompu.lire() == avant


def test_depart_ne_peut_pas_inventer_assignation_sans_prefixe_planifie():
    reg, ids, _ = f.f.monde_date()
    iid = next(iter(ids.values()))
    reg.ajouter({'type_entree': etats.TYPE_TRANSITION, 'intervention_id': iid,
        'statut_precedent': 'sur_site', 'statut': 'en_route', 'technicien_id': 'T-fictif',
        'horodatage': D + 'T08:00:00-04:00'})
    with pytest.raises(ValueError):
        journal_quotidien.lire(reg, D)



def test_identifiant_historique_espaces_accepte_par_les_deux_writers_reste_lisible():
    reg, ids, _ = f.f.monde_date()
    iid = next(iter(ids.values()))
    f.f._reussi(etats.assigner_technicien(iid, '   ', reg, D + 'T08:00:00-04:00'))
    f.f._reussi(etats.transitionner(iid, 'en_route', reg, D + 'T08:30:00-04:00',
        assignation={'intervention_id': iid, 'technicien_id': '   '}))
    avant = reg.lire()
    vue = journal_quotidien.lire(reg, D)
    assert [x['technicien_assigne'] for x in vue['lignes']] == ['   ', '   ']
    assert journal_quotidien.lire(reg, SUIVANT)['lignes'] == []
    assert reg.lire() == avant
