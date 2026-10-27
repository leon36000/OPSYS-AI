"""Dates du cockpit : outils M4 et SQLite réels, données fictives uniquement."""
import importlib.util
import re
from pathlib import Path

import pytest

from opsys import identite

spec = importlib.util.spec_from_file_location(
    "fixture_dates_cedule", Path(__file__).with_name("test_console_cedule.py"))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
client_crm = base.client_crm
planning = base.planning
FICTIF = True


def _url(planning):
    return '/crm/cedule/plan/' + planning[2]['plan_id']


def _champs(client, plan_id=None, **autres):
    preuve = {}
    if plan_id is not None:
        page = client.get("/crm/cedule/plan/" + plan_id)
        trouve = re.search(r'name="empreinte_memoire_attendue" value="([0-9a-f]{64})"', page.text)
        if trouve:
            preuve["empreinte_memoire_attendue"] = trouve[1]
    return {'csrf': client.get('/api/session').json()['csrf'], 'revision_attendue': '1',
            'mutation_id': 'date-fictive-unique', 'date_0': '2030-06-10', **preuve, **autres}


def test_lire_modifier_et_rejouer_dates_reelles(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    avant = base.base._instantane_base(session)
    page = client_crm.get(_url(planning))
    assert page.status_code == 200, page.text
    assert 'name="date_0"' in page.text and 'value="2030-06-03"' in page.text
    assert 'name="revision_attendue" value="1"' in page.text
    assert planning[2]['ligne_id'] in page.text
    assert 'confirmation client' in page.text
    assert page.headers['cache-control'] == 'no-store'
    assert base.base._instantane_base(session) == avant
    champs = _champs(client_crm, planning[2]['plan_id'])
    assert client_crm.post(_url(planning), data=champs, follow_redirects=False).status_code == 303
    with session():
        dates = [m for m in base.terrain._maillons() if m['type_entree'] == 'cedule_datee']
    assert len(dates) == 2 and dates[-1]['revision'] == 2
    assert dates[-1]['calendrier'] == {'0': '2030-06-10'}
    assert dates[-1]['confirme_par'] == 'admin.fictif'
    apres = base.base._instantane_base(session)
    assert client_crm.post(_url(planning), data=champs, follow_redirects=False).status_code == 200
    assert base.base._instantane_base(session) == apres
    semaine = client_crm.get('/crm/cedule?debut_semaine=2030-06-10')
    assert 'data-intervention=' in semaine.text and _url(planning) in semaine.text


def test_revision_obsolete_et_reutilisation_id_different_refusees(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    champs = _champs(client_crm, planning[2]['plan_id'])
    assert client_crm.post(_url(planning), data=champs, follow_redirects=False).status_code == 303
    avant = base.base._instantane_base(session)
    for modification in [{'mutation_id': 'autre-fictif'}, {'date_0': '2030-06-11'}]:
        assert client_crm.post(_url(planning), data={**champs, **modification}).status_code == 409
        assert base.base._instantane_base(session) == avant


def test_csrf_et_formulaire_borne_unique(client_crm, planning, session):
    from urllib.parse import urlencode
    base.base._connecter(client_crm, 'admin.fictif')
    champs = _champs(client_crm, planning[2]['plan_id'])
    avant = base.base._instantane_base(session)
    assert client_crm.post(_url(planning), data={**champs, 'csrf': 'faux'}).status_code == 403
    assert client_crm.post(_url(planning), data={**champs, 'confirme_par': 'usurpe'}).status_code == 400
    assert client_crm.post(_url(planning), data={**champs, 'date_00': '2030-06-10'}).status_code == 400
    assert client_crm.post(_url(planning), content=urlencode(champs)+'&date_0=2030-06-11',
                           headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 400
    assert client_crm.post(_url(planning), content=b'x'*9000,
                           headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 413
    assert base.base._instantane_base(session) == avant


@pytest.mark.parametrize('acteur', ['employe', 'nathan'])
def test_non_admin_refuse(client_crm, planning, session, acteur):
    base.base._connecter(client_crm, acteur)
    avant = base.base._instantane_base(session)
    assert client_crm.get(_url(planning)).status_code == 403
    assert client_crm.post(_url(planning), data=_champs(client_crm, planning[2]['plan_id'])).status_code == 403
    assert base.base._instantane_base(session) == avant


def test_revocation_avant_rejeu(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    champs = _champs(client_crm, planning[2]['plan_id'])
    assert client_crm.post(_url(planning), data=champs, follow_redirects=False).status_code == 303
    with session() as cnx:
        identite.ajouter_role(cnx, 'admin.fictif', 'nathan_owner')
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = base.base._instantane_base(session)
    assert client_crm.post(_url(planning), data=champs, follow_redirects=False).status_code == 403
    assert base.base._instantane_base(session) == avant


def test_source_changee_entre_affichage_et_post(client_crm, planning, session):
    from m4_field_ops import etats
    base.base._connecter(client_crm, 'admin.fictif')
    assert client_crm.get(_url(planning)).status_code == 200
    with session():
        assert etats.transitionner(planning[1]['lead-fictif-001'], 'reportee', base.terrain._registre(),
                                   base.terrain.RECU_LE.isoformat(), motif='meteo')[1] is None
    avant = base.base._instantane_base(session)
    page = client_crm.get(_url(planning))
    assert page.status_code == 200 and 'Confirmer les dates internes' not in page.text
    assert client_crm.post(_url(planning), data=_champs(client_crm, planning[2]['plan_id'])).status_code == 409
    assert base.base._instantane_base(session) == avant


def test_jour_manquant_date_impossible_et_mauvais_plan(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    champs = _champs(client_crm, planning[2]['plan_id'])
    avant = base.base._instantane_base(session)
    for changement in [{'date_0': ''}, {'date_0': '2030-02-30'}, {'date_1': '2030-06-11'},
                       {'revision_attendue': '-1'}]:
        assert client_crm.post(_url(planning), data={**champs, **changement}).status_code in {400, 409}
    assert client_crm.get('/crm/cedule/plan/invalide').status_code == 404
    assert client_crm.get(_url(planning)+'?confirme_par=x').status_code == 400
    assert base.base._instantane_base(session) == avant


def test_plan_applique_sans_date_reste_vide_avant_confirmation(client_crm, session):
    from m4_field_ops.outils import outils
    par_nom = {o.nom: o for o in outils()}
    ids = {}
    for rang, original in enumerate(base.terrain.SCENARIO["leads"][:3]):
        lead = {**original, "lead_id": f"non-date-fictif-{rang}"}
        ids[lead["lead_id"]] = base.terrain._inscrire(par_nom, lead)
        base.terrain._resultat(base.terrain._confirmer(par_nom, lead))
    plan = base.terrain._resultat(base.terrain._proposer(par_nom, ids))["plan_id"]
    base.terrain._resultat(base.terrain._appliquer(par_nom, plan))
    base.base._connecter(client_crm, "admin.fictif")
    url = "/crm/cedule/plan/" + plan
    avant = base.base._instantane_base(session)
    page = client_crm.get(url)
    assert page.status_code == 200 and 'name="revision_attendue" value="0"' in page.text
    assert 'value="" required' in page.text and 'Aucune confirmation' in page.text
    assert url in client_crm.get('/crm/cedule?debut_semaine=2030-06-03').text
    assert base.base._instantane_base(session) == avant
    champs = _champs(client_crm, plan, revision_attendue='0')
    assert client_crm.post(url, data=champs, follow_redirects=False).status_code == 303
    with session():
        dates = [m for m in base.terrain._maillons() if m['type_entree'] == 'cedule_datee']
    assert len(dates) == 1 and dates[0]['revision'] == 1
    assert dates[0]['calendrier'] == {'0': '2030-06-10'}


@pytest.mark.parametrize('defaut', ['tronque', 'source_manquante'])
def test_projection_partielle_ou_invalide_ne_permet_pas_confirmation(
        client_crm, planning, session, monkeypatch, defaut):
    from opsys.console import metier
    vue = base.terrain._resultat(base.terrain._appeler(
        planning[0], 'm4_lire_calendrier_plan', {'plan_id': planning[2]['plan_id']}, base.terrain.ADMIN))
    if defaut == 'tronque':
        vue['total_visites'] = 201
        vue['tronque'] = True
    else:
        vue['source_application_id'] = ''
    original = metier.executer

    def faux_lecteur(cnx, deps, sess, nom, arguments, **kwargs):
        if nom == 'm4_lire_calendrier_plan':
            return {'ok': True, 'resultat': {'accepte': True, 'resultat': vue}}
        return original(cnx, deps, sess, nom, arguments, **kwargs)

    monkeypatch.setattr(metier, 'executer', faux_lecteur)
    base.base._connecter(client_crm, 'admin.fictif')
    avant = base.base._instantane_base(session)
    page = client_crm.get(_url(planning))
    assert page.status_code == (200 if defaut == 'tronque' else 503)
    assert 'Confirmer les dates internes' not in page.text
    assert client_crm.post(_url(planning), data=_champs(client_crm, planning[2]['plan_id'])).status_code == (
        409 if defaut == 'tronque' else 503)
    assert base.base._instantane_base(session) == avant
