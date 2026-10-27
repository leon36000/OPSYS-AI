"""fictif: true — historique pur des écarts M4; aucune facturation d'extra."""
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from m4_field_ops import ecarts, encodage, etats, journal_quotidien
from m4_field_ops.registre import Registre

spec = importlib.util.spec_from_file_location('journal_ecarts_fixture', Path(__file__).with_name('test_ecarts.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
FICTIF = True
DECLARE_LE = '2025-06-02T12:00:00+00:00'
ARBITRE_LE = '2025-06-03T12:00:00+00:00'


def monde():
    reg, iid = f._registre_sur_site()
    declaree = {'duree_minutes': 240, 'perimetre': 'PERIMETRE_CONFIDENTIEL_FICTIF',
                'materiaux': ['MATERIAU_LIBRE_CONFIDENTIEL_FICTIF']}
    acc, ver = ecarts.creer_demande_ecart(iid, f.VERSION_PREVUE, declaree, DECLARE_LE, reg,
                                        horodatage_appareil='2000-01-01T00:00:00+00:00')
    assert ver is None, ver
    return reg, iid, acc['demande_id']


def test_declaration_et_arbitrage_sur_deux_jours_sont_faits_distincts_minimises():
    reg, iid, demande = monde()
    acc, ver = ecarts.resoudre_demande(demande, 'validee', ARBITRE_LE, reg,
                                      motif='MOTIF_LIBRE_CONFIDENTIEL_FICTIF')
    assert ver is None, ver
    avant = reg.lire()
    premier = journal_quotidien.lire(reg, '2025-06-02')
    lendemain = journal_quotidien.lire(reg, '2025-06-03')
    declarations = [x for x in premier['lignes'] if x['type'] == 'ecart_declare']
    arbitrages = [x for x in lendemain['lignes'] if x['type'] == 'ecart_arbitre']
    assert len(declarations) == len(arbitrages) == 1
    d, a = declarations[0], arbitrages[0]
    assert d['demande_id'] == a['demande_id'] == demande and d['intervention_id'] == a['intervention_id'] == iid
    assert d['statut_arbitrage'] == 'en_attente' and a['statut_arbitrage'] == 'validee'
    assert d['origine_heure'] == 'serveur' and a['origine_heure'] == 'appelant'
    assert d['ancre_visite'] is a['ancre_visite'] is None
    assert d['dimensions_modifiees'] == a['dimensions_modifiees'] == ['duree_minutes', 'materiaux', 'perimetre']
    assert a['source_demande_id'] == d['source_ligne_id']
    for secret in ['PERIMETRE_CONFIDENTIEL_FICTIF', 'MATERIAU_LIBRE_CONFIDENTIEL_FICTIF',
                   'MOTIF_LIBRE_CONFIDENTIEL_FICTIF', '2000-01-01', 'latitude', 'version_declaree']:
        assert secret not in json.dumps([d, a])
    assert reg.lire() == avant


def rechainer(lignes):
    reg = Registre()
    for m in lignes:
        reg.ajouter({k: deepcopy(v) for k, v in m.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
    return reg


def resolu(decision='validee', horodatage=ARBITRE_LE):
    reg, iid, demande = monde()
    acc, ver = ecarts.resoudre_demande(demande, decision, horodatage, reg)
    assert ver is None, ver
    return reg, iid, demande


def test_rejet_reste_un_arbitrage_et_pas_un_extra_facture():
    reg, _, demande = resolu('rejetee')
    lignes = journal_quotidien.lire(reg, '2025-06-03')['lignes']
    arbitre = next(x for x in lignes if x['type'] == 'ecart_arbitre')
    assert arbitre['statut_arbitrage'] == 'rejetee' and arbitre['demande_id'] == demande
    assert any(x.get('statut') == 'annulee' for x in lignes)
    assert not {'prix', 'montant', 'facture', 'duree_minutes', 'materiaux', 'motif'} & set(arbitre)


def test_anomalie_gps_et_sa_resolution_ne_deviennent_pas_ecart_metier():
    reg, _, demande = f._registre_en_revue_par_anomalie()
    acc, ver = ecarts.resoudre_demande(demande, 'validee', f.H4, reg)
    assert ver is None, ver
    avant = reg.lire()
    r = journal_quotidien.lire(reg, '2025-06-02')
    assert not any(x['type'].startswith('ecart_') for x in r['lignes'])
    assert any(x.get('statut') == 'sur_site' for x in r['lignes'])
    assert 'causes_possibles' not in json.dumps(r) and 'latitude' not in json.dumps(r)
    assert reg.lire() == avant


@pytest.mark.parametrize('cas', ['demande_dupliquee', 'resolution_dupliquee', 'resolution_orpheline',
    'resolution_avant_demande', 'identifiant_demande', 'identifiant_resolution', 'decision_inconnue',
    'decision_contradictoire', 'version_invalide', 'version_identique', 'type_inconnu'])
def test_contradictions_meme_rechainees_refusees(cas):
    reg, _, _ = resolu()
    lignes = reg.lire()
    decl = next(m for m in lignes if m.get('type_demande') == 'ecart_metier')
    resolution = next(m for m in lignes if m['type_entree'] == ecarts.TYPE_RESOLUTION)
    if cas == 'demande_dupliquee':
        lignes.append(deepcopy(decl))
    elif cas == 'resolution_dupliquee':
        lignes.append(deepcopy(resolution))
    elif cas == 'resolution_orpheline':
        lignes.remove(decl)
    elif cas == 'resolution_avant_demande':
        lignes.remove(resolution)
        lignes.insert(lignes.index(decl), resolution)
    elif cas == 'identifiant_demande':
        decl['demande_id'] = 'a' * 64
    elif cas == 'identifiant_resolution':
        resolution['resolution_id'] = 'a' * 64
    elif cas == 'decision_inconnue':
        resolution['decision'] = resolution['statut_arbitrage'] = 'acceptee-finance'
    elif cas == 'decision_contradictoire':
        resolution['statut_arbitrage'] = 'rejetee'
    elif cas == 'version_invalide':
        decl['version_declaree']['duree_minutes'] = True
    elif cas == 'version_identique':
        decl['version_declaree'] = deepcopy(decl['version_prevue'])
    else:
        decl['type_demande'] = 'completion_inventee'
    mauvais = rechainer(lignes)
    avant = mauvais.lire()
    with pytest.raises(ValueError):
        journal_quotidien.lire(mauvais, '2025-06-03')
    assert mauvais.lire() == avant


def test_resolution_sur_autre_intervention_inscrite_refusee():
    reg, _, _ = resolu()
    autre = Registre()
    contrat = {**f.CONTRAT_VALIDE, 'lead_id': 'AUTRE-FICTIF', 'conversation_id': 'CONV-AUTRE-FICTIVE'}
    acc, ver = etats.inscrire_intervention(contrat, {**f.MARQUEUR_VALIDE, 'lead_id': contrat['lead_id']},
                                          autre, f.H1, f.SEL)
    assert ver is None, ver
    lignes = reg.lire()
    next(m for m in lignes if m['type_entree'] == ecarts.TYPE_RESOLUTION)['intervention_id'] = acc['intervention_id']
    mauvais = rechainer(autre.lire() + lignes)
    with pytest.raises(ValueError, match='liaison'):
        journal_quotidien.lire(mauvais, '2025-06-03')


def test_collision_demande_metier_et_gps_refusee():
    reg, iid, demande = monde()
    gps, _, _ = f._registre_en_revue_par_anomalie()
    forme = next(m for m in gps.lire() if m.get('type_demande') == 'anomalie_pointage')
    forme.update(intervention_id=iid, demande_id=demande, horodatage=DECLARE_LE)
    assert demande == encodage.empreinte('demande_revue', iid, DECLARE_LE)
    mauvais = rechainer(reg.lire() + [forme])
    with pytest.raises(ValueError, match='demande unique'):
        journal_quotidien.lire(mauvais, '2025-06-02')


def test_demande_sans_inscription_refusee_meme_hors_jour():
    reg, _, _ = monde()
    decl = next(m for m in reg.lire() if m.get('type_demande') == 'ecart_metier')
    mauvais = rechainer([decl])
    with pytest.raises(ValueError, match='inscription'):
        journal_quotidien.lire(mauvais, '2025-06-03')


def test_pages_et_dimensions_restees_independantes_avec_instants_egaux():
    reg, _, _ = resolu(horodatage=DECLARE_LE)
    avant = reg.lire()
    tout = journal_quotidien.lire(reg, '2025-06-02')
    page, lignes = tout, []
    debut = 0
    while debut is not None:
        page = journal_quotidien.lire(reg, '2025-06-02', debut=debut, limite=1, source_attendue=tout['source'])
        lignes += page['lignes']
        debut = page['suivant']
    assert lignes == tout['lignes']
    ec = [x for x in lignes if x['type'].startswith('ecart_')]
    assert [x['type'] for x in ec] == ['ecart_declare', 'ecart_arbitre']
    ec[0]['dimensions_modifiees'].clear()
    assert ec[1]['dimensions_modifiees'] == ['duree_minutes', 'materiaux', 'perimetre']
    assert journal_quotidien.lire(reg, '2025-06-02')['lignes'] == tout['lignes']
    assert reg.lire() == avant


@pytest.mark.parametrize('cas', ['decision_inverse', 'compagnon_retire', 'revue_wct_etrangere', 'signal_ecart_retire'])
def test_resolution_doit_garder_preuve_de_transition_proprietaire(cas):
    from m4_field_ops import outbox

    reg, _, _ = resolu()
    lignes = reg.lire()
    rang = next(i for i, m in enumerate(lignes) if m['type_entree'] == ecarts.TYPE_RESOLUTION)
    resolution, compagnon = lignes[rang], lignes[rang - 1]
    assert compagnon['type_entree'] == etats.TYPE_TRANSITION and compagnon['statut'] == 'completed_pending_review'
    if cas == 'decision_inverse':
        resolution['decision'] = resolution['statut_arbitrage'] = 'rejetee'
    elif cas == 'compagnon_retire':
        lignes.pop(rang - 1)
    elif cas == 'revue_wct_etrangere':
        compagnon[outbox.CLE_WCT]['revue_id'] = '0' * 64
    else:
        compagnon[outbox.CLE_WCT]['ecart_signale'] = False
    mauvais = rechainer(lignes)
    with pytest.raises(ValueError):
        journal_quotidien.lire(mauvais, '2025-06-03')


def test_demande_ajoutee_apres_etat_terminal_refusee_comme_par_le_writer():
    reg, iid, _ = resolu()
    avant = reg.lire()
    source = next(m for m in avant if m.get('type_demande') == 'ecart_metier')
    instant = '2025-06-04T12:00:00+00:00'
    acc, ver = ecarts.creer_demande_ecart(iid, source['version_prevue'], source['version_declaree'], instant, reg)
    assert acc is None and ver['code'] == 'REJ-TRANSITION-ILLEGALE'
    assert reg.lire() == avant
    ajout = {**source, 'horodatage': instant, 'demande_id': encodage.empreinte('demande_revue', iid, instant)}
    mauvais = rechainer(avant + [ajout])
    with pytest.raises(ValueError):
        journal_quotidien.lire(mauvais, '2025-06-04')


def test_demande_depuis_planifiee_reste_valide_sans_presence_deduite():
    reg = Registre()
    acc, ver = etats.inscrire_intervention(f.CONTRAT_VALIDE, f.MARQUEUR_VALIDE, reg, f.H1, f.SEL)
    assert ver is None, ver
    iid = acc['intervention_id']
    acc, ver = ecarts.creer_demande_ecart(iid, f.VERSION_PREVUE, f.VERSION_DECLAREE, DECLARE_LE, reg)
    assert ver is None, ver
    assert etats.statut_courant(reg, iid) == 'planifiee'
    accuse, ver = ecarts.resoudre_demande(acc['demande_id'], 'rejetee', ARBITRE_LE, reg)
    assert ver is None, ver
    r = journal_quotidien.lire(reg, '2025-06-03')
    assert any(x['type'] == 'ecart_arbitre' and x['statut_arbitrage'] == 'rejetee' for x in r['lignes'])
    assert not any(x['type'] == 'pointage' for x in r['lignes'])
