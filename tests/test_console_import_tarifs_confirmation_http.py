"""fictif: true — vraie revue multipart → confirmation privée et reçu historique sans doublon."""
import importlib.util
import logging
from html.parser import HTMLParser
from pathlib import Path

import pytest

from opsys import identite, stockage
from opsys.console import journaux_http, metier, pages
from opsys.stockage import codec
from opsys.stockage.schema import MUTATIONS_APPLIQUEES

spec = importlib.util.spec_from_file_location('batch_import_http_fixture',
    Path(__file__).with_name('test_console_import_tarifs_http.py'))
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
client_crm, catalogue, sources = u.client_crm, u.catalogue, u.sources
ROUTE = u.ROUTE + '/confirmer'
CSV = u.p.CSV + 'soffite-fictif;pi;2.50;CAD;2026-01-01;note-fictive\n'
NOM = 'm6_confirmer_import_tarifs_console'


class Formulaires(HTMLParser):
    def __init__(self, texte):
        super().__init__()
        self.formulaires = []
        self.courant = None
        self.feed(texte)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.courant = dict(action=attrs.get('action'), champs={})
            self.formulaires.append(self.courant)
        elif self.courant is not None and tag in {'input', 'button'} and 'name' in attrs and 'value' in attrs:
            self.courant['champs'][attrs['name']] = attrs['value']

    def handle_endtag(self, tag):
        if tag == 'form':
            self.courant = None


def preparer(catalogue, session, **options):
    c = u.p.h.p.c
    assert c.executer(session, c.ECRIRE, c.args(materiau_id='soffite-fictif', nom='Soffite FICTIF'),
                      'seconde-fictive')['resultat']['accepte']
    page = u.post(catalogue, source=CSV.encode(), donnees=u.champs(catalogue, **options))
    assert page.status_code == 200, page.text
    forms = [f for f in Formulaires(page.text).formulaires if f['action'].endswith(ROUTE)]
    assert len(forms) == 1, 'formulaire explicite de confirmation lot absent'
    return forms[0]['champs'], page


def confirmer(catalogue, donnees, source=CSV):
    return catalogue.post(ROUTE, data=donnees, files={'source_csv': ('fictif.csv', source.encode(), 'text/csv')})


def instantane(session):
    return u.p.h.p.c.m.base._instantane_base(session)


def test_aperçu_confirme_deux_tarifs_et_rejoue_recu_historique_apres_prix_ulterieur(sources, session, catalogue):
    donnees, page = preparer(catalogue, session)
    assert 'NOTE-PRIVEE-FICTIVE' not in page.text and 'note-fictive' not in page.text
    assert 'source_csv_utf8' not in donnees and 'preparation_attendue' in donnees
    with session():
        assert len(stockage.maillons('m06-material-control', 'livre_prix')) == 0
    confirme = confirmer(catalogue, donnees)
    assert confirme.status_code == 200, confirme.text
    assert 'Reçu de confirmation' in confirme.text and '15.500000' in confirme.text and '2.50' in confirme.text
    assert not any(f['action'].endswith(ROUTE) for f in Formulaires(confirme.text).formulaires)
    assert 'NOTE-PRIVEE-FICTIVE' not in confirme.text and 'NOTE-PRIVEE-FICTIVE' not in str(instantane(session))
    assert confirme.headers['cache-control'] == 'no-store' and 'content-security-policy' in confirme.headers
    with session():
        assert len(stockage.maillons('m06-material-control', 'livre_prix')) == 2
        assert len(stockage.maillons('m06-material-control', 'receptions_tarifs')) == 2
    c = u.p.h.p.c
    suivant = u.p.h.p.preparer(session, prix_unitaire='19.00')
    assert c.executer(session, u.p.h.p.CONFIRMER, suivant, 'ulterieur-fictif')['resultat']['accepte']
    avant = instantane(session)
    stockage.liberer()
    rejoue = confirmer(catalogue, donnees)
    assert rejoue.status_code == 200 and rejoue.text == confirme.text
    assert instantane(session) == avant


@pytest.mark.parametrize('cas', ['csrf', 'employee', 'owner'])
def test_acces_et_csrf_avant_t1(sources, session, catalogue, monkeypatch, cas):
    donnees, _ = preparer(catalogue, session)
    if cas == 'csrf':
        donnees['csrf'] = 'faux'
    else:
        u.p.h.p.c.m.base._connecter(catalogue, 'employe' if cas == 'employee' else 'nathan')
    avant = instantane(session)

    def interdit(*args, **kw):
        raise AssertionError('outil appelé après refus accès/CSRF')

    monkeypatch.setattr(metier, 'executer', interdit)
    assert confirmer(catalogue, donnees).status_code == 403
    assert instantane(session) == avant


@pytest.mark.parametrize('cas', ['nonce', 'action', 'fichier', 'mapping', 'source', 'preparation'])
def test_intention_modifiee_refuse_sans_ecriture(sources, session, catalogue, cas):
    donnees, _ = preparer(catalogue, session)
    source = CSV
    if cas == 'nonce':
        donnees['mutation_id'] = 'invalide'
    elif cas == 'action':
        donnees['approbation'] = 'automatique'
    elif cas == 'fichier':
        source = CSV.replace('15.500000', '12.50')
    elif cas == 'mapping':
        donnees['mapping_materiau_id'] = 'Note'
    else:
        donnees['source_attendue' if cas == 'source' else 'preparation_attendue'] = '0' * 64
    avant = instantane(session)
    assert confirmer(catalogue, donnees, source).status_code in {400, 409}
    assert instantane(session) == avant


@pytest.mark.parametrize('cas', ['resultat', 'admin_apres_gabarit', 'expiration', 'recu', 'html'])
def test_rollback_y_compris_apres_rendu(sources, session, catalogue, monkeypatch, cas):
    donnees, _ = preparer(catalogue, session)
    avant = instantane(session)
    if cas == 'resultat':
        original = metier.executer

        def alterer(cnx, deps, auth, nom, arguments, **kw):
            r = original(cnx, deps, auth, nom, arguments, **kw)
            if nom == NOM:
                r['resultat']['resultat']['tarifs'][0]['prix_unitaire_decimal'] = '999.99'
            return r

        monkeypatch.setattr(metier, 'executer', alterer)
    else:
        original = pages.gabarit

        def rendre(*args, **kw):
            r = original(*args, **kw)
            cnx = stockage.connexion_courante()
            if cnx is not None:
                if cas == 'admin_apres_gabarit':
                    identite.retirer_role(cnx, 'admin.fictif', 'admin')
                elif cas == 'expiration':
                    object.__setattr__(kw['session'], 'expire', 0)
                elif cas == 'recu':
                    condition = MUTATIONS_APPLIQUEES.c.cle_idempotence == donnees['mutation_id']
                    cnx.execute(MUTATIONS_APPLIQUEES.update().where(condition)
                                .values(reponse=codec.encoder(dict(ok=True, resultat={}))))
                else:
                    r += 'x' * 131072
            return r

        monkeypatch.setattr(pages, 'gabarit', rendre)
    r = confirmer(catalogue, donnees)
    assert r.status_code == (403 if cas in {'admin_apres_gabarit', 'expiration'} else 503), r.text
    assert '15.500000' not in r.text and '999.99' not in r.text
    assert instantane(session) == avant


@pytest.mark.parametrize('slash', ['', '/'])
def test_query_confirmation_privee_masquee(slash):
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 1, '',
        ('client', 'POST', '/prefix' + ROUTE + slash + '?n=SECRET-FICTIF', '1.1', 200), None)
    assert journaux_http.MasquerRecherche().filter(record)
    assert 'SECRET-FICTIF' not in str(record.args) and '[MASQUE]' in record.args[2]


def test_formulaire_partiellement_invalide_ne_propose_pas_confirmation(sources, session, catalogue):
    avant = instantane(session)
    r = u.post(catalogue, source=u.p.CSV.replace(';pi;', ';cm;').encode())
    assert r.status_code == 200 and 'UNITE_CATALOGUE_DIFFERENTE' in r.text
    assert not any(f['action'].endswith(ROUTE) for f in Formulaires(r.text).formulaires)
    assert instantane(session) == avant


def test_reference_document_echappee_et_aucun_csv_cache_ou_persiste(sources, session, catalogue):
    document = '<img src=x onerror=alert(1)>FICTIF'
    donnees, page = preparer(catalogue, session, source_document=document)
    assert document not in page.text and '&lt;img' in page.text
    assert document == donnees['source_document']
    assert 'NOTE-PRIVEE-FICTIVE' not in str(donnees)
    r = confirmer(catalogue, donnees)
    assert r.status_code == 200 and document not in r.text and '&lt;img' in r.text
    assert 'NOTE-PRIVEE-FICTIVE' not in str(instantane(session))


def test_refus_deuxieme_enfant_annule_la_premiere_ligne_http(sources, session, catalogue, monkeypatch):
    from m6_material_control import prix_console

    donnees, _ = preparer(catalogue, session)
    avant = instantane(session)
    original = prix_console.confirmer
    appels = []

    def refuser(**kw):
        appels.append(True)
        return original(**kw) if len(appels) == 1 else dict(accepte=False, raison='SOURCE-MODIFIEE')

    monkeypatch.setattr(prix_console, 'confirmer', refuser)
    assert confirmer(catalogue, donnees).status_code == 409
    assert len(appels) == 2 and instantane(session) == avant


def test_parser_confirmation_ferme_media_duplicates_queries_et_octets(sources, session, catalogue):
    donnees, _ = preparer(catalogue, session)
    avant = instantane(session)
    assert catalogue.get(ROUTE).status_code in {404, 405}
    assert catalogue.post(ROUTE, json={}).status_code == 415
    assert confirmer(catalogue, dict(donnees, surprise='FICTIF')).status_code == 400
    assert confirmer(catalogue, dict(donnees, approbation='')).status_code == 400
    assert confirmer(catalogue, donnees, 'x' * 1048577).status_code == 413
    assert catalogue.post(ROUTE + '?sensible=FICTIF', data=donnees,
        files={'source_csv': ('fictif.csv', CSV.encode(), 'text/csv')}).status_code == 400
    doublons = [(k, (None, v)) for k, v in donnees.items()]
    doublons += [('csrf', (None, 'autre')), ('source_csv', ('fictif.csv', CSV.encode(), 'text/csv'))]
    assert catalogue.post(ROUTE, files=doublons).status_code == 400
    assert catalogue.post(ROUTE, data=donnees,
        files={'source_csv': ('fictif.csv', b'\xff', 'text/csv')}).status_code == 400
    assert instantane(session) == avant


def test_nonce_deja_utilise_avec_autre_intention_refuse_sans_double_tarif(sources, session, catalogue):
    donnees, _ = preparer(catalogue, session)
    assert confirmer(catalogue, donnees).status_code == 200
    avant = instantane(session)
    assert confirmer(catalogue, dict(donnees, source_document='autre-fictif.csv')).status_code == 409
    assert instantane(session) == avant


def test_admin_sql_avant_lecture_du_corps(sources, session, catalogue, monkeypatch):
    donnees, _ = preparer(catalogue, session)
    u.p.h.p.c.m.base._connecter(catalogue, 'nathan')

    async def interdit(*args, **kw):
        raise AssertionError('corps privé lu pour owner sans admin SQL')

    monkeypatch.setattr(u.ui(), 'extraire', interdit)
    assert confirmer(catalogue, donnees).status_code == 403


@pytest.mark.parametrize('source', ['', 'sans-entetes', 'SKU;SKU\na;b\n',
    'SKU;Unite;Prix;Devise;Date\nmat-fictif;pi\n', 'CSV\x00FICTIF'])
def test_erreurs_csv_client_sont_400_et_non_indisponibilite_serveur(sources, session, catalogue, source):
    donnees, _ = preparer(catalogue, session)
    avant = instantane(session)
    r = confirmer(catalogue, donnees, source)
    assert r.status_code == 400, r.text
    assert 'CSV\x00FICTIF' not in r.text and instantane(session) == avant
