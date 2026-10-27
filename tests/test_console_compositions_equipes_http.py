"""fictif: true — affichage HTTP de compositions déclarées, jamais de présence déduite."""
import importlib.util
import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from opsys import identite
from opsys.console import compositions_equipes as port
from opsys.console import journal_equipes
from opsys.departements import charger_departements

spec = importlib.util.spec_from_file_location('composition_http_fixture',
    Path(__file__).with_name('test_console_compositions_equipes.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
client_crm, planning = g.client_crm, g.f.planning
base = g.f.f.base
FICTIF = True
URL = '/crm/journal-equipes/composition?jour=2030-06-03&equipe_id=eq-a'


def connecter(client):
    base._connecter(client, 'admin.fictif')


def suivante(html):
    m = re.search(r'href="([^"]+)"[^>]*>Page suivante</a>', html)
    return unescape(m[1]).removeprefix(base.PREFIXE) if m else None


def test_lecture_http_source_canonique_et_temporalites_sans_ecriture(client_crm, session):
    premier = g.ajouter(session)
    connecter(client_crm)
    avant = base._instantane_base(session)
    r = client_crm.get(URL)
    assert r.status_code == 200, r.text
    assert 'Composition déclarée' in r.text and '2030-06-03' in r.text and '2030-06-10' in r.text
    assert 'alice.fictive' in r.text and premier['resultat']['declaration_id'] in r.text
    assert 'aucune présence terrain' in r.text
    assert 'Empreinte calculée du snapshot' in r.text
    assert r.headers['cache-control'] == 'no-store' and 'content-security-policy' in r.headers
    assert client_crm.post(URL).status_code == 405
    assert base._instantane_base(session) == avant


def test_inconnu_vide_retrait_et_historique_distincts(client_crm, session):
    connecter(client_crm)
    r = client_crm.get(URL)
    assert r.status_code == 200 and 'Aucune déclaration pour cette équipe et cette journée' in r.text
    g.ajouter(session, membres=[])
    r = client_crm.get(URL)
    assert r.status_code == 200 and 'Liste déclarée explicitement vide' in r.text
    g.ajouter(session, revision=1, membres=None, statut='retiree', cle='m-2')
    avant = base._instantane_base(session)
    r = client_crm.get(URL)
    assert r.status_code == 200 and 'Déclaration retirée; composition inconnue' in r.text
    assert 'Révision 1' in r.text and 'Révision 2' in r.text
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('query', ['', 'jour=2030-06-03', 'equipe_id=eq-a',
    'jour=20300603&equipe_id=eq-a', 'jour=2030-06-03&equipe_id=eq-a&equipe_id=eq-b',
    'jour=2030-06-03&equipe_id=eq-a&inconnu=1', 'jour=2030-06-03&equipe_id=eq-a&debut=1',
    'jour=2030-06-03&equipe_id=%20eq-a', 'jour=2030-06-03&equipe_id=eq-a&limite=101'])
def test_parametres_fermes_avant_lecture(query, client_crm, session):
    connecter(client_crm)
    avant = base._instantane_base(session)
    r = client_crm.get('/crm/journal-equipes/composition?' + query)
    assert r.status_code == 400, r.text
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('personne', ['employe', 'nathan'])
def test_membres_prives_reserves_admin_courant(personne, client_crm, session):
    g.ajouter(session)
    base._connecter(client_crm, personne)
    avant = base._instantane_base(session)
    r = client_crm.get(URL)
    assert r.status_code == 403 and 'alice.fictive' not in r.text
    assert base._instantane_base(session) == avant


def test_revocation_pendant_rendu_ne_retourne_aucun_membre(client_crm, session, monkeypatch):
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
    assert r.status_code == 403 and 'alice.fictive' not in r.text


def test_ids_echappes_et_plafond_html_sans_ecriture(client_crm, session, monkeypatch):
    g.ajouter(session, membres=['membre.<script>'])
    connecter(client_crm)
    avant = base._instantane_base(session)
    r = client_crm.get(URL)
    assert r.status_code == 200 and 'membre.&lt;script&gt;' in r.text
    assert 'membre.<script>' not in r.text
    monkeypatch.setattr(port, 'contenu', lambda *args: '<p>' + 'x' * 131073 + '</p>')
    r = client_crm.get(URL)
    assert r.status_code == 503 and len(r.content) < 1024
    assert base._instantane_base(session) == avant


def test_pagination_ancienne_source_et_page_terminale_ne_deviennent_pas_inconnu(client_crm, session):
    g.ajouter(session)
    g.ajouter(session, revision=1, membres=[], cle='m-2')
    connecter(client_crm)
    p1 = client_crm.get(URL + '&limite=1')
    lien = suivante(p1.text)
    assert lien
    p2 = client_crm.get(lien)
    assert p2.status_code == 200 and 'Révision 2' in p2.text
    with session() as cnx:
        vue = port.lire(cnx, charger_departements(), g.AUTH, g.D, g.EQUIPE)
    fin = client_crm.get(URL + '&debut=2&source_attendue=' + vue['source'])
    assert fin.status_code == 200 and 'Aucune révision sur cette page' in fin.text
    assert 'Aucune déclaration pour cette équipe' not in fin.text
    g.ajouter(session, revision=2, membres=['nouveau.fictif'], cle='m-3')
    avant = base._instantane_base(session)
    r = client_crm.get(lien)
    assert r.status_code == 503 and 'alice.fictive' not in r.text
    assert base._instantane_base(session) == avant


def test_liens_du_journal_depuis_previsions_uniquement_sans_copie_membres(client_crm, planning, session):
    from m4_field_ops import etats

    _, ids, _, _ = planning
    with session() as cnx:
        assert etats.transitionner(next(iter(ids.values())), 'reportee', g.f.f.terrain._registre(),
                                   g.D + 'T10:00:00-04:00', motif='meteo')[1] is None
        avant = journal_equipes.lire(cnx, charger_departements(), g.AUTH, g.D)
    g.ajouter(session)
    with session() as cnx:
        apres = journal_equipes.lire(cnx, charger_departements(), g.AUTH, g.D)
    assert avant == apres
    connecter(client_crm)
    r = client_crm.get('/crm/journal-equipes?jour=' + g.D)
    liens = [unescape(x).removeprefix(base.PREFIXE) for x in
             re.findall(r'href="([^"]+)"[^>]*>Composition déclarée</a>', r.text)]
    previsions = [x for x in apres['lignes'] if x['type'] == 'prevision']
    assert len(liens) == len(previsions) > 0
    assert [parse_qs(urlparse(x).query) for x in liens] == [dict(jour=[g.D], equipe_id=[x['equipe_planifiee']])
                                                            for x in previsions]
    assert 'alice.fictive' not in r.text
    assert all(client_crm.get(x).status_code == 200 for x in liens)



@pytest.mark.parametrize('equipe', ['e' * 65, ' eq-a'])
def test_prevision_native_legacy_ne_propose_pas_de_lien_composition_invalide(equipe):
    from m4_field_ops import calendrier_civil, cedule_tournees, journal_quotidien

    chemin = Path(__file__).parents[1] / 'departments/m04-field-ops/tests/test_calendrier_civil.py'
    spec = importlib.util.spec_from_file_location('composition_legacy_plan_fixture', chemin)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    a = fixture._aide
    reg, ids, positions = a._monde()
    equipes = a._equipes()[:1]
    equipes[0]['id'] = equipe
    args = a._arguments(ids, equipes=equipes)
    plan = a._reussi(a._proposer(reg, ids, positions, args))['plan_id']
    a._reussi(cedule_tournees.appliquer(reg, plan, positions, a.HORODATAGE, 'admin.fictif'))
    calendrier_civil.confirmer(reg, plan, {'0': g.D}, 0, 'admin.fictif', a.HORODATAGE)
    vue = journal_quotidien.lire(reg, g.D)
    assert any(x.get('equipe_planifiee') == equipe for x in vue['lignes'])
    # Contrat de rendu pur : pas une preuve de snapshot SQL ou de navigateur.
    vue['source_snapshot'] = vue['source']
    html = journal_equipes.contenu(vue, '', 50)
    assert '>Composition déclarée</a>' not in html
    assert 'Composition non consultable pour cet identifiant historique' in html
    assert 'Notes et historique' in html
