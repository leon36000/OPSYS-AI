"""CRM03 : rendez-vous internes réels M2/SQLite/HTTP, fixtures exclusivement fictives."""
import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opsys import contexte, idempotence, identite, stockage
from opsys.console import agenda_ui

spec = importlib.util.spec_from_file_location('fixture_crm_agenda', Path(__file__).with_name('test_console_crm.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
client_crm = base.client_crm
FICTIF = True
PAGE = '/crm/agenda?vendeur_id=vendeur.fictif&jour=2030-06-03&vue=semaine'
POST = '/crm/agenda/enregistrer'
DETAIL = '/crm/agenda/rendez-vous/visite-fictive'


@pytest.fixture
def agenda(client_crm, session):
    with session() as cnx:
        identite.creer_personne(cnx, 'vendeur.fictif', 'Vendeur FICTIF', 'mot-de-passe-vendeur-fictif-123', ['seller'])
    base._connecter(client_crm, 'admin.fictif')
    return client_crm


def arguments(**kw):
    return {'rendez_vous_id': 'visite-fictive', 'lead_id': 'lead-fictif-001', 'vendeur_id': 'vendeur.fictif',
            'debut': '2030-06-03T10:00-04:00', 'fin': '2030-06-03T11:00-04:00',
            'titre': 'Visite <script>FICTIVE</script>', 'statut': 'actif', 'revision_attendue': 0, **kw}


def champs(client, **kw):
    return {**arguments(), 'csrf': client.get('/api/session').json()['csrf'], 'mutation_id': 'agenda-fictive-1', **kw}


def source(session):
    with session():
        return list(stockage.maillons('m02-revenue-crm', 'agenda_vendeurs'))


def direct(session, *, cle='direct-fictif', quota=65536, origine='console', **kw):
    from m2_revenue_crm import outils

    now = datetime(2030, 6, 1, tzinfo=UTC)
    meta = idempotence.Meta(cle, 'console:admin.fictif', now.isoformat())
    with (session(), contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source=origine)),
          contexte.appeler_en_tant_que('m02-revenue-crm', origine='console'),
          contexte.sortie_bornee(quota), outils.contexte_agenda(meta),
          contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, now, now))):
        return outils.enregistrer_rendez_vous(**arguments(**kw))


def test_parcours_creation_deplacement_annulation_historique(agenda, session):
    with session():
        principal = list(stockage.maillons('m02-revenue-crm', 'principal'))
        terrain = list(stockage.maillons('m04-field-ops', 'principal'))
    assert agenda.get(PAGE).status_code == 200
    r = agenda.post(POST, data=champs(agenda), follow_redirects=False)
    assert r.status_code == 303, r.text
    rdv = source(session)[0]
    assert rdv['auteur'] == {'personne': 'admin.fictif', 'role': 'admin'}
    for vue in ['jour', 'semaine', 'mois']:
        page = agenda.get(PAGE.replace('vue=semaine', 'vue='+vue))
        assert page.status_code == 200, page.text
        assert '&lt;script&gt;FICTIVE&lt;/script&gt;' in page.text
        assert '<script>FICTIVE</script>' not in page.text
        assert '2030-06-03T10:00' in page.text and 'lead-fictif-001' in page.text
        assert page.headers['cache-control'] == 'no-store'
    assert 'source' in agenda.get(DETAIL).text.lower()
    avant = base._instantane_base(session)
    assert agenda.post(POST, data=champs(agenda), follow_redirects=False).status_code == 303
    assert base._instantane_base(session) == avant
    assert agenda.post(POST, data=champs(agenda, titre='Saisie différente'), follow_redirects=False).status_code == 409
    assert agenda.post(POST, data=champs(agenda, mutation_id='autre'), follow_redirects=False).status_code == 409
    assert base._instantane_base(session) == avant
    modification = champs(agenda, mutation_id='deplacement-fictif', revision_attendue=1,
                          debut='2030-06-04T14:00-04:00', fin='2030-06-04T15:00-04:00')
    assert agenda.post(POST, data=modification, follow_redirects=False).status_code == 303
    assert agenda.post(POST, data={**modification, 'revision_attendue': 2, 'statut': 'annule',
                                  'mutation_id': 'annulation-fictive'}, follow_redirects=False).status_code == 303
    page = agenda.get(DETAIL)
    assert page.status_code == 200 and 'Révision 3' in page.text and 'Révision 1' in page.text
    assert 'name="mutation_id"' not in page.text
    with session():
        assert list(stockage.maillons('m02-revenue-crm', 'principal')) == principal
        assert list(stockage.maillons('m04-field-ops', 'principal')) == terrain
    assert len(source(session)) == 3


def test_conflit_horaire_pas_de_double_reservation(agenda, session):
    assert direct(session)['accepte'] is True
    avant = base._instantane_base(session)
    r = agenda.post(POST, data=champs(agenda, rendez_vous_id='autre-visite', mutation_id='conflit'),
                    follow_redirects=False)
    assert r.status_code == 409 and 'occupe ce créneau' in r.text
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('acteur', ['employe', 'nathan'])
def test_pas_de_nouveaux_droits(agenda, session, acteur):
    base._connecter(agenda, acteur)
    avant = base._instantane_base(session)
    for chemin in [PAGE, DETAIL, '/crm/agenda']:
        assert agenda.get(chemin).status_code == 403
    assert agenda.post(POST, data=champs(agenda)).status_code == 403
    assert base._instantane_base(session) == avant


def test_rejeu_admin_revoque(agenda, session):
    assert direct(session)['accepte'] is True
    with session() as cnx:
        identite.ajouter_role(cnx, 'admin.fictif', 'nathan_owner')
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = base._instantane_base(session)
    assert agenda.get(PAGE).status_code == 403
    assert agenda.post(POST, data=champs(agenda)).status_code == 403
    assert base._instantane_base(session) == avant


def test_csrf_et_formulaire_strict(agenda, session):
    avant = base._instantane_base(session)
    assert agenda.post(POST, data=champs(agenda, csrf='incorrect')).status_code == 403
    assert agenda.post(POST, data=champs(agenda, auteur='vendeur.fictif')).status_code == 400
    assert agenda.post(POST, json=champs(agenda)).status_code == 415
    for query in [PAGE+'&jour=2030-06-04', PAGE+'&autre=oui', PAGE.replace('vue=semaine', 'vue=annee')]:
        assert agenda.get(query).status_code == 400
    assert base._instantane_base(session) == avant


def test_quota_identite_appareil_refus_avant_effet(agenda, session):
    avant = base._instantane_base(session)
    assert direct(session, quota=10)['accepte'] is False
    assert direct(session, origine='appareil')['accepte'] is False
    assert base._instantane_base(session) == avant


def test_audit_rollback(agenda, session, monkeypatch):
    from opsys import etat

    def echouer(*args, **kwargs):
        raise RuntimeError('audit fictif indisponible')

    avant = base._instantane_base(session)
    monkeypatch.setattr(etat, 'journaliser', echouer)
    with pytest.raises(RuntimeError, match='audit fictif'):
        direct(session)
    assert base._instantane_base(session) == avant


def test_deux_creations_concurrentes_meme_vendeur(agenda, session):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(direct, session, cle='intention-'+str(i), rendez_vous_id='visite-'+str(i))
                for i in range(2)]
        resultats = [f.result(timeout=10) for f in futs]
    assert sorted(r['accepte'] for r in resultats) == [False, True]
    assert len(source(session)) == 1


def test_ports_generique_et_profil_prives(session):
    from opsys.capacites import Capacites

    cap = Capacites({}, cnx_factory=session)
    avant = base._instantane_base(session)
    for nom in ['m2_enregistrer_rendez_vous', 'm2_lire_agenda_vendeur', 'm2_historique_rendez_vous']:
        attendu = {'ok': False, 'erreur': 'port_console_prive_requis'}
        assert cap.appeler(nom, arguments()) == attendu
        assert cap.appeler_profil_runtime(nom, arguments(), None, None,
                                         profile_id='fictif', profile_revision=1, server='fictif') == attendu
    assert base._instantane_base(session) == avant


def test_vendeur_inactif_et_annulation_historique(agenda, session):
    assert direct(session)['accepte'] is True
    with session() as cnx:
        identite.retirer_role(cnx, 'vendeur.fictif', 'seller')
    avant = base._instantane_base(session)
    r = direct(session, cle='modif', revision_attendue=1)
    assert r['accepte'] is False and r['verdict']['code'].endswith('VENDEUR-INACTIF')
    assert base._instantane_base(session) == avant
    assert direct(session, cle='annul', revision_attendue=1, statut='annule')['accepte'] is True
    assert agenda.get(DETAIL).status_code == 200


def test_titre_ne_fuit_pas_dans_journaux(agenda, session):
    from sqlalchemy import select

    from opsys.stockage.schema import META

    assert direct(session)['accepte'] is True
    with session() as cnx:
        for table in META.sorted_tables:
            if 'maillon' not in table.name:
                assert 'Visite <script>FICTIVE</script>' not in repr(cnx.execute(select(table)).all()), table.name


def test_donnees_persistantes_apres_reouverture(agenda, session):
    assert direct(session)['accepte'] is True
    attendu = source(session)
    stockage.liberer()
    assert source(session) == attendu
    assert agenda.get(DETAIL).status_code == 200


@pytest.mark.parametrize('jour,vue,attendu', [('2032-02-12', 'mois', ('2032-02-01','2032-03-01')),
    ('2030-06-09','semaine',('2030-06-03','2030-06-10')), ('2199-12-31','jour',('2199-12-31','2200-01-01'))])
def test_periode(jour, vue, attendu):
    assert tuple(d.isoformat() for d in agenda_ui.periode(jour, vue)) == attendu


def test_reassignation_visible_et_annulation_sans_transfert(agenda, session):
    from m2_revenue_crm import assignation, outils

    assert direct(session)['accepte'] is True
    with session():
        r, v = assignation.reassigner(outils._obtenir_registre(), 'lead-fictif-001', 'autre.vendeur.fictif',
                                     'Réassignation fictive à vérifier', base.H2, 'admin.fictif', 'admin', 'appareil')
        assert r is not None and v is None
    for chemin in [PAGE, DETAIL]:
        page = agenda.get(chemin)
        assert page.status_code == 200 and 'Assignation modifiée' in page.text
    r = agenda.post(POST, data=champs(agenda, mutation_id='modif-fictive', revision_attendue=1),
                    follow_redirects=False)
    assert r.status_code == 409 and len(source(session)) == 1
    r = agenda.post(POST, data=champs(agenda, mutation_id='annul-fictive', revision_attendue=1, statut='annule'),
                    follow_redirects=False)
    assert r.status_code == 303 and len(source(session)) == 2


def test_formulaire_reel_prefixe_http(agenda, session):
    import html
    import re

    page = agenda.get(PAGE)
    forms = re.findall(r'<form method="post" action="([^"]+/crm/agenda/enregistrer)"(.*?)</form>',
                       page.text, re.S)
    assert len(forms) == 1 and forms[0][0] == base.PREFIXE + POST
    donnees = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', forms[0][1]))
    assert set(donnees) == {'csrf', 'mutation_id', 'revision_attendue', 'rendez_vous_id', 'vendeur_id'}
    donnees = {k: html.unescape(v) for k, v in donnees.items()}
    donnees.update({k: v for k, v in arguments().items() if k not in donnees})
    r = agenda.post('https://testserver'+forms[0][0], data=donnees, follow_redirects=False)
    assert r.status_code == 303, r.text
    assert source(session)[0]['rendez_vous_id'] == donnees['rendez_vous_id']
