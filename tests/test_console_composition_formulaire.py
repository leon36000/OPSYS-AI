"""fictif: true — vrais formulaires humains, CSRF et historique durable de composition."""
import importlib.util
import re
from html import unescape
from pathlib import Path
from urllib.parse import urlencode

import pytest

from opsys import equipes as equipes_entreprise
from opsys import identite
from opsys.stockage.schema import JOURNAL, REGISTRES

spec = importlib.util.spec_from_file_location('composition_form_fixture',
    Path(__file__).with_name('test_console_composition_ecriture.py'))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
client_crm, monde, planning = w.client_crm, w.monde, w.planning
base = w.base
FICTIF = True
URL = '/crm/journal-equipes/composition?jour=2030-06-03&equipe_id=eq-a'


def connecter(client, personne='admin.fictif'):
    base._connecter(client, personne)


def formulaire(client, statut='declaree'):
    r = client.get(URL)
    assert r.status_code == 200, r.text
    formes = re.findall(r'<form\b.*?</form>', r.text, re.S)
    bloc = next(x for x in formes if f'name="statut_declaration" value="{statut}"' in x)
    champs = {k: unescape(v) for k, v in re.findall(r'name="([^"]+)" value="([^"]*)"', bloc)}
    texte = re.search(r'<textarea[^>]*name="membres"[^>]*>(.*?)</textarea>', bloc, re.S)
    if texte:
        champs['membres'] = unescape(texte[1])
    assert set(champs) == {'csrf', 'membres', 'revision_attendue', 'mutation_id', 'statut_declaration'}
    return champs


def post(client, champs, url=URL):
    return client.post(url, data=champs, follow_redirects=False)


def test_formulaire_reel_declaration_correction_retrait_redeclaration_et_rejeu(planning, monde, session, client_crm):
    connecter(client_crm)
    avant = dict(base._instantane_base(session))
    profil = equipes_entreprise.fichier_profil().read_bytes()
    initial = formulaire(client_crm)
    assert initial['revision_attendue'] == '0' and initial['membres'] == ''
    initial['membres'] = 'employe\nequipier.inactif'
    r = post(client_crm, initial)
    assert r.status_code == 303, r.text
    assert r.headers['location'].removeprefix(base.PREFIXE) == URL
    page = client_crm.get(URL)
    assert 'equipier.inactif' in page.text and 'Révision 1' in page.text
    stable = base._instantane_base(session)
    assert post(client_crm, initial).status_code == 303
    assert base._instantane_base(session) == stable
    autre = {**initial, 'membres': 'employe'}
    assert post(client_crm, autre).status_code == 409
    correction = formulaire(client_crm)
    correction['membres'] = ''
    assert post(client_crm, correction).status_code == 303
    assert 'Liste déclarée explicitement vide' in client_crm.get(URL).text
    retrait = formulaire(client_crm, 'retiree')
    assert retrait['membres'] == '' and post(client_crm, retrait).status_code == 303
    page = client_crm.get(URL)
    assert 'Déclaration retirée; composition inconnue' in page.text
    nouvelle = formulaire(client_crm)
    assert nouvelle['revision_attendue'] == '3' and nouvelle['membres'] == ''
    nouvelle['membres'] = 'employe'
    assert post(client_crm, nouvelle).status_code == 303
    page = client_crm.get(URL)
    assert all('Révision ' + str(i) in page.text for i in range(1, 5))
    assert post(client_crm, initial).status_code == 303
    assert formulaire(client_crm)['membres'] == 'employe'
    assert len(w.lignes(session)) == 4
    apres = dict(base._instantane_base(session))
    for table in avant:
        if table not in {REGISTRES.name, JOURNAL.name}:
            assert avant[table] == apres[table], table
    assert equipes_entreprise.fichier_profil().read_bytes() == profil


@pytest.mark.parametrize('modif', [{'csrf': 'faux'}, {'revision_attendue': '00'}, {'mutation_id': 'faux'},
    {'membres': 'personne.inconnue'}, {'membres': 'employe\nemploye'}, {'membres': ' employe'},
    {'auteur': 'autre.admin'}, {'horodatage': '2030-01-01T00:00:00+00:00'}])
def test_formulaire_malforme_non_signe_ou_identites_inconnues_refuses(monde, client_crm, session, modif):
    connecter(client_crm)
    champs = {**formulaire(client_crm), 'membres': 'employe', **modif}
    avant = base._instantane_base(session)
    r = post(client_crm, champs)
    assert r.status_code in {400, 403}, r.text
    assert base._instantane_base(session) == avant


def test_champs_doubles_taille_type_et_url_fermes(monde, client_crm, session):
    connecter(client_crm)
    champs = {**formulaire(client_crm), 'membres': 'employe'}
    avant = base._instantane_base(session)
    corps = urlencode(champs) + '&membres=autre.fictif'
    r = client_crm.post(URL, content=corps, headers={'content-type': 'application/x-www-form-urlencoded'})
    assert r.status_code == 400
    assert post(client_crm, {**champs, 'membres': 'x' * 13000}).status_code == 413
    assert client_crm.post(URL, json=champs).status_code == 415
    assert post(client_crm, champs, URL + '&debut=0').status_code == 400
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('personne', ['employe', 'nathan'])
def test_formulaire_non_admin_et_rejeu_revoque_necrivent_pas(monde, client_crm, session, personne):
    connecter(client_crm)
    champs = {**formulaire(client_crm), 'membres': 'employe'}
    connecter(client_crm, personne)
    avant = base._instantane_base(session)
    assert client_crm.get(URL).status_code == 403
    assert post(client_crm, champs).status_code == 403
    assert base._instantane_base(session) == avant


def test_rejeu_admin_revoque_et_revision_concurrente(monde, client_crm, session):
    connecter(client_crm)
    premier = {**formulaire(client_crm), 'membres': 'employe'}
    concurrent = {**formulaire(client_crm), 'membres': ''}
    assert post(client_crm, premier).status_code == 303
    avant = base._instantane_base(session)
    assert post(client_crm, concurrent).status_code == 409
    assert base._instantane_base(session) == avant
    with session() as cnx:
        identite.ajouter_role(cnx, w.g.AUTH.utilisateur, 'nathan_owner')
        identite.retirer_role(cnx, w.g.AUTH.utilisateur, 'admin')
    avant = base._instantane_base(session)
    assert post(client_crm, premier).status_code == 403
    assert base._instantane_base(session) == avant


def test_equipe_supprimee_autorise_correction_historique_mais_pas_premiere_declaration(monde, client_crm, session):
    connecter(client_crm)
    premier = {**formulaire(client_crm), 'membres': 'employe'}
    assert post(client_crm, premier).status_code == 303
    equipes_entreprise.enregistrer_equipes(w.profil(('eq-b',)), par=w.g.AUTH.utilisateur)
    correction = formulaire(client_crm)
    correction['membres'] = ''
    assert post(client_crm, correction).status_code == 303
    autre = '/crm/journal-equipes/composition?jour=2030-06-07&equipe_id=eq-a'
    r = client_crm.get(autre)
    assert r.status_code == 200 and 'Déclaration initiale indisponible' in r.text
    assert 'name="statut_declaration"' not in r.text


@pytest.mark.parametrize('separateur', ['\v', '\x1c', '\u2028'])
def test_controles_non_silencieusement_transformes_en_deux_membres(monde, client_crm, session, separateur):
    connecter(client_crm)
    champs = {**formulaire(client_crm), 'membres': 'employe' + separateur + 'equipier.inactif'}
    avant = base._instantane_base(session)
    assert post(client_crm, champs).status_code == 400
    assert base._instantane_base(session) == avant


def test_erreur_audit_apres_append_http_annule_declaration_et_journal(monde, client_crm, session, monkeypatch):
    from m4_field_ops import composition_ecriture

    connecter(client_crm)
    champs = {**formulaire(client_crm), 'membres': 'employe'}
    avant = base._instantane_base(session)
    original = composition_ecriture.journaliser

    def erreur(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('audit fictif indisponible')

    monkeypatch.setattr(composition_ecriture, 'journaliser', erreur)
    assert post(client_crm, champs).status_code == 503
    assert base._instantane_base(session) == avant


def test_retrait_ne_cache_pas_une_liste_et_crlf_accepte(monde, client_crm, session):
    connecter(client_crm)
    champs = {**formulaire(client_crm), 'membres': 'employe\r\nequipier.inactif\r\n'}
    assert post(client_crm, champs).status_code == 303
    retrait = {**formulaire(client_crm, 'retiree'), 'membres': 'employe'}
    avant = base._instantane_base(session)
    assert post(client_crm, retrait).status_code == 400
    assert base._instantane_base(session) == avant
