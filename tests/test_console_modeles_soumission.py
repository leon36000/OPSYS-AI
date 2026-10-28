"""Catalogue réel M3/SQLite/HTTP; toutes les données sont fictives."""
import html
import importlib.util
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opsys import contexte, idempotence, identite, stockage

spec = importlib.util.spec_from_file_location('fixture_crm_modeles', Path(__file__).with_name('test_console_crm.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
client_crm = base.client_crm
devis_crm = base.devis_crm
FICTIF = True
PAGE = '/crm/modeles-soumission'
POST = PAGE + '/enregistrer'
DETAIL = PAGE + '/modele-fictif'


@pytest.fixture
def catalogue(client_crm):
    base._connecter(client_crm, 'admin.fictif')
    return client_crm


def arguments(**kw):
    return {'modele_id': 'modele-fictif', 'titre': 'Gouttières FICTIVES',
            'description': 'Travaux FICTIFS <script>texte</script>\nLongueur à renseigner.',
            'clauses': 'Note FICTIVE, sans valeur légale.\nÀ réviser.', 'revision_attendue': 0, **kw}


def champs(client, **kw):
    return {**arguments(), 'csrf': client.get('/api/session').json()['csrf'], 'mutation_id': 'modele-fictif-1', **kw}


def source(session):
    with session():
        return list(stockage.maillons('m03-estimation', 'modeles_soumission'))


def direct(session, *, cle='direct-fictif', quota=65536, origine='console', **kw):
    from m3_estimation import outils

    now = datetime(2030, 6, 1, tzinfo=UTC)
    meta = idempotence.Meta(cle, 'console:admin.fictif', now.isoformat())
    with (session(), contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source=origine)),
          contexte.appeler_en_tant_que('m03-estimation', origine=origine),
          contexte.sortie_bornee(quota), outils.contexte_modeles(meta),
          contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, now, now))):
        return outils.enregistrer_modele_soumission(**arguments(**kw))


def test_parcours_formulaire_reel_versions_rejeu_et_lecture(catalogue, session):
    page = catalogue.get(PAGE)
    assert page.status_code == 200 and 'Aucun modèle enregistré' in page.text
    action, formulaire = re.search(
        r'<form method="post" action="([^"]+/enregistrer)"(.*?)</form>', page.text, re.S).groups()
    assert action == base.PREFIXE + POST
    donnees = {k: html.unescape(v) for k, v in re.findall(
        r'<input type="hidden" name="([^"]+)" value="([^"]*)">', formulaire)}
    donnees.update({k: v for k, v in arguments().items() if k not in donnees})
    r = catalogue.post(action.removeprefix(base.PREFIXE), data=donnees, follow_redirects=False)
    assert r.status_code == 303, r.text
    lien_v1 = r.headers['location'].removeprefix(base.PREFIXE)
    page = catalogue.get(lien_v1)
    assert page.status_code == 200 and 'Version 1 sur 1' in page.text
    assert '&lt;script&gt;texte&lt;/script&gt;' in page.text and '<script>texte</script>' not in page.text
    assert page.headers['cache-control'] == 'no-store'
    modele_id = donnees['modele_id']
    avant = base._instantane_base(session)
    assert catalogue.post(POST, data=donnees, follow_redirects=False).status_code == 303
    assert base._instantane_base(session) == avant
    modif = {**donnees, 'mutation_id': 'v2', 'revision_attendue': '1', 'clauses': 'Nouvelle clause FICTIVE'}
    assert catalogue.post(POST, data=modif, follow_redirects=False).status_code == 303
    assert len(source(session)) == 2
    avant = base._instantane_base(session)
    ancien = catalogue.get(lien_v1)
    assert 'Version 1 sur 2' in ancien.text and 'Nouvelle clause FICTIVE' not in ancien.text
    assert 'Réviser ce modèle' not in ancien.text
    courant = catalogue.get(PAGE + '/' + modele_id)
    assert 'Nouvelle clause FICTIVE' in courant.text and 'Réviser ce modèle' in courant.text
    assert catalogue.post(POST, data={**modif, 'mutation_id': 'concurrent', 'clauses': 'Autre'}).status_code == 409
    assert catalogue.post(POST, data={**donnees, 'titre': 'Autre'}).status_code == 409
    assert base._instantane_base(session) == avant
    stockage.liberer()
    assert len(source(session)) == 2 and catalogue.get(lien_v1).status_code == 200


def test_catalogue_ne_change_ni_devis_accepte_ni_document_client(devis_crm, session):
    from m3_estimation import devis_durable, outils, soumission

    base._connecter(devis_crm, 'admin.fictif')
    with session():
        journal = outils.registre_devis_production()
        d, v = devis_durable.marquer_devis_accepte('devis-fictif-001', 'client.fictif', base.H2, journal)
        assert d is not None and v is None
        avant = list(journal)
        document = soumission.generer_brouillon_html(d)
    assert direct(session)['accepte'] is True
    assert direct(session, cle='v2', revision_attendue=1, clauses='Clause FICTIVE changée')['accepte'] is True
    with session():
        assert list(outils.registre_devis_production()) == avant
        courant, v = devis_durable.lire_devis(outils.registre_devis_production(), 'devis-fictif-001')
        assert v is None and courant['statut'] == 'accepte'
        assert soumission.generer_brouillon_html(courant) == document
    page = devis_crm.get('/crm/lead/lead-fictif-001/soumissions')
    assert f'href="{base.PREFIXE}{PAGE}"' in page.text


def test_catalogue_pagination_source_et_lecture_sans_ecriture(catalogue, session):
    for i in range(26):
        assert direct(session, cle=f'cree-{i}', modele_id=f'modele-{i:02}', titre=f'Modèle FICTIF {i:02}')['accepte']
    avant = base._instantane_base(session)
    premier = catalogue.get(PAGE)
    suite_url = html.unescape(re.search(r'href="([^"]+)">Page suivante', premier.text)[1])
    suite = catalogue.get(suite_url.removeprefix(base.PREFIXE))
    assert suite.status_code == 200
    assert re.findall(r'>Modèle FICTIF (\d+)</a>', premier.text + suite.text) == [f'{i:02}' for i in range(26)]
    assert base._instantane_base(session) == avant
    assert direct(session, cle='revision', modele_id='modele-00', revision_attendue=1)['accepte']
    assert catalogue.get(suite_url.removeprefix(base.PREFIXE)).status_code == 409


@pytest.mark.parametrize('suffixe', ['?autre=1', '?decalage=1', '?decalage=25', '?decalage=0&decalage=0',
    '?decalage='+'9'*300, '?source_attendue=<script>', '/modele-fictif?version=1&version=2',
    '/modele-fictif?version=-1', '/modele-fictif?autre=1'])
def test_parametres_invalides(catalogue, suffixe):
    assert catalogue.get(PAGE + suffixe).status_code == 400


def test_securite_csrf_corps_quota_identite_et_revocation(catalogue, session):
    avant = base._instantane_base(session)
    assert catalogue.post(POST, data=champs(catalogue, csrf='faux')).status_code == 403
    assert catalogue.post(POST, data={**champs(catalogue), 'role': 'admin'}).status_code == 400
    assert catalogue.post(POST, data=champs(catalogue, clauses='x'*12001)).status_code == 400
    assert catalogue.post(POST, content=b'x'*200001,
                          headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 413
    assert direct(session, quota=10)['accepte'] is False
    assert direct(session, origine='appareil')['accepte'] is False
    assert base._instantane_base(session) == avant
    for personne in ['employe', 'nathan']:
        base._connecter(catalogue, personne)
        assert catalogue.get(PAGE).status_code == 403
    base._connecter(catalogue, 'admin.fictif')
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    assert catalogue.get(PAGE).status_code == 403
    assert direct(session)['verdict']['code'] == 'REJ-MODELE-IDENTITE'


def test_audit_rollback_et_pas_de_texte_dans_autres_tables(catalogue, session, monkeypatch):
    from sqlalchemy import select

    from opsys import etat
    from opsys.stockage.schema import META

    original = etat.journaliser

    def panne(*args, **kwargs):
        raise RuntimeError('Audit fictif indisponible')

    avant = base._instantane_base(session)
    monkeypatch.setattr(etat, 'journaliser', panne)
    with pytest.raises(RuntimeError, match='Audit fictif'):
        direct(session)
    assert base._instantane_base(session) == avant
    monkeypatch.setattr(etat, 'journaliser', original)
    assert direct(session)['accepte']
    with session() as cnx:
        for table in META.sorted_tables:
            if 'maillon' not in table.name:
                assert arguments()['clauses'] not in repr(cnx.execute(select(table)).all())


def test_deux_redacteurs_un_seul_cas(catalogue, session):
    from concurrent.futures import ThreadPoolExecutor

    assert direct(session)['accepte']
    with ThreadPoolExecutor(max_workers=2) as pool:
        futurs = [pool.submit(direct, session, cle=f'concurrent-{i}', revision_attendue=1,
                              clauses=f'Révision fictive {i}') for i in range(2)]
        resultats = [f.result(timeout=10) for f in futurs]
    assert sorted(r['accepte'] for r in resultats) == [False, True]
    assert len(source(session)) == 2


def test_ports_agents_fermes_avant_charge(session):
    from opsys.capacites import Capacites

    cap = Capacites({}, cnx_factory=session)
    for nom in ['m3_enregistrer_modele_soumission', 'm3_lire_modele_soumission', 'm3_lister_modeles_soumission']:
        attendu = {'ok': False, 'erreur': 'port_console_prive_requis'}
        assert cap.appeler(nom, arguments()) == attendu
        assert cap.appeler_profil_runtime(nom, arguments(), None, None,
                                         profile_id='fictif', profile_revision=1, server='fictif') == attendu


@pytest.mark.parametrize('identifiant', ['.', '..'])
def test_segment_normalise_refuse_avant_ecriture(catalogue, session, identifiant):
    avant = base._instantane_base(session)
    r = catalogue.post(POST, data=champs(catalogue, modele_id=identifiant))
    assert r.status_code == 400
    assert base._instantane_base(session) == avant


def test_premier_lf_preserve_dans_formulaire_et_consultation(catalogue, session):
    texte = '\nTexte FICTIF <b>préservé</b>'
    assert direct(session, description=texte, clauses=texte)['accepte']
    page = catalogue.get(DETAIL)
    assert page.status_code == 200
    # HTML consomme un LF immédiatement après textarea/pre : le rendu doit en fournir un de protection.
    # Contrat du HTML reçu, pas une qualification navigateur natif.
    for nom in ['description', 'clauses']:
        contenu = re.search(r'<textarea name="' + nom + r'"[^>]*>(.*?)</textarea>', page.text, re.S)[1]
        assert contenu.startswith('\n\n')
        assert html.unescape(contenu[1:]) == texte
    assert page.text.count('<pre>\n\nTexte FICTIF &lt;b&gt;préservé&lt;/b&gt;</pre>') == 2
    modif = champs(catalogue, revision_attendue=1, description=texte, clauses=texte, mutation_id='lf-preserve')
    assert catalogue.post(POST, data=modif, follow_redirects=False).status_code == 303
    assert len(source(session)) == 2 and source(session)[1]['clauses'] == texte
