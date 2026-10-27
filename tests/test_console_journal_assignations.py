"""fictif: true — assignations SQL/HTTP, sans composition réelle ni présence déduites."""
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import etats
from m4_field_ops.registre import Registre

from opsys import stockage
from opsys.console import journal_equipes
from opsys.departements import charger_departements

spec = importlib.util.spec_from_file_location('journal_assignations_sql_fixture',
    Path(__file__).with_name('test_console_journal_equipes.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, planning = f.client_crm, f.planning
FICTIF = True
D, SUIVANT = '2030-06-03', '2030-06-07'


def decisions(planning, session):
    _, ids, _, _ = planning
    iid = next(iter(ids.values()))
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        a, v = etats.assigner_technicien(iid, '<T1-fictif>', reg, D + 'T08:00:00-04:00')
        assert v is None
        assert etats.transitionner(iid, 'reportee', reg, D + 'T09:00:00-04:00', motif='meteo')[1] is None
        assert etats.transitionner(iid, 'planifiee', reg, SUIVANT + 'T07:00:00-04:00')[1] is None
        assert etats.assigner_technicien(iid, 'T2-fictif', reg, SUIVANT + 'T08:00:00-04:00')[1] is None
        assert etats.transitionner(iid, 'en_route', reg, SUIVANT + 'T08:30:00-04:00',
            assignation={'intervention_id': iid, 'technicien_id': 'T2-fictif'})[1] is None
    return iid, a['ligne_id']


def test_decisions_historiques_sql_http_minimisees_sans_ecriture(client_crm, planning, session):
    import re

    iid, source = decisions(planning, session)
    f.f.base._connecter(client_crm, 'admin.fictif')
    avant = f.f.base._instantane_base(session)
    with session() as cnx:
        vue = journal_equipes.lire(cnx, charger_departements(), f.AUTH, D)
    assert any(x.get('technicien_assigne') == '<T1-fictif>' for x in vue['lignes'])
    r = client_crm.get('/crm/journal-equipes?jour=' + D)
    assert r.status_code == 200, r.text
    assert 'Technicien assigné' in r.text and 'Décision d’assignation' in r.text
    assert '&lt;T1-fictif&gt;' in r.text and '<T1-fictif>' not in r.text and iid in r.text
    ligne = next(x for x in re.findall(r'<tr>.*?</tr>', r.text) if source in x)
    assert 'Notes et historique' not in ligne and 'Non applicable' in ligne
    r = client_crm.get('/crm/journal-equipes?jour=' + SUIVANT)
    assert r.status_code == 200 and r.text.count('T2-fictif') == 2, r.text
    assert 'Décision d’assignation' in r.text and 'Départ consigné' in r.text
    assert '&lt;T1-fictif&gt;' not in r.text
    assert f.f.base._instantane_base(session) == avant


@pytest.mark.parametrize('personne', ['employe', 'nathan'])
def test_decisions_affectation_fermees_aux_non_admin(client_crm, planning, session, personne):
    iid, _ = decisions(planning, session)
    f.f.base._connecter(client_crm, personne)
    avant = f.f.base._instantane_base(session)
    r = client_crm.get('/crm/journal-equipes?jour=' + D)
    assert r.status_code == 403 and iid not in r.text and 'T1-fictif' not in r.text
    assert f.f.base._instantane_base(session) == avant



def test_identifiant_historique_espaces_signale_sans_normalisation_sql(client_crm, planning, session):
    _, ids, _, _ = planning
    iid = next(iter(ids.values()))
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        assert etats.assigner_technicien(iid, '   ', reg, D + 'T08:00:00-04:00')[1] is None
    f.f.base._connecter(client_crm, 'admin.fictif')
    avant = f.f.base._instantane_base(session)
    with session() as cnx:
        vue = journal_equipes.lire(cnx, charger_departements(), f.AUTH, D)
    assert any(x.get('technicien_assigne') == '   ' for x in vue['lignes'])
    r = client_crm.get('/crm/journal-equipes?jour=' + D)
    assert r.status_code == 200 and 'Identifiant à vérifier (espaces uniquement)' in r.text
    assert f.f.base._instantane_base(session) == avant
