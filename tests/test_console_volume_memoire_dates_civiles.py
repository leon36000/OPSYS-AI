"""fictif: true — vrais plans PyVRP et frontière des contextes; jamais un quota PASS global."""
import importlib.util
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from m4_field_ops import tournees
from m4_field_ops.outils import outils
from sqlalchemy import event

from opsys.console import memoire_chantier, memoire_plan_calendrier
from opsys.console.preparation_chantier import Refus
from opsys.departements import charger_departements

spec = importlib.util.spec_from_file_location('volume_memoire_civil_fixture',
    Path(__file__).with_name('test_console_memoire_plan_calendrier.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm = f.client_crm
FICTIF = True


def _plan_reel(session, nombre, attendre_refus_matrice=False):
    if not tournees.pyvrp_installe()[0]:
        pytest.skip('extra tournees épinglé requis pour cette qualification de volume réel')
    from m10_memoire import amont, registre

    from opsys import stockage

    debut = time.perf_counter()
    m4 = {o.nom: o for o in outils()}
    ids = {}
    for i in range(nombre):
        original = f.b.terrain.SCENARIO['leads'][i % 2]
        lead = {**original, 'lead_id': f'volume-affaire-fictive-{i:03d}', 'type_travaux': 'ravalement'}
        heure = (datetime(2030, 1, 1, tzinfo=UTC) + timedelta(seconds=i)).isoformat()
        ids[lead['lead_id']] = f.b.terrain._inscrire(m4, lead, heure)
        f.b.terrain._resultat(f.b.terrain._confirmer(m4, lead))
        with session():
            reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
            assert amont.memoriser('m1.lead_qualifie', dict(lead=dict(lead_id=lead['lead_id'],
                service='gouttieres', canal='telephone', urgence_declaree=False), horodatage=heure), reg)[1] is None
    equipes = f.b.terrain._equipes()
    for equipe in equipes:
        equipe['quarts'] = [dict(jour=j, debut_min=480, fin_min=1020) for j in range(4)]
    chantiers = [dict(intervention_id=iid,
        fenetre=dict(jours=list(range(4)), debut_min=480, fin_min=1020), creneau_fige=None) for iid in ids.values()]
    avant = f.b.base._instantane_base(session) if attendre_refus_matrice else None
    reponse = f.b.terrain._proposer(m4, ids, moteur='pyvrp', equipes=equipes,
        intervention_ids=list(ids.values()), chantiers=chantiers, durees_par_type_travaux={'ravalement': 5},
        competences_par_type_travaux={'ravalement': []},
        parametres={**f.b.terrain.SCENARIO['parametres'], 'iterations': 100})
    if attendre_refus_matrice:
        assert f.b.terrain._code_refus(reponse) == 'REJ-CONTRAT-INVALIDE'
        assert '202 points, maximum 100 par matrice' in reponse['resultat']['verdict']['detail']
        assert f.b.base._instantane_base(session) == avant
        return m4, ids, reponse, time.perf_counter() - debut
    plan = f.b.terrain._resultat(reponse)
    assert plan['totaux']['chantiers_cedules'] == nombre and not plan['non_cedulees'], plan
    assert plan['solveur'] == 'pyvrp' and plan['version_solveur'] == '0.14.0'
    assert plan['mode_bride'] is True and plan['mode_distance'] == 'haversine_detour'
    f.b.terrain._resultat(f.b.terrain._appliquer(m4, plan['plan_id']))
    preparation = time.perf_counter() - debut
    return m4, ids, plan, preparation


@pytest.mark.parametrize('nombre', [6, 24, 64])
def test_mesure_plan_reel_et_quota_sans_confirmation_partielle(
        client_crm, session, monkeypatch, record_testsuite_property, nombre):
    m4, ids, plan, preparation = _plan_reel(session, nombre)
    f.b.base._connecter(client_crm, f.AUTH.utilisateur)
    avant = f.b.base._instantane_base(session)
    original_paquet = memoire_chantier._paquet
    appels, requetes = [], []

    def lire_paquet(*args):
        appels.append(args[2])
        return original_paquet(*args)

    def compter(cnx, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            requetes.append(statement)

    monkeypatch.setattr(memoire_chantier, '_paquet', lire_paquet)
    reponse, refus = None, None
    with session() as cnx:
        event.listen(cnx, 'before_cursor_execute', compter)
        debut = time.perf_counter()
        try:
            reponse = memoire_plan_calendrier.lire(cnx, charger_departements(), f.AUTH, plan['plan_id'])
        except Refus as erreur:
            assert erreur.code == 'SORTIE-TROP-VOLUMINEUSE'
            refus = erreur.code
        finally:
            secondes = time.perf_counter() - debut
            event.remove(cnx, 'before_cursor_execute', compter)
    assert 0 < len(appels) <= nombre and len(appels) == len(set(appels))
    if reponse is not None:
        assert reponse['synthese']['affaires'] == reponse['synthese']['visites'] == len(appels) == nombre
        assert 0 < len(reponse['liaisons']) <= memoire_plan_calendrier.TAILLE_PAGE
        assert len(reponse['affaires']) <= len(reponse['liaisons'])
        assert all(a['paquet']['affaire']['origine_recue'] for a in reponse['affaires'])
        octets = len(json.dumps(reponse, ensure_ascii=False, allow_nan=False).encode())
        assert octets <= 65536
    else:
        octets = None
        assert refus == 'SORTIE-TROP-VOLUMINEUSE'
    assert f.b.base._instantane_base(session) == avant
    monkeypatch.setattr(memoire_chantier, '_paquet', original_paquet)
    page = client_crm.get('/crm/cedule/plan/' + plan['plan_id'])
    assert page.status_code == (200 if reponse is not None else 503), page.text
    assert ('Confirmer les dates internes' in page.text) is (reponse is not None)
    assert f.b.base._instantane_base(session) == avant
    mesure = dict(affaires=nombre, visites_reellement_appliquees=nombre, solveur='pyvrp-0.14.0',
        duree_fictive_minutes=5, horizon_jours=4, mode_distance=plan['mode_distance'],
        mode_bride=plan['mode_bride'], preparation_secondes=preparation,
        lecture_secondes=secondes, appels_paquet=len(appels), select_sql=len(requetes),
        select_maillons=sum('registres_maillons.maillon' in s for s in requetes), octets=octets,
        refus=refus, http=page.status_code, html_octets=len(page.content),
        detail_visites=len(reponse['liaisons']) if reponse is not None else 0,
        preparation_globale_complete=reponse is not None)
    record_testsuite_property(f'volume_civil_{nombre}', json.dumps(mesure, sort_keys=True))



def test_plan_64_affaires_reel_devient_consultable_par_pages(client_crm, session):
    _m4, _ids, plan, _preparation = _plan_reel(session, 64)
    f.b.base._connecter(client_crm, f.AUTH.utilisateur)
    avant = f.b.base._instantane_base(session)
    page = client_crm.get('/crm/cedule/plan/' + plan['plan_id'])
    assert page.status_code == 200, page.text
    assert 'Synthèse globale de mémoire' in page.text
    assert 'sur 64' in page.text and 'Page suivante' in page.text
    assert f.b.base._instantane_base(session) == avant



def _http_fixture():
    spec_http = importlib.util.spec_from_file_location('volume_pagination_formulaire_reel',
        Path(__file__).with_name('test_console_memoire_dates_civiles.py'))
    module = importlib.util.module_from_spec(spec_http)
    spec_http.loader.exec_module(module)
    return module


def test_preuve_globale_identique_pages_et_vraie_confirmation(client_crm, session, monkeypatch):
    from opsys import idempotence

    _m4, ids, plan, _preparation = _plan_reel(session, 64)
    f.b.base._connecter(client_crm, f.AUTH.utilisateur)
    captures = {}
    original = memoire_chantier._paquet

    def capturer(*args):
        paquet = original(*args)
        captures.setdefault(args[2], paquet)
        return paquet

    monkeypatch.setattr(memoire_chantier, '_paquet', capturer)
    avant = f.b.base._instantane_base(session)
    offset, source, liens = 0, None, []
    while True:
        with session() as cnx:
            r = memoire_plan_calendrier.lire(cnx, charger_departements(), f.AUTH, plan['plan_id'], offset, source)
        assert r['synthese']['affaires'] == 64 and len(captures) == 64
        assert len(json.dumps(r, ensure_ascii=False).encode()) <= 65536
        if source is None:
            source = r['source_pagination']
        assert source == r['source_pagination'] == memoire_plan_calendrier.preuve(r)
        liens.extend(r['liaisons'])
        prochain = r['pagination']['suivant']
        if prochain is None:
            break
        assert prochain > offset
        offset = prochain
    assert len(liens) == len({lien['intervention_id'] for lien in liens}) == 64
    assert {lien['intervention_id'] for lien in liens} == set(ids.values())
    historique = dict(liaisons=liens, sources=r['sources_m10'], affaires=[dict(lead_id=lead, affaire_id=lead,
        etat='CONTEXTE_AFFAIRE', paquet={k: v for k, v in paquet.items() if k != 'horodatage'})
        for lead, paquet in captures.items()])
    assert r['empreinte_memoire'] == idempotence.empreinte_arguments(historique)
    url = '/crm/cedule/plan/' + plan['plan_id']
    page = client_crm.get(url, params={'offset_memoire': str(offset), 'source_memoire': source})
    assert page.status_code == 200 and 'Page précédente' in page.text, page.text
    assert f.b.base._instantane_base(session) == avant
    champs = _http_fixture().Formulaire(page.text).champs
    assert champs['empreinte_memoire_attendue'] == source
    for cle in champs:
        if cle.startswith('date_'):
            champs[cle] = '2030-06-' + str(3 + int(cle.removeprefix('date_'))).zfill(2)
    reponse = client_crm.post(url, data=champs, follow_redirects=False)
    assert reponse.status_code == 303, reponse.text
    with session():
        dates = [m for m in f.b.terrain._maillons() if m['type_entree'] == 'cedule_datee']
        assert len(dates) == 1 and dates[0]['plan_id'] == plan['plan_id']
    apres = f.b.base._instantane_base(session)
    assert client_crm.post(url, data=champs).status_code == 200
    assert f.b.base._instantane_base(session) == apres


def test_changement_m10_et_arguments_pagination_refusent_sans_effet(client_crm, session):
    from m10_memoire import amont, registre

    from opsys import stockage

    _m4, _ids, plan, _preparation = _plan_reel(session, 6)
    f.b.base._connecter(client_crm, f.AUTH.utilisateur)
    url = '/crm/cedule/plan/' + plan['plan_id']
    with session() as cnx:
        r = memoire_plan_calendrier.lire(cnx, charger_departements(), f.AUTH, plan['plan_id'])
    page = client_crm.get(url)
    champs = _http_fixture().Formulaire(page.text).champs
    source = r['source_pagination']
    invalide = [{'offset_memoire': '3'}, {'offset_memoire': '03', 'source_memoire': source},
        {'offset_memoire': '-1', 'source_memoire': source}, {'offset_memoire': '200', 'source_memoire': source},
        {'offset_memoire': '6', 'source_memoire': source}, {'source_memoire': source},
        [('offset_memoire', '3'), ('offset_memoire', '0'), ('source_memoire', source)]]
    avant = f.b.base._instantane_base(session)
    for params in invalide:
        assert client_crm.get(url, params=params).status_code == 400
    assert client_crm.post(url+'?offset_memoire=0', data=champs).status_code == 400
    assert f.b.base._instantane_base(session) == avant
    with session():
        reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
        assert amont.memoriser('m1.lead_qualifie', dict(lead=dict(lead_id='volume-perturbation-fictive',
            service='gouttieres', canal='telephone', urgence_declaree=False),
            horodatage='2030-06-03T08:00:00-04:00'), reg)[1] is None
    avant = f.b.base._instantane_base(session)
    page = client_crm.get(url, params={'offset_memoire': '3', 'source_memoire': source})
    assert page.status_code == 409 and 'Reprendre au début' in page.text
    assert 'Confirmer les dates internes' not in page.text
    for cle in champs:
        if cle.startswith('date_'):
            champs[cle] = '2030-06-03'
    assert client_crm.post(url, data=champs).status_code == 409
    assert f.b.base._instantane_base(session) == avant


def test_signaux_et_paquet_defectueux_hors_page_restent_controles(client_crm, session, monkeypatch):
    from m10_memoire import registre, variance, wct

    from opsys import stockage

    _m4, _ids, plan, _preparation = _plan_reel(session, 6)
    with session() as cnx:
        premier = memoire_plan_calendrier.lire(cnx, charger_departements(), f.AUTH, plan['plan_id'])
    affiches = {a['lead_id'] for a in premier['affaires']}
    autre = next(lead for lead in _ids if lead not in affiches)
    spec_signaux = importlib.util.spec_from_file_location('volume_signaux_reels',
        Path(__file__).parents[1] / 'departments/m10-memoire/tests/test_signaux.py')
    signaux = importlib.util.module_from_spec(spec_signaux)
    spec_signaux.loader.exec_module(signaux)
    with session():
        reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
        for i in range(6):
            ident = f'WCT-VOLUME-FICTIF-{i}'
            assert wct.memoriser_wct(signaux._wct(ident, autre), reg)[1] is None
            assert variance.memoriser_variance(signaux._variance(f'VAR-VOLUME-FICTIF-{i}', ident), reg)[1] is None
    f.b.base._connecter(client_crm, f.AUTH.utilisateur)
    avant = f.b.base._instantane_base(session)
    with session() as cnx:
        r = memoire_plan_calendrier.lire(cnx, charger_departements(), f.AUTH, plan['plan_id'])
    assert autre not in {a['lead_id'] for a in r['affaires']}
    assert r['synthese']['signaux_ouverts'] == 6
    assert any(r['synthese']['omissions_par_couche'].values())
    page = client_crm.get('/crm/cedule/plan/' + plan['plan_id'])
    assert page.status_code == 200 and 'Signaux ouverts hors détail compris : 6' in page.text
    assert 'Confirmer les dates internes' in page.text
    original = memoire_chantier._paquet

    def casser(*args):
        paquet = original(*args)
        if args[2] == autre:
            paquet['couches'] = []
        return paquet

    monkeypatch.setattr(memoire_chantier, '_paquet', casser)
    page = client_crm.get('/crm/cedule/plan/' + plan['plan_id'])
    assert page.status_code == 503 and 'Confirmer les dates internes' not in page.text
    assert f.b.base._instantane_base(session) == avant


def test_98_visites_reelles_premiere_et_derniere_pages(client_crm, session, record_testsuite_property):
    _m4, _ids, plan, preparation = _plan_reel(session, 98)
    avant = f.b.base._instantane_base(session)
    debut = time.perf_counter()
    with session() as cnx:
        premier = memoire_plan_calendrier.lire(cnx, charger_departements(), f.AUTH, plan['plan_id'])
        dernier = memoire_plan_calendrier.lire(cnx, charger_departements(), f.AUTH, plan['plan_id'],
            97, premier['source_pagination'])
    assert premier['synthese']['affaires'] == premier['synthese']['visites'] == 98
    assert dernier['source_pagination'] == premier['source_pagination']
    assert dernier['pagination']['suivant'] is None and dernier['pagination']['inclus'] == 1
    assert len(json.dumps(premier, ensure_ascii=False).encode()) <= 65536
    assert f.b.base._instantane_base(session) == avant
    record_testsuite_property('volume98_premiere_derniere', json.dumps(dict(
        visites_reellement_appliquees=98, solveur='pyvrp0.14.0', preparation_secondes=preparation,
        deux_lectures_secondes=time.perf_counter()-debut,
        premiere_octets=len(json.dumps(premier, ensure_ascii=False).encode()),
        derniere_octets=len(json.dumps(dernier, ensure_ascii=False).encode()),
        navigation_complete_98=False, donnees_fictives=True)))



def test_retour_page_adaptative_ne_saute_aucune_visite(client_crm, session, monkeypatch):
    from opsys.console import preparation_chantier as lecture

    _m4, _ids, plan, _preparation = _plan_reel(session, 6)
    avant = f.b.base._instantane_base(session)
    monkeypatch.setattr(memoire_plan_calendrier, 'TAILLE_PAGE', 1)
    with session() as cnx:
        une = memoire_plan_calendrier.lire(cnx, charger_departements(), f.AUTH, plan['plan_id'])
    budget = len(json.dumps(une, ensure_ascii=False).encode()) + 64
    monkeypatch.setattr(memoire_plan_calendrier, 'TAILLE_PAGE', 3)
    monkeypatch.setattr(lecture, 'MAX_SORTIE_OCTETS', budget)
    with session() as cnx:
        trois = memoire_plan_calendrier.lire(cnx, charger_departements(), f.AUTH, plan['plan_id'],
            3, une['source_pagination'])
        assert trois['pagination']['inclus'] == 1
        quatre = memoire_plan_calendrier.lire(cnx, charger_departements(), f.AUTH, plan['plan_id'],
            trois['pagination']['suivant'], une['source_pagination'])
    assert quatre['pagination']['offset'] == 4
    assert quatre['pagination']['precedent'] == 3
    assert f.b.base._instantane_base(session) == avant



def test_200_inscriptions_refusees_par_borne_matrice_sans_plan(client_crm, session, record_testsuite_property):
    _m4, ids, refus, preparation = _plan_reel(session, 200, attendre_refus_matrice=True)
    assert len(ids) == 200 and refus['resultat']['accepte'] is False
    with session():
        assert not any(m['type_entree'] in ('cedule_proposee', 'cedule_appliquee')
                       for m in f.b.terrain._maillons())
    record_testsuite_property('volume200_refus_matrice', json.dumps(dict(inscriptions_reelles=200,
        points_matrice=202, maximum_matrice=100, preparation_secondes=preparation,
        plan_cree=False, capacite_200_qualifiee=False, verdict=refus['resultat']['verdict']['code'])))
