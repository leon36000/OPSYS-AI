"""fictif: true — vrais écrivains, T0 et GET; aucune connexion fournisseur."""
import html
import importlib
import importlib.util
import logging
import re
from pathlib import Path
from urllib.parse import urlencode

import pytest
from m6_material_control import fournisseurs, livre_prix
from sqlalchemy import select

from opsys import identite, stockage
from opsys.console import journaux_http, metier, pages
from opsys.stockage.schema import REGISTRES

spec = importlib.util.spec_from_file_location('price_history_http_fixture',
    Path(__file__).with_name('test_console_historique_prix_m6.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
client_crm, catalogue, sources = h.client_crm, h.catalogue, h.sources
ROUTE = '/crm/materiaux/mat-fictif/tarifs/historique'


def ui():
    return importlib.import_module('opsys.console.historique_tarifs_ui')


def get(client, **options):
    return client.get(ROUTE, params=dict(fournisseur_id='fourn-fictif', **options))


def suivant(page):
    liens = re.findall(r'<a href="([^"]+)">Page suivante</a>', page.text)
    assert len(liens) == 1
    return html.unescape(liens[0]).removeprefix(h.p.c.m.base.PREFIXE)


def test_vrai_get_pagine_source_et_lecture_sans_effet(sources, session, catalogue):
    h.semer(session)
    avant = h.p.c.m.base._instantane_base(session)
    page = get(catalogue, limite=1)
    assert page.status_code == 200, page.text
    assert '12.500001' in page.text and '14.0' not in page.text
    assert 'noms actuels' in page.text and 'Fournisseur FICTIF' in page.text
    assert page.headers['cache-control'] == 'no-store' and 'content-security-policy' in page.headers
    assert 'Dernière écriture' in page.text and 'Date commerciale déclarée' in page.text
    suite = catalogue.get(suivant(page))
    assert suite.status_code == 200 and '14.0' in suite.text and '2025-01-01' in suite.text
    assert 'Page suivante</a>' not in suite.text and 'prix utilisable' in suite.text
    assert h.p.c.m.base._instantane_base(session) == avant


def test_choix_explicite_sans_livre_et_lien_fiche_historique(sources, session, catalogue, monkeypatch):
    def interdit(*a, **kw):
        raise AssertionError('livre lu sans fournisseur choisi')

    monkeypatch.setattr(h.module(), 'capturer', interdit)
    choix = catalogue.get(ROUTE)
    assert choix.status_code == 200 and 'Choisir explicitement' in choix.text
    assert 'fourn-fictif' in choix.text and '25 premiers' in choix.text and '/crm/fournisseurs' in choix.text
    r = h.p.c.executer(session, h.p.c.ECRIRE, h.p.c.args(revision_attendue=1, actif=False), 'inactif-http-fictif')
    assert r['resultat']['accepte']
    for suffixe in ('', '?version=1'):
        page = catalogue.get('/crm/materiaux/mat-fictif' + suffixe)
        assert page.status_code == 200 and ROUTE in page.text


@pytest.mark.parametrize('query', [
    'fournisseur_id=fourn-fictif&fournisseur_id=autre', 'inconnu=x', 'debut=1',
    'fournisseur_id=fourn-fictif&debut=1', 'fournisseur_id=fourn-fictif&limite=51',
    'fournisseur_id=fourn-fictif&source_attendue=xxx', 'fournisseur_id=%0A',
    'fournisseur_id=fourn-fictif&debut=-1', 'limite=1',
])
def test_parametres_fermes(sources, catalogue, query):
    assert catalogue.get(ROUTE + '?' + query).status_code == 400


def test_source_perimee_409_et_couple_vide_distinct_page_terminale(sources, session, catalogue):
    h.semer(session)
    premier = get(catalogue, limite=1)
    suite = suivant(premier)
    with session():
        _, refus = livre_prix.enregistrer_prix('autre.fictif', 'fourn-fictif', 33, 'CAD', '2026-01-01',
            stockage.maillons('m06-material-control', 'livre_prix'), unite='pi')
        assert refus is None
    perime = catalogue.get(suite)
    assert perime.status_code == 409 and 'Recommencer' in perime.text and '12.500001' not in perime.text
    vide = catalogue.get(ROUTE, params={'fournisseur_id': 'inconnu-fictif'})
    assert vide.status_code == 200 and 'Aucun tarif enregistré pour ce couple exact' in vide.text
    courant = get(catalogue)
    source = re.search(r'Source du couple : ([0-9a-f]{64})', courant.text).group(1)
    terminale = get(catalogue, debut=2, source_attendue=source)
    assert terminale.status_code == 200 and 'Fin des versions' in terminale.text
    assert 'Aucun tarif enregistré pour ce couple exact' not in terminale.text


def test_declares_echappes_sans_conversion_contacts_ou_lien_document(sources, session, catalogue):
    with session():
        _, refus = livre_prix.enregistrer_prix('mat-fictif', 'fourn-fictif', 7.1, 'USD', 'ancienne date',
            stockage.maillons('m06-material-control', 'livre_prix'), source_document='<script>DOC-FICTIF</script>')
        assert refus is None
    page = get(catalogue)
    assert page.status_code == 200
    for texte in ('7.1', 'USD', 'UNITE_NON_DOCUMENTEE', 'DATE_NON_ISO_DECLAREE', 'SOURCE_DECLAREE'):
        assert texte in page.text
    assert '&lt;script&gt;DOC-FICTIF&lt;/script&gt;' in page.text
    assert '<script>DOC-FICTIF</script>' not in page.text and 'mailto:' not in page.text


@pytest.mark.parametrize('cas', ['t0', 'corruption', 'apres_rendu_source', 'apres_rendu_admin', 'quota_html'])
def test_frontieres_sans_ancien_prix(sources, session, catalogue, monkeypatch, cas):
    h.semer(session)
    if cas == 't0':
        original = metier.executer

        def alterer(cnx, deps, auth, nom, args, **kw):
            r = original(cnx, deps, auth, nom, args, **kw)
            if nom == h.NOM:
                r['resultat']['resultat']['lignes'][0]['prix_unitaire_decimal'] = '999.99'
            return r

        monkeypatch.setattr(metier, 'executer', alterer)
    elif cas == 'corruption':
        with session():
            stockage.maillons('m06-material-control', 'livre_prix').append(dict(materiau_id='autre',
                fournisseur_id='fourn-fictif', prix_unitaire=True, devise='CAD', date_effet='2026-01-01'))
    else:
        original = ui().contenu

        def rendre(*a, **kw):
            r = original(*a, **kw)
            cnx = stockage.connexion_courante()
            if cas == 'apres_rendu_admin':
                identite.retirer_role(cnx, 'admin.fictif', 'admin')
            elif cas == 'apres_rendu_source':
                condition = (REGISTRES.c.departement == 'm06-material-control') & (REGISTRES.c.registre == 'livre_prix')
                ligne = cnx.execute(select(REGISTRES).where(condition).limit(1)).mappings().one()
                cnx.execute(REGISTRES.update().where(condition & (REGISTRES.c.rang == ligne['rang']))
                            .values(cree_le=ligne['cree_le'].replace(year=2020)))
            else:
                r += 'x' * 131072
            return r

        monkeypatch.setattr(ui(), 'contenu', rendre)
    page = get(catalogue)
    assert page.status_code == (403 if cas == 'apres_rendu_admin' else 503), page.text
    assert '12.500001' not in page.text and '999.99' not in page.text


@pytest.mark.parametrize('registre', ['fournisseurs', 'livre_prix'])
def test_quota_source_avant_decodage(sources, session, catalogue, monkeypatch, registre):
    h.semer(session)
    if registre == 'fournisseurs':
        monkeypatch.setattr(ui().lecture, 'MAX_SOURCE_OCTETS', 0)
        cible, nom = ui(), 'copier_maillons_avec_metadonnees'
    else:
        monkeypatch.setattr(h.historique_prix, 'MAX_OCTETS', 0)
        cible, nom = h.module(), 'copier_maillons_avec_metadonnees'

    def interdit(*a, **kw):
        raise AssertionError('décodage après quota')

    monkeypatch.setattr(cible, nom, interdit)
    assert get(catalogue).status_code == 503


def test_autorite_admin_et_post_absent(sources, session, catalogue):
    assert catalogue.post(ROUTE).status_code == 405
    h.p.c.m.base._connecter(catalogue, 'employe')
    assert get(catalogue).status_code == 403
    h.p.c.m.base._connecter(catalogue, 'nathan')
    assert get(catalogue).status_code == 403


def test_nom_legacy_long_autre_fournisseur_ne_bloque_pas_livre(sources, session, catalogue):
    h.semer(session)
    with session():
        _, refus = fournisseurs.enregistrer_fournisseur('ancien-fictif', 'FICTIF-' + 'é' * 201,
            '2026-01-01T00:00:00+00:00', stockage.maillons('m06-material-control', 'fournisseurs'),
            courriel_commande='CONTACT-SECRET@example.test', telephone='TELEPHONE-SECRET')
        assert refus is None
    page = get(catalogue)
    assert page.status_code == 200, page.text
    assert '12.500001' in page.text and 'é' * 201 in page.text
    assert 'CONTACT-SECRET' not in page.text and 'TELEPHONE-SECRET' not in page.text


def test_plus_de_25_noms_aucune_selection_forcee_et_reference_historique(sources, session, catalogue):
    with session():
        for i in range(26):
            _, refus = fournisseurs.enregistrer_fournisseur(f'aaa-fictif-{i:02}', 'Nom FICTIF',
                '2026-01-01T00:00:00+00:00', stockage.maillons('m06-material-control', 'fournisseurs'))
            assert refus is None
        _, refus = livre_prix.enregistrer_prix('mat-fictif', 'historique-sans-fiche', 18, 'USD', '2026-01-01',
            stockage.maillons('m06-material-control', 'livre_prix'), unite='autre')
        assert refus is None
    choix = catalogue.get(ROUTE)
    assert choix.status_code == 200 and 'value="aaa-fictif-24"' in choix.text
    assert 'value="aaa-fictif-25"' not in choix.text and 'value="fourn-fictif"' not in choix.text
    historique = catalogue.get(ROUTE, params={'fournisseur_id': 'historique-sans-fiche'})
    assert historique.status_code == 200 and '18 USD' in historique.text
    assert 'FALLBACK_PRICE_BOOK' in historique.text and 'historique-sans-fiche' in historique.text


@pytest.mark.parametrize('cas', ['fournisseurs', 'expire', 'quota_json', 'type_t0'])
def test_frontieres_complementaires(sources, session, catalogue, monkeypatch, cas):
    h.semer(session)
    if cas == 'type_t0':
        original = metier.executer

        def t0(cnx, deps, auth, nom, args, **kw):
            r = original(cnx, deps, auth, nom, args, **kw)
            if nom == 'm6_lister_fournisseurs_console':
                r['resultat']['resultat']['total'] = True  # True == 1 ne suffit pas.
            return r

        monkeypatch.setattr(metier, 'executer', t0)
    elif cas == 'quota_json':
        monkeypatch.setattr(ui().lecture, 'MAX_SORTIE_OCTETS', 10)
    else:
        original = pages.gabarit

        def rendre(*a, **kw):
            r = original(*a, **kw)
            cnx = stockage.connexion_courante()
            if cnx is not None:
                if cas == 'expire':
                    # Le contrôle final doit relire l’objet session fourni au rendu réel.
                    object.__setattr__(kw['session'], 'expire', 1)
                else:
                    _, refus = fournisseurs.enregistrer_fournisseur('fourn-fictif', 'Nouveau FICTIF',
                        '2026-01-02T00:00:00+00:00', stockage.maillons('m06-material-control', 'fournisseurs'))
                    assert refus is None
            return r

        monkeypatch.setattr(pages, 'gabarit', rendre)
    page = get(catalogue)
    assert page.status_code == (403 if cas == 'expire' else 503), page.text
    assert '12.500001' not in page.text


@pytest.mark.parametrize('suffixe', ['', '/'])
def test_query_logs_privee_entiere(suffixe):
    cible = '/prefix' + ROUTE + suffixe + '?' + urlencode(
        dict(fournisseur_id='SECRET-FICTIF', source_attendue='CURSOR'))
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 1, '',
                              ('client', 'GET', cible, '1.1', 200), None)
    assert journaux_http.MasquerRecherche().filter(record)
    assert 'SECRET-FICTIF' not in str(record.args) and 'CURSOR' not in str(record.args)
    assert record.args[-1] == 200 and '[MASQUE]' in record.args[2]
