"""fictif: true — interruption de visite, interface privée versionnée."""
import importlib.util
from contextlib import ExitStack
from pathlib import Path

import pytest
from m4_field_ops.outils import outils

from opsys import contexte
from opsys.outils import executer, executer_atomique

spec = importlib.util.spec_from_file_location('fixture_console_report_v2',
    Path(__file__).with_name('test_console_cedule.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, planning = f.client_crm, f.planning


def test_contrats_report_v1_et_interruption_privee_v2_distincts():
    par_nom = {outil.nom: outil for outil in outils()}
    ancien = par_nom['m4_signaler_report']
    assert set(ancien.parametres['properties']) == {'intervention_id', 'motif', 'horodatage'}
    assert ancien.parametres['required'] == ['intervention_id', 'motif', 'horodatage']
    assert ancien.roles_appareil == frozenset({'employee', 'admin'})
    nouveau = par_nom['m4_interrompre_visite_console_v2']
    assert set(nouveau.parametres['properties']) == {
        'intervention_id', 'motif', 'horodatage', 'visite_id', 'source_attendue'}
    assert set(nouveau.parametres['required']) == set(nouveau.parametres['properties'])
    assert nouveau.parametres['additionalProperties'] is False
    assert nouveau.roles_appareil == frozenset()
    assert nouveau.autonomie.value == 'T1'


def test_interruption_privee_v2_refuse_sans_identite_console():
    nouveau = next(o for o in outils() if o.nom == 'm4_interrompre_visite_console_v2')
    r = executer(nouveau, {'intervention_id': 'chantier-fictif', 'motif': 'meteo',
        'horodatage': '2030-06-03T12:02:00-04:00', 'visite_id': 'a' * 64, 'source_attendue': 'b' * 64})
    assert r['ok'] is True and r['resultat']['accepte'] is False


@pytest.mark.parametrize('nom', ['m4_interrompre_visite_console_v2', 'm4_replanifier_visite_console'])
def test_mutations_console_exigent_reception_serveur(planning, session, nom):
    iid = planning[1]['lead-fictif-001']
    args = {'intervention_id': iid, 'visite_id': 'a' * 64, 'source_attendue': 'b' * 64,
            'horodatage': '2030-06-03T12:02:00-04:00'}
    args.update({'motif': 'meteo'} if nom == 'm4_interrompre_visite_console_v2' else {'report_id': 'c' * 64})
    outil = next(o for o in outils() if o.nom == nom)
    avant = f.base._instantane_base(session)
    with (session(),
          contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')),
          contexte.appeler_en_tant_que('m04-field-ops', origine='console')):
        resultat = executer_atomique(outil, args)
    assert resultat['ok'] is True and resultat['resultat']['accepte'] is False
    assert resultat['resultat']['verdict']['detail'] == 'HORODATAGE-SERVEUR-REQUIS'
    assert f.base._instantane_base(session) == avant


@pytest.mark.parametrize('source,origine,mcp', [
    ('appareil', 'm04-field-ops', False),
    ('console', 'm04-field-ops', False),
    ('console', 'console', True),
])
@pytest.mark.parametrize('nom', ['m4_interrompre_visite_console_v2', 'm4_replanifier_visite_console',
                                 'm4_lire_visites_console'])
def test_ports_refusent_transport_non_console_meme_admin_sql(planning, session, nom, source, origine, mcp):
    iid = planning[1]['lead-fictif-001']
    args = {'intervention_id': iid}
    if nom != 'm4_lire_visites_console':
        args.update(visite_id='a' * 64, source_attendue='b' * 64, horodatage='2030-06-03T12:02:00-04:00')
        args.update({'motif': 'meteo'} if nom == 'm4_interrompre_visite_console_v2' else {'report_id': 'c' * 64})
    outil = next(o for o in outils() if o.nom == nom)
    avant = f.base._instantane_base(session)
    with session(), ExitStack() as pile:
        pile.enter_context(contexte.appele_par_appareil(
            contexte.IdentiteAppelante('admin.fictif', 'admin', source=source)))
        pile.enter_context(contexte.appeler_en_tant_que('m04-field-ops', origine=origine))
        if mcp:
            pile.enter_context(contexte.transport_mcp())
        resultat = executer_atomique(outil, args)
    assert resultat['ok'] is True and resultat['resultat']['accepte'] is False
    verdict = resultat['resultat']['verdict']
    assert (verdict['code'], verdict['detail']) in {
        ('REJ-CONTRAT-INVALIDE', 'IDENTITE'),
        ('REJ-IDENTITE-APPAREIL-INVALIDE', 'admin console actif requis'),
    }
    assert f.base._instantane_base(session) == avant
