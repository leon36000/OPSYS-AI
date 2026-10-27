"""fictif: true — lecture SQL/HTTP d'écarts écrits par les fonctions propriétaires M4.

Fixture canonique durable ; pas de nouvelle preuve MCP/appareil ni facturation.
"""
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import ecarts, etats, pointage
from m4_field_ops.registre import Registre

from opsys import stockage
from opsys.console import journal_equipes
from opsys.departements import charger_departements


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


f = charger('journal_ecarts_http_fixture', Path(__file__).with_name('test_console_journal_equipes.py'))
m = charger('journal_ecarts_metier_fixture', Path(__file__).parents[1] /
            'departments/m04-field-ops/tests/test_ecarts.py')
client_crm = f.client_crm
FICTIF = True


def monde_sql(session, decision='validee'):
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        acc, ver = etats.inscrire_intervention(m.CONTRAT_VALIDE, m.MARQUEUR_VALIDE, reg, m.H1, m.SEL)
        assert ver is None, ver
        iid = acc['intervention_id']
        assignation = {'intervention_id': iid, 'technicien_id': 'T1'}
        assert etats.transitionner(iid, 'en_route', reg, m.H2, assignation=assignation)[1] is None
        for action, instant in [('arrivee', m.H2), ('depart', m.H3)]:
            assert pointage.enregistrer_pointage(iid, 'T1', action, instant, m.GPS_PROCHE, m.ATTESTATION,
                assignation, m.FENETRE, m.REFERENTIEL, m.VILLE, m.SEL, reg)[1] is None
        acc, ver = ecarts.creer_demande_ecart(iid, m.VERSION_PREVUE,
            {'duree_minutes': 240, 'perimetre': 'PERIMETRE_PRIVE_FICTIF', 'materiaux': ['MATERIAU_PRIVE_FICTIF']},
            '2025-06-02T12:00:00+00:00', reg)
        assert ver is None, ver
        demande = acc['demande_id']
        assert ecarts.resoudre_demande(demande, decision, '2025-06-03T12:00:00+00:00', reg,
                                      motif='MOTIF_PRIVE_FICTIF')[1] is None
    return iid, demande


def test_ecarts_sql_vrais_t0_et_http_sans_ecriture(client_crm, session):
    _, demande = monde_sql(session)
    f.f.base._connecter(client_crm, 'admin.fictif')
    avant = f.f.base._instantane_base(session)
    with session() as cnx:
        vue = journal_equipes.lire(cnx, charger_departements(), f.AUTH, '2025-06-03')
    assert any(x['type'] == 'ecart_arbitre' and x['demande_id'] == demande for x in vue['lignes'])
    declaration = client_crm.get('/crm/journal-equipes?jour=2025-06-02')
    arbitrage = client_crm.get('/crm/journal-equipes?jour=2025-06-03')
    assert declaration.status_code == arbitrage.status_code == 200, (declaration.text, arbitrage.text)
    assert 'Écart déclaré' in declaration.text and 'En attente d’arbitrage M4' in declaration.text
    assert 'Arbitrage M4 validé' in arbitrage.text and demande in arbitrage.text
    assert 'M3/M5' in arbitrage.text
    for secret in ['PERIMETRE_PRIVE_FICTIF', 'MATERIAU_PRIVE_FICTIF', 'MOTIF_PRIVE_FICTIF', 'latitude']:
        assert secret not in declaration.text + arbitrage.text
    assert 'Notes de cette prévision' not in declaration.text + arbitrage.text
    assert f.f.base._instantane_base(session) == avant


def test_rejet_arbitrage_et_pagination_sql_sans_confusion(client_crm, session):
    import re
    from html import unescape

    _, demande = monde_sql(session, decision='rejetee')
    f.f.base._connecter(client_crm, 'admin.fictif')
    avant = f.f.base._instantane_base(session)
    r = client_crm.get('/crm/journal-equipes?jour=2025-06-03&limite=1')
    pages = []
    while True:
        assert r.status_code == 200, r.text
        pages.append(r.text)
        lien = re.search(r'href="([^"]+)"[^>]*>Page suivante</a>', r.text)
        if lien is None:
            break
        r = client_crm.get(unescape(lien[1]).removeprefix(f.f.base.PREFIXE))
    assert sum('Arbitrage M4 rejeté' in page for page in pages) == 1
    assert any(demande in page for page in pages)
    assert not any('Arbitrage M4 validé' in page for page in pages)
    assert f.f.base._instantane_base(session) == avant


@pytest.mark.parametrize('personne', ['employe', 'nathan'])
def test_ecarts_ne_devoilent_pas_les_references_sans_admin(client_crm, session, personne):
    iid, demande = monde_sql(session)
    f.f.base._connecter(client_crm, personne)
    avant = f.f.base._instantane_base(session)
    r = client_crm.get('/crm/journal-equipes?jour=2025-06-03')
    assert r.status_code == 403 and demande not in r.text and iid not in r.text
    assert f.f.base._instantane_base(session) == avant
