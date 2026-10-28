"""fictif: true — actions admin explicites, formes CSRF et histoire des absences déclarées."""
import importlib.util
import re
import uuid
from html import unescape
from pathlib import Path
from urllib.parse import urlencode

import pytest

from opsys import identite
from opsys.stockage.schema import JOURNAL, REGISTRES

spec = importlib.util.spec_from_file_location('absence_form_fixture',
    Path(__file__).with_name('test_console_absence_ecriture.py'))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
client_crm, monde = w.client_crm, w.monde
base = w.base
FICTIF = True
URL = '/crm/journal-equipes/absence?jour=2030-06-03&personne_id=inactif.fictif'


def connecter(client, personne='admin.fictif'):
    base._connecter(client, personne)


def formulaire(client, statut='signalee'):
    r = client.get(URL)
    assert r.status_code == 200, r.text
    bloc = next(x for x in re.findall(r'<form\b.*?</form>', r.text, re.S)
                if f'name="statut_declaration" value="{statut}"' in x)
    champs = {k: unescape(v) for k, v in re.findall(r'name="([^"]+)" value="([^"]*)"', bloc)}
    assert set(champs) == {'csrf', 'revision_attendue', 'mutation_id', 'statut_declaration'}
    return champs


def post(client, champs, url=URL):
    return client.post(url, data=champs, follow_redirects=False)


def test_formes_reelles_signaler_retirer_redeclarer_et_rejeu_sans_retour_arriere(monde, client_crm, session):
    connecter(client_crm)
    avant = dict(base._instantane_base(session))
    initial = formulaire(client_crm)
    assert initial['revision_attendue'] == '0'
    r = post(client_crm, initial)
    assert r.status_code == 303, r.text
    assert r.headers['location'].removeprefix(base.PREFIXE) == URL
    assert 'Révision 1' in client_crm.get(URL).text
    stable = base._instantane_base(session)
    assert post(client_crm, initial).status_code == 303
    assert base._instantane_base(session) == stable
    retire = formulaire(client_crm, 'retiree')
    assert post(client_crm, retire).status_code == 303
    page = client_crm.get(URL)
    assert 'Signalement retiré; aucune présence déduite' in page.text
    assert 'name="statut_declaration" value="retiree"' not in page.text
    nouveau = formulaire(client_crm)
    assert nouveau['revision_attendue'] == '2' and post(client_crm, nouveau).status_code == 303
    stable = base._instantane_base(session)
    assert post(client_crm, initial).status_code == 303
    assert formulaire(client_crm)['revision_attendue'] == '3'
    assert base._instantane_base(session) == stable and len(w.lignes(session)) == 3
    apres = dict(base._instantane_base(session))
    for table in avant:
        if table not in {REGISTRES.name, JOURNAL.name}:
            assert avant[table] == apres[table], table
    assert all(w.g.PERSONNE not in str(x) for x in apres[JOURNAL.name][len(avant[JOURNAL.name]):])


@pytest.mark.parametrize('modif', [{'csrf': 'faux'}, {'revision_attendue': '00'}, {'mutation_id': 'faux'},
    {'statut_declaration': 'present'}, {'motif': 'information fictive interdite'}, {'auteur': 'autre.admin'},
    {'horodatage': '2030-01-01T00:00:00+00:00'}, {'minutes_payees': '480'}])
def test_formulaire_non_signe_ou_champs_sensibles_refuses(monde, client_crm, session, modif):
    connecter(client_crm)
    champs = {**formulaire(client_crm), **modif}
    avant = base._instantane_base(session)
    r = post(client_crm, champs)
    assert r.status_code in {400, 403}, r.text
    assert base._instantane_base(session) == avant


def test_intention_corps_et_cas_concurrent_ou_autre_url_refuses(monde, client_crm, session):
    connecter(client_crm)
    initial, concurrent = formulaire(client_crm), formulaire(client_crm)
    assert post(client_crm, initial).status_code == 303
    avant = base._instantane_base(session)
    assert post(client_crm, concurrent).status_code == 409
    assert post(client_crm, {**initial, 'statut_declaration': 'retiree'}).status_code == 409
    autre = URL.replace('2030-06-03', '2030-06-07')
    assert post(client_crm, initial, autre).status_code == 409
    assert base._instantane_base(session) == avant


def test_forme_cible_historique_apres_changement_role_pas_autre_jour_initial(monde, client_crm, session):
    connecter(client_crm)
    initial = formulaire(client_crm)
    assert post(client_crm, initial).status_code == 303
    with session() as cnx:
        identite.ajouter_role(cnx, w.g.PERSONNE, 'client')
        identite.retirer_role(cnx, w.g.PERSONNE, 'employee')
    assert post(client_crm, formulaire(client_crm, 'retiree')).status_code == 303
    assert post(client_crm, formulaire(client_crm)).status_code == 303
    autre = URL.replace('2030-06-03', '2030-06-07')
    r = client_crm.get(autre)
    assert r.status_code == 200 and 'Première déclaration indisponible' in r.text
    assert 'name="statut_declaration"' not in r.text
    avant = base._instantane_base(session)
    champs = {**initial, 'mutation_id': str(uuid.uuid4())}
    assert post(client_crm, champs, autre).status_code == 400
    assert base._instantane_base(session) == avant


def test_champs_doubles_taille_type_et_url_fermes(monde, client_crm, session):
    connecter(client_crm)
    champs = formulaire(client_crm)
    avant = base._instantane_base(session)
    corps = urlencode(champs) + '&statut_declaration=retiree'
    r = client_crm.post(URL, content=corps, headers={'content-type': 'application/x-www-form-urlencoded'})
    assert r.status_code == 400
    assert post(client_crm, {**champs, 'csrf': 'x' * 31000}).status_code == 413
    assert client_crm.post(URL, json=champs).status_code == 415
    assert post(client_crm, champs, URL + '&debut=0').status_code == 400
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('personne', ['employe', 'nathan'])
def test_non_admin_ne_peut_utiliser_formulaire(monde, client_crm, session, personne):
    connecter(client_crm)
    champs = formulaire(client_crm)
    connecter(client_crm, personne)
    avant = base._instantane_base(session)
    assert client_crm.get(URL).status_code == 403
    assert post(client_crm, champs).status_code == 403
    assert base._instantane_base(session) == avant


def test_admin_revoque_ne_peut_rejouer_intention(monde, client_crm, session):
    connecter(client_crm)
    champs = formulaire(client_crm)
    assert post(client_crm, champs).status_code == 303
    with session() as cnx:
        identite.ajouter_role(cnx, w.g.AUTH.utilisateur, 'nathan_owner')
        identite.retirer_role(cnx, w.g.AUTH.utilisateur, 'admin')
    avant = base._instantane_base(session)
    assert post(client_crm, champs).status_code == 403
    assert base._instantane_base(session) == avant


def test_panne_audit_apres_append_annule_post(monde, client_crm, session, monkeypatch):
    from m4_field_ops import absences_ecriture

    connecter(client_crm)
    champs = formulaire(client_crm)
    avant = base._instantane_base(session)
    original = absences_ecriture.journaliser

    def panne(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('audit fictif indisponible')

    monkeypatch.setattr(absences_ecriture, 'journaliser', panne)
    assert post(client_crm, champs).status_code == 503
    assert base._instantane_base(session) == avant


def test_autorite_http_perdue_apres_retour_sdk_annule_post(monde, client_crm, session, monkeypatch):
    from opsys.console import metier

    connecter(client_crm)
    champs = formulaire(client_crm)
    avant = base._instantane_base(session)
    original = metier.executer

    def revoquer(cnx, *args, **kwargs):
        r = original(cnx, *args, **kwargs)
        assert r['resultat']['accepte'] is True
        identite.ajouter_role(cnx, w.g.AUTH.utilisateur, 'nathan_owner')
        identite.retirer_role(cnx, w.g.AUTH.utilisateur, 'admin')
        return r

    monkeypatch.setattr(metier, 'executer', revoquer)
    assert post(client_crm, champs).status_code == 403
    assert base._instantane_base(session) == avant
