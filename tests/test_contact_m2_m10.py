"""Correction CRM vers mémoire : données FICTIVES, vrai bus et SQLite, aucune coordonnée transférée."""
from __future__ import annotations

import json

import pytest
from m2_revenue_crm import outils as m2
from m10_memoire import amont, audit, classification, consolidation, paquets, registre
from sqlalchemy import select

from opsys import contexte, evenements, identite, stockage
from opsys.departements import charger_departements
from opsys.evenements.schemas import erreurs_charge
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

FICTIF = True
TYPE = 'm2.contact_corrige'
H = '2026-10-27T01:00:00+00:00'
ADMIN = contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')


@pytest.fixture
def dossier(session):
    m2.utiliser_stockage_durable()
    with session() as cnx:
        identite.creer_personne(cnx, 'admin.fictif', 'FICTIF', 'mot-de-passe-fictif-123456', ['admin'])
        for numero in [1, 2]:
            assert m2.ingerer_lead({'lead_id': f'lead-fictif-{numero}', 'conversation_id': f'conv-fictive-{numero}',
                'contact': {'nom': 'Client FICTIF', 'courriel': 'initial@example.test'},
                'type_travaux': 'renovation_totale', 'ville': 'Québec', 'urgence_declaree': False,
                'canal': 'telephone'}, H)['accepte']
        cid = m2.trouver_client_de_lead('lead-fictif-1')['resultat']['client_id']
    yield cid, charger_departements()
    m2.reinitialiser_registre()


def _correction(session, cid, revision):
    with session(), contexte.appele_par_appareil(ADMIN):
        contact = {'nom': f'Corrigé FICTIF {revision}', 'courriel': f'prive{revision}@example.test'}
        r = m2.corriger_contact_client(cid, contact,
                                      revision, 'Motif personnel FICTIF strictement admin', H)
        assert r['accepte'], r
        return r['resultat']


def _sortants(session):
    with session() as cnx:
        rows = cnx.execute(select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == TYPE)).mappings()
        return [{**dict(r), 'charge': codec.decoder(r['charge'])} for r in rows]


def _memorises(session):
    with session():
        return [m for m in stockage.maillons('m10-memoire', 'evenements') if m.get('type_evenement') == TYPE]


def _drainer(deps):
    for _ in range(5):
        r = evenements.repartir(deps, maintenant='2026-10-28T01:00:00+00:00')
        assert r['echecs'] == 0 and r['quarantaines'] == 0, r
        if r['livres'] == 0:
            return
    pytest.fail('Bus fictif non vidé après cinq tours')


def test_contact_memorise_par_projet_revision_et_rejeu_semantique(session, dossier):
    cid, deps = dossier
    premiere = _correction(session, cid, 0)
    faits = _sortants(session)
    assert len(faits) == 2
    assert {e['charge']['lead_id'] for e in faits} == {'lead-fictif-1', 'lead-fictif-2'}
    for e in faits:
        assert set(e['charge']) == {'fait_id', 'lead_id', 'client_id', 'revision', 'source_ligne_id', 'horodatage'}
        assert e['charge']['source_ligne_id'] == premiere['ligne_id'] and e['charge']['revision'] == 1
    assert 'example.test' not in json.dumps(faits) and 'Motif personnel' not in json.dumps(faits)
    _drainer(deps)
    assert len(_memorises(session)) == 2
    _correction(session, cid, 1)
    _drainer(deps)
    avant = _memorises(session)
    assert len(avant) == 4 and {m['revision'] for m in avant} == {1, 2}
    with session():
        evenements.publier(TYPE, 'm02-revenue-crm', faits[0]['charge'], evenement_id='relivraison-fictive')
    _drainer(deps)
    assert _memorises(session) == avant
    with session() as cnx:
        recu = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == 'relivraison-fictive') &
            (EVENEMENTS_RECUS.c.consommateur == 'm10-memoire'))).mappings().one()
        assert codec.decoder(recu['resultat'])['deja_memorise'] is True
    assert {classification.identifiant(m) for m in avant} == {e['charge']['fait_id'] for e in _sortants(session)}
    # Sources M2 consultables sous autorité admin, aucun contact ou motif dupliqué dans M10.
    assert all(m['confidentialite'] == 'CLIENT_PRIVATE' for m in avant)
    assert 'example.test' not in json.dumps(avant) and 'Motif personnel' not in json.dumps(avant)
    reg = registre.Registre()
    for e in _sortants(session):
        assert amont.memoriser(TYPE, e['charge'], reg)[1] is None
    for agent in [None, 'm03-estimation', 'm09-strategic-intelligence']:
        paquet = paquets.assembler_paquet_contexte('lead-fictif-1', H, reg, registre.Registre(), agent=agent)
        assert all(e['charge']['fait_id'] not in json.dumps(paquet) for e in faits)
    paquet = paquets.assembler_paquet_contexte('lead-fictif-1', H, reg, registre.Registre(), agent='m02-revenue-crm')
    assert 'coordonnées' in json.dumps(paquet, ensure_ascii=False)
    attendu = [{'type_evenement': TYPE, 'identifiant': e['charge']['fait_id']} for e in _sortants(session)]
    assert audit.auditer_non_oubli(attendu, reg, registre.Registre())['nb_oublis'] == 0
    affaires = registre.Registre()
    consolide = consolidation.consolider_affaire('lead-fictif-1', '2026-10-27', H, reg, affaires)
    assert consolide['ecrit'] and '2 référence(s)' in consolide['fait']['resume']
    paquet = paquets.assembler_paquet_contexte('lead-fictif-1', H, reg, affaires, agent='m09-strategic-intelligence')
    assert 'example.test' not in json.dumps(paquet) and 'Motif personnel' not in json.dumps(paquet)
    assert all(m['source_ligne_id'] not in json.dumps(paquet) for m in avant)


def test_contact_et_outbox_annules_ensemble_si_publication_echoue(session, dossier, monkeypatch):
    cid, _ = dossier
    with session():
        avant = m2._obtenir_registre().lire()
    publier = m2._publier_si_durable
    appels = []
    def panne(type_, charge, evenement_id):
        if type_ == TYPE:
            appels.append(evenement_id)
            if len(appels) == 2:
                raise RuntimeError('panne fictive seconde publication')
        return publier(type_, charge, evenement_id)
    monkeypatch.setattr(m2, '_publier_si_durable', panne)
    with pytest.raises(RuntimeError, match='panne fictive'):
        _correction(session, cid, 0)
    assert len(appels) == 2 and _sortants(session) == []
    with session():
        assert m2._obtenir_registre().lire() == avant


@pytest.mark.parametrize('champ,valeur', [
    ('fait_id', 'a' * 64), ('client_id', 'courriel@example.test'),
    ('lead_id', 'client@example.test'), ('revision', True), ('revision', 0),
    ('horodatage', '2026-10-27T01:00:00'), ('source_ligne_id', 'note libre'),
])
def test_m10_refuse_reference_invalide_sans_memoriser(session, dossier, champ, valeur):
    cid, _ = dossier
    _correction(session, cid, 0)
    charge = dict(_sortants(session)[0]['charge'], **{champ: valeur})
    reg = registre.Registre()
    _, verdict = amont.memoriser(TYPE, charge, reg)
    assert verdict is not None and reg.lire() == []


def test_rejeu_contradictoire_ne_remplace_pas_la_provenance(session, dossier):
    cid, deps = dossier
    _correction(session, cid, 0)
    _drainer(deps)
    avant = _memorises(session)
    charge = dict(_sortants(session)[0]['charge'], source_ligne_id='b' * 64)
    with session():
        evenements.publier(TYPE, 'm02-revenue-crm', charge, evenement_id='conflit-fictif')
    _drainer(deps)
    assert _memorises(session) == avant
    with session() as cnx:
        recu = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == 'conflit-fictif') &
            (EVENEMENTS_RECUS.c.consommateur == 'm10-memoire'))).mappings().one()
        resultat = codec.decoder(recu['resultat'])
        assert resultat['deja_memorise'] is True and resultat['identique'] is False


def test_refus_revision_ne_publie_aucun_fait(session, dossier):
    cid, _ = dossier
    with session(), contexte.appele_par_appareil(ADMIN):
        resultat = m2.corriger_contact_client(cid, {'nom': 'FICTIF'}, 99, 'Test FICTIF', H)
        assert not resultat['accepte']
    assert _sortants(session) == []


def test_catalogue_refuse_coordonnees_et_motif_et_extracteur_ne_les_copie_pas(session, dossier):
    cid, _ = dossier
    _correction(session, cid, 0)
    charge = _sortants(session)[0]['charge']
    assert erreurs_charge(TYPE, charge) == []
    ajoute = dict(charge, contact={'courriel': 'secret@example.test'}, motif='Motif privé FICTIF')
    assert erreurs_charge(TYPE, ajoute)
    assert erreurs_charge(TYPE, dict(charge, lead_id='secret@example.test'))
    reg = registre.Registre()
    resultat, verdict = amont.memoriser(TYPE, ajoute, reg)
    assert verdict is None
    assert 'secret@example.test' not in json.dumps(resultat) and 'Motif privé' not in json.dumps(resultat)
