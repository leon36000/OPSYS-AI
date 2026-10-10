"""Task3 fictive : pipeline M1/SQLite réels, sans fournisseur, HMAC ou appareil."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml
from m1_front_office import digest, transferts
from m1_front_office import outils as m1
from m1_front_office.registre import Registre
from sqlalchemy import MetaData, Table, select, update

from opsys import agents, canaux, departements, identite, stockage, taxonomie
from opsys.reception_sms_runtime import valider_commande
from opsys.stockage import schema

FICTIF = True
ROOT = Path(__file__).resolve().parents[1]
M1 = ROOT / 'departments/m01-front-office'
SID = 'AC' + 'a' * 32
FULL_RECEVOIR = 'opsys_runtime_recevoir_sms'
FULL_LIRE = 'opsys_runtime_lire_reception_sms'
TYPE_RECU = 'reception_hote_sms_v1'
WINDOWS = []


@pytest.fixture(autouse=True)
def _tracer_census(request):
    start = len(WINDOWS)
    yield
    request.node.user_properties.append(('m1_receipt_sql_windows', json.dumps(WINDOWS[start:], sort_keys=True)))


def _sql_value(v):
    if isinstance(v, (dt.datetime, dt.date)):
        return {'date': v.isoformat()}
    if isinstance(v, (bytes, memoryview)):
        return {'bytes': bytes(v).hex()}
    raise TypeError(type(v).__name__)


def census(cnx):
    """Toutes tables réellement présentes, toutes lignes/contenus et empreintes."""
    names = cnx.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").scalars().all()
    result = {}
    for name in names:
        table = schema.META.tables.get(name)
        if table is None:
            table = Table(name, MetaData(), autoload_with=cnx)
        rows = sorted(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, allow_nan=False, default=_sql_value)
                      for row in cnx.execute(select(table)).mappings())
        result[name] = {'lignes': rows, 'nombre': len(rows),
                        'sha256': hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()}
    return result


def etat(session):
    with session() as cnx:
        snapshot = census(cnx)
    WINDOWS.append({name: {'nombre': row['nombre'], 'sha256': row['sha256']} for name, row in snapshot.items()})
    return snapshot


def ligne_registre(session):
    with session():
        return m1._obtenir_registre().lire()


@pytest.fixture
def instance(session, declarer_services):
    declarer_services()
    taxonomie.enregistrer_zone_desservie(['Laval', 'Québec'])
    for filename, setters in [
        ('qualification/profil-fictif.v1.yaml', {
            'questions_qualification': taxonomie.enregistrer_questions_qualification,
            'poids_score_lead': taxonomie.enregistrer_poids_score_lead}),
        ('plaintes/plaintes.v1.yaml', {
            'signaux_plainte': taxonomie.enregistrer_signaux_plainte,
            'destinataires_transfert': taxonomie.enregistrer_destinataires_transfert}),
    ]:
        corpus = yaml.safe_load((M1 / 'fixtures' / filename).read_text())
        assert corpus['fictif'] is True
        for key, setter in setters.items():
            setter(corpus[key])
    deps = departements.charger_departements(ROOT / 'departments')
    with session() as cnx:
        identite.creer_personne(cnx, 'admin.sms.fictif', 'Admin fictif', 'mot-de-passe-sms-fictif-1234', ['admin'])
        profil = agents.creer(cnx, deps, {
            'id': 'm01-sms-un', 'departement': 'm01-front-office', 'responsabilite': 'Accueil SMS fictif',
            'palier_modele': 'rapide', 'outils': ['m1_recevoir_message_canal'],
            'budget_jour': 1000, 'budget_mois': 10000, 'limite_tours': 8, 'limite_reessais': 1,
            'limite_concurrence': 1, 'declencheurs': [
                {'type': 'canal', 'version': 1, 'canal': 'sms', 'compte_id': 'cabinet-1', 'account_sid': SID}],
        }, par='admin.sms.fictif', mutation_id='creer-sms-receipt-0001')
        profil = agents.definir_actif(cnx, profil['id'], deps, True, par='admin.sms.fictif',
                                     mutation_id='actif-sms-receipt-0001', revision_attendue=1)
    m1.utiliser_stockage_durable()
    yield session, profil, deps
    m1.reinitialiser_registre()


def arguments(profil, n=1, texte='Bonjour, mes gouttières fuient à Laval.', numero='+15145550142'):
    agent_id = 'opsys-agent-' + profil['id']
    return {'version': 1, 'commande': {
        'canal': 'sms', 'provider': 'twilio', 'compte_id': 'cabinet-1', 'account_sid': SID,
        'message_sid': 'SM' + f'{n:032x}', 'expediteur': numero, 'destinataire': '+15145550177',
        'recu_le': f'2031-01-15T14:{n // 60:02d}:{n % 60:02d}.000Z', 'texte': texte,
        'session_key': canaux.cle_session(agent_id, 'sms', numero), 'agent_id': agent_id,
        'preuve_sha256': 'b' * 64,
    }, 'permission': {'profil_id': profil['id'], 'revision_profil': profil['revision'],
                      'outil_m1': 'opsys_m1__m1_recevoir_message_canal'}}


def appel(session, args, operation=FULL_RECEVOIR):
    api = importlib.import_module('opsys.reception_sms_receipt')
    with session() as cnx:
        return api.executer(cnx, args, operation=operation, m1=m1)


def test_recu_reel_session_hote_rejeu_et_lire_purs(instance):
    session, profil, _ = instance
    args = arguments(profil)
    before = etat(session)
    absent = appel(session, args, FULL_LIRE)
    assert absent['ok'] and absent['etat'] == 'absent' and absent['recu'] is None
    assert etat(session) == before
    first = appel(session, args)
    assert first['ok'] and first['etat'] == 'recu' and first['operation'] == 'recevoir'
    assert first['recu']['decision'] == 'TRANSMETTRE_M2'
    rows = ligne_registre(session)
    signal, lead, receipt = rows
    assert [r['type_entree'] for r in rows] == ['signal', 'lead_emis', TYPE_RECU]
    assert lead['cle_session'] == args['commande']['session_key']
    assert first['recu']['signal_ligne_id'] == signal['ligne_id']
    assert first['recu']['lead_ligne_id'] == lead['ligne_id']
    stored_hash = valider_commande(args, operation=FULL_RECEVOIR).arguments_sha256
    assert receipt['arguments_sha256'] == stored_hash
    stable = etat(session)
    assert {n for n in stable if stable[n] != before[n]} == {'registres_maillons', 'evenements_sortants'}
    for op in (FULL_RECEVOIR, FULL_LIRE):
        r = appel(session, args, op)
        assert r['recu'] == first['recu']
        assert r['arguments_sha256'] == valider_commande(args, operation=op).arguments_sha256
        assert etat(session) == stable
    assert ligne_registre(session)[-1]['arguments_sha256'] == stored_hash


def test_type_receipt_proprietaire_et_digest_ignore_seulement_ce_type():
    reg = Registre()
    reg.ajouter({'type_entree': TYPE_RECU, 'horodatage': '2031-01-15T14:00:00.000Z'})
    assert reg.valider_chaine() == (True, None)
    signal = {'type_entree': 'signal', 'canal': 'texte', 'horodatage': '2031-01-15T14:00:00.000Z'}
    original = digest.produire_digest([signal], '2031-01-15')
    assert digest.produire_digest([signal, *reg.lire()], '2031-01-15') == original
    assert 'entrées non classées : 1' in digest.produire_digest([signal, {'type_entree': 'inconnu'}], '2031-01-15')


def test_sept_decisions_pipeline_reel_et_references(instance):
    session, profil, _ = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    corpus = yaml.safe_load((M1 / 'fixtures/plaintes/plaintes.v1.yaml').read_text())
    plainte = next(c for c in corpus['plaintes'] if 'securite' not in c['categories'])['texte']
    urgence = next(c for c in corpus['urgences'] if 'securite' in c['categories'])['texte']
    samples = [arguments(profil, 1, 'Bonjour.'), arguments(profil, 2),
               arguments(profil, 3, 'Merci beaucoup!'), arguments(profil, 4, 'STOP'),
               arguments(profil, 5, plainte, '+15145550143'),
               arguments(profil, 6, 'Merci', '+15145550143'),
               arguments(profil, 7, urgence, '+15145550144')]
    results = [appel(session, a) for a in samples]
    assert all(r['ok'] for r in results), results
    assert [r['recu']['decision'] for r in results] == [
        'DEMANDER_PRECISIONS', 'TRANSMETTRE_M2', 'CONVERSATION_DEJA_QUALIFIEE',
        'RETRAIT_CONSENTEMENT', 'ESCALADE_PLAINTE', 'TRANSFERT_EN_COURS', 'ESCALADE_URGENCE']
    rows = ligne_registre(session)
    assert Registre(rows).valider_chaine() == (True, None)
    assert sum(r['type_entree'] == TYPE_RECU for r in rows) == 7
    assert results[1]['recu']['lead_ligne_id'] == results[2]['recu']['lead_ligne_id']
    assert results[4]['recu']['transfert_id'] == results[5]['recu']['transfert_id']
    stable = etat(session)
    for args, initial in zip(samples, results, strict=True):
        assert appel(session, args, FULL_LIRE)['recu'] == initial['recu']
    assert etat(session) == stable
    with session() as cnx:
        assert cnx.execute(select(schema.EVENEMENTS_SORTANTS.c.type_evenement)).scalars().all() == [
            'm1.lead_qualifie', 'm1.retrait_consentement']


@pytest.mark.parametrize('field', ['texte', 'recu_le', 'preuve_sha256', 'compte_id'])
def test_meme_intention_autre_C_conflit_sans_delta(instance, field):
    session, profil, _ = instance
    a = arguments(profil)
    assert appel(session, a)['ok']
    stable = etat(session)
    b = copy.deepcopy(a)
    b['commande'][field] = {'texte': 'Autre corps', 'recu_le': '2031-01-15T15:00:01.000Z',
                            'preuve_sha256': 'c' * 64, 'compte_id': 'autre'}[field]
    r = appel(session, b)
    assert not r['ok'] and r['etat'] in ('conflit', 'refus')
    assert etat(session) == stable


def test_P_perimee_avant_R_et_sql_retrait(instance):
    session, profil, deps = instance
    a = arguments(profil)
    assert appel(session, a)['ok']
    with session() as cnx:
        agents.definir_actif(cnx, profil['id'], deps, False, par='admin.sms.fictif',
                            mutation_id='retirer-sms-receipt-0001', revision_attendue=profil['revision'])
    stable = etat(session)
    for op in (FULL_RECEVOIR, FULL_LIRE):
        r = appel(session, a, op)
        assert not r['ok'] and 'recu' not in r
    assert etat(session) == stable


def test_signal_legacy_sans_receipt_jamais_absent(instance):
    session, profil, _ = instance
    a = arguments(profil)
    c = a['commande']
    with session():
        m1.recevoir_message_canal('sms', c['expediteur'], c['message_sid'], c['recu_le'], c['texte'])
    stable = etat(session)
    for op in (FULL_LIRE, FULL_RECEVOIR):
        r = appel(session, a, op)
        assert not r['ok'] and r['etat'] == 'conflit'
    assert etat(session) == stable


def test_chaine_corrompue_hors_intention_ne_devient_pas_absente(instance):
    session, profil, _ = instance
    assert appel(session, arguments(profil))['ok']
    with session() as cnx:
        cnx.execute(update(schema.REGISTRES).where(schema.REGISTRES.c.departement == 'm01-front-office',
                                                  schema.REGISTRES.c.rang == 0).values(maillon='{}'))
    stable = etat(session)
    for op in (FULL_LIRE, FULL_RECEVOIR):
        r = appel(session, arguments(profil, 2), op)
        assert not r['ok'] and r['etat'] == 'inconnu'
    assert etat(session) == stable


def test_concurrence_deux_connexions_fortes_et_rejeu(instance):
    session, profil, _ = instance
    rendezvous = threading.Barrier(2)
    connexions = []
    lock = threading.Lock()
    api = importlib.import_module('opsys.reception_sms_receipt')
    a = arguments(profil)

    def run():
        rendezvous.wait(timeout=5)
        with session() as cnx:
            with lock:
                connexions.append(cnx)
            return api.executer(cnx, a, operation=FULL_RECEVOIR, m1=m1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run), pool.submit(run)]
        results = [f.result(timeout=15) for f in futures]
    assert len({id(c) for c in connexions}) == 2
    assert all(r['ok'] for r in results)
    assert results[0]['recu'] == results[1]['recu']
    assert [r['type_entree'] for r in ligne_registre(session)] == ['signal', 'lead_emis', TYPE_RECU]


def test_R_historique_apres_cloture_transfert(instance):
    session, profil, _ = instance
    a = arguments(profil, texte='Je suis déçu de votre service.')
    first = appel(session, a)
    assert first['recu']['decision'] == 'ESCALADE_PLAINTE'
    with session():
        reg = m1._obtenir_registre()
        et = next(e for e in transferts.lire(reg.lire()) if e.identifiant == first['recu']['transfert_id'])
        reg.ajouter(transferts.ligne_de_cloture(et, par='admin.sms.fictif', role='admin', voie='console',
                                             motif='Client rappelé.', horodatage='2031-01-15T15:00:00Z'))
    stable = etat(session)
    assert appel(session, a, FULL_LIRE)['recu'] == first['recu']
    assert appel(session, a)['recu'] == first['recu']
    assert etat(session) == stable


@pytest.mark.parametrize('fault', ['arguments_sha256', 'permission', 'horodatage', 'panne'])
def test_revalider_maillon_apres_append_et_rollback(instance, monkeypatch, fault):
    session, profil, _ = instance
    api = importlib.import_module('opsys.reception_sms_receipt')
    original = m1.inscrire_recu_sms_hote
    written = []

    def altered(mail):
        if fault == 'arguments_sha256':
            mail['arguments_sha256'] = 'c' * 64
        if fault == 'permission':
            mail['permission']['revision_profil'] += 1
        if fault == 'horodatage':
            mail['horodatage'] = '2031-01-15T15:00:00Z'
        result = original(mail)
        written.append(result)
        if fault == 'panne':
            raise RuntimeError('panne fictive après receipt')
        return result

    monkeypatch.setattr(m1, 'inscrire_recu_sms_hote', altered)
    before = etat(session)
    result = appel(session, arguments(profil))
    assert written and not result['ok'] and result['etat'] in ('inconnu', 'conflit')
    assert etat(session) == before
    assert api is not None


def test_decision_precisions_ne_cache_pas_le_lead_reel(instance, monkeypatch):
    session, profil, _ = instance
    original = m1.recevoir_sms_hote

    def lie(**kwargs):
        result = original(**kwargs)
        result['decision'] = 'DEMANDER_PRECISIONS'
        result.pop('lead_ligne_id')
        return result

    monkeypatch.setattr(m1, 'recevoir_sms_hote', lie)
    before = etat(session)
    result = appel(session, arguments(profil))
    assert not result['ok']
    assert etat(session) == before


def test_operation_non_scalaire_refusee_sans_effet(instance):
    session, profil, _ = instance
    before = etat(session)
    result = appel(session, arguments(profil), [])
    assert result == {'version': 1, 'operation': 'recevoir', 'ok': False,
                      'etat': 'forme_invalide', 'code': 'REJ-M1-SMS-FORME-INVALIDE'}
    assert etat(session) == before


def test_P_changee_apres_receipt_avant_ACK_rollback(instance, monkeypatch):
    session, profil, deps = instance
    original = m1.inscrire_recu_sms_hote
    seen = []

    def revoke(mail):
        result = original(mail)
        agents.definir_actif(stockage.connexion_courante(), profil['id'], deps, False,
                            par='admin.sms.fictif', mutation_id='retirer-apres-receipt',
                            revision_attendue=profil['revision'])
        seen.append(result)
        return result

    monkeypatch.setattr(m1, 'inscrire_recu_sms_hote', revoke)
    before = etat(session)
    result = appel(session, arguments(profil))
    assert seen and not result['ok'] and result['etat'] == 'revision_perimee'
    assert etat(session) == before


def test_erreur_encodage_ACK_apres_append_rollback(instance, monkeypatch):
    session, profil, _ = instance
    api = importlib.import_module('opsys.reception_sms_receipt')
    seen = []

    def fail(_cmd, _receipt):
        seen.extend(m1._obtenir_registre().lire())
        raise ValueError('encodage fictif indisponible')

    monkeypatch.setattr(api, '_ack', fail)
    before = etat(session)
    result = appel(session, arguments(profil))
    assert seen[-1]['type_entree'] == TYPE_RECU and not result['ok']
    assert etat(session) == before


def test_quota_8192_encodeur_synthetique_sans_abaisser_borne(instance):
    _session, profil, _ = instance
    api = importlib.import_module('opsys.reception_sms_receipt')
    cmd = valider_commande(arguments(profil), operation=FULL_RECEVOIR)
    # Vecteur d'encodeur fictif hors R11 ; pas une réception native valide trop volumineuse.
    assert api._QUOTA_ACK == 8192
    with pytest.raises(api._Refus):
        api._ack(cmd, {'fictif': True, 'extra': 'é' * 4096})


def test_reprise_processus_distinct_SQLite_recu_original(instance, request):
    session, profil, _ = instance
    args = arguments(profil)
    first = appel(session, args)
    stable = etat(session)
    code = '''import json,os,sys
from opsys import stockage
from opsys.reception_sms_receipt import executer
from m1_front_office import outils as m1
m1.utiliser_stockage_durable()
a=json.load(sys.stdin)
with stockage.transaction() as cnx:
 r=executer(cnx,a,operation='opsys_runtime_lire_reception_sms',m1=m1)
with stockage.transaction() as cnx:
 s=executer(cnx,a,operation='opsys_runtime_recevoir_sms',m1=m1)
print(json.dumps({'pid':os.getpid(),'lire':r,'recevoir':s,'source':__import__('opsys.reception_sms_receipt',fromlist=['']).__file__}))
stockage.liberer()
'''
    env = {'PATH': os.environ['PATH'], 'PYTHONDONTWRITEBYTECODE': '1',
           'OPSYS_HOME': os.environ['OPSYS_HOME'], 'OPSYS_BASE_URL': stockage.url_base(),
           'PYTHONPATH': os.pathsep.join([str(ROOT / 'src'), str(M1 / 'src')])}
    child = subprocess.run([sys.executable, '-c', code], input=json.dumps(args),
                           text=True, capture_output=True, env=env, timeout=15, check=False)
    assert child.returncode == 0, child.stderr
    report = json.loads(child.stdout)
    assert report['pid'] != os.getpid()
    request.node.user_properties.append(('m1_receipt_restart', json.dumps({
        'first_pid': os.getpid(), 'second_pid': report['pid'], 'child_returncode': child.returncode,
        'actual_source': report['source'],
        'same_R': report['lire']['recu'] == report['recevoir']['recu'] == first['recu'], 'fictif': True})))
    assert Path(report['source']).resolve() == ROOT / 'src/opsys/reception_sms_receipt.py'
    assert report['lire']['recu'] == report['recevoir']['recu'] == first['recu']
    assert etat(session) == stable


def test_outils_SQL_non_liste_ne_donnent_pas_autorite(instance):
    session, profil, _ = instance
    with session() as cnx:
        cnx.execute(update(schema.AGENTS_CONFIGURABLES).where(schema.AGENTS_CONFIGURABLES.c.id == profil['id'])
                    .values(outils=json.dumps('m1_recevoir_message_canal')))
    before = etat(session)
    result = appel(session, arguments(profil))
    assert not result['ok'] and 'recu' not in result
    assert etat(session) == before


def _recoudre(cnx, rows):
    owner = Registre()
    for row in rows:
        owner.ajouter(row)
    for i, row in enumerate(owner.lire()):
        cnx.execute(update(schema.REGISTRES).where(schema.REGISTRES.c.departement == 'm01-front-office',
                                                  schema.REGISTRES.c.rang == i)
                    .values(maillon=stockage.codec.encoder(row)))


def test_double_signal_memeSID_ambigu_ne_prouve_pas_recu(instance):
    session, profil, _ = instance
    a = arguments(profil)
    assert appel(session, a)['ok']
    with session():
        reg = m1._obtenir_registre()
        reg.ajouter(reg.lire()[0])
    before = etat(session)
    for op in (FULL_LIRE, FULL_RECEVOIR):
        result = appel(session, a, op)
        assert not result['ok']
    assert etat(session) == before


@pytest.mark.parametrize('reference', ['signal_ligne_id', 'lead_ligne_id'])
def test_reference_de_meme_type_autre_conversation_refusee(instance, reference):
    session, profil, _ = instance
    a = arguments(profil)
    r = appel(session, a)
    other = appel(session, arguments(profil, 2, numero='+15145550143'))
    assert r['ok'] and other['ok']
    with session() as cnx:
        rows = m1._obtenir_registre().lire()
        receipt = next(row for row in rows if row.get('type_entree') == TYPE_RECU
                       and row['recu']['message_sid'] == a['commande']['message_sid'])
        receipt['recu'][reference] = other['recu'][reference]
        _recoudre(cnx, rows)
    before = etat(session)
    assert not appel(session, a, FULL_LIRE)['ok']
    assert etat(session) == before


def test_lead_legacy_session_origine_preservee_dans_complement(instance):
    session, profil, _ = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    a = arguments(profil)
    c = a['commande']
    with session():
        old = m1.recevoir_message_canal('sms', c['expediteur'], c['message_sid'], c['recu_le'], c['texte'])
    old_rows = ligne_registre(session)
    old_session = old_rows[1]['cle_session']
    b = arguments(profil, 2, 'Merci!')
    assert old_session != b['commande']['session_key']
    result = appel(session, b)
    assert result['ok'] and result['recu']['decision'] == 'CONVERSATION_DEJA_QUALIFIEE'
    assert result['recu']['lead_ligne_id'] == old['lead_ligne_id']
    assert ligne_registre(session)[:len(old_rows)] == old_rows
    before = etat(session)
    assert appel(session, b, FULL_LIRE)['recu'] == result['recu']
    assert etat(session) == before


def test_regrant_revision_ne_rebase_pas_permission_initiale(instance):
    session, profil, deps = instance
    a = arguments(profil)
    assert appel(session, a)['ok']
    with session() as cnx:
        stopped = agents.definir_actif(cnx, profil['id'], deps, False, par='admin.sms.fictif',
            mutation_id='retirer-pour-regrant', revision_attendue=profil['revision'])
        live = agents.definir_actif(cnx, profil['id'], deps, True, par='admin.sms.fictif',
            mutation_id='reactiver-pour-regrant', revision_attendue=stopped['revision'])
    before = etat(session)
    assert appel(session, a, FULL_LIRE)['etat'] == 'revision_perimee'
    rebased = copy.deepcopy(a)
    rebased['permission']['revision_profil'] = live['revision']
    assert appel(session, rebased, FULL_LIRE)['etat'] == 'conflit'
    assert etat(session) == before


def test_ouverture_transfert_apres_receipt_ne_prouve_pas_receipt_historique(instance):
    session, profil, _ = instance
    a = arguments(profil, texte='Je suis déçu de votre service.')
    assert appel(session, a)['ok']
    with session() as cnx:
        signal, opening, receipt = m1._obtenir_registre().lire()
        _recoudre(cnx, [signal, receipt, opening])
        assert m1._obtenir_registre().valider_chaine() == (True, None)
    before = etat(session)
    assert not appel(session, a, FULL_LIRE)['ok']
    assert etat(session) == before


@pytest.mark.parametrize('change', ['extra', 'meta', 'bool_revision', 'cycle', 'NaN', 'operation_courte'])
def test_formes_invalides_ACK_erreur5_sans_lecture_ou_delta(instance, monkeypatch, change):
    session, profil, _ = instance
    a = arguments(profil)
    op = FULL_RECEVOIR
    if change in ('extra', 'meta'):
        a['extra' if change == 'extra' else '_meta'] = {'acteur': 'admin.forge'}
    if change == 'bool_revision':
        a['permission']['revision_profil'] = True
    if change == 'cycle':
        a['commande'] = a
    if change == 'NaN':
        a['commande']['texte'] = float('nan')
    if change == 'operation_courte':
        op = 'recevoir'

    def forbidden():
        raise AssertionError('Source non admise ne doit pas être lue')

    monkeypatch.setattr(m1, 'registre_sms_hote', forbidden)
    before = etat(session)
    r = appel(session, a, op)
    assert set(r) == {'version', 'operation', 'ok', 'etat', 'code'}
    assert r['etat'] == 'forme_invalide' and r['ok'] is False
    assert r['code'] == 'REJ-M1-SMS-FORME-INVALIDE'
    assert etat(session) == before


def test_sous_classe_dict_non_executee(instance):
    session, profil, _ = instance
    calls = []

    class Hostile(dict):
        def __iter__(self):
            calls.append('iter')
            raise AssertionError('ne pas exécuter le mapping hostile')

    before = etat(session)
    r = appel(session, Hostile(arguments(profil)))
    assert r['etat'] == 'forme_invalide' and not r['ok'] and calls == []
    assert etat(session) == before


def test_connexion_absente_ou_etrangere_ne_cree_pas_transaction_de_repli(instance):
    session, profil, _ = instance
    api = importlib.import_module('opsys.reception_sms_receipt')
    a = arguments(profil)
    before = etat(session)
    r = api.executer(None, a, operation=FULL_RECEVOIR, m1=m1)
    assert r['etat'] == 'inconnu' and not r['ok']
    with session(), stockage.moteur().connect() as other:
        r = api.executer(other, a, operation=FULL_RECEVOIR, m1=m1)
        assert r['etat'] == 'inconnu' and not r['ok']
    assert etat(session) == before


def test_deux_comptes_distincts_meme_SID_autorises_via_factories_reelles(instance):
    session, profil, deps = instance
    with session() as cnx:
        spec = {key: profil[key] for key in ('departement', 'responsabilite', 'palier_modele', 'outils',
            'budget_jour', 'budget_mois', 'limite_tours', 'limite_reessais', 'limite_concurrence')}
        spec.update(id='m01-sms-deux', declencheurs=[{'type': 'canal', 'version': 1, 'canal': 'sms',
                                                   'compte_id': 'cabinet-2', 'account_sid': SID}])
        b = agents.creer(cnx, deps, spec, par='admin.sms.fictif', mutation_id='creer-receipt-compte2')
        b = agents.definir_actif(cnx, b['id'], deps, True, par='admin.sms.fictif',
                                mutation_id='actif-receipt-compte2', revision_attendue=1)
    a1 = arguments(profil)
    a2 = arguments(b, 2, numero='+15145550143')
    a2['commande']['compte_id'] = 'cabinet-2'
    assert appel(session, a1)['ok']
    result = appel(session, a2)
    assert result['ok'] and result['recu']['compte_id'] == 'cabinet-2'
    before = etat(session)
    assert appel(session, a1, FULL_LIRE)['recu']['compte_id'] == 'cabinet-1'
    assert appel(session, a2, FULL_LIRE)['recu'] == result['recu']
    assert etat(session) == before


def test_panne_apres_publication_bus_annule_signal_lead_bus(instance, monkeypatch):
    session, profil, _ = instance
    original = m1._publier_lead
    wrote = []

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        wrote.extend(m1._obtenir_registre().lire())
        raise ValueError('panne fictive après publication')

    monkeypatch.setattr(m1, '_publier_lead', fail)
    before = etat(session)
    r = appel(session, arguments(profil))
    assert [row['type_entree'] for row in wrote] == ['signal', 'lead_emis']
    assert not r['ok'] and r['etat'] == 'inconnu'
    assert etat(session) == before


@pytest.mark.parametrize('malformed', ['profil_id', 'agent_id', 'message_sid', 'horodatage'])
def test_autre_recu_malforme_ne_cache_pas_absence(instance, malformed):
    session, profil, _ = instance
    assert appel(session, arguments(profil))['ok']
    with session() as cnx:
        reg = m1._obtenir_registre()
        rows = reg.lire()
        other = rows[-1]
        if malformed == 'profil_id':
            other['permission']['profil_id'] = '../profil'
        elif malformed == 'horodatage':
            other['horodatage'] = '2031-01-15T15:00:00-04:00'
        else:
            other['recu'][malformed] = 'autre/non-canonique'
        _recoudre(cnx, rows)
        assert reg.valider_chaine() == (True, None)
    before = etat(session)
    result = appel(session, arguments(profil, 2), FULL_LIRE)
    assert not result['ok'] and result['etat'] == 'inconnu'
    assert etat(session) == before


@pytest.mark.parametrize('phase', ['avant', 'apres_pipeline', 'apres_receipt'])
def test_bascule_stockage_vraie_connexion_contextuelle_retient_erreur_et_rollback(
    instance, monkeypatch, tmp_path, phase,
):
    session, profil, _ = instance
    old_url = stockage.url_base()
    other_url = f"sqlite:///{tmp_path / 'autre-instance-fictive.db'}"
    stockage.migrer(other_url)
    with stockage.transaction(other_url) as other:
        other_before = census(other)
    before = etat(session)
    assert stockage.moteur().url != stockage.moteur(other_url).url
    seen = []
    if phase != 'avant':
        name = 'recevoir_sms_hote' if phase == 'apres_pipeline' else 'inscrire_recu_sms_hote'
        original = getattr(m1, name)

        def switched(*args, **kwargs):
            result = original(*args, **kwargs)
            seen.extend(m1._obtenir_registre().lire())
            monkeypatch.setenv(stockage.ENV_URL, other_url)
            return result

        monkeypatch.setattr(m1, name, switched)
    api = importlib.import_module('opsys.reception_sms_receipt')
    try:
        with session() as cnx:
            if phase == 'avant':
                monkeypatch.setenv(stockage.ENV_URL, other_url)
            assert cnx is stockage.connexion_courante()
            result = api.executer(cnx, arguments(profil), operation=FULL_RECEVOIR, m1=m1)
    finally:
        monkeypatch.setenv(stockage.ENV_URL, old_url)
    assert not result['ok'] and result['etat'] == 'inconnu'
    if phase != 'avant':
        assert any(r['type_entree'] == 'signal' for r in seen)
    assert etat(session) == before
    with stockage.transaction(other_url) as other:
        assert census(other) == other_before


@pytest.mark.parametrize('session_key', ['inconnue', 'agent:opsys-agent-autre:sms:direct:+15145550142'])
def test_session_recu_hors_intention_malformee_ou_autre_agent_ferme_absent(instance, session_key):
    session, profil, _ = instance
    assert appel(session, arguments(profil))['ok']
    with session() as cnx:
        rows = m1._obtenir_registre().lire()
        rows[-1]['recu']['session_key'] = session_key
        _recoudre(cnx, rows)
        assert m1._obtenir_registre().valider_chaine() == (True, None)
    before = etat(session)
    result = appel(session, arguments(profil, 2), FULL_LIRE)
    assert not result['ok'] and result['etat'] == 'inconnu'
    assert etat(session) == before


def test_revision_courante_avant_toute_lecture_registre(instance, monkeypatch):
    session, profil, _ = instance
    a = arguments(profil)
    a['permission']['revision_profil'] -= 1

    def forbidden():
        raise AssertionError('R ne doit pas être lu après refus P')

    monkeypatch.setattr(m1, 'registre_sms_hote', forbidden)
    before = etat(session)
    result = appel(session, a, FULL_LIRE)
    assert result['etat'] == 'revision_perimee' and not result['ok']
    assert etat(session) == before


@pytest.mark.parametrize('field', ['signal_ligne_id', 'lead_ligne_id', 'arguments_sha256', 'double_receipt'])
def test_references_falsifiees_et_double_receipt_chaine_valide_refuses(instance, field):
    session, profil, _ = instance
    a = arguments(profil)
    assert appel(session, a)['ok']
    with session() as cnx:
        original = m1._obtenir_registre().lire()
        if field == 'double_receipt':
            m1._obtenir_registre().ajouter(original[-1])
        else:
            modified = copy.deepcopy(original)
            if field == 'arguments_sha256':
                modified[-1][field] = 'c' * 64
            else:
                modified[-1]['recu'][field] = modified[0 if field == 'lead_ligne_id' else 1]['ligne_id']
            # Corruption SQL fictive recousue par le vrai propriétaire de hash, pas un faux hash privé.
            owner = Registre()
            for row in modified:
                owner.ajouter(row)
            for i, row in enumerate(owner.lire()):
                cnx.execute(update(schema.REGISTRES).where(schema.REGISTRES.c.departement == 'm01-front-office',
                                                          schema.REGISTRES.c.rang == i)
                            .values(maillon=stockage.codec.encoder(row)))
        assert m1._obtenir_registre().valider_chaine() == (True, None)
    before = etat(session)
    for op in (FULL_LIRE, FULL_RECEVOIR):
        result = appel(session, a, op)
        assert not result['ok'] and 'recu' not in result
    assert etat(session) == before
