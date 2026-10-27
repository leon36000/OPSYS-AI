"""Grand carnet fictif, vrai registre SQLite et HTTP, sans fournisseur ni notification."""
import html
import importlib.util
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from m4_field_ops import etats

from opsys import stockage
from opsys.console import cedule_ui

spec = importlib.util.spec_from_file_location('fixture_page_http', Path(__file__).with_name('test_console_cedule.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
client_crm, planning = base.client_crm, base.planning
FICTIF = True
URL = '/crm/cedule?debut_semaine=2030-06-03'


def _lien(page, label):
    resultat = re.search(r'<a href="([^"]+)">'+label+r'</a>', page.text)
    return html.unescape(resultat[1]) if resultat else None


def _grande_fixture():
    chemin = Path(__file__).parents[1]/'departments/m04-field-ops/tests/test_pages_semaine.py'
    spec = importlib.util.spec_from_file_location('fixture_grand_carnet_http', chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._registre_grand_carnet()


def test_grand_carnet_sqlite_toutes_pages_independantes_sans_ecriture(client_crm, session):
    reg = _grande_fixture()
    with session():
        durable = stockage.maillons('m04-field-ops', 'principal')
        for maillon in reg.lire():
            durable.append(maillon)
    base.base._connecter(client_crm, 'admin.fictif')
    avant = base.base._instantane_base(session)
    page = client_crm.get(URL)
    assert page.status_code == 200, page.text
    dates, non_dates, pages = [], [], 0
    while True:
        dates += re.findall('data-intervention="([^"]+)"', page.text)
        lien = _lien(page, 'Page suivante — Créneaux')
        pages += 1
        assert pages <= 20
        if not lien:
            break
        assert parse_qs(urlsplit(lien).query)['offset_sans_date'] == ['0']
        page = client_crm.get('https://testserver'+lien)
        assert page.status_code == 200, page.text
    assert len(dates) == len(set(dates)) > 200
    dernier_offset = str((pages-1)*25)
    pages = 0
    while True:
        non_dates += re.findall(r'<li>Intervention ([^< ]+) ·', page.text)
        lien = _lien(page, 'Page suivante — Sans date')
        pages += 1
        assert pages <= 10
        if not lien:
            break
        assert parse_qs(urlsplit(lien).query)['offset_interventions'] == [dernier_offset]
        page = client_crm.get('https://testserver'+lien)
        assert page.status_code == 200, page.text
    assert len(non_dates) == len(set(non_dates)) > 50
    assert not set(non_dates).intersection(dates)
    assert 'Page précédente — Créneaux' in page.text and 'Page précédente — Sans date' in page.text
    assert page.headers['cache-control'] == 'no-store'
    assert base.base._instantane_base(session) == avant


def test_source_changee_refuse_et_propose_recommencer(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    with session():
        source = base.terrain._registre().tete()
        etats.transitionner(next(iter(planning[1].values())), 'reportee', base.terrain._registre(),
                           base.terrain.RECU_LE.isoformat(), motif='meteo')
    avant = base.base._instantane_base(session)
    page = client_crm.get(URL+'&source_attendue='+source)
    assert page.status_code == 409
    assert 'La cédule a changé' in page.text and 'Recommencer la lecture' in page.text
    assert 'data-intervention=' not in page.text
    assert client_crm.get(URL).status_code == 200
    assert base.base._instantane_base(session) == avant


@pytest.mark.parametrize('query', [
    '&offset_interventions=25', '&offset_sans_date=-25', '&offset_sans_date=1',
    '&offset_sans_date=025', '&offset_interventions=true', '&offset_interventions=10025',
    '&offset_interventions=0&offset_interventions=25', '&source_attendue=',
    '&source_attendue='+'z'*64, '&inconnu=1',
])
def test_arguments_stricts(client_crm, session, query):
    base.base._connecter(client_crm, 'admin.fictif')
    assert client_crm.get(URL+query).status_code == 400


def test_continuation_requiert_semaine_et_source_et_refuse_hors_fin(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    with session():
        tete = base.terrain._registre().tete()
    assert client_crm.get('/crm/cedule?source_attendue='+tete).status_code == 400
    assert client_crm.get(URL+'&offset_interventions=25&source_attendue='+tete).status_code == 400


def test_rendu_refuse_pages_incoherentes(planning, session):
    from m4_field_ops.pages_semaine import lire

    with session():
        vue = lire(base.terrain._registre(), '2030-06-03')['resultat']
    for champ, valeur in [('taille_page', True), ('offset_sans_date', True), ('source_nombre', -1),
                          ('source_tete', 'x'), ('total_interventions', 100), ('offset_interventions', 25)]:
        faux = deepcopy(vue)
        faux[champ] = valeur
        with pytest.raises(ValueError):
            cedule_ui.contenu(faux, set(), '')


def test_ports_generiques_restent_fermes(session):
    from opsys.capacites import Capacites
    from opsys.departements import charger_departements

    deps = charger_departements(Path(__file__).parents[1]/'departments')
    cap = Capacites(deps, session, filtre={'m04-field-ops'}, memoire=False)
    attendu = {'ok': False, 'erreur': 'port_console_prive_requis'}
    nom = 'm4_lire_page_cedule_semaine'
    args = {'debut_semaine': '2030-06-03'}
    assert cap.appeler(nom, args) == attendu
    assert cap.appeler_profil_runtime(nom, args, None, None,
                                     profile_id='fictif', profile_revision=1, server='opsys_m4') == attendu


def test_badges_ne_rechargent_pas_principal_par_intervention(client_crm, planning, session):
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    base.base._connecter(client_crm, 'admin.fictif')
    lectures = []

    def observer(cnx, cursor, statement, parameters, context, executemany):
        if (statement.startswith('SELECT registres_maillons.maillon')
                and 'm04-field-ops' in parameters and 'principal' in parameters):
            lectures.append(statement)

    event.listen(Engine, 'before_cursor_execute', observer)
    try:
        page = client_crm.get(URL)
    finally:
        event.remove(Engine, 'before_cursor_execute', observer)
    assert page.status_code == 200, page.text
    # Une lecture pour la page, une par famille de badges ; marge pour garde de source.
    assert len(lectures) <= 6, len(lectures)
