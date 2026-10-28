"""fictif: true — liste classée, filtre et pagination sous identité admin SQL réelle."""
import html
import importlib.util
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

spec = importlib.util.spec_from_file_location('filtre_pieces_http_fixture',
    Path(__file__).with_name('test_console_pieces_projet_http.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, catalogue = f.client_crm, f.catalogue
spec = importlib.util.spec_from_file_location('filtre_pieces_metier_fixture',
    Path(__file__).with_name('test_console_liste_pieces_classees.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def deux_pieces(client, session):
    un = f.champs(client) | dict(titre='Plan TOITURE FICTIF')
    assert f.envoyer(client, un).status_code == 303
    deux = f.champs(client) | dict(titre='Autre PIECE FICTIVE')
    assert f.envoyer(client, deux).status_code == 303
    with session() as cnx:
        pieces = g.liste(cnx)['pieces']
        plan = next(p['piece_id'] for p in pieces if p['titre'] == un['titre'])
        g.g.classer(cnx, plan)
    return plan


def test_filtre_affiche_categorie_et_totaux(catalogue, session):
    plan = deux_pieces(catalogue, session)
    avant = f.f._instantane_base(session)
    r = catalogue.get(f.URL + '?categorie=plan')
    assert r.status_code == 200, r.text
    assert 'Plan TOITURE FICTIF' in r.text and 'Autre PIECE FICTIVE' not in r.text
    assert 'Classement : Plan' in r.text and 'révision 1' in r.text
    assert '1 pièce(s) correspondent sur 2' in r.text and plan in r.text
    assert f.f._instantane_base(session) == avant


@pytest.mark.parametrize('suffixe', ['?categorie=INTERNAL', '?categorie=plan&categorie=photo',
    '?source_attendue=invalide', '?decalage=20&categorie=plan', '?source_attendue=0&source_attendue=0'])
def test_parametres_fermes(catalogue, suffixe):
    r = catalogue.get(f.URL + suffixe)
    assert r.status_code == 400


def test_liste_perimee_propose_actualisation_sans_vieille_empreinte(catalogue, session):
    plan = deux_pieces(catalogue, session)
    with session() as cnx:
        token = g.liste(cnx, categorie='plan')['source_calculee']
        g.g.classer(cnx, plan, 'photo', 1, 'b' * 32, 'correction_erreur')
    r = catalogue.get(f.URL + '?categorie=plan&source_attendue=' + token)
    assert r.status_code == 409 and 'Actualiser les résultats' in r.text
    assert token not in r.text and 'categorie=plan' in r.text


def test_pagination_conserve_filtre_et_empreinte(catalogue, session):
    plans = set()
    with session() as cnx:
        for i in range(41):
            recu = g.g.f.depot(cnx, mutation=f'{i:032x}')
            code = 'plan' if i % 2 == 0 else 'photo'
            g.g.classer(cnx, recu['piece_id'], code, mutation=f'{i:032x}')
            if code == 'plan':
                plans.add(recu['piece_id'])
    r = catalogue.get(f.URL + '?categorie=plan')
    suivant = html.unescape(re.search(r'<a href="([^"]+)">Page suivante</a>', r.text).group(1))
    q = parse_qs(urlsplit(suivant).query)
    assert q['categorie'] == ['plan'] and q['decalage'] == ['20'] and len(q['source_attendue'][0]) == 64
    suite = catalogue.get(suivant.removeprefix('/opsys'))
    assert suite.status_code == 200 and '21 pièce(s) correspondent sur 41' in suite.text
    visibles = set(re.findall(r'pieces-recues/([0-9a-f]{32})', r.text))
    derniers = set(re.findall(r'pieces-recues/([0-9a-f]{32})', suite.text))
    assert len(visibles) == 20 and len(derniers) == 1 and visibles.isdisjoint(derniers)
    assert visibles | derniers == plans


def test_changement_hors_page_pendant_rendu_ferme(catalogue, session, monkeypatch):
    from opsys.console import pieces_projet_ui as ui

    plan = deux_pieces(catalogue, session)
    avant = f.f._instantane_base(session)
    rendu = ui.contenu
    def modifier(*args):
        with session() as cnx:
            g.g.classer(cnx, plan, 'photo', 1, 'b' * 32, 'correction_erreur')
        return rendu(*args)
    monkeypatch.setattr(ui, 'contenu', modifier)
    assert catalogue.get(f.URL + '?categorie=photo').status_code == 503
    assert f.f._instantane_base(session) == avant


def test_refus_liste_perimee_revalide_role_apres_rendu(catalogue, session, monkeypatch):
    from opsys import identite
    from opsys.console import pages

    plan = deux_pieces(catalogue, session)
    with session() as cnx:
        token = g.liste(cnx, categorie='plan')['source_calculee']
        g.g.classer(cnx, plan, 'photo', 1, 'b' * 32)
    rendu = pages.gabarit
    def revoquer(*args, **kwargs):
        with session() as cnx:
            identite.retirer_role(cnx, 'admin.fictif', 'admin')
        return rendu(*args, **kwargs)
    monkeypatch.setattr(pages, 'gabarit', revoquer)
    r = catalogue.get(f.URL + '?categorie=plan&source_attendue=' + token)
    assert r.status_code == 403
