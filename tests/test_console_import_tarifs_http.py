"""fictif: true — formulaire multipart réel vers préparation privée, aucun prix appliqué."""
import hashlib
import importlib
import importlib.util
import logging
from pathlib import Path

import pytest
from m6_material_control import fournisseurs

from opsys import identite, stockage
from opsys.console import journaux_http, metier, pages

spec = importlib.util.spec_from_file_location('price_import_http_fixture',
    Path(__file__).with_name('test_console_import_tarifs_m6.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
client_crm, catalogue, sources = p.client_crm, p.catalogue, p.sources
ROUTE = '/crm/materiaux/tarifs/importer'


def ui():
    return importlib.import_module('opsys.console.import_tarifs_ui')


def champs(client, **kw):
    base = dict(csrf=client.get('/api/session').json()['csrf'], fournisseur_id='fourn-fictif',
                source_document='liste-fictive.csv', separateur=';', source_attendue='')
    base.update({'mapping_' + k: v for k, v in p.MAPPING.items()})
    return dict(base, **kw)


def post(client, *, source=None, donnees=None):
    fichier = ('liste-fictive.csv', p.CSV.encode() if source is None else source, 'text/csv')
    return client.post(ROUTE, data=champs(client) if donnees is None else donnees, files={'source_csv': fichier})


def test_formulaire_et_vrai_csv_t0_ancien_prix_sans_aucune_ecriture(sources, session, catalogue):
    p.h.semer(session)
    formulaire = catalogue.get(ROUTE)
    assert formulaire.status_code == 200 and 'multipart/form-data' in formulaire.text
    assert 'mapping_materiau_id' in formulaire.text and 'Aucun prix appliqué' in formulaire.text
    assert 'value="SKU"' not in formulaire.text
    donnees = champs(catalogue)
    avant = p.h.p.c.m.base._instantane_base(session)
    source = ('\ufeff' + p.CSV.replace('\n', '\r\n')).encode()
    page = post(catalogue, source=source, donnees=donnees)
    assert page.status_code == 200, page.text
    for texte in ('15.500000', '14.0', 'Prix fourni', 'Prix précédent', 'A_REVOIR', hashlib.sha256(source).hexdigest()):
        assert texte in page.text
    assert 'NOTE-PRIVEE-FICTIVE' not in page.text and ROUTE + '/confirmer' in page.text
    assert page.headers['cache-control'] == 'no-store' and 'content-security-policy' in page.headers
    assert p.h.p.c.m.base._instantane_base(session) == avant
    assert ROUTE in catalogue.get('/crm/materiaux').text
    fiche = catalogue.get('/crm/fournisseurs/fourn-fictif')
    assert ROUTE in fiche.text and 'fournisseur_id=fourn-fictif' in fiche.text


def test_reference_et_nom_echappes_colonnes_libres_contacts_absents(sources, session, catalogue):
    with session():
        _, refus = fournisseurs.enregistrer_fournisseur('fourn-fictif', '<script>NOM-FICTIF</script>',
            '2026-01-02T00:00:00+00:00', stockage.maillons('m06-material-control', 'fournisseurs'),
            courriel_commande='CONTACT-PRIVE@example.test')
        assert refus is None
    page = post(catalogue, donnees=champs(catalogue, source_document='<script>DOC-FICTIF</script>'))
    assert page.status_code == 200
    assert '&lt;script&gt;NOM-FICTIF&lt;/script&gt;' in page.text
    assert '&lt;script&gt;DOC-FICTIF&lt;/script&gt;' in page.text and '<script>DOC-FICTIF' not in page.text
    assert 'CONTACT-PRIVE' not in page.text and 'NOTE-PRIVEE-FICTIVE' not in page.text


def test_csv_incoherent_et_erreur_metier_distincts(sources, catalogue):
    invalide = post(catalogue, source=b'colonnes absentes')
    assert invalide.status_code == 400 and 'colonnes absentes' not in invalide.text
    vue = post(catalogue, source=p.CSV.replace(';pi;', ';cm;').encode())
    assert vue.status_code == 200 and 'UNITE_CATALOGUE_DIFFERENTE' in vue.text


@pytest.mark.parametrize('cas', ['csrf', 'employee', 'owner'])
def test_autorite_et_csrf_avant_t0(sources, session, catalogue, monkeypatch, cas):
    data = champs(catalogue, csrf='faux' if cas == 'csrf' else catalogue.get('/api/session').json()['csrf'])
    if cas != 'csrf':
        p.h.p.c.m.base._connecter(catalogue, 'employe' if cas == 'employee' else 'nathan')

    def interdit(*a, **kw):
        raise AssertionError('T0 appelé après admission refusée')

    monkeypatch.setattr(metier, 'executer', interdit)
    assert post(catalogue, donnees=data).status_code == 403


def test_parametres_champs_et_taille_fermes(sources, catalogue):
    assert catalogue.get(ROUTE + '?inconnu=fictif').status_code == 400
    assert catalogue.get(ROUTE + '?fournisseur_id=a&fournisseur_id=b').status_code == 400
    assert catalogue.post(ROUTE, json={}).status_code == 415
    assert post(catalogue, donnees=champs(catalogue, surprise='fictif')).status_code == 400
    assert post(catalogue, source=b'x' * 1048577).status_code == 413
    assert post(catalogue, source=b'\xff').status_code == 400
    doublons = [(k, (None, v)) for k, v in champs(catalogue).items()]
    doublons += [('csrf', (None, 'autre')), ('source_csv', ('fictif.csv', p.CSV.encode(), 'text/csv'))]
    assert catalogue.post(ROUTE, files=doublons).status_code == 400


def test_stream_borne_avant_parser_sans_content_length(sources, catalogue):
    def corps():
        yield b'x' * (1048576 + 65536 + 1)

    r = catalogue.post(ROUTE, content=corps(), headers={'content-type': 'multipart/form-data; boundary=fictif'})
    assert r.status_code == 413


@pytest.mark.parametrize('cas', ['t0', 'source_apres_gabarit', 'admin_apres_gabarit', 'html'])
def test_pas_ancien_resultat_si_t0_source_ou_autorite_change(sources, session, catalogue, monkeypatch, cas):
    if cas == 't0':
        original = metier.executer

        def changer(cnx, deps, auth, nom, args, **kw):
            r = original(cnx, deps, auth, nom, args, **kw)
            if nom == p.NOM:
                r['resultat']['resultat']['lignes'][0]['preparation_saisie']['prix_unitaire_decimal'] = '999.99'
            return r

        monkeypatch.setattr(metier, 'executer', changer)
    else:
        original = pages.gabarit

        def rendre(*a, **kw):
            r = original(*a, **kw)
            cnx = stockage.connexion_courante()
            if cnx is not None:
                if cas == 'admin_apres_gabarit':
                    identite.retirer_role(cnx, 'admin.fictif', 'admin')
                elif cas == 'source_apres_gabarit':
                    _, refus = fournisseurs.enregistrer_fournisseur('autre-fictif', 'Autre FICTIF',
                        '2026-01-01T00:00:00+00:00', stockage.maillons('m06-material-control', 'fournisseurs'))
                    assert refus is None
                else:
                    r += 'x' * 131072
            return r

        monkeypatch.setattr(pages, 'gabarit', rendre)
    r = post(catalogue)
    assert r.status_code == (403 if cas == 'admin_apres_gabarit' else 503), r.text
    assert '15.500000' not in r.text and '999.99' not in r.text


@pytest.mark.parametrize('slash', ['', '/'])
def test_query_import_masquee_entierement(slash):
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 1, '',
        ('client', 'GET', '/prefix' + ROUTE + slash + '?fournisseur_id=SECRET-FICTIF&autre=PRIVE', '1.1', 200), None)
    assert journaux_http.MasquerRecherche().filter(record)
    assert 'SECRET-FICTIF' not in str(record.args) and 'PRIVE' not in str(record.args)
    assert record.args[-1] == 200 and '[MASQUE]' in record.args[2]


def test_curseur_invalide_400_et_source_perimee_409(sources, catalogue):
    assert post(catalogue, donnees=champs(catalogue, source_attendue='invalide')).status_code == 400
    perime = post(catalogue, donnees=champs(catalogue, source_attendue='a' * 64))
    assert perime.status_code == 409 and '15.500000' not in perime.text


@pytest.mark.parametrize('cas', ['admin', 'html'])
def test_get_revalide_autorite_et_borne_html_apres_gabarit(sources, catalogue, monkeypatch, cas):
    original = pages.gabarit

    def rendre(*a, **kw):
        r = original(*a, **kw)
        if cas == 'admin':
            identite.retirer_role(stockage.connexion_courante(), 'admin.fictif', 'admin')
        else:
            r += 'x' * 131072
        return r

    monkeypatch.setattr(pages, 'gabarit', rendre)
    assert catalogue.get(ROUTE).status_code == (403 if cas == 'admin' else 503)
