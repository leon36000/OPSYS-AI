"""fictif: true — un badge M10 exige publication, reçu cohérent et chaîne vérifiée."""
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, update

from opsys import identite, stockage
from opsys.console import catalogue_memoire_ui
from opsys.console.securite import Session
from opsys.departements import charger_departements
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

spec = importlib.util.spec_from_file_location('fixtures_catalogue_memoire',
                                              Path(__file__).with_name('test_cascade_catalogues_m10.py'))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
client_crm = c.client_crm
catalogue = c.catalogue
AUTH = Session('admin.fictif', frozenset({'admin'}), 'csrf-fictif', 4102444800)


def preparer(client, session):
    action, choix, ancre, materiau, _ = c.h.preparer_lignes(client, session)
    assert client.post(action, data=choix, follow_redirects=False).status_code == 303
    base = '/crm/modeles-soumission/' + ancre['modele_id']
    return [materiau, base + '?version=1', base + '/lignes?' + urlencode(ancre),
            action + '?' + urlencode(ancre)]


def test_publication_puis_recu_et_memoire_qualifient_badge(catalogue, session):
    routes = preparer(catalogue, session)
    avant = c.h.h.p.m.base._instantane_base(session)
    for route in routes:
        page = catalogue.get(route)
        assert page.status_code == 200
        assert 'data-memoire="EN_ATTENTE"' in page.text
    assert c.h.h.p.m.base._instantane_base(session) == avant
    total = c.b._drainer(charger_departements(), datetime(2031, 1, 1, tzinfo=UTC))
    assert total['echecs'] == total['quarantaines'] == 0
    avant = c.h.h.p.m.base._instantane_base(session)
    for route in routes:
        page = catalogue.get(route)
        assert 'data-memoire="MEMORISE"' in page.text
        assert 'Référence M10 mémorisée et vérifiée' in page.text
    assert c.h.h.p.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('cas,etat', [('absent', 'EN_ATTENTE'), ('echec', 'ECHEC_LIVRAISON'),
                                     ('quarantaine', 'QUARANTAINE'), ('faux_resultat', 'CONFLIT'),
                                     ('corruption', 'A_VERIFIER')])
def test_badge_ne_confond_pas_memoire_et_recu(catalogue, session, cas, etat):
    routes = preparer(catalogue, session)
    c.b._drainer(charger_departements(), c.INSTANT)
    with session() as cnx:
        if cas == 'corruption':
            stockage.maillons('m10-memoire', c.references.REGISTRE).append({'prive': 'CANARI_FICTIF'})
        else:
            if cas == 'absent':
                cnx.execute(delete(EVENEMENTS_RECUS).where(EVENEMENTS_RECUS.c.consommateur == 'm10-memoire'))
            elif cas == 'faux_resultat':
                cnx.execute(update(EVENEMENTS_RECUS).where(EVENEMENTS_RECUS.c.consommateur == 'm10-memoire').values(
                    resultat=codec.encoder({'memorise': True, 'ligne_id': 'CANARI_FICTIF'})))
            else:
                cnx.execute(update(EVENEMENTS_RECUS).where(EVENEMENTS_RECUS.c.consommateur == 'm10-memoire').values(
                    statut=cas))
    avant = c.h.h.p.m.base._instantane_base(session)
    for route in routes:
        page = catalogue.get(route)
        assert page.status_code == 200
        assert f'data-memoire="{etat}"' in page.text
        assert 'CANARI_FICTIF' not in page.text
    assert c.h.h.p.m.base._instantane_base(session) == avant


def test_version_sans_publication_reste_historique_sans_rattrapage(catalogue, session):
    routes = preparer(catalogue, session)
    with session() as cnx:
        cnx.execute(delete(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement.in_(c.TYPES)))
    avant = c.h.h.p.m.base._instantane_base(session)
    for route in routes:
        assert 'data-memoire="NON_PUBLIE"' in catalogue.get(route).text
    assert c.h.h.p.m.base._instantane_base(session) == avant
    with session() as cnx:
        assert cnx.execute(select(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement.in_(c.TYPES))).all() == []


def test_facade_revalide_admin_avant_lecture_m10(catalogue, session, monkeypatch):
    def interdit(*args, **kw):
        raise AssertionError('Aucune lecture M10 sans autorité')
    monkeypatch.setattr(catalogue_memoire_ui.catalogues_memoire, 'consulter', interdit)
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    with pytest.raises(HTTPException) as erreur:
        catalogue_memoire_ui.indicateur(AUTH, session, 'm03-estimation', 'modeles_soumission', '0'*64)
    assert erreur.value.status_code == 403
