"""fictif: true — parcours HTTP pièces reçues, sans fichier/clé/donnée de production."""
import base64
import importlib.util
import logging
import re
from pathlib import Path

import pytest
from sqlalchemy import update

from opsys import identite
from opsys.console.journaux_http import MasquerRecherche

spec = importlib.util.spec_from_file_location('pieces_http_fixture', Path(__file__).with_name('test_console_crm.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm = f.client_crm
CLE = base64.b64encode(b'c' * 32).decode()
ENV = 'OPSYS_PIECES_PROJET_CLE'
URL = '/crm/lead/lead-fictif-001/pieces-recues'
PDF = b'%PDF-1.7\nPLAN-CLIENT-FICTIF\n%%EOF'


@pytest.fixture
def catalogue(client_crm, monkeypatch):
    monkeypatch.setenv(ENV, CLE)
    f._connecter(client_crm, 'admin.fictif')
    return client_crm


def champs(client):
    r = client.get(URL)
    assert r.status_code == 200, r.text
    return {nom: re.search('name="' + nom + '" value="([^"]+)"', r.text).group(1)
            for nom in ('csrf', 'mutation_id')} | dict(titre='Plan <script>FICTIF</script>')


def envoyer(client, valeurs=None, *, contenu=PDF, mime='application/pdf', url=URL):
    return client.post(url, data=valeurs or champs(client),
                       files={'piece': ('nom-client-fictif.pdf', contenu, mime)}, follow_redirects=False)


def test_formulaire_depot_et_telechargement_original_prive(catalogue, session):
    avant = f._instantane_base(session)
    valeurs = champs(catalogue)
    assert f._instantane_base(session) == avant
    r = envoyer(catalogue, valeurs)
    assert r.status_code == 303, r.text
    r = catalogue.get(URL)
    assert '&lt;script&gt;FICTIF&lt;/script&gt;' in r.text
    assert 'NON_ANALYSE' in r.text and 'PDF' in r.text
    assert 'nom-client-fictif.pdf' not in r.text and CLE not in r.text
    piece = re.search(r'pieces-recues/([0-9a-f]{32})', r.text).group(1)
    avant = f._instantane_base(session)
    original = catalogue.get(URL + '/' + piece)
    assert original.status_code == 200 and original.content == PDF
    assert original.headers['content-type'] == 'application/octet-stream'
    assert original.headers['content-disposition'] == 'attachment; filename="piece-projet.pdf"'
    assert original.headers['cache-control'] == 'no-store'
    assert original.headers['x-content-type-options'] == 'nosniff'
    assert "default-src 'none'" in original.headers['content-security-policy']
    assert 'sandbox' in original.headers['content-security-policy']
    assert "script-src 'self'" in original.headers['content-security-policy']
    assert f._instantane_base(session) == avant
    assert 'pieces-recues' in catalogue.get('/crm/lead/lead-fictif-001').text


def test_rejeu_HTTP_et_conflit_preservent_un_original(catalogue, session):
    valeurs = champs(catalogue)
    assert envoyer(catalogue, valeurs).status_code == 303
    avant = f._instantane_base(session)
    assert envoyer(catalogue, valeurs).status_code == 303
    assert f._instantane_base(session) == avant
    assert envoyer(catalogue, valeurs | dict(titre='Autre FICTIF')).status_code == 409
    assert f._instantane_base(session) == avant


@pytest.mark.parametrize('changement', [dict(csrf='invalide'), dict(inconnu='secret-fictif'),
    dict(titre=''), dict(mutation_id='invalide')])
def test_formulaire_invalide_sans_ecriture(catalogue, session, changement):
    valeurs = champs(catalogue) | changement
    avant = f._instantane_base(session)
    assert envoyer(catalogue, valeurs).status_code in (400, 403)
    assert f._instantane_base(session) == avant


def test_champ_duplique_et_fichier_supplementaire_refuses(catalogue, session):
    valeurs = champs(catalogue)
    avant = f._instantane_base(session)
    fichiers = [(k, (None, v)) for k, v in valeurs.items()]
    fichiers += [('csrf', (None, valeurs['csrf'])), ('piece', ('fictif.pdf', PDF, 'application/pdf'))]
    assert catalogue.post(URL, files=fichiers).status_code == 400
    fichiers = [('piece', ('a.pdf', PDF, 'application/pdf')), ('piece', ('b.pdf', PDF, 'application/pdf'))]
    assert catalogue.post(URL, data=valeurs, files=fichiers).status_code == 400
    assert f._instantane_base(session) == avant


@pytest.mark.parametrize('suffixe', ['?inconnu=secret-fictif', '?decalage=0&decalage=0', '?decalage=00',
    '?decalage=1', '?decalage=-20'])
def test_parametres_fermes(catalogue, suffixe):
    r = catalogue.get(URL + suffixe)
    assert r.status_code == 400 and 'secret-fictif' not in r.text


def test_mauvais_projet_meme_client_et_corruption_refuses(catalogue, session):
    assert envoyer(catalogue).status_code == 303
    r = catalogue.get(URL)
    piece = re.search(r'pieces-recues/([0-9a-f]{32})', r.text).group(1)
    assert catalogue.get(URL.replace('001', '002') + '/' + piece).status_code == 404
    from opsys.console.pieces_projet import PIECES
    with session() as cnx:
        cnx.execute(update(PIECES).values(chiffre='AAAA'))
    r = catalogue.get(URL + '/' + piece)
    assert r.status_code == 503 and b'PLAN-CLIENT' not in r.content


@pytest.mark.parametrize('valeur', [None, '', 'invalide', base64.b64encode(b'court').decode(), CLE + '\n'])
def test_configuration_cle_absente_ou_invalide_ferme(catalogue, monkeypatch, valeur):
    if valeur is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, valeur)
    r = catalogue.get(URL)
    assert r.status_code == 503 and 'secret-fictif' not in r.text
    assert CLE not in r.text


def test_role_SQL_revoque_avant_lecture_du_corps(catalogue, session, monkeypatch):
    from opsys.console import pieces_projet_ui as ui

    valeurs = champs(catalogue)
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    async def interdit(*args):
        raise AssertionError('corps lu avant autorité')
    monkeypatch.setattr(ui, '_multipart', interdit)
    assert envoyer(catalogue, valeurs).status_code == 403


def test_role_SQL_revoque_pendant_rendu_refuse_page(catalogue, session, monkeypatch):
    from opsys.console import pieces_projet_ui as ui

    rendu = ui.contenu
    def revoquer(*args):
        with session() as cnx:
            identite.retirer_role(cnx, 'admin.fictif', 'admin')
        return rendu(*args)
    monkeypatch.setattr(ui, 'contenu', revoquer)
    assert catalogue.get(URL).status_code == 403


def test_corps_trop_volumineux_refuse_avant_ecriture(catalogue, session):
    valeurs = champs(catalogue)
    avant = f._instantane_base(session)
    assert envoyer(catalogue, valeurs, contenu=PDF + b'x' * 1048576).status_code == 413
    assert f._instantane_base(session) == avant


def test_parametres_documentaires_masques_dans_journal():
    for chemin in (URL, URL + '/', URL + '/' + 'a' * 32):
        record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s %s %s %s %s',
                                   ('127.0.0.1', 'GET', chemin + '?inconnu=secret-fictif', '1.1', 400), None)
        assert MasquerRecherche().filter(record)
        assert 'secret-fictif' not in record.getMessage()


def test_corps_chunked_borne_avant_parseur(catalogue, session):
    avant = f._instantane_base(session)
    r = catalogue.post(URL, content=iter([b'x' * 600000, b'x' * 600000]),
                       headers={'content-type': 'multipart/form-data; boundary=FICTIF'})
    assert r.status_code == 413
    assert f._instantane_base(session) == avant


@pytest.mark.parametrize('annonce,attendu', [('invalide', 400), ('9999999', 413)])
def test_taille_annoncee_refusee(catalogue, annonce, attendu):
    r = catalogue.post(URL, content=b'fictif', headers={
        'content-type': 'multipart/form-data; boundary=FICTIF', 'content-length': annonce})
    assert r.status_code == attendu


def test_cle_changee_pendant_rendu_ferme(catalogue, monkeypatch):
    from opsys.console import pieces_projet_ui as ui

    rendu = ui.contenu
    def changer(*args):
        monkeypatch.setenv(ENV, base64.b64encode(b'z' * 32).decode())
        return rendu(*args)
    monkeypatch.setattr(ui, 'contenu', changer)
    assert catalogue.get(URL).status_code == 503


def test_cle_changee_apres_depot_annule_piece_et_audit(catalogue, session, monkeypatch):
    from opsys.console import pieces_projet_ui as ui

    valeurs = champs(catalogue)
    avant = f._instantane_base(session)
    depot = ui.pieces_projet.deposer
    def changer(*args, **kwargs):
        recu = depot(*args, **kwargs)
        monkeypatch.setenv(ENV, base64.b64encode(b'z' * 32).decode())
        return recu
    monkeypatch.setattr(ui.pieces_projet, 'deposer', changer)
    assert envoyer(catalogue, valeurs).status_code == 503
    assert f._instantane_base(session) == avant


def test_source_M2_changee_pendant_rendu_ferme(catalogue, monkeypatch):
    from opsys.console import pieces_projet_ui as ui

    rendu = ui.contenu
    def changer(*args):
        resultat = f.outils_m2.enregistrer_interaction('lead-fictif-001', 'admin.fictif', 'Note FICTIVE', f.H2)
        assert resultat['accepte']
        return rendu(*args)
    monkeypatch.setattr(ui, 'contenu', changer)
    assert catalogue.get(URL).status_code == 503


def test_download_modifie_pendant_construction_refuse_original(catalogue, session, monkeypatch):
    from opsys.console import pieces_projet_ui as ui

    assert envoyer(catalogue).status_code == 303
    piece = re.search(r'pieces-recues/([0-9a-f]{32})', catalogue.get(URL).text).group(1)
    reponse = ui.Response
    def corrompre(*args, **kwargs):
        with session() as cnx:
            cnx.execute(update(ui.pieces_projet.PIECES).values(chiffre='AAAA'))
        return reponse(*args, **kwargs)
    monkeypatch.setattr(ui, 'Response', corrompre)
    r = catalogue.get(URL + '/' + piece)
    assert r.status_code == 503 and b'PLAN-CLIENT-FICTIF' not in r.content


@pytest.mark.parametrize('specifiques', [['default-src *; sandbox'], ['default-src *', 'sandbox']])
def test_CSP_specifique_et_globale_cumulees_sans_relachement(specifiques):
    import asyncio

    from opsys.console.application import CSP, _EntetesSecurite

    messages = []
    async def app(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200, 'headers': [
            (b'content-security-policy', valeur.encode()) for valeur in specifiques]})
        await send({'type': 'http.response.body', 'body': b'fictif'})
    async def recevoir():
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    async def envoyer(message):
        messages.append(message)
    asyncio.run(_EntetesSecurite(app)({'type': 'http'}, recevoir, envoyer))
    politiques = [v.decode() for k, v in messages[0]['headers'] if k == b'content-security-policy']
    assert len(politiques) == 1
    assert politiques[0].split(', ') == [*specifiques, CSP]
