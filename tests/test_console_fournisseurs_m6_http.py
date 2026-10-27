"""fictif: true — fournisseur → matériau → tarif → devis par les formulaires HTTP."""
import html
import importlib.util
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from m6_material_control import fournisseurs

from opsys import identite, stockage

spec = importlib.util.spec_from_file_location('fixture_fournisseurs_http',
                                             Path(__file__).with_name('test_console_catalogue_m6_http.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
client_crm = h.client_crm
catalogue = h.catalogue
BASE = '/crm/fournisseurs'


def instantane(session):
    return h.h.p.m.base._instantane_base(session)


def creer(client, **kw):
    action, p = h.form(client.get(BASE))
    assert p['nom'] == p['telephone'] == p['courriel_commande'] == ''
    p.update(nom='Fournisseur FICTIF', telephone='+15145550142',
             courriel_commande='commandes@fournisseur-fictif.test', **kw)
    r = client.post(action, data=p, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r.headers['location'].removeprefix(h.h.p.m.base.PREFIXE), action, p


def test_fournisseur_materiau_tarif_modele_devis_http(catalogue, session):
    lien, action_creation, original = creer(catalogue)
    page = catalogue.get(lien)
    assert page.headers['cache-control'] == 'no-store'
    avant = instantane(session)
    assert catalogue.post(action_creation, data=original, follow_redirects=False).status_code == 303
    assert instantane(session) == avant
    materiau_lien, _, materiau = h.creer(catalogue)
    tarif_route = materiau_lien.split('?', 1)[0] + '/tarifs'
    page = catalogue.get(tarif_route)
    assert 'Créer ou corriger un fournisseur' in page.text
    assert original['fournisseur_id'] in page.text
    a, tarif = h.form(page, 'name="prix_unitaire"')
    tarif.update(fournisseur_id=original['fournisseur_id'], prix_unitaire='12.5',
                 date_effet='2026-01-01', source_document='prix-FOURNISSEUR-FICTIF.pdf')
    a, confirme = h.form(catalogue.post(a, data=tarif), 'name="tarif_empreinte"')
    assert catalogue.post(a, data=confirme, follow_redirects=False).status_code == 303
    a, modele = h.form(catalogue.get('/crm/modeles-soumission'), 'name="titre"')
    modele.update(titre='Pose FICTIVE', description='Travaux FICTIFS', clauses='Clause FICTIVE à réviser')
    r = catalogue.post(a, data=modele, follow_redirects=False)
    assert r.status_code == 303, r.text
    # L'identité, la révision et la source viennent de la redirection du vrai port M3.
    modele_lien = r.headers['location'].removeprefix(h.h.p.m.base.PREFIXE)
    modele_page = catalogue.get(modele_lien)
    lien_lignes = html.unescape(next(v for v in re.findall(r'href="([^"]+)"', modele_page.text)
                                    if '/lignes?' in v))
    ancre = {k: v[0] for k, v in parse_qs(urlsplit(lien_lignes).query).items()}
    page = catalogue.get('/crm/modeles-soumission/' + modele['modele_id'] + '/lignes/catalogue?' + urlencode(ancre))
    a, lignes = h.form(page, 'name="selection_0"')
    options = re.findall(r'<option value="([^"]+)">', page.text)
    lignes.update(description_0='Pose FICTIVE', selection_0=next(
        html.unescape(v) for v in options if v.startswith(materiau['materiau_id'] + '@')))
    assert catalogue.post(a, data=lignes, follow_redirects=False).status_code == 303
    a, choix = h.h.form(catalogue.get(h.h.ROUTE + '?' + urlencode(ancre)))
    choix.update(quantite_0='2', fournisseur_id_0=original['fournisseur_id'], taux_marge='0.2')
    a, confirme = h.h.form(catalogue.post(a, data=choix))
    r = catalogue.post(a, data=confirme, follow_redirects=False)
    assert r.status_code == 303, r.text
    document = catalogue.get(r.headers['location'].removeprefix(h.h.p.m.base.PREFIXE) + '/document/html')
    assert document.status_code == 200 and '30.00' in document.text
    for prive in (original['fournisseur_id'], original['nom'], original['courriel_commande'],
                  original['telephone'], 'prix-FOURNISSEUR-FICTIF.pdf', '12.5'):
        assert prive not in document.text


def test_revision_http_preserve_historique_et_rejeu(catalogue, session):
    ident = 'fournisseur-fictif-Québec'
    with session():
        _, refus = fournisseurs.enregistrer_fournisseur(ident, 'FICTIF', '2026-01-01T00:00:00+00:00',
            stockage.maillons('m06-material-control', 'fournisseurs'), telephone='+15145550142',
            categories_vendues=[f'Catégorie FICTIVE {i}' for i in range(26)], delai_habituel_jours=4000)
        assert refus is None
    lien = BASE + '/' + ident
    a, p = h.form(catalogue.get(lien))
    p.update(nom='Corrigé FICTIF <script>x</script>', nom_action='remplacer', telephone_action='effacer')
    assert catalogue.post(a, data=p, follow_redirects=False).status_code == 303
    stockage.liberer()
    avant = instantane(session)
    assert catalogue.post(a, data=p, follow_redirects=False).status_code == 303
    page = catalogue.get(lien)
    assert '&lt;script&gt;x&lt;/script&gt;' in page.text and '<script>x</script>' not in page.text
    assert instantane(session) == avant
    with session():
        f = fournisseurs.lire_fournisseur(stockage.maillons('m06-material-control', 'fournisseurs'), ident)
        assert f['telephone'] is None and f['delai_habituel_jours'] == 4000
        assert len(f['categories_vendues']) == 26


@pytest.mark.parametrize('cas', ['csrf', 'stale', 'extra', 'courriel', 'corps', 'revoque'])
def test_refus_http_sans_effet(catalogue, session, cas):
    lien, _, _ = creer(catalogue)
    a, p = h.form(catalogue.get(lien))
    p.update(nom='Autre FICTIF', nom_action='remplacer')
    if cas == 'csrf':
        p['csrf'] = 'faux'
    elif cas == 'stale':
        a2, p2 = h.form(catalogue.get(lien))
        p2.update(nom='Déjà corrigé FICTIF', nom_action='remplacer')
        assert catalogue.post(a2, data=p2, follow_redirects=False).status_code == 303
    elif cas == 'extra':
        p['categories_vendues'] = '[]'
    elif cas == 'courriel':
        p.update(courriel_commande='invalide', courriel_commande_action='remplacer')
    elif cas == 'revoque':
        with session() as cnx:
            identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = instantane(session)
    r = (catalogue.post(a, content=b'x'*131073, headers={'content-type': 'application/x-www-form-urlencoded'})
         if cas == 'corps' else catalogue.post(a, data=p))
    assert r.status_code in {400, 403, 409, 413}, r.text
    assert instantane(session) == avant


def test_acces_et_liste_ne_divulguent_pas_contacts(client_crm, catalogue, session):
    lien, a, p = creer(catalogue)
    page = catalogue.get(BASE)
    assert p['nom'] in page.text and p['courriel_commande'] not in page.text
    for utilisateur in ('employe', 'nathan'):
        h.h.p.m.base._connecter(client_crm, utilisateur)
        avant = instantane(session)
        assert client_crm.get(BASE).status_code == 403
        assert client_crm.get(lien).status_code == 403
        assert client_crm.post(a, data=p).status_code == 403
        assert instantane(session) == avant


def test_confirmation_tarif_refuse_si_fournisseur_corrige(catalogue, session):
    lien, _, fournisseur = creer(catalogue)
    materiau, _, _ = h.creer(catalogue)
    a, p = h.form(catalogue.get(materiau.split('?', 1)[0] + '/tarifs'), 'name="prix_unitaire"')
    p.update(fournisseur_id=fournisseur['fournisseur_id'], prix_unitaire='12.5', date_effet='2026-01-01')
    a, confirme = h.form(catalogue.post(a, data=p), 'name="tarif_empreinte"')
    a2, revision = h.form(catalogue.get(lien))
    revision.update(telephone='+15145550143', telephone_action='remplacer')
    assert catalogue.post(a2, data=revision, follow_redirects=False).status_code == 303
    avant = instantane(session)
    assert catalogue.post(a, data=confirme).status_code == 409
    assert instantane(session) == avant


def test_contacts_historiques_conserves_malgre_normalisation_navigateur(catalogue, session):
    with session():
        _, refus = fournisseurs.enregistrer_fournisseur('ancien-fictif', 'FICTIF',
            '2026-01-01T00:00:00+00:00', stockage.maillons('m06-material-control', 'fournisseurs'),
            telephone='514\n5550142', courriel_commande='ancien\r\nformat FICTIF')
        assert refus is None
    a, p = h.form(catalogue.get(BASE + '/ancien-fictif'))
    assert p['telephone_action'] == p['courriel_commande_action'] == 'conserver'
    p.update(nom='Nom corrigé FICTIF', nom_action='remplacer', telephone='5145550142',
             courriel_commande='ancienformat FICTIF')
    assert catalogue.post(a, data=p, follow_redirects=False).status_code == 303
    with session():
        fiche = fournisseurs.lire_fournisseur(
            stockage.maillons('m06-material-control', 'fournisseurs'), 'ancien-fictif')
        assert fiche['telephone'] == '514\n5550142'
        assert fiche['courriel_commande'] == 'ancien\r\nformat FICTIF'
