"""Notes d'achat CRM : vrais outils M2/M3/M6 et HTTP/SQLite, fixtures fictives."""
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from m2_revenue_crm import outils as m2
from m3_estimation import outils as m3
from m6_material_control import outils as m6
from sqlalchemy import select

from opsys import identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.stockage.schema import META

FICTIF = True
PASSWORD = 'mot-de-passe-fictif-123456'
DATE = '2030-01-01T12:00:00+00:00'
URL = '/crm/lead/lead-fictif/soumissions/devis-fictif/notes-achats'
TEXT = "  Achats FICTIFS <script>alert('x')</script>\r\nVis & scellant\t\n"


@pytest.fixture
def client(session):
    m2.utiliser_stockage_durable()
    with session() as cnx:
        for personne, role in [('admin-fictif', 'admin'), ('employee-fictif', 'employee'),
                               ('owner-fictif', 'nathan_owner')]:
            identite.creer_personne(cnx, personne, 'Personne FICTIVE', PASSWORD, [role])
        for suffixe in ['', '-autre', '-sans-chantier']:
            lead, devis = 'lead-fictif'+suffixe, 'devis-fictif'+suffixe
            assert m2.ingerer_lead({'lead_id': lead, 'conversation_id': 'conv-'+lead,
                                   'contact': {'nom': 'FICTIF', 'courriel': lead+'@example.test'},
                                   'type_travaux': 'renovation_totale', 'ville': 'Québec',
                                   'urgence_declaree': False, 'canal': 'telephone'}, DATE)['accepte']
            assert m3.creer_devis(devis, lead, None,
                                  [{'description': 'FICTIF', 'quantite': '2', 'unite': 'pi',
                                    'cout_unitaire': '10', 'reference_besoin_materiau': None}],
                                  '0.20', DATE)['accepte']
            if suffixe != '-sans-chantier':
                assert m6.enregistrer_besoins_prevus('chantier-fictif'+suffixe, devis, [])['accepte']
    app = application.creer_application(Configuration('secret-fictif-'+'x'*40, cookie_securise=False,
                                                       prefixe='/opsys'), None, session)
    with TestClient(app, base_url='https://testserver/opsys') as c:
        yield c


def login(c, user='admin-fictif'):
    r = c.post('/connexion', data={'identifiant': user, 'mot_de_passe': PASSWORD}, follow_redirects=False)
    assert r.status_code == 303


def fields(c, **change):
    return {'csrf': c.get('/api/session').json()['csrf'], 'note_id': 'note-fictive',
            'revision_attendue': '0', 'mutation_id': 'intention-fictive', 'texte_libre': TEXT, **change}


def snapshot(session):
    with session() as cnx:
        return [(t.name, [tuple(r) for r in cnx.execute(select(t)).all()]) for t in META.sorted_tables]


def versions(session):
    with session():
        return list(stockage.maillons('m06-material-control', 'notes_commande'))


def test_formulaire_texte_exact_versions_rejeu_et_historique(client, session):
    login(client)
    before = snapshot(session)
    page = client.get(URL)
    assert page.status_code == 200, page.text
    assert 'chantier-fictif' in page.text and 'name="texte_libre"' in page.text
    assert 'aucune commande' in page.text.lower() and page.headers['cache-control'] == 'no-store'
    assert snapshot(session) == before
    body = fields(client)
    saved = client.post(URL, data=body, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    detail = URL+'/note-fictive'
    assert saved.headers['location'] == '/opsys'+detail
    assert versions(session)[0]['texte_libre'] == TEXT
    first = snapshot(session)
    assert client.post(URL, data=body, follow_redirects=False).status_code == 303
    assert snapshot(session) == first
    page = client.get(detail)
    assert '&lt;script&gt;' in page.text and "<script>alert('x')</script>" not in page.text
    assert 'admin-fictif' in page.text and 'Révision 1' in page.text
    assert client.post(detail, data=fields(client, revision_attendue='1', mutation_id='correction-fictive',
                                          texte_libre='Correction FICTIVE'), follow_redirects=False).status_code == 303
    assert len(versions(session)) == 2
    old = client.get(detail+'?revision=1')
    assert old.status_code == 200 and '&lt;script&gt;' in old.text
    assert 'name="texte_libre"' not in old.text and 'Révision suivante' in old.text
    latest = client.get(detail)
    assert 'Correction FICTIVE' in latest.text and 'Révision précédente' in latest.text
    assert 'note-fictive' in client.get(URL).text
    after = snapshot(session)
    assert client.post(URL, data=body, follow_redirects=False).status_code == 303
    assert snapshot(session) == after


def test_long_texte_20000_sans_artefact(client, session):
    login(client)
    text = '😀é\n\t'*5000
    assert client.post(URL, data=fields(client, texte_libre=text), follow_redirects=False).status_code == 303
    assert versions(session)[0]['texte_libre'] == text
    assert client.get(URL+'/note-fictive').status_code == 200
    with session() as cnx:
        for t in META.sorted_tables:
            if 'artefact' in t.name:
                assert not cnx.execute(select(t)).all()


@pytest.mark.parametrize('user', ['employee-fictif', 'owner-fictif'])
def test_non_admin_ne_lit_ni_ecrit(client, session, user):
    login(client, user)
    before = snapshot(session)
    assert client.get(URL).status_code == 403
    assert client.post(URL, data=fields(client)).status_code == 403
    assert snapshot(session) == before


def test_csrf_forme_taille_et_champs_usurpes(client, session):
    login(client)
    body = fields(client)
    before = snapshot(session)
    for changes, status in [({'csrf': 'faux'}, 403), ({'auteur': 'usurpe'}, 400),
                            ({'texte_libre': 'x'*20001}, 400), ({'revision_attendue': '-1'}, 400),
                            ({'texte_libre': '  '}, 400), ({'chantier_id': 'autre'}, 400)]:
        assert client.post(URL, data={**body, **changes}).status_code == status
    assert client.post(URL, content=urlencode(body)+'&texte_libre=duplique',
                       headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 400
    assert client.post(URL, content=b'x'*260001,
                       headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 413
    assert client.post(URL, json=body).status_code == 415
    assert snapshot(session) == before


def test_ancres_croisees_inconnues_et_absentes(client, session):
    login(client)
    assert client.post(URL, data=fields(client), follow_redirects=False).status_code == 303
    before = snapshot(session)
    wrong = URL.replace('/devis-fictif/', '/devis-fictif-autre/')
    assert client.get(wrong).status_code == 404
    other = URL.replace('lead-fictif', 'lead-fictif-autre').replace('devis-fictif', 'devis-fictif-autre')
    assert client.get(other+'/note-fictive').status_code == 404
    assert client.post(other+'/note-fictive', data=fields(client, revision_attendue='1')).status_code == 404
    absent = URL.replace('lead-fictif', 'lead-fictif-sans-chantier')
    absent = absent.replace('devis-fictif', 'devis-fictif-sans-chantier')
    assert client.get(absent).status_code == 409
    assert client.post(absent, data=fields(client)).status_code == 409
    assert client.get(URL+'/inconnue').status_code == 404
    assert snapshot(session) == before


def test_conflit_cas_et_mutation_sans_fuite(client, session):
    login(client)
    body = fields(client)
    assert client.post(URL, data=body, follow_redirects=False).status_code == 303
    before = snapshot(session)
    for changes in [{'texte_libre': 'nouveau texte fictif'}, {'mutation_id': 'autre-fictive'}]:
        r = client.post(URL, data={**body, **changes})
        assert r.status_code == 409 and TEXT not in r.text
    assert snapshot(session) == before


def test_revocation_et_desactivation_avant_rejeu(client, session):
    login(client)
    body = fields(client)
    assert client.post(URL, data=body, follow_redirects=False).status_code == 303
    with session() as cnx:
        identite.ajouter_role(cnx, 'admin-fictif', 'nathan_owner')
        identite.retirer_role(cnx, 'admin-fictif', 'admin')
    before = snapshot(session)
    assert client.get(URL+'/note-fictive').status_code == 403
    assert client.post(URL, data=body).status_code == 403
    assert snapshot(session) == before


def test_parametres_bornes_et_pas_de_faux_lien(client, session):
    login(client)
    before = snapshot(session)
    for q in ['?decalage=-1', '?decalage=10001', '?decalage=0&decalage=1', '?inconnu=1']:
        assert client.get(URL+q).status_code == 400
    assert snapshot(session) == before
    page = client.get('/crm/lead/lead-fictif/soumissions/devis-fictif')
    assert '/notes-achats' in page.text


def test_session_expiree_et_compte_inactif_interdisent_rejeu(client, session):
    from dataclasses import replace

    from opsys.console import securite
    login(client)
    body = fields(client)
    assert client.post(URL, data=body, follow_redirects=False).status_code == 303
    with session() as cnx:
        identite.activer(cnx, 'admin-fictif', False)
    before = snapshot(session)
    denied = client.post(URL, data=body, follow_redirects=False)
    assert denied.status_code in {303, 403} and TEXT not in denied.text
    assert snapshot(session) == before
    with session() as cnx:
        identite.activer(cnx, 'admin-fictif', True)
    expired = replace(securite.ouvrir_session('admin-fictif', ['admin']), expire=1)
    client.cookies.clear()
    client.cookies.set(securite.NOM_COOKIE, securite.signer_session(expired, 'secret-fictif-'+'x'*40))
    before = snapshot(session)
    result = client.post(URL, data=body, follow_redirects=False)
    assert result.status_code == 303 and result.headers['location'].endswith('/connexion')
    assert snapshot(session) == before


def test_recu_expire_et_journal_ne_copient_pas_note(client, session):
    import json

    from sqlalchemy import delete

    from opsys.stockage.schema import APPROBATIONS, JOURNAL, MUTATIONS_APPLIQUEES
    login(client)
    body = fields(client)
    assert client.post(URL, data=body, follow_redirects=False).status_code == 303
    assert client.post(URL+'/note-fictive', data=fields(client, revision_attendue='1',
                       mutation_id='v2-fictive', texte_libre='FICTIF V2'), follow_redirects=False).status_code == 303
    with session() as cnx:
        cnx.execute(delete(MUTATIONS_APPLIQUEES))
    assert client.post(URL, data=body, follow_redirects=False).status_code == 303
    assert len(versions(session)) == 2
    with session() as cnx:
        assert not cnx.execute(select(APPROBATIONS)).all()
        traces = json.dumps([dict(r) for r in cnx.execute(select(JOURNAL)).mappings()], default=str)
        assert 'alert' not in traces and 'Achats FICTIFS' not in traces
        assert traces.count('m6.note_commande_enregistree') == 2


def test_edition_historique_query_et_identifiant_usurpe(client, session):
    login(client)
    assert client.post(URL, data=fields(client), follow_redirects=False).status_code == 303
    before = snapshot(session)
    for q in ['?revision=0', '?revision=1&revision=2', '?revision=1000001', '?inconnu=1']:
        assert client.get(URL+'/note-fictive'+q).status_code == 400
    for change in [{'note_id': 'autre'}, {'revision_attendue': '0'}]:
        assert client.post(URL+'/note-fictive', data=fields(client, **change)).status_code == 400
    assert client.get(URL+'/note-fictive?revision=2').status_code == 404
    assert client.post(URL+'?inconnu=1', data=fields(client)).status_code == 400
    assert snapshot(session) == before


@pytest.mark.parametrize('ident', ['note fictive / matériel ? # 😀', '.', '..', '~fictif'])
def test_identifiant_m6_existant_avec_espace_et_slash_accessible(client, session, ident):
    import base64

    from opsys import contexte, idempotence
    ref = '~'+base64.urlsafe_b64encode(ident.encode()).decode().rstrip('=')
    with (session(), contexte.appele_par_appareil(contexte.IdentiteAppelante('admin-fictif', 'admin')),
          m6.contexte_mutation_note_commande(idempotence.Meta('id-fictive-etrange', 'app-fictive', DATE))):
        assert m6.enregistrer_note_commande(ident, 'devis-fictif', 'FICTIF note antérieure', 0)['accepte']
    login(client)
    page = client.get(URL)
    assert '/notes-achats/'+ref in page.text
    detail = client.get(URL+'/'+ref)
    assert detail.status_code == 200 and 'FICTIF note antérieure' in detail.text
    assert client.post(URL+'/'+ref, data=fields(client, note_id=ident, revision_attendue='1',
                       mutation_id='id-correction-fictive', texte_libre='FICTIF corrigé'),
                       follow_redirects=False).status_code == 303
    assert versions(session)[-1]['note_id'] == ident
