"""CRM01 couleurs : vraie cédule SQLite/HTTP; acteurs et chantiers fictifs."""
import html
import importlib.util
import re
from pathlib import Path
from urllib.parse import urlencode

import pytest
from m4_field_ops import calendrier_civil, etats

from opsys import identite, stockage
from opsys.console import annotations_cedule_ui as notes
from opsys.console import couleurs_cedule_ui as ui

spec = importlib.util.spec_from_file_location(
    'fixture_couleurs', Path(__file__).with_name('test_console_annotations_cedule.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
client_crm, planning = base.client_crm, base.planning
FICTIF = True


def _url(session, planning):
    return ui.url(base._ancre(session, planning), '')


def _champs(client, **kw):
    return {'csrf': client.get('/api/session').json()['csrf'], 'couleur': 'violet',
            'revision_attendue': '0', 'mutation_id': 'couleur-fictive-1', **kw}


def _couleurs(session):
    with session():
        return list(stockage.maillons('m04-field-ops', 'couleurs_calendrier'))


def test_couleur_exacte_historique_rejeu_et_retrait_sans_changement_metier(client_crm, planning, session):
    base.base.base._connecter(client_crm, 'admin.fictif')
    cible, champs = _url(session, planning), _champs(client_crm)
    avant = base.base.base._instantane_base(session)
    page = client_crm.get(cible)
    assert page.status_code == 200 and 'Sans repère' in page.text
    assert base.base.base._instantane_base(session) == avant
    with session():
        terrain_avant = base.base.terrain._maillons()
    assert client_crm.post(cible, data=champs, follow_redirects=False).status_code == 303
    couleur = _couleurs(session)[0]
    assert couleur['ancre'] == base._ancre(session, planning)
    assert couleur['auteur'] == {'personne': 'admin.fictif', 'role': 'admin'}
    with session():
        assert base.base.terrain._maillons() == terrain_avant
    assert base._notes(session) == []
    page = client_crm.get(cible)
    assert page.status_code == 200 and couleur['ligne_id'] in page.text and 'admin.fictif' in page.text
    assert page.headers['cache-control'] == 'no-store'
    semaine = client_crm.get(base.base.SEMAINE)
    assert semaine.status_code == 200 and 'repere-violet' in semaine.text and 'Repère : Violet' in semaine.text
    assert 'Date interne confirmée' in semaine.text
    apres = base.base.base._instantane_base(session)
    assert client_crm.post(cible, data=champs, follow_redirects=False).status_code == 303
    assert base.base.base._instantane_base(session) == apres
    for kw in [{'couleur': 'rose'}, {'mutation_id': 'autre-fictif'}]:
        assert client_crm.post(cible, data={**champs, **kw}, follow_redirects=False).status_code == 409
        assert base.base.base._instantane_base(session) == apres
    assert client_crm.post(cible, data={**champs, 'couleur': 'aucune', 'revision_attendue': '1',
                                     'mutation_id': 'retrait-fictif'}, follow_redirects=False).status_code == 303
    assert len(_couleurs(session)) == 2
    assert 'Repère : Violet' in client_crm.get(cible).text  # historique conservé
    assert 'repere-violet' not in client_crm.get(base.base.SEMAINE).text


@pytest.mark.parametrize('acteur', ['employe', 'nathan'])
def test_non_admin_refuse(client_crm, planning, session, acteur):
    base.base.base._connecter(client_crm, acteur)
    avant = base.base.base._instantane_base(session)
    cible = _url(session, planning)
    assert client_crm.get(cible).status_code == 403
    assert client_crm.post(cible, data=_champs(client_crm)).status_code == 403
    assert base.base.base._instantane_base(session) == avant


def test_rejeu_apres_revocation_refuse(client_crm, planning, session):
    base.base.base._connecter(client_crm, 'admin.fictif')
    cible, champs = _url(session, planning), _champs(client_crm)
    assert client_crm.post(cible, data=champs, follow_redirects=False).status_code == 303
    with session() as cnx:
        identite.ajouter_role(cnx, 'admin.fictif', 'nathan_owner')
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = base.base.base._instantane_base(session)
    assert client_crm.get(cible).status_code == 403
    assert client_crm.post(cible, data=champs).status_code == 403
    assert base.base.base._instantane_base(session) == avant


def test_redatation_sans_transfert_et_rejeu_historique(client_crm, planning, session):
    base.base.base._connecter(client_crm, 'admin.fictif')
    cible, champs = _url(session, planning), _champs(client_crm)
    assert client_crm.post(cible, data=champs, follow_redirects=False).status_code == 303
    with session():
        calendrier_civil.confirmer(base.base.terrain._registre(), planning[2]['plan_id'], {'0': '2030-06-10'},
                                   1, 'admin.fictif', base.base.terrain.RECU_LE.isoformat())
    avant = base.base.base._instantane_base(session)
    page = client_crm.get(cible)
    assert page.status_code == 200 and 'Ancien créneau' in page.text and 'Repère : Violet' in page.text
    assert 'name="couleur"' not in page.text
    assert client_crm.post(cible, data=champs, follow_redirects=False).status_code == 303
    assert client_crm.post(cible, data={**champs, 'revision_attendue': '1', 'mutation_id': 'nouveau'},
                           follow_redirects=False).status_code == 409
    assert base.base.base._instantane_base(session) == avant
    page = client_crm.get('/crm/cedule?debut_semaine=2030-06-10')
    assert page.status_code == 200 and 'repere-violet' not in page.text and 'Sans repère' in page.text


def test_repere_vert_ne_masque_pas_report(client_crm, planning, session):
    base.base.base._connecter(client_crm, 'admin.fictif')
    with session():
        etats.transitionner(planning[1]['lead-fictif-001'], 'reportee', base.base.terrain._registre(),
                           base.base.terrain.RECU_LE.isoformat(), motif='meteo')
        avant = base.base.terrain._maillons()
    assert client_crm.post(_url(session, planning), data=_champs(client_crm, couleur='vert'),
                           follow_redirects=False).status_code == 303
    with session():
        assert base.base.terrain._maillons() == avant
    page = client_crm.get(base.base.SEMAINE)
    assert page.status_code == 200
    assert 'Repère : Vert' in page.text and 'cedule-perimee' in page.text
    assert 'Reporté' in page.text and 'À reconfirmer — ancien créneau' in page.text


def test_csrf_palette_injection_et_ancre_forgee(client_crm, planning, session):
    base.base.base._connecter(client_crm, 'admin.fictif')
    cible, champs = _url(session, planning), _champs(client_crm)
    avant = base.base.base._instantane_base(session)
    for kw, code in [({'csrf': 'faux'}, 403), ({'auteur': 'usurpe'}, 400), ({'couleur': ''}, 400),
                     ({'couleur': 'violet" style="background:red'}, 400), ({'couleur': '#fff'}, 400),
                     ({'revision_attendue': 'true'}, 400)]:
        assert client_crm.post(cible, data={**champs, **kw}).status_code == code
    assert client_crm.post(cible, content=urlencode(champs)+'&couleur=vert',
                           headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 400
    a = base._ancre(session, planning)
    assert client_crm.post(ui.url({**a, 'source_ligne_id': '0'*64}, ''), data=champs).status_code in {400, 409, 503}
    assert base.base.base._instantane_base(session) == avant
    with pytest.raises(ValueError):
        ui.marqueur('<img src=x>')


def test_carte_formulaire_complet_et_legend(client_crm, planning, session):
    base.base.base._connecter(client_crm, 'admin.fictif')
    semaine = client_crm.get(base.base.SEMAINE)
    liens = re.findall(r'href="([^"]+)" aria-label="Couleur de ce créneau"', semaine.text)
    assert len(liens) == 3
    page = client_crm.get('https://testserver'+html.unescape(liens[0]))
    assert page.status_code == 200
    champs = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', page.text))
    assert set(re.findall(r'<option value="([^"]+)"', page.text)) == set(ui.palette())
    action = html.unescape(re.search(r'<form method="post" action="([^"]+)"', page.text)[1])
    assert client_crm.post('https://testserver'+action, data={**champs, 'couleur': 'rose'},
                           follow_redirects=False).status_code == 303


def _direct(session, ancre, cle, quota=65536):
    from datetime import UTC, datetime

    from m4_field_ops import outils

    from opsys import contexte, idempotence

    now = datetime(2030, 6, 1, tzinfo=UTC)
    meta = idempotence.Meta(cle, 'console:admin.fictif', now.isoformat())
    with (session(),
          contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')),
          contexte.appeler_en_tant_que('m04-field-ops', origine='console'), contexte.sortie_bornee(quota),
          outils.contexte_annotation_calendrier(meta),
          contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, now, now))):
        return outils.definir_couleur_calendrier(ancre, 'violet', 0)


def test_quota_et_rollback_audit(client_crm, planning, session, monkeypatch):
    from opsys import etat

    a, avant = base._ancre(session, planning), base.base.base._instantane_base(session)
    assert _direct(session, a, 'quota-fictif', 10)['accepte'] is False
    assert base.base.base._instantane_base(session) == avant

    def echouer(*args, **kwargs):
        raise RuntimeError('audit fictif indisponible')

    monkeypatch.setattr(etat, 'journaliser', echouer)
    with pytest.raises(RuntimeError, match='audit fictif'):
        _direct(session, a, 'rollback-fictif')
    assert base.base.base._instantane_base(session) == avant


def test_concurrence_une_couleur_gagne(client_crm, planning, session):
    from concurrent.futures import ThreadPoolExecutor

    a = base._ancre(session, planning)
    with ThreadPoolExecutor(max_workers=2) as pool:
        fs = [pool.submit(_direct, session, a, 'editeur-fictif-'+str(i)) for i in range(2)]
        resultats = [f.result(timeout=10) for f in fs]
    assert sorted(r['accepte'] for r in resultats) == [False, True]
    assert len(_couleurs(session)) == 1


def test_generique_et_profil_fermes_avant_approbation(client_crm, planning, session):
    from opsys.capacites import Capacites
    from opsys.departements import charger_departements

    deps = charger_departements(Path(__file__).parents[1]/'departments')
    cap = Capacites(deps, session, filtre={'m04-field-ops'}, memoire=False)
    args = {'ancre': base._ancre(session, planning), 'couleur': 'violet', 'revision_attendue': 0}
    avant = base.base.base._instantane_base(session)
    for nom in ['m4_definir_couleur_calendrier', 'm4_lire_couleurs_calendrier', 'm4_resumer_couleurs_calendrier']:
        attendu = {'ok': False, 'erreur': 'port_console_prive_requis'}
        assert cap.appeler(nom, args) == attendu
        assert cap.appeler_profil_runtime(nom, args, None, None,
                                         profile_id='fictif', profile_revision=1, server='opsys_m4') == attendu
    assert base.base.base._instantane_base(session) == avant


def test_formulaires_absents_si_backend_non_qualifie(client_crm, planning, session, monkeypatch):
    # Test de l'UX de fermeture, pas une qualification PostgreSQL.
    base.base.base._connecter(client_crm, 'admin.fictif')
    monkeypatch.setattr(notes, 'ecriture_qualifiee', lambda factory: False)
    for chemin, champ in [(_url(session, planning), 'couleur'), (base._url(session, planning), 'texte_libre')]:
        page = client_crm.get(chemin)
        assert page.status_code == 200 and 'Lecture seule' in page.text
        assert f'name="{champ}"' not in page.text
