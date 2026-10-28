"""fictif: true — journal pur M4, dates explicites et aucun fait terrain déduit."""
import importlib
import importlib.util
import json
from pathlib import Path

import pytest
from m4_field_ops import calendrier_civil, cedule, etats, pointage
from m4_field_ops.registre import Registre

spec = importlib.util.spec_from_file_location('journal_fixture', Path(__file__).with_name('test_calendrier_civil.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
FICTIF = True
D, REPRISE = '2030-06-03', '2030-06-07'


def journal(reg, jour, **kwargs):
    return importlib.import_module('m4_field_ops.journal_quotidien').lire(reg, jour, **kwargs)


def test_ancienne_date_conservee_apres_report_et_reprise_quatre_jours_apres():
    reg, ids, plan = f.monde_date()
    calendrier_civil.confirmer(reg, plan, {'0': D}, 0, 'admin.fictif', f.HORODATAGE)
    iid = next(iter(ids.values()))
    f._reussi(etats.transitionner(iid, 'reportee', reg, D + 'T10:00:00-04:00', motif='meteo'))
    f._reussi(etats.transitionner(iid, 'planifiee', reg, D + 'T10:01:00-04:00'))
    calendrier_civil.confirmer(reg, plan, {'0': REPRISE}, 1, 'admin.fictif', D + 'T10:02:00-04:00')
    avant = reg.lire()
    ancien, nouveau = journal(reg, D), journal(reg, REPRISE)
    prev = [x for x in ancien['lignes'] if x['type'] == 'prevision']
    suivants = [x for x in nouveau['lignes'] if x['type'] == 'prevision']
    assert len(prev) == len(suivants) == len(ids)
    assert all(x['revision'] == 1 and x['remplace_par'] for x in prev)
    assert all(x['validite'] == 'historique' and x['source_courante'] is False for x in prev)
    assert all(x['revision'] == 2 and x['remplace_par'] is None for x in suivants)
    assert all(x['validite'] == 'date_confirmee' and x['source_courante'] is True for x in suivants)
    assert any(x['type'] == 'etat' and x['statut'] == 'reportee' for x in ancien['lignes'])
    assert not any(x['type'] == 'pointage' for x in ancien['lignes'] + nouveau['lignes'])
    assert reg.lire() == avant


def test_plan_non_date_ne_devient_pas_presence_ou_date_civile():
    reg, _, _ = f.monde_date()
    r = journal(reg, D)
    assert r['lignes'] == [] and r['total'] == 0
    assert 'Absence de pointage ne signifie pas absence du salarié.' in r['avertissements']


def test_vrais_pointages_minimises_et_heure_locale_sans_lien_visite_invente():
    reg, ids, plan = f.monde_date()
    calendrier_civil.confirmer(reg, plan, {'0': D}, 0, 'admin.fictif', f.HORODATAGE)
    iid = next(iter(ids.values()))
    equipe = next(x['equipe_id'] for x in calendrier_civil.lire_semaine(reg, D)['interventions']
                  if x['intervention_id'] == iid)
    assignation = {'intervention_id': iid, 'technicien_id': equipe}
    f._reussi(etats.transitionner(iid, 'en_route', reg, D + 'T19:00:00-04:00', assignation=assignation))
    ville, sel = 'Ville fictive', 'sel.fictif'
    ref = {cedule.tokeniser_ville(sel, ville): {'latitude': 45.5, 'longitude': -73.5, 'rayon_km': 2}}
    for action, instant in [('arrivee', '2030-06-04T00:30:00+00:00'), ('depart', '2030-06-04T01:30:00+00:00')]:
        f._reussi(pointage.enregistrer_pointage(iid, equipe, action, instant,
            {'latitude': 45.5, 'longitude': -73.5}, {'fictif': True, 'appareil_id': 'appareil.prive.fictif'},
            assignation, {'debut': D + 'T18:00:00-04:00', 'fin': '2030-06-04T04:00:00+00:00'},
            ref, ville, sel, reg, horodatage_appareil='heure-appareil-non-fiable'))
    avant = reg.lire()
    r = journal(reg, D)
    faits = [x for x in r['lignes'] if x['type'] == 'pointage']
    assert [x['action'] for x in faits] == ['arrivee', 'depart']
    assert all(x['instant'].startswith(D) and x['origine_heure'] == 'serveur'
               and x['ancre_visite'] is None and x['technicien_id'] == equipe for x in faits)
    rangs = {m['ligne_id']: i for i, m in enumerate(avant)}
    egaux = [x for x in r['lignes'] if x['instant'] == faits[0]['instant']]
    assert [rangs[x['source_ligne_id']] for x in egaux] == sorted(rangs[x['source_ligne_id']] for x in egaux)
    texte = json.dumps(r)
    for secret in ['latitude', 'longitude', 'ville_tokenisee', 'gps_coherent', 'appareil.prive',
                   'heure-appareil-non-fiable', 'position_chiffree', 'attestation']:
        assert secret not in texte
    assert journal(reg, '2030-06-04')['lignes'] == []
    assert reg.lire() == avant


def test_pagination_tete_exacte_sans_perte_et_conteneurs_independants():
    reg, _, plan = f.monde_date()
    calendrier_civil.confirmer(reg, plan, {'0': D}, 0, 'admin.fictif', f.HORODATAGE)
    tout = journal(reg, D)
    pages, debut = [], 0
    while debut is not None:
        page = journal(reg, D, debut=debut, limite=1, source_attendue=tout['source'])
        pages += page['lignes']
        debut = page['suivant']
    assert pages == tout['lignes']
    tout['lignes'][0]['revision'] = 999
    tout['avertissements'].clear()
    relu = journal(reg, D)
    assert relu['lignes'][0]['revision'] == 1 and relu['avertissements']


def test_continuation_source_changee_et_offset_sans_source_refuses():
    reg, ids, plan = f.monde_date()
    calendrier_civil.confirmer(reg, plan, {'0': D}, 0, 'admin.fictif', f.HORODATAGE)
    avant = journal(reg, D, limite=1)
    with pytest.raises(ValueError, match='source'):
        journal(reg, D, debut=1, limite=1)
    f._reussi(etats.transitionner(next(iter(ids.values())), 'reportee', reg, D + 'T10:00:00-04:00', motif='meteo'))
    with pytest.raises(ValueError, match='source'):
        journal(reg, D, debut=1, limite=1, source_attendue=avant['source'])


@pytest.mark.parametrize('kwargs', [{'debut': True}, {'debut': -1}, {'limite': True}, {'limite': 0},
                                   {'limite': 101}, {'debut': 10, 'source_attendue': 'fausse'}])
def test_pagination_invalide_refusee_sans_ecriture(kwargs):
    reg, _, _ = f.monde_date()
    avant = reg.lire()
    with pytest.raises(ValueError):
        journal(reg, D, **kwargs)
    assert reg.lire() == avant


def test_chaine_corrompue_et_ancre_civile_non_validee_refusees():
    reg, _, plan = f.monde_date()
    calendrier_civil.confirmer(reg, plan, {'0': D}, 0, 'admin.fictif', f.HORODATAGE)
    brut = reg.lire()
    brut[-1]['revision'] = 99
    with pytest.raises(ValueError, match='invalide'):
        journal(Registre(brut), D)
    # Rechaînage valide, mais révision métier impossible : ne pas confondre les deux preuves.
    autre = Registre()
    for ligne in brut:
        autre.ajouter({k: v for k, v in ligne.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
    with pytest.raises(ValueError, match='invalide'):
        journal(autre, D)


def test_bornes_avant_lecture_et_avant_retour(monkeypatch):
    from m4_field_ops import journal_quotidien as module

    class TropGrand:
        def taille(self):
            return 10001

        def lire(self):
            raise AssertionError('lecture interdite après quota')

    with pytest.raises(ValueError, match='volumineuses'):
        journal(TropGrand(), D)
    reg, _, plan = f.monde_date()
    calendrier_civil.confirmer(reg, plan, {'0': D}, 0, 'admin.fictif', f.HORODATAGE)
    monkeypatch.setattr(module, 'MAX_OCTETS', 10)
    with pytest.raises(ValueError, match='volumineuses'):
        journal(reg, D)
    monkeypatch.setattr(module, 'MAX_OCTETS', 8 * 1024 * 1024)
    monkeypatch.setattr(module, 'MAX_PREVISIONS', 1)
    with pytest.raises(ValueError, match='volumineuses'):
        journal(reg, D)


@pytest.mark.parametrize('typ,faits', [('pointage', {'technicien_id': 'fictif', 'action': 'arrivee'}),
                                     ('transition_statut', {'statut': 'sur_site'})])
def test_fait_sans_inscription_anterieure_refuse(typ, faits):
    reg = Registre()
    reg.ajouter({'type_entree': typ, 'intervention_id': 'absente',
                 'horodatage': D + 'T10:00:00-04:00', **faits})
    avant = reg.lire()
    with pytest.raises(ValueError, match='inscription'):
        journal(reg, D)
    assert reg.lire() == avant


def test_report_sans_redatation_reste_a_reconfirmer_et_pas_presence():
    reg, ids, plan = f.monde_date()
    calendrier_civil.confirmer(reg, plan, {'0': D}, 0, 'admin.fictif', f.HORODATAGE)
    iid = next(iter(ids.values()))
    f._reussi(etats.transitionner(iid, 'reportee', reg, D + 'T10:00:00-04:00', motif='meteo'))
    prev = next(x for x in journal(reg, D)['lignes'] if x['type'] == 'prevision' and x['intervention_id'] == iid)
    assert prev['remplace_par'] is None and prev['validite'] == 'a_reconfirmer' and prev['source_courante']


def test_nouveau_plan_ne_rend_pas_ancienne_prevision_courante():
    from m4_field_ops import cedule_tournees

    reg, ids, positions = f._monde()
    plan = f._reussi(f._proposer(reg, ids, positions))['plan_id']
    f._reussi(cedule_tournees.appliquer(reg, plan, positions, f.HORODATAGE, 'admin.fictif'))
    calendrier_civil.confirmer(reg, plan, {'0': D}, 0, 'admin.fictif', f.HORODATAGE)
    args = f._aide._arguments(ids, durees_par_type_travaux={'extension': 140, 'ravalement': 120})
    second = f._reussi(f._proposer(reg, ids, positions, arguments=args))['plan_id']
    assert second != plan
    f._reussi(cedule_tournees.appliquer(reg, second, positions, f.HORODATAGE, 'admin.fictif'))
    calendrier_civil.confirmer(reg, second, {'0': REPRISE}, 0, 'admin.fictif', f.HORODATAGE)
    assert all(x['validite'] == 'historique' and not x['source_courante'] for x in journal(reg, D)['lignes'])
    assert all(x['validite'] == 'date_confirmee' and x['source_courante']
               for x in journal(reg, REPRISE)['lignes'])


@pytest.mark.parametrize('inscription_apres', [True, False])
def test_inscription_future_ou_dupliquee_ne_valide_pas_fait(inscription_apres):
    reg, ids, _ = f.monde_date()
    iid = next(iter(ids.values()))
    inscription = next(m for m in reg.lire() if m.get('intervention_id') == iid)
    brut = {k: v for k, v in inscription.items() if k not in {'ligne_id', 'precedent_ligne_id'}}
    autre = Registre()
    if not inscription_apres:
        autre.ajouter(brut)
    autre.ajouter({'type_entree': 'pointage', 'intervention_id': iid, 'technicien_id': 'fictif',
                  'action': 'arrivee', 'horodatage': D + 'T10:00:00-04:00'})
    autre.ajouter(brut)
    with pytest.raises(ValueError, match='inscription'):
        journal(autre, D)
