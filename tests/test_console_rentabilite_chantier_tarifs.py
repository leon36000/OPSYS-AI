"""Gestion de tarifs d'équipe fictifs, admission console et SQLite réels."""
import importlib.util
from pathlib import Path

from opsys import identite, stockage

spec = importlib.util.spec_from_file_location(
    'tarifs_console_fixtures', Path(__file__).with_name('test_console_finance.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_finance = f.client_finance

URL = '/api/finance/tarifs-equipes'


def tarif():
    return {'equipe_id': 'FICTIF-A', 'taux': '100.00', 'unite': 'heure-equipe', 'devise': 'CAD',
            'source': 'FICTIF-doc', 'version': 'v1', 'date_effet': '2030-01-01',
            'date_fin': '2030-12-31', 'remplace_id': None}


def _client(client):
    return f._connecter(client, 'admin.fictif')


def _headers(client):
    return {'x-csrf-token': f._csrf(client)}


def test_admin_lit_puis_declare_avec_rejeu_et_conflit(client_finance):
    client = _client(client_finance)
    lecture = client.get(URL)
    assert lecture.status_code == 200, lecture.text
    assert lecture.headers['cache-control'] == 'no-store'
    source = lecture.json()['source']
    corps = {'tarif': tarif(), 'mutation_id': 'FICTIF-1', 'source_attendue': source}
    r = client.post(URL, json=corps, headers=_headers(client))
    assert r.status_code == 200, r.text
    assert r.json()['tarif']['taux'] == '100.00'
    assert client.post(URL, json=corps, headers=_headers(client)).json() == r.json()
    conflit = {**corps, 'tarif': {**tarif(), 'taux': '101'}}
    assert client.post(URL, json=conflit, headers=_headers(client)).status_code == 409
    assert len(client.get(URL).json()['historique']) == 1


def test_csrf_source_perimee_et_surcharge_refuses_sans_ecriture(client_finance):
    client = _client(client_finance)
    source = client.get(URL).json()['source']
    corps = {'tarif': tarif(), 'mutation_id': 'FICTIF-2', 'source_attendue': source}
    assert client.post(URL, json=corps).status_code == 403
    assert client.post(URL, json={**corps, 'auteur': 'admin.fictif'}, headers=_headers(client)).status_code == 400
    assert client.post(URL, json={**corps, 'source_attendue': '0' * 64}, headers=_headers(client)).status_code == 409
    assert client.get(URL).json()['historique'] == []


def test_admin_revoque_et_proprietaire_sans_admin_sont_refuses(client_finance):
    client = _client(client_finance)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    assert client.get(URL).status_code == 403
    f._connecter(client, f.NOM)
    assert client.get(URL).status_code == 403


def test_revocation_pendant_ecriture_annule_le_tarif(client_finance, monkeypatch):
    client = _client(client_finance)
    source = client.get(URL).json()['source']
    import m5_financecore.outils as m5
    original = m5._inscrire_tarif_equipe

    def revocation(*args, **kwargs):
        result = original(*args, **kwargs)
        identite.retirer_role(stockage.connexion_courante(), 'admin.fictif', 'admin')
        return result

    monkeypatch.setattr(m5, '_inscrire_tarif_equipe', revocation)
    corps = {'tarif': tarif(), 'mutation_id': 'FICTIF-3', 'source_attendue': source}
    assert client.post(URL, json=corps, headers=_headers(client)).status_code == 403
    monkeypatch.setattr(m5, '_inscrire_tarif_equipe', original)
    r = client.get(URL)
    assert r.status_code == 200 and r.json()['historique'] == []


def test_formulaire_admin_cree_tarif_et_echappe_la_source(client_finance):
    import re

    client = _client(client_finance)
    page = client.get('/finance/tarifs-equipes')
    assert page.status_code == 200 and 'Déclarer le tarif' in page.text
    source = re.search(r'name="source_attendue" value="([^"]+)"', page.text).group(1)
    mutation = re.search(r'name="mutation_id" value="([^"]+)"', page.text).group(1)
    champs = {k: v for k, v in tarif().items() if k not in ('unite', 'devise', 'remplace_id')}
    champs.update(source='<fictif>', remplace_id='', csrf=f._csrf(client),
                  source_attendue=source, mutation_id=mutation)
    r = client.post('/finance/tarifs-equipes', data=champs, follow_redirects=False)
    assert r.status_code == 303, r.text
    page = client.get('/finance/tarifs-equipes')
    assert page.status_code == 200 and '&lt;fictif&gt;' in page.text and '<fictif>' not in page.text
    assert '100.00' in page.text and page.headers['cache-control'] == 'no-store'


def test_concurrence_avec_meme_source_refuse_un_des_deux(client_finance):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    client = _client(client_finance)
    source = client.get(URL).json()['source']
    headers = _headers(client)
    barriere = Barrier(2)

    def ecrire(i):
        barriere.wait(timeout=10)
        return client.post(URL, json={'tarif': {**tarif(), 'taux': str(100 + i)},
                           'mutation_id': f'FICTIF-CONC-{i}', 'source_attendue': source}, headers=headers).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuts = list(pool.map(ecrire, [1, 2]))
    assert sorted(statuts) == [200, 409]
    assert len(client.get(URL).json()['historique']) == 1


def test_transport_mcp_et_falsification_de_la_chaine_sont_refuses(client_finance, monkeypatch):
    from sqlalchemy import update

    from opsys import contexte
    from opsys.stockage.schema import REGISTRES

    client = _client(client_finance)
    source = client.get(URL).json()['source']
    corps = {'tarif': tarif(), 'mutation_id': 'FICTIF-MCP', 'source_attendue': source}
    with monkeypatch.context() as m:
        m.setattr(contexte, 'appel_provient_du_mcp', lambda: True)
        assert client.post(URL, json=corps, headers=_headers(client)).status_code == 403
    assert client.post(URL, json=corps, headers=_headers(client)).status_code == 200
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).where((REGISTRES.c.departement == 'm05-financecore') &
            (REGISTRES.c.registre == 'tarifs_equipes')).values(maillon='{}'))
    assert client.get(URL).status_code == 503


def test_revocation_pendant_lecture_refuse_la_reponse(client_finance, monkeypatch):
    from m5_financecore import outils as m5

    from opsys import stockage

    client = _client(client_finance)
    original, appels = m5._lire_tarifs_equipes, []

    def revoquer():
        resultat = original()
        appels.append(1)
        if len(appels) == 1:
            identite.retirer_role(stockage.connexion_courante(), 'admin.fictif', 'admin')
        return resultat

    monkeypatch.setattr(m5, '_lire_tarifs_equipes', revoquer)
    response = client.get(URL)
    assert response.status_code == 403 and 'historique' not in response.text
