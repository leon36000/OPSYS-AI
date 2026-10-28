"""fictif: true — prix saisi en HTTP puis réellement utilisé dans une soumission."""
import importlib.util
from pathlib import Path
from urllib.parse import urlencode

import pytest

from opsys import identite, stockage


def charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, Path(__file__).with_name(fichier))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p = charger('fixture_prix_http_ports', 'test_console_prix_m6.py')
h = charger('fixture_prix_http_forms', 'test_console_catalogue_m6_http.py')
client_crm = p.client_crm
catalogue = p.catalogue
sources = p.sources
ROUTE = '/crm/materiaux/mat-fictif/tarifs'


def preparer(client, session, **kw):
    action, donnees = h.form(client.get(ROUTE), 'name="prix_unitaire"')
    assert donnees['prix_unitaire'] == donnees['date_effet'] == donnees['fournisseur_id'] == ''
    donnees.update({'fournisseur_id': 'fourn-fictif', 'prix_unitaire': '12.500001',
                    'date_effet': '2026-01-01', 'source_document': 'tarif-FICTIF.pdf', **kw})
    avant = p.c.m.base._instantane_base(session)
    page = client.post(action, data=donnees)
    assert page.status_code == 200, page.text
    assert p.c.m.base._instantane_base(session) == avant
    final, champs = h.form(page, 'name="tarif_empreinte"')
    return final, champs, page


def test_tarif_http_vers_soumission_et_ancien_devis_fige(sources, catalogue, session):
    action, donnees, page = preparer(catalogue, session)
    assert 'SOURCE_DECLAREE' in page.text and '12.500001' in page.text
    assert 'Premier tarif' in page.text
    r = catalogue.post(action, data=donnees, follow_redirects=False)
    assert r.status_code == 303, r.text
    stockage.liberer()
    avant = p.c.m.base._instantane_base(session)
    assert catalogue.post(action, data=donnees, follow_redirects=False).status_code == 303
    assert p.c.m.base._instantane_base(session) == avant
    modele = h.h.p.m.direct(session)['resultat']
    ancre = dict(modele_id=modele['modele_id'], modele_revision=modele['revision'], modele_source=modele['source_id'])
    lignes = h.h.p.appel(session, 'enregistrer_lignes_modele', dict(**ancre, revision_attendue=0,
                         lignes=[dict(ligne_id='fictif', description='Pose FICTIVE',
                                      materiau_id='mat-fictif', unite='pi')]))
    assert lignes['accepte'], lignes
    route = h.h.ROUTE + '?' + urlencode(ancre)
    a, choix = h.h.form(catalogue.get(route))
    choix.update(quantite_0='2', fournisseur_id_0='fourn-fictif', taux_marge='0.2')
    a, champs = h.h.form(catalogue.post(a, data=choix))
    assert catalogue.post(a, data=champs, follow_redirects=False).status_code == 303
    lien = '/crm/lead/lead-fictif-001/soumissions/' + champs['devis_id'] + '/document/html'
    document = catalogue.get(lien)
    assert document.status_code == 200 and '30.00' in document.text
    for prive in ('12.500001', 'fourn-fictif', 'tarif-FICTIF.pdf'):
        assert prive not in document.text
    a2, p2, page2 = preparer(catalogue, session, prix_unitaire='17')
    assert 'Prix actuellement utilisable' in page2.text
    assert '<strong>17</strong> CAD' in page2.text
    assert catalogue.post(a2, data=p2, follow_redirects=False).status_code == 303
    assert catalogue.get(lien).text == document.text
    assert catalogue.post(action, data=donnees, follow_redirects=False).status_code == 303
    with session():
        assert len(stockage.maillons('m06-material-control', 'livre_prix')) == 2


@pytest.mark.parametrize('cas', ['csrf', 'prix_perime', 'unite', 'devise', 'extra', 'fournisseur', 'corps'])
def test_confirmation_http_refuse_sans_effet(sources, catalogue, session, cas):
    action, donnees, _ = preparer(catalogue, session)
    if cas == 'csrf':
        donnees['csrf'] = 'faux'
    elif cas == 'prix_perime':
        nouveau = p.c.executer(session, p.CONFIRMER, p.preparer(session, prix_unitaire='14'), 'autre')
        assert nouveau['resultat']['accepte']
    elif cas == 'unite':
        donnees['unite'] = 'm'
    elif cas == 'devise':
        donnees['devise'] = 'USD'
    elif cas == 'extra':
        donnees['livre_prix_historique'] = '[]'
    elif cas == 'fournisseur':
        donnees['fournisseur_id'] = 'inconnu'
    avant = p.c.m.base._instantane_base(session)
    r = (catalogue.post(action, content=b'x'*131073, headers={'content-type': 'application/x-www-form-urlencoded'})
         if cas == 'corps' else catalogue.post(action, data=donnees))
    assert r.status_code in {400, 403, 404, 409, 413}, r.text
    assert p.c.m.base._instantane_base(session) == avant


def test_tarif_sans_source_est_fallback(sources, catalogue, session):
    a, donnees = h.form(catalogue.get(ROUTE), 'name="prix_unitaire"')
    donnees.update(fournisseur_id='fourn-fictif', prix_unitaire='0.000001', date_effet='2026-01-01')
    page = catalogue.post(a, data=donnees)
    assert 'FALLBACK_PRICE_BOOK' in page.text and 'Sans document source' in page.text
    a, donnees = h.form(page, 'name="tarif_empreinte"')
    assert catalogue.post(a, data=donnees, follow_redirects=False).status_code == 303
    with session():
        ligne, = list(stockage.maillons('m06-material-control', 'livre_prix'))
        assert ligne['source_document'] is None and ligne['prix_unitaire'] == 0.000001


def test_replay_revoque_refuse_et_materiau_inactif(sources, catalogue, session):
    a, donnees, _ = preparer(catalogue, session)
    assert catalogue.post(a, data=donnees, follow_redirects=False).status_code == 303
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = p.c.m.base._instantane_base(session)
    assert catalogue.post(a, data=donnees).status_code == 403
    assert catalogue.get(ROUTE).status_code == 403
    assert p.c.m.base._instantane_base(session) == avant


def test_sans_fournisseur_et_inactif_explicitement_signales(catalogue, session):
    assert p.c.direct(session)['accepte']
    page = catalogue.get(ROUTE)
    assert page.status_code == 200 and 'Aucun fournisseur sur cette page' in page.text
    assert 'name="prix_unitaire"' not in page.text
    assert p.c.direct(session, cle='inactif', valeur=p.c.args(revision_attendue=1, actif=False))['accepte']
    assert catalogue.get(ROUTE).status_code == 409


def test_reference_declaree_echappee_et_non_authentifiee(sources, catalogue, session):
    _, _, page = preparer(catalogue, session, source_document='<script>FICTIF</script>.pdf')
    assert '&lt;script&gt;FICTIF&lt;/script&gt;.pdf' in page.text
    assert '<script>FICTIF</script>' not in page.text
    assert 'SOURCE_DECLAREE' in page.text
