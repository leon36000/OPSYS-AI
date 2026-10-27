"""fictif: true — vrai GET admin des signalements, jamais une absence ou présence déduite."""
import importlib.util
import logging
import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from opsys import identite
from opsys.console import journal_equipes
from opsys.departements import charger_departements

spec = importlib.util.spec_from_file_location('absence_http_fixture',
    Path(__file__).with_name('test_console_absences_personnes.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
client_crm, planning = g.client_crm, g.f.f.f.planning
base = g.base
FICTIF = True
URL = '/crm/journal-equipes/absence?jour=2030-06-03&personne_id=inactif.fictif'


def connecter(client, personne='admin.fictif'):
    base._connecter(client, personne)


def suivante(html):
    m = re.search(r'href="([^"]+)"[^>]*>Page suivante</a>', html)
    return unescape(m[1]).removeprefix(base.PREFIXE) if m else None


def test_http_reel_source_temporalites_et_retrait_historise_sans_ecriture(client_crm, session):
    premier = g.ajouter(session)
    g.ajouter(session, revision=1, statut='retiree', cle='m-2')
    connecter(client_crm)
    avant = base._instantane_base(session)
    r = client_crm.get(URL)
    assert r.status_code == 200, r.text
    assert 'Absence signalée' in r.text and 'Signalement retiré; aucune présence déduite' in r.text
    assert '2030-06-03' in r.text and '2030-06-10' in r.text
    assert premier['resultat']['declaration_id'] in r.text and 'inactif.fictif' in r.text
    assert 'Empreinte calculée du snapshot' in r.text
    assert r.headers['cache-control'] == 'no-store' and 'content-security-policy' in r.headers
    assert client_crm.post(URL).status_code == 415
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('query', ['', 'jour=2030-06-03', 'personne_id=inactif.fictif',
    'jour=20300603&personne_id=inactif.fictif',
    'jour=2030-06-03&personne_id=inactif.fictif&personne_id=autre.fictif',
    'jour=2030-06-03&personne_id=inactif.fictif&role=admin',
    'jour=2030-06-03&personne_id=inactif.fictif&debut=1',
    'jour=2030-06-03&personne_id=%20inactif.fictif',
    'jour=2030-06-03&personne_id=inactif.fictif&limite=101'])
def test_parametres_fermes_sans_lecture_ou_ecriture(query, client_crm, session):
    connecter(client_crm)
    avant = base._instantane_base(session)
    r = client_crm.get('/crm/journal-equipes/absence?' + query)
    assert r.status_code == 400, r.text
    assert base._instantane_base(session) == avant


def test_aucun_signalement_ne_dit_pas_present(client_crm, session):
    connecter(client_crm)
    avant = base._instantane_base(session)
    r = client_crm.get(URL)
    assert r.status_code == 200 and 'Aucune absence signalée pour cet identifiant et ce jour' in r.text
    assert 'Aucune présence, heure travaillée ou paie déduite' in r.text
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('personne', ['employe', 'nathan'])
def test_historique_prive_non_admin_refuse(personne, client_crm, session):
    g.ajouter(session)
    connecter(client_crm, personne)
    avant = base._instantane_base(session)
    r = client_crm.get(URL)
    assert r.status_code == 403 and 'inactif.fictif' not in r.text
    assert base._instantane_base(session) == avant


def test_revocation_pendant_rendu_ne_divulgue_pas_signalement(client_crm, session, monkeypatch):
    from opsys.console import pages

    g.ajouter(session)
    connecter(client_crm)
    original = pages.gabarit

    def revoquer(*args, **kwargs):
        html = original(*args, **kwargs)
        with session() as cnx:
            identite.ajouter_role(cnx, g.AUTH.utilisateur, 'nathan_owner')
            identite.retirer_role(cnx, g.AUTH.utilisateur, 'admin')
        return html

    monkeypatch.setattr(pages, 'gabarit', revoquer)
    r = client_crm.get(URL)
    assert r.status_code == 403 and 'inactif.fictif' not in r.text


def test_source_modifiee_pendant_rendu_ne_repond_pas_historique_perime(client_crm, session, monkeypatch):
    from opsys.console import pages

    g.ajouter(session)
    connecter(client_crm)
    original = pages.gabarit

    def changer(*args, **kwargs):
        html = original(*args, **kwargs)
        g.ajouter(session, revision=1, statut='retiree', cle='m-2')
        return html

    monkeypatch.setattr(pages, 'gabarit', changer)
    r = client_crm.get(URL)
    assert r.status_code == 503 and 'inactif.fictif' not in r.text


def test_pagination_source_et_page_terminale_sans_fausse_absence(client_crm, session):
    from opsys.console import absences_personnes as port

    g.ajouter(session)
    g.ajouter(session, revision=1, statut='retiree', cle='m-2')
    connecter(client_crm)
    page = client_crm.get(URL + '&limite=1')
    lien = suivante(page.text)
    assert lien
    page2 = client_crm.get(lien)
    assert page2.status_code == 200 and 'Révision 2' in page2.text
    with session() as cnx:
        vue = port.lire(cnx, charger_departements(), g.AUTH, g.D, g.PERSONNE)
    fin = client_crm.get(URL + '&debut=2&source_attendue=' + vue['source'])
    assert fin.status_code == 200 and 'Aucune version sur cette page' in fin.text
    assert 'Aucune absence signalée pour cet identifiant' not in fin.text
    g.ajouter(session, revision=2, cle='m-3')
    avant = base._instantane_base(session)
    r = client_crm.get(lien)
    assert r.status_code == 503 and 'inactif.fictif' not in r.text
    assert base._instantane_base(session) == avant


def test_html_echappe_et_borne(client_crm, session, monkeypatch):
    from opsys.console import absences_personnes as port

    g.ajouter(session, personne='membre.<script>')
    connecter(client_crm)
    avant = base._instantane_base(session)
    r = client_crm.get('/crm/journal-equipes/absence', params={'jour': g.D, 'personne_id': 'membre.<script>'})
    assert r.status_code == 200 and 'membre.&lt;script&gt;' in r.text
    assert 'membre.<script>' not in r.text
    monkeypatch.setattr(port, 'contenu', lambda *args: 'x' * 131073)
    r = client_crm.get(URL)
    assert r.status_code == 503 and len(r.content) < 1024
    assert base._instantane_base(session) == avant


def test_formulaire_get_journal_utile_sans_copie_ou_compteur_absences(client_crm, planning, session):
    connecter(client_crm)
    with session() as cnx:
        avant = journal_equipes.lire(cnx, charger_departements(), g.AUTH, g.D)
    g.ajouter(session)
    with session() as cnx:
        apres = journal_equipes.lire(cnx, charger_departements(), g.AUTH, g.D)
    assert avant == apres
    r = client_crm.get('/crm/journal-equipes?jour=' + g.D)
    assert 'inactif.fictif' not in r.text
    bloc = next(x for x in re.findall(r'<form\b.*?</form>', r.text, re.S)
                if '/crm/journal-equipes/absence' in x)
    assert 'method="get"' in bloc and 'name="personne_id"' in bloc
    jour = re.search(r'name="jour" value="([^"]+)"', bloc)[1]
    cible = unescape(re.search(r'action="([^"]+)"', bloc)[1]).removeprefix(base.PREFIXE)
    url = str(client_crm.get(cible, params={'jour': jour, 'personne_id': g.PERSONNE}).url)
    assert parse_qs(urlparse(url).query) == {'jour': [g.D], 'personne_id': [g.PERSONNE]}
    assert client_crm.get(url).status_code == 200


@pytest.mark.parametrize('query', ['personne_id=inactif.fictif&jour=2030-06-03',
    '%70ersonne_id=inactif.fictif&jour=2030-06-03', 'identifiant=inactif.fictif&jour=2030-06-03'])
def test_logs_uvicorn_masquent_query_privee_mais_gardent_chemin_statut(query):
    from uvicorn.logging import AccessFormatter

    from opsys.console.journaux_http import MasquerRecherche

    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s - "%s %s HTTP/%s" %d',
        ('127.0.0.1', 'GET', '/opsys/crm/journal-equipes/absence?' + query, '1.1', 200), None)
    assert MasquerRecherche().filter(record)
    ligne = AccessFormatter(fmt='%(request_line)s %(status_code)s', use_colors=False).format(record)
    assert 'inactif.fictif' not in ligne and '2030-06-03' not in ligne
    assert '[MASQUE]' in ligne and '/opsys/crm/journal-equipes/absence' in ligne and '200' in ligne


def test_logs_slash_final_masquent_premier_acces_avant_redirection(client_crm):
    from uvicorn.logging import AccessFormatter

    from opsys.console.journaux_http import MasquerRecherche

    cible = '/crm/journal-equipes/absence/?identifiant=inactif.fictif&jour=2030-06-03'
    r = client_crm.get(cible, follow_redirects=False)
    assert r.status_code == 307
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s - "%s %s HTTP/%s" %d',
        ('127.0.0.1', 'GET', '/opsys' + cible, '1.1', r.status_code), None)
    assert MasquerRecherche().filter(record)
    ligne = AccessFormatter(fmt='%(request_line)s %(status_code)s', use_colors=False).format(record)
    assert 'inactif.fictif' not in ligne and '2030-06-03' not in ligne
    assert '[MASQUE]' in ligne and '/opsys/crm/journal-equipes/absence/' in ligne and '307' in ligne
