"""fictif: true — classification manuelle HTTP, hors décision métier et hors classes M10."""
import importlib.util
import re
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('classement_http_fixture',
    Path(__file__).with_name('test_console_pieces_projet_http.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, catalogue = f.client_crm, f.catalogue


@pytest.fixture
def route(catalogue):
    assert f.envoyer(catalogue).status_code == 303
    piece = re.search(r'pieces-recues/([0-9a-f]{32})', catalogue.get(f.URL).text).group(1)
    return f.URL + '/' + piece + '/classement'


def champs(client, route):
    r = client.get(route)
    assert r.status_code == 200, r.text
    return {nom: re.search('name="' + nom + '" value="([^"]+)"', r.text).group(1)
            for nom in ('csrf', 'mutation_id', 'revision_attendue')} | dict(
                categorie='plan', motif='organisation_dossier')


def test_classement_HTTP_et_historique_courant(catalogue, route, session):
    avant = f.f._instantane_base(session)
    valeurs = champs(catalogue, route)
    assert f.f._instantane_base(session) == avant
    assert 'Classement et historique' in catalogue.get(f.URL).text
    r = catalogue.post(route, data=valeurs, follow_redirects=False)
    assert r.status_code == 303, r.text
    page = catalogue.get(route)
    assert 'Classement courant : Plan' in page.text and 'Révision 1' in page.text
    assert 'Organiser le dossier' in page.text and 'Non classée' in page.text
    assert 'ADMIN' not in page.text and 'FINANCIAL' not in page.text


def test_rejeu_historique_apres_correction_ne_fait_pas_reculer_courant(catalogue, route, session):
    premier = champs(catalogue, route)
    assert catalogue.post(route, data=premier, follow_redirects=False).status_code == 303
    second = champs(catalogue, route) | dict(categorie='materiaux', motif='correction_erreur')
    assert catalogue.post(route, data=second, follow_redirects=False).status_code == 303
    avant = f.f._instantane_base(session)
    r = catalogue.post(route, data=premier)
    assert r.status_code == 200 and 'Reçu historique' in r.text
    assert 'Classement courant : Matériaux' in r.text and 'Révision 2' in r.text
    assert f.f._instantane_base(session) == avant
    conflit = catalogue.post(route, data=premier | dict(categorie='photo'))
    assert conflit.status_code == 409


@pytest.mark.parametrize('changement,attendu', [(dict(csrf='invalide'), 403), (dict(categorie='INTERNAL'), 400),
    (dict(categorie='inconnue'), 400), (dict(revision_attendue='True'), 400),
    (dict(revision_attendue='00'), 400), (dict(inconnu='secret-fictif'), 400)])
def test_formulaire_ferme_sans_ecriture(catalogue, route, session, changement, attendu):
    valeurs = champs(catalogue, route) | changement
    avant = f.f._instantane_base(session)
    assert catalogue.post(route, data=valeurs).status_code == attendu
    assert f.f._instantane_base(session) == avant


def test_mauvais_projet_meme_client(catalogue, route):
    assert catalogue.get(route.replace('001', '002')).status_code == 404


def test_champs_dupliques_et_taille_bornee(catalogue, route):
    valeurs = champs(catalogue, route)
    from urllib.parse import urlencode

    corps = urlencode([*valeurs.items(), ('categorie', 'photo')])
    assert catalogue.post(route, content=corps, headers={
        'content-type': 'application/x-www-form-urlencoded'}).status_code == 400
    assert catalogue.post(route, content=b'x' * 4097, headers={
        'content-type': 'application/x-www-form-urlencoded'}).status_code == 413


def test_revocation_pendant_rendu_refuse_page(catalogue, route, session, monkeypatch):
    from opsys import identite
    from opsys.console import classement_pieces_ui as ui

    rendu = ui.contenu
    def revoquer(*args):
        with session() as cnx:
            identite.retirer_role(cnx, 'admin.fictif', 'admin')
        return rendu(*args)
    monkeypatch.setattr(ui, 'contenu', revoquer)
    assert catalogue.get(route).status_code == 403


@pytest.mark.parametrize('suffixe', ['?inconnu=secret-fictif', '?decalage=00', '?decalage=20',
    '?decalage=0&decalage=0', '?revision_max=True', '?revision_max=33'])
def test_parametres_stricts(catalogue, route, suffixe):
    r = catalogue.get(route + suffixe)
    assert r.status_code == 400 and 'secret-fictif' not in r.text


def test_classification_changee_pendant_rendu_ferme(catalogue, route, session, monkeypatch):
    from sqlalchemy import update

    from opsys.console import classement_pieces_ui as ui

    valeurs = champs(catalogue, route)
    assert catalogue.post(route, data=valeurs, follow_redirects=False).status_code == 303
    rendu = ui.contenu
    def corrompre(*args):
        with session() as cnx:
            cnx.execute(update(ui.classement.CLASSEMENTS).values(categorie='autre'))
        return rendu(*args)
    monkeypatch.setattr(ui, 'contenu', corrompre)
    assert catalogue.get(route).status_code == 503


def test_revocation_apres_ecriture_annule_classement_et_audit(catalogue, route, session, monkeypatch):
    from opsys import identite
    from opsys.console import classement_pieces_ui as ui

    valeurs = champs(catalogue, route)
    avant = f.f._instantane_base(session)
    reponse = ui.RedirectResponse
    def revoquer(*args, **kwargs):
        with session() as cnx:
            identite.retirer_role(cnx, 'admin.fictif', 'admin')
        return reponse(*args, **kwargs)
    monkeypatch.setattr(ui, 'RedirectResponse', revoquer)
    assert catalogue.post(route, data=valeurs).status_code == 403
    assert f.f._instantane_base(session) == avant


def test_role_SQL_revoque_avant_corps(catalogue, route, session, monkeypatch):
    from opsys import identite
    from opsys.console import classement_pieces_ui as ui

    valeurs = champs(catalogue, route)
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    async def interdit(*args):
        raise AssertionError('corps lu avant autorité')
    monkeypatch.setattr(ui, '_formulaire', interdit)
    assert catalogue.post(route, data=valeurs).status_code == 403


def test_historique_HTTP_garde_plafond_et_affiche_courant(catalogue, route, session):
    from opsys.console import classement_pieces
    from opsys.departements import charger_departements

    spec = importlib.util.spec_from_file_location('classement_http_auth_fixture',
        Path(__file__).with_name('test_console_pieces_projet.py'))
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    piece = route.split('/')[-2]
    with session() as cnx:
        for i in range(21):
            classement_pieces.classer(cnx, charger_departements(), g.AUTH, g.LEAD, piece, cle=g.CLE,
                categorie='plan' if i % 2 == 0 else 'photo', revision_attendue=i,
                mutation_id=f'{i:032x}', motif='organisation_dossier')
    page = catalogue.get(route)
    assert 'decalage=20&amp;revision_max=21' in page.text
    with session() as cnx:
        classement_pieces.classer(cnx, charger_departements(), g.AUTH, g.LEAD, piece, cle=g.CLE,
            categorie='autre', revision_attendue=21, mutation_id='f' * 32, motif='correction_erreur')
    suite = catalogue.get(route + '?decalage=20&revision_max=21')
    assert suite.status_code == 200
    assert 'Révision 22' in suite.text and 'Classement courant : Autre' in suite.text
    histoire = suite.text.split('<ol>', 1)[1].split('</ol>', 1)[0]
    assert 'Révision 21' in histoire and 'Révision 22' not in histoire


def test_compagnon_corrompu_apres_ecriture_annule_transaction(catalogue, route, session, monkeypatch):
    from sqlalchemy import update

    from opsys.console import classement_pieces_ui as ui

    valeurs = champs(catalogue, route)
    avant = f.f._instantane_base(session)
    reponse = ui.RedirectResponse
    def corrompre(*args, **kwargs):
        with session() as cnx:
            cnx.execute(update(ui.classement.CLASSEMENTS).values(categorie='autre'))
        return reponse(*args, **kwargs)
    monkeypatch.setattr(ui, 'RedirectResponse', corrompre)
    assert catalogue.post(route, data=valeurs, follow_redirects=False).status_code == 503
    assert f.f._instantane_base(session) == avant
