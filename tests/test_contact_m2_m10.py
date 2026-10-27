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


def _reconciliation(session, cid, **options):
    with session(), contexte.appele_par_appareil(ADMIN):
        r = m2.reconcilier_memoire_contact_client(cid, **options)
        assert r['accepte'], r
        return r['resultat']


def test_reconciliation_observe_attente_puis_memoire_sans_ecriture(session, dossier):
    from opsys.stockage.schema import META
    cid, deps = dossier
    _correction(session, cid, 0)
    attente = _reconciliation(session, cid, limite=1)
    assert attente['total_references'] == 2 and attente['total_corrections'] == 1 and attente['suivant'] == 1
    assert attente['references'][0]['etat'] == 'EN_ATTENTE'
    _drainer(deps)
    with session() as cnx:
        avant = [cnx.execute(select(t)).all() for t in META.sorted_tables]
    rendu = _reconciliation(session, cid)
    assert {r['etat'] for r in rendu['references']} == {'MEMORISE'}
    assert 'example.test' not in json.dumps(rendu) and 'Motif personnel' not in json.dumps(rendu)
    with session() as cnx:
        assert [cnx.execute(select(t)).all() for t in META.sorted_tables] == avant


def test_reconciliation_historique_exclut_projet_tardif_et_borne_revisions(session, dossier):
    from m2_revenue_crm import clients
    cid, _ = dossier
    with session():
        # Simule une correction historique avant la publication automatique, avec la vraie primitive M2.
        _, verdict = clients.corriger_contact(m2._obtenir_registre(), cid, {'nom': 'Historique FICTIF'},
                                             0, 'Privé FICTIF', 'admin.fictif', H)
        assert verdict is None
        assert m2.ingerer_lead({'lead_id': 'lead-tardif', 'conversation_id': 'conv-tardive',
            'contact': {'nom': 'Historique FICTIF'}, 'type_travaux': 'renovation_totale',
            'ville': 'Québec', 'urgence_declaree': False, 'canal': 'telephone'}, H)['accepte']
    ancien = _reconciliation(session, cid)
    assert ancien['total_references'] == 2
    assert {r['lead_id'] for r in ancien['references']} == {'lead-fictif-1', 'lead-fictif-2'}
    assert {r['etat'] for r in ancien['references']} == {'NON_PUBLIE'}
    _correction(session, cid, 1)
    assert _reconciliation(session, cid)['total_references'] == 5
    assert _reconciliation(session, cid, revision_max=1) == ancien


def test_reconciliation_refuse_agent_sans_identite_et_parametres_invalides(session, dossier):
    cid, _ = dossier
    with session():
        assert not m2.reconcilier_memoire_contact_client(cid)['accepte']
    for options in [{'limite': True}, {'limite': 51}, {'decalage': -1}, {'revision_max': 1}]:
        with session(), contexte.appele_par_appareil(ADMIN):
            assert not m2.reconcilier_memoire_contact_client(cid, **options)['accepte']


@pytest.mark.parametrize('statut,etat', [
    ('echec', 'ECHEC_LIVRAISON'), ('quarantaine', 'QUARANTAINE'), ('traite', 'CONFLIT'),
])
def test_reconciliation_recu_sans_fait_ne_vaut_pas_memoire(session, dossier, statut, etat):
    from sqlalchemy import insert
    cid, _ = dossier
    _correction(session, cid, 0)
    evenement = _sortants(session)[0]['evenement_id']
    # États de livraison fictifs stockés ; diagnostic réel, sans invoquer de fournisseur externe.
    with session() as cnx:
        cnx.execute(insert(EVENEMENTS_RECUS).values(
            evenement_id=evenement, consommateur='m10-memoire', statut=statut,
            tentatives=5, derniere_erreur='Erreur privée FICTIVE secret@example.test',
            resultat=codec.encoder({'identique': True})))
    resultat = _reconciliation(session, cid)
    assert {r['etat'] for r in resultat['references']} == {etat, 'EN_ATTENTE'}
    assert 'secret@example.test' not in json.dumps(resultat) and 'Erreur privée' not in json.dumps(resultat)


def test_reconciliation_detecte_provenance_divergente(session, dossier):
    from sqlalchemy import update
    cid, deps = dossier
    _correction(session, cid, 0)
    event = _sortants(session)[0]
    altere = dict(event['charge'], source_ligne_id='f' * 64)
    with session() as cnx:
        cnx.execute(update(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.evenement_id == event['evenement_id']).values(charge=codec.encoder(altere)))
    _drainer(deps)
    assert {r['etat'] for r in _reconciliation(session, cid)['references']} == {'CONFLIT', 'MEMORISE'}


def test_reconciliation_pagine_sous_budget_sans_perte_et_borne_clients(session, dossier):
    from m2_revenue_crm import clients
    cid, _ = dossier
    assert _reconciliation(session, cid)['references'] == []
    with session(), contexte.appele_par_appareil(ADMIN):
        assert not m2.reconcilier_memoire_contact_client('0' * 64)['accepte']
        for revision in range(25):
            _, v = clients.corriger_contact(m2._obtenir_registre(), cid, {'nom': f'FICTIF {revision}'},
                                           revision, 'Privé FICTIF', ADMIN.personne, H)
            assert v is None
    offset, ids = 0, []
    for _ in range(10):
        page = _reconciliation(session, cid, limite=50, decalage=offset, revision_max=25)
        assert page['total_corrections'] == 25 and page['total_references'] == 50
        assert len(json.dumps(page, ensure_ascii=False)) <= m2.BUDGET_SORTIE
        ids.extend(r['fait_id'] for r in page['references'])
        if page['suivant'] is None:
            break
        assert page['suivant'] > offset
        offset = page['suivant']
    assert len(ids) == len(set(ids)) == 50
    assert _reconciliation(session, cid, decalage=99)['references'] == []
