"""fictif: true — consultation HTTP du journal SQL M4, sans saisie RH."""
import importlib.util
import re
from html import unescape
from pathlib import Path

import pytest

from opsys import identite
from opsys.departements import charger_departements

spec = importlib.util.spec_from_file_location('journal_http_fixture',
    Path(__file__).with_name('test_console_journal_equipes.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, planning = f.client_crm, f.planning
FICTIF = True
URL = '/crm/journal-equipes?jour=2030-06-03'


def test_journal_http_sql_reel_source_et_aucun_effet(client_crm, planning, session):
    f.f.base._connecter(client_crm, 'admin.fictif')
    _, ids, confirmation, _ = planning
    avant = f.f.base._instantane_base(session)
    r = client_crm.get(URL)
    assert r.status_code == 200, r.text
    assert 'Journal des équipes' in r.text and 'America/Montreal' in r.text
    assert confirmation['ligne_id'] in r.text
    for iid in ids.values():
        assert iid in r.text
    assert 'Absence de pointage ne signifie pas absence du salarié.' in r.text
    assert r.headers['cache-control'] == 'no-store' and 'content-security-policy' in r.headers
    assert client_crm.post(URL).status_code == 405
    assert f.f.base._instantane_base(session) == avant


def _suivante(html):
    m = re.search(r'href="([^"]+)"[^>]*>Page suivante</a>', html)
    return unescape(m.group(1)).removeprefix(f.f.base.PREFIXE) if m else None


def test_liens_semaine_pagination_complete_et_jour_vide(client_crm, planning, session):
    f.f.base._connecter(client_crm, 'admin.fictif')
    _, ids, _, _ = planning
    avant = f.f.base._instantane_base(session)
    semaine = client_crm.get('/crm/cedule?debut_semaine=2030-06-03')
    assert f'href="{f.f.base.PREFIXE}{URL}"' in semaine.text
    assert 'jour=2030-06-09' in semaine.text
    url, vus = URL + '&limite=1', []
    while url is not None:
        r = client_crm.get(url)
        assert r.status_code == 200, r.text
        vus += [iid for iid in ids.values() if f'<td>{iid}</td>' in r.text]
        url = _suivante(r.text)
    assert sorted(vus) == sorted(ids.values()) and len(vus) == len(set(vus))
    vide = client_crm.get('/crm/journal-equipes?jour=2030-06-04')
    assert vide.status_code == 200 and 'Aucun fait ou prévision' in vide.text
    assert f.f.base._instantane_base(session) == avant


@pytest.mark.parametrize('requete', ['', 'jour=20300603', 'jour=2030-02-30',
    'jour=2030-06-03&jour=2030-06-04', 'jour=2030-06-03&role=admin',
    'jour=2030-06-03&debut=1', 'jour=2030-06-03&debut=01', 'jour=2030-06-03&limite=0',
    'jour=2030-06-03&limite=101', 'jour=2030-06-03&source_attendue=faux'])
def test_requete_fermee_sans_ecriture(client_crm, planning, session, requete):
    f.f.base._connecter(client_crm, 'admin.fictif')
    avant = f.f.base._instantane_base(session)
    assert client_crm.get('/crm/journal-equipes?' + requete).status_code == 400
    assert f.f.base._instantane_base(session) == avant


def test_admin_exige_et_revocation_pendant_rendu_sans_faits(client_crm, planning, session, monkeypatch):
    from opsys.console import journal_equipes as port

    assert client_crm.get(URL, follow_redirects=False).status_code == 303
    for personne in ['employe', 'nathan']:
        f.f.base._connecter(client_crm, personne)
        assert client_crm.get(URL).status_code == 403
    f.f.base._connecter(client_crm, 'admin.fictif')
    original = port.contenu

    def revoquer(*args):
        html = original(*args)
        with session() as cnx:
            identite.ajouter_role(cnx, f.AUTH.utilisateur, 'nathan_owner')
            identite.retirer_role(cnx, f.AUTH.utilisateur, 'admin')
        return html

    monkeypatch.setattr(port, 'contenu', revoquer)
    r = client_crm.get(URL)
    assert r.status_code == 403 and all(iid not in r.text for iid in planning[1].values())


def test_html_echappe_et_plafond_avant_reponse(client_crm, planning, session, monkeypatch):
    from opsys.console import journal_equipes as port

    with session() as cnx:
        vue = port.lire(cnx, charger_departements(), f.AUTH, f.JOUR)
    vue['lignes'][0]['intervention_id'] = '<script>fictif()</script>'
    html = port.contenu(vue, '', 50)
    assert '<script>' not in html and '&lt;script&gt;' in html
    f.f.base._connecter(client_crm, 'admin.fictif')
    avant = f.f.base._instantane_base(session)
    monkeypatch.setattr(port, 'contenu', lambda *a: '<p>' + 'x' * 131073 + '</p>')
    r = client_crm.get(URL)
    assert r.status_code == 503 and len(r.content) < 1024
    assert f.f.base._instantane_base(session) == avant


def test_continuation_perimee_ne_renvoie_pas_ancienne_page(client_crm, planning, session):
    from m4_field_ops import etats

    f.f.base._connecter(client_crm, 'admin.fictif')
    suivante = _suivante(client_crm.get(URL + '&limite=1').text)
    with session():
        assert etats.transitionner(next(iter(planning[1].values())), 'reportee', f.f.terrain._registre(),
                                  f.JOUR + 'T10:00:00-04:00', motif='meteo')[1] is None
    avant = f.f.base._instantane_base(session)
    r = client_crm.get(suivante)
    assert r.status_code == 503 and all(iid not in r.text for iid in planning[1].values())
    assert f.f.base._instantane_base(session) == avant


def test_report_et_reprise_d4_conservent_ancienne_entree_http(client_crm, planning, session):
    from m4_field_ops import etats

    par_nom, ids, confirmation, _ = planning
    with session():
        reg = f.f.terrain._registre()
        iid = next(iter(ids.values()))
        assert etats.transitionner(iid, 'reportee', reg, f.JOUR + 'T10:00:00-04:00', motif='meteo')[1] is None
        assert etats.transitionner(iid, 'planifiee', reg, f.JOUR + 'T10:01:00-04:00')[1] is None
    nouvelle = f.f.terrain._resultat(f.f.terrain._appeler(par_nom, 'm4_confirmer_dates_cedule', dict(
        plan_id=confirmation['plan_id'], calendrier={'0': '2030-06-07'}, revision_attendue=1), f.f.terrain.ADMIN))
    f.f.base._connecter(client_crm, 'admin.fictif')
    avant = f.f.base._instantane_base(session)
    ancien = client_crm.get(URL)
    nouveau = client_crm.get('/crm/journal-equipes?jour=2030-06-07')
    assert ancien.status_code == nouveau.status_code == 200
    assert 'Ancienne prévision' in ancien.text and 'Reporté' in ancien.text
    assert confirmation['ligne_id'] in ancien.text and nouvelle['ligne_id'] in nouveau.text
    assert 'Date confirmée' in nouveau.text
    assert f.f.base._instantane_base(session) == avant


def test_page_fin_vide_ne_declare_pas_journee_vide(client_crm, planning, session):
    from opsys.console import journal_equipes as port

    with session() as cnx:
        vue = port.lire(cnx, charger_departements(), f.AUTH, f.JOUR)
    assert vue['total'] > 0
    f.f.base._connecter(client_crm, 'admin.fictif')
    avant = f.f.base._instantane_base(session)
    r = client_crm.get(URL + f'&debut={vue["total"]}&source_attendue={vue["source"]}')
    assert r.status_code == 200, r.text
    assert 'Aucun fait ou prévision pour cette journée.' not in r.text
    assert 'Aucune entrée sur cette page.' in r.text and 'Première page' in r.text
    assert f.f.base._instantane_base(session) == avant
