"""fictif: true — lien d’un pointage vers les temps de la personne pour le jour civil."""
import importlib.util
import re
from copy import deepcopy
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from m4_field_ops import cedule, etats, pointage
from m4_field_ops.registre import Registre

from opsys import stockage
from opsys.console import journal_equipes
from opsys.departements import charger_departements

spec = importlib.util.spec_from_file_location('journal_temps_fixture',
    Path(__file__).with_name('test_console_journal_equipes_http.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, planning = f.client_crm, f.planning
base = f.f.f.base
FICTIF = True
JOUR = '2030-06-03'
TITRE = 'Temps pointés de cette personne pour le jour'


def inscrire_points(planning, session):
    _, ids, _, _ = planning
    iid = next(iter(ids.values()))
    assignation = dict(intervention_id=iid, technicien_id='employe')
    ville, sel = 'Ville fictive', 'sel.fictif'
    ref = {cedule.tokeniser_ville(sel, ville): dict(latitude=45.5, longitude=-73.5, rayon_km=2)}
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        _, verdict = etats.transitionner(iid, 'en_route', reg, JOUR + 'T19:00:00-04:00', assignation=assignation)
        assert verdict is None
        for action, instant in [('arrivee', '2030-06-04T00:30:00+00:00'), ('depart', '2030-06-04T01:30:00+00:00')]:
            _, verdict = pointage.enregistrer_pointage(iid, 'employe', action, instant,
                dict(latitude=45.5, longitude=-73.5), dict(fictif=True, appareil_id='appareil.prive.fictif'),
                assignation, dict(debut=JOUR + 'T18:00:00-04:00', fin='2030-06-04T04:00:00+00:00'),
                ref, ville, sel, reg)
            assert verdict is None


def test_vrais_pointages_utc_lendemain_lient_jour_montreal_et_apercu_exact(client_crm, planning, session):
    inscrire_points(planning, session)
    base._connecter(client_crm, 'admin.fictif')
    avant = base._instantane_base(session)
    r = client_crm.get('/crm/journal-equipes?jour=' + JOUR)
    assert r.status_code == 200, r.text
    liens = [unescape(x).removeprefix(base.PREFIXE) for x in re.findall(
        r'href="([^"]+)"[^>]*>' + TITRE + r'</a>', r.text)]
    assert len(liens) == 2
    assert all(parse_qs(urlparse(x).query) == dict(jour=[JOUR], personne_id=['employe']) for x in liens)
    apercu = client_crm.get(liens[0])
    assert apercu.status_code == 200 and 'Minutes de travail net après pauses' in apercu.text
    assert '<dd>60</dd>' in apercu.text and '<dd>90</dd>' in apercu.text
    assert 'Aucune ancre de visite démontrée' in r.text and 'Employé FICTIF' not in r.text
    assert '45.5' not in r.text and 'Minutes de travail net après pauses' not in r.text
    assert base._instantane_base(session) == avant


def test_previsions_seules_ne_deviennent_pas_des_temps(client_crm, planning, session):
    base._connecter(client_crm, 'admin.fictif')
    r = client_crm.get('/crm/journal-equipes?jour=' + JOUR)
    assert r.status_code == 200 and TITRE not in r.text
    assert 'name="personne_id"' in r.text and 'Consulter les temps pointés du jour' in r.text


@pytest.mark.parametrize('personne', [' employe', 'employe ', 'T1', 'nom<script>fictif</script>'])
def test_id_historique_non_canonique_signale_sans_normalisation(client_crm, planning, session, personne):
    inscrire_points(planning, session)
    with session() as cnx:
        vue = journal_equipes.lire(cnx, charger_departements(), f.f.AUTH, JOUR)
    original = deepcopy(vue)
    for ligne in vue['lignes']:
        if ligne['type'] == 'pointage':
            ligne['technicien_id'] = personne
    avant = deepcopy(vue)
    html = journal_equipes.contenu(vue, base.PREFIXE, 50)
    assert 'Temps non consultables pour cet identifiant historique' in html and TITRE not in html
    assert vue == avant and original != vue
    assert unescape(personne) not in re.findall(r'href="([^"]+)"', html)
