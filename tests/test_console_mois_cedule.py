"""Trois mois M4 via vraie chaîne SQLite et HTTP; toutes les données sont fictives."""
import html
import importlib.util
import re
from pathlib import Path

import pytest
from m4_field_ops import calendrier_civil, etats

from opsys import identite
from opsys.console import mois_cedule_ui as ui

spec = importlib.util.spec_from_file_location('fixture_multimois', Path(__file__).with_name('test_console_cedule.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
client_crm, planning = base.client_crm, base.planning
FICTIF = True
URL = '/crm/cedule/mois?premier_mois=2030-06'


def test_apercu_reel_sans_ecriture_sans_date_compte_une_fois(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    avant = base.base._instantane_base(session)
    with session():
        tete = base.terrain._registre().tete()
    page = client_crm.get(URL)
    assert page.status_code == 200, page.text
    assert page.headers['cache-control'] == 'no-store'
    assert '3 créneau(x) daté(s) sur les trois mois.' in page.text
    assert 'Sans date dans tout le carnet : 1' in page.text
    assert page.text.count('Sans date dans tout le carnet') == 1
    assert 'Juin 2030' in page.text and 'Juillet 2030' in page.text and 'Août 2030' in page.text
    assert 'une disponibilité' in page.text and tete in page.text
    assert 'lead-fictif-001' not in page.text  # aucun client dans la projection mensuelle
    dates = re.findall(r'data-jour="([^"]+)"', page.text)
    assert len(dates) == len(set(dates)) == 92
    assert dates[0] == '2030-06-01' and dates[-1] == '2030-08-31'
    assert base.base._instantane_base(session) == avant
    # Le lien complet fonctionne avec le préfixe réel de la console.
    lien = re.search(r'href="([^"]+)" aria-label="3 Juin 2030 : 3 confirmé', page.text)[1]
    semaine = client_crm.get('https://testserver'+html.unescape(lien))
    assert semaine.status_code == 200
    assert 'data-intervention="'+planning[1]['lead-fictif-001']+'"' in semaine.text
    assert 'Vue trois mois' in semaine.text


def test_report_et_redatation_recalculent_le_meme_snapshot(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    with session():
        etats.transitionner(planning[1]['lead-fictif-001'], 'reportee', base.terrain._registre(),
                           base.terrain.RECU_LE.isoformat(), motif='meteo')
    avant = base.base._instantane_base(session)
    page = client_crm.get(URL)
    assert page.status_code == 200
    assert '2 date(s) interne(s) confirmée(s) · 1 à reconfirmer' in page.text
    assert 'mois-a-reconfirmer' in page.text
    assert base.base._instantane_base(session) == avant


def test_changement_mois_ne_double_pas_ancienne_date(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    with session():
        calendrier_civil.confirmer(base.terrain._registre(), planning[2]['plan_id'], {'0': '2030-07-01'},
                                   1, 'admin.fictif', base.terrain.RECU_LE.isoformat())
    page = client_crm.get(URL)
    assert page.status_code == 200
    assert '3 créneau(x) daté(s) sur les trois mois.' in page.text
    assert '3 Juin 2030 : 0 confirmé(s)' in page.text
    assert '1 Juillet 2030 : 3 confirmé(s)' in page.text


@pytest.mark.parametrize('acteur', ['employe', 'nathan'])
def test_lecture_reservee_admin(client_crm, planning, session, acteur):
    base.base._connecter(client_crm, acteur)
    avant = base.base._instantane_base(session)
    assert client_crm.get(URL).status_code == 403
    assert base.base._instantane_base(session) == avant


def test_anonyme_et_admin_revoque(client_crm, planning, session):
    assert client_crm.get(URL, follow_redirects=False).status_code == 303
    base.base._connecter(client_crm, 'admin.fictif')
    with session() as cnx:
        identite.ajouter_role(cnx, 'admin.fictif', 'nathan_owner')
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    assert client_crm.get(URL).status_code == 403


@pytest.mark.parametrize('requete', ['2030-6', '2030-13', '1899-12', '2199-11', '2030-06-01', '', 'x'*5000])
def test_mois_invalide(client_crm, session, requete):
    base.base._connecter(client_crm, 'admin.fictif')
    avant = base.base._instantane_base(session)
    assert client_crm.get('/crm/cedule/mois', params={'premier_mois': requete}).status_code == 400
    assert client_crm.get(URL+'&premier_mois=2030-07').status_code == 400
    assert client_crm.get(URL+'&inconnu=1').status_code == 400
    assert base.base._instantane_base(session) == avant


def test_vide_reel_bissextile_et_bornes_navigation(client_crm, session):
    base.base._connecter(client_crm, 'admin.fictif')
    avant = base.base._instantane_base(session)
    page = client_crm.get('/crm/cedule/mois?premier_mois=2031-12')
    assert page.status_code == 200, page.text
    assert 'data-jour="2032-02-29"' in page.text and 'Registre vide' in page.text
    assert '0 créneau(x) daté(s) sur les trois mois.' in page.text
    assert 'Sans date dans tout le carnet : 0' in page.text
    bas = client_crm.get('/crm/cedule/mois?premier_mois=1900-01')
    haut = client_crm.get('/crm/cedule/mois?premier_mois=2199-10')
    assert bas.status_code == haut.status_code == 200
    assert 'Mois précédent' not in bas.text and 'Mois suivant' not in haut.text
    assert 'Détail semaine hors bornes' in haut.text
    assert base.base._instantane_base(session) == avant


def test_vue_malformee_ne_devient_pas_calendrier_vide(client_crm, planning, session, monkeypatch):
    base.base._connecter(client_crm, 'admin.fictif')
    monkeypatch.setattr(ui.notes, 'appeler', lambda *a, **k: {'premier_mois': '2030-06', 'mois': []})
    page = client_crm.get(URL)
    assert page.status_code == 503 and 'Aperçu M4 indisponible' in page.text


def test_totaux_incoherents_refuses_et_warning_echappe(client_crm, planning, session):
    from copy import deepcopy

    from m4_field_ops.apercu_mois import lire

    with session():
        vue = lire(base.terrain._registre(), '2030-06')['resultat']
    vue['avertissements'].append('<script>fictif</script>')
    assert '&lt;script&gt;fictif&lt;/script&gt;' in ui.contenu(vue, '')
    for cle in ['total_interventions', 'source_nombre', 'total_sans_date']:
        faux = deepcopy(vue)
        faux[cle] = True
        with pytest.raises(ValueError):
            ui.contenu(faux, '')
    faux = deepcopy(vue)
    faux['mois'][0]['jours'][2]['total'] += 1
    with pytest.raises(ValueError):
        ui.contenu(faux, '')
    faux = deepcopy(vue)
    faux['mois'][0]['jours'].append(faux['mois'][0]['jours'][0])
    with pytest.raises(ValueError):
        ui.contenu(faux, '')


def test_port_generique_ferme(session):
    from opsys.capacites import Capacites
    from opsys.departements import charger_departements

    deps = charger_departements(Path(__file__).parents[1]/'departments')
    cap = Capacites(deps, session, filtre={'m04-field-ops'}, memoire=False)
    avant = base.base._instantane_base(session)
    attendu = {'ok': False, 'erreur': 'port_console_prive_requis'}
    assert cap.appeler('m4_lire_apercu_mois', {'premier_mois': '2030-06'}) == attendu
    assert cap.appeler_profil_runtime('m4_lire_apercu_mois', {'premier_mois': '2030-06'}, None, None,
                                     profile_id='fictif', profile_revision=1, server='opsys_m4') == attendu
    assert base.base._instantane_base(session) == avant
