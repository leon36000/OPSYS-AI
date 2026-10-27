"""CRM-02 : HTML, vraie chaîne M4 et SQLite; toutes les personnes/données sont fictives."""
import html
import importlib.util
import re
from pathlib import Path
from urllib.parse import urlencode

import pytest
from m4_field_ops import calendrier_civil, etats

from opsys import identite, stockage
from opsys.console import annotations_cedule_ui as ui

spec = importlib.util.spec_from_file_location('fixture_annotations', Path(__file__).with_name('test_console_cedule.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
client_crm, planning = base.client_crm, base.planning
FICTIF = True


def _ancre(session, planning):
    with session():
        lignes = calendrier_civil.lire_semaine(base.terrain._registre(), '2030-06-03')['interventions']
    return ui.ancre_de(next(ligne for ligne in lignes if ligne['intervention_id'] == planning[1]['lead-fictif-001']))


def _url(session, planning):
    return ui.url(_ancre(session, planning), '')


def _champs(client, **kw):
    return {'csrf': client.get('/api/session').json()['csrf'], 'texte_libre': 'Note fictive <script>bonjour</script>',
            'revision_attendue': '0', 'mutation_id': 'annotation-fictive-1', **kw}


def _notes(session):
    with session():
        return list(stockage.maillons('m04-field-ops', 'annotations_calendrier'))


def test_note_exacte_badge_historique_et_planning_intact(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    cible = _url(session, planning)
    avant = base.base._instantane_base(session)
    assert client_crm.get(cible).status_code == 200
    assert base.base._instantane_base(session) == avant
    with session():
        terrain_avant = base.terrain._maillons()
    champs = _champs(client_crm)
    r = client_crm.post(cible, data=champs, follow_redirects=False)
    assert r.status_code == 303, r.text
    note = _notes(session)[0]
    assert note['ancre'] == _ancre(session, planning)
    assert note['auteur'] == {'personne': 'admin.fictif', 'role': 'admin'}
    with session():
        assert base.terrain._maillons() == terrain_avant
    page = client_crm.get(cible)
    assert page.status_code == 200, page.text
    assert '<script>bonjour</script>' not in page.text
    assert '&lt;script&gt;bonjour&lt;/script&gt;' in page.text
    assert note['ligne_id'] in page.text and 'admin.fictif' in page.text
    assert page.headers['cache-control'] == 'no-store'
    semaine = client_crm.get(base.SEMAINE)
    assert semaine.status_code == 200, semaine.text
    assert '● Notes : 1' in semaine.text and 'bonjour' not in semaine.text
    apres = base.base._instantane_base(session)
    assert client_crm.post(cible, data=champs, follow_redirects=False).status_code == 303
    assert base.base._instantane_base(session) == apres
    for kw in [{'texte_libre': 'contradiction'}, {'mutation_id': 'autre-fictif'}]:
        r = client_crm.post(cible, data={**champs, **kw}, follow_redirects=False)
        assert r.status_code == 409, r.text
        assert base.base._instantane_base(session) == apres
    assert client_crm.post(cible, data={**champs, 'revision_attendue': '1', 'mutation_id': 'note-2-fictive',
                                     'texte_libre': 'Correction fictive'}, follow_redirects=False).status_code == 303
    assert len(_notes(session)) == 2
    assert 'Révision 2' in client_crm.get(cible).text


@pytest.mark.parametrize('acteur', ['employe', 'nathan'])
def test_non_admin_refuse(client_crm, planning, session, acteur):
    cible = _url(session, planning)
    base.base._connecter(client_crm, acteur)
    avant = base.base._instantane_base(session)
    assert client_crm.get(cible).status_code == 403
    assert client_crm.post(cible, data=_champs(client_crm)).status_code == 403
    assert base.base._instantane_base(session) == avant


def test_rejeu_revoque_ne_lit_ni_necrit(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    cible, champs = _url(session, planning), _champs(client_crm)
    assert client_crm.post(cible, data=champs, follow_redirects=False).status_code == 303
    with session() as cnx:
        identite.ajouter_role(cnx, 'admin.fictif', 'nathan_owner')
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = base.base._instantane_base(session)
    assert client_crm.get(cible).status_code == 403
    assert client_crm.post(cible, data=champs).status_code == 403
    assert base.base._instantane_base(session) == avant


def test_redatation_pas_de_transfert_et_rejeu_historique(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    cible, champs = _url(session, planning), _champs(client_crm)
    assert client_crm.post(cible, data=champs, follow_redirects=False).status_code == 303
    with session():
        calendrier_civil.confirmer(base.terrain._registre(), planning[2]['plan_id'], {'0': '2030-06-10'},
                                   1, 'admin.fictif', base.terrain.RECU_LE.isoformat())
    avant = base.base._instantane_base(session)
    page = client_crm.get(cible)
    assert page.status_code == 200 and 'Ancien créneau' in page.text
    assert 'name="texte_libre"' not in page.text
    assert client_crm.post(cible, data=champs, follow_redirects=False).status_code == 303
    r = client_crm.post(cible, data={**champs, 'revision_attendue': '1', 'mutation_id': 'autre-note'},
                        follow_redirects=False)
    assert r.status_code == 409, r.text
    assert base.base._instantane_base(session) == avant
    page = client_crm.get('/crm/cedule?debut_semaine=2030-06-10')
    assert page.status_code == 200 and '○ Notes : 0 · historique : 1' in page.text


def test_report_annotation_ne_reconfirme_pas(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    cible = _url(session, planning)
    with session():
        etats.transitionner(planning[1]['lead-fictif-001'], 'reportee', base.terrain._registre(),
                           base.terrain.RECU_LE.isoformat(), motif='meteo')
        avant = base.terrain._maillons()
    assert client_crm.post(cible, data=_champs(client_crm), follow_redirects=False).status_code == 303
    with session():
        assert base.terrain._maillons() == avant
    assert 'a_reconfirmer' in client_crm.get(cible).text


def test_csrf_champs_et_limites(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    cible, champs = _url(session, planning), _champs(client_crm)
    avant = base.base._instantane_base(session)
    for kw, code in [({'csrf': 'faux'}, 403), ({'auteur': 'usurpe'}, 400),
                     ({'texte_libre': ''}, 400), ({'texte_libre': 'x'*2001}, 400),
                     ({'revision_attendue': 'true'}, 400), ({'texte_libre': 'nul\x00'}, 400)]:
        assert client_crm.post(cible, data={**champs, **kw}).status_code == code
    assert client_crm.post(cible, content=urlencode(champs)+'&texte_libre=double',
                           headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 400
    assert client_crm.post(cible, content=b'x'*30001,
                           headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 413
    assert client_crm.get(cible+'&revision_max=01').status_code == 400
    assert base.base._instantane_base(session) == avant


def test_route_badge_complete_et_formulaire_utilisable(client_crm, planning, session):
    base.base._connecter(client_crm, 'admin.fictif')
    semaine = client_crm.get(base.SEMAINE)
    liens = re.findall(r'href="([^"]+)" aria-label="Notes de ce créneau"', semaine.text)
    assert len(liens) == 3
    page = client_crm.get('https://testserver'+html.unescape(liens[0]))
    assert page.status_code == 200
    champs = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', page.text))
    action = html.unescape(re.search(r'<form method="post" action="([^"]+)"', page.text)[1])
    r = client_crm.post('https://testserver'+action, data={**champs, 'texte_libre': 'Accès fictif côté cour'},
                        follow_redirects=False)
    assert r.status_code == 303, r.text


def _direct(session, ancre, cle, *, quota=65536, source='console'):
    from datetime import UTC, datetime

    from m4_field_ops import outils

    from opsys import contexte, idempotence

    now = datetime(2030, 6, 1, tzinfo=UTC)
    meta = idempotence.Meta(cle, 'console:admin.fictif', now.isoformat())
    with (session(), contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source=source)),
          contexte.appeler_en_tant_que('m04-field-ops', origine='console'),
          contexte.sortie_bornee(quota), outils.contexte_annotation_calendrier(meta),
          contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, now, now))):
        return outils.enregistrer_annotation_calendrier(ancre, 'Texte privé fictif', 0)


def test_quota_avant_append_et_appareil_non_qualifie(client_crm, planning, session):
    ancre = _ancre(session, planning)
    avant = base.base._instantane_base(session)
    assert _direct(session, ancre, 'quota-fictif', quota=10)['accepte'] is False
    assert _direct(session, ancre, 'appareil-fictif', source='appareil')['accepte'] is False
    assert base.base._instantane_base(session) == avant


def test_rollback_si_audit_echoue(client_crm, planning, session, monkeypatch):
    from opsys import etat

    def echouer(*args, **kwargs):
        raise RuntimeError('échec audit fictif')

    ancre, avant = _ancre(session, planning), base.base._instantane_base(session)
    monkeypatch.setattr(etat, 'journaliser', echouer)
    with pytest.raises(RuntimeError, match='audit fictif'):
        _direct(session, ancre, 'rollback-fictif')
    assert base.base._instantane_base(session) == avant


def test_deux_editeurs_concurrents_une_revision(client_crm, planning, session):
    from concurrent.futures import ThreadPoolExecutor

    ancre = _ancre(session, planning)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futurs = [pool.submit(_direct, session, ancre, 'editeur-fictif-'+str(i)) for i in range(2)]
        resultats = [f.result(timeout=10) for f in futurs]
    assert sorted(r['accepte'] for r in resultats) == [False, True]
    assert len(_notes(session)) == 1


def test_port_mcp_ferme_avant_copie_du_texte(session):
    from opsys.capacites import Capacites

    cap = Capacites({}, cnx_factory=session)
    avant = base.base._instantane_base(session)
    for nom in ['m4_enregistrer_annotation_calendrier', 'm4_lire_annotations_calendrier',
                'm4_resumer_annotations_calendrier']:
        assert cap.appeler(nom, {'texte_libre': 'secret fictif'}) == {
            'ok': False, 'erreur': 'port_console_prive_requis'}
    assert base.base._instantane_base(session) == avant


def test_journal_ne_contient_pas_le_texte(client_crm, planning, session):
    from sqlalchemy import select

    from opsys.stockage.schema import META

    ancre = _ancre(session, planning)
    assert _direct(session, ancre, 'confidentialite-fictive')['accepte'] is True
    with session() as cnx:
        for table in META.sorted_tables:
            if 'maillon' not in table.name:
                assert 'Texte privé fictif' not in repr(cnx.execute(select(table)).all()), table.name


def test_vrai_departement_refuse_avant_demande_approbation(client_crm, planning, session):
    from opsys.capacites import Capacites
    from opsys.departements import charger_departements
    from opsys.idempotence import Meta

    deps = charger_departements(Path(__file__).parents[1]/'departments')
    cap = Capacites(deps, session, filtre={'m04-field-ops'}, memoire=False)
    ancre = _ancre(session, planning)
    args = {'ancre': ancre, 'texte_libre': 'Privé fictif jamais en approbation', 'revision_attendue': 0}
    avant = base.base._instantane_base(session)
    for meta in [None, Meta('intention-fictive', 'appareil-fictif', '2030-06-01T00:00:00+00:00')]:
        assert cap.appeler('m4_enregistrer_annotation_calendrier', args, meta) == {
            'ok': False, 'erreur': 'port_console_prive_requis'}
        assert base.base._instantane_base(session) == avant
