"""fictif: true — journal vers le vrai écran de notes existant, sans nouveau writer."""
import importlib.util
import re
from html import unescape
from pathlib import Path

from opsys import identite

spec = importlib.util.spec_from_file_location('journal_notes_fixture',
    Path(__file__).with_name('test_console_annotations_cedule.py'))
n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n)
client_crm, planning = n.client_crm, n.planning
FICTIF = True
URL = '/crm/journal-equipes?jour=2030-06-03'


def liens(html):
    return [unescape(url).removeprefix(n.base.base.PREFIXE) for url in
            re.findall(r'href="([^"]+)" aria-label="Notes de cette prévision"', html)]


def test_journal_lie_les_notes_de_chaque_prevision_exacte(client_crm, planning, session):
    n.base.base._connecter(client_crm, 'admin.fictif')
    avant = n.base.base._instantane_base(session)
    r = client_crm.get(URL)
    assert r.status_code == 200, r.text
    urls = liens(r.text)
    assert len(urls) == len(planning[1]) == 3
    assert n._url(session, planning) in urls
    for url in urls:
        page = client_crm.get(url)
        assert page.status_code == 200 and 'Note rapide du créneau' in page.text
    assert n.base.base._instantane_base(session) == avant


def test_notes_ne_sortent_pas_apres_revocation_pendant_rendu(client_crm, planning, session, monkeypatch):
    n.base.base._connecter(client_crm, 'admin.fictif')
    url = n._url(session, planning)
    secret = 'NOTE_CONFIDENTIELLE_FICTIVE_QUALIFICATION'
    assert client_crm.post(url, data=n._champs(client_crm, texte_libre=secret),
                           follow_redirects=False).status_code == 303
    original, passages = n.ui.pages.gabarit, []

    def rendu(*args, **kwargs):
        html = original(*args, **kwargs)
        if secret in html:
            passages.append(1)
            with session() as cnx:
                identite.ajouter_role(cnx, 'admin.fictif', 'nathan_owner')
                identite.retirer_role(cnx, 'admin.fictif', 'admin')
        return html

    monkeypatch.setattr(n.ui.pages, 'gabarit', rendu)
    r = client_crm.get(url)
    assert passages == [1]
    assert r.status_code == 403 and secret not in r.text


def test_creer_depuis_journal_puis_ancien_et_nouveau_creneaux_restent_distincts(client_crm, planning, session):
    from m4_field_ops import calendrier_civil, etats

    n.base.base._connecter(client_crm, 'admin.fictif')
    ancien = n._url(session, planning)
    assert ancien in liens(client_crm.get(URL).text)
    champs = n._champs(client_crm, texte_libre='Note fictive du premier passage <script>ancien</script>')
    assert client_crm.post(ancien, data=champs, follow_redirects=False).status_code == 303
    note = n._notes(session)[0]
    assert note['ancre'] == n._ancre(session, planning)
    with session():
        reg = n.base.terrain._registre()
        iid = planning[1]['lead-fictif-001']
        assert etats.transitionner(iid, 'reportee', reg, '2030-06-03T10:00:00-04:00', motif='meteo')[1] is None
        assert etats.transitionner(iid, 'planifiee', reg, '2030-06-03T10:01:00-04:00')[1] is None
        calendrier_civil.confirmer(reg, planning[2]['plan_id'], {'0': '2030-06-07'}, 1,
                                   'admin.fictif', '2030-06-03T10:02:00-04:00')
    nouvelle = n._url(session, planning)
    assert nouvelle != ancien
    assert ancien in liens(client_crm.get(URL).text)
    assert nouvelle in liens(client_crm.get('/crm/journal-equipes?jour=2030-06-07').text)
    avant = n.base.base._instantane_base(session)
    page = client_crm.get(ancien)
    assert page.status_code == 200 and 'Ancien créneau' in page.text
    assert 'name="texte_libre"' not in page.text
    assert '<script>ancien</script>' not in page.text and '&lt;script&gt;ancien&lt;/script&gt;' in page.text
    assert client_crm.post(ancien, data={**champs, 'revision_attendue': '1', 'mutation_id': 'nouvelle-sur-ancien'},
                           follow_redirects=False).status_code == 409
    assert n.base.base._instantane_base(session) == avant
    assert client_crm.post(nouvelle, data={**champs, 'revision_attendue': '1', 'mutation_id': 'note-sur-reprise',
                                          'texte_libre': 'Note fictive de reprise'},
                           follow_redirects=False).status_code == 303
    notes = n._notes(session)
    assert len(notes) == 2 and notes[0] == note
    assert notes[1]['ancre'] == n._ancre(session, planning) != note['ancre']


def test_note_pas_copiee_dans_snapshot_du_journal(client_crm, planning, session):
    from opsys.console import journal_equipes
    from opsys.console.securite import Session
    from opsys.departements import charger_departements

    auth = Session('admin.fictif', frozenset({'admin'}), 'fictif', 4102444800)
    with session() as cnx:
        avant = journal_equipes.lire(cnx, charger_departements(), auth, '2030-06-03')
    n.base.base._connecter(client_crm, 'admin.fictif')
    note = 'Texte privé fictif non copié dans le journal'
    assert client_crm.post(n._url(session, planning), data=n._champs(client_crm, texte_libre=note),
                           follow_redirects=False).status_code == 303
    with session() as cnx:
        apres = journal_equipes.lire(cnx, charger_departements(), auth, '2030-06-03')
    assert apres == avant
    r = client_crm.get(URL)
    assert r.status_code == 200 and note not in r.text and 'Notes et historique' in r.text


def test_note_liee_garde_csrf_et_identite_sql(client_crm, planning, session):
    n.base.base._connecter(client_crm, 'admin.fictif')
    cible = n._url(session, planning)
    assert cible in liens(client_crm.get(URL).text)
    avant = n.base.base._instantane_base(session)
    assert client_crm.post(cible, data=n._champs(client_crm, csrf='faux')).status_code == 403
    assert n.base.base._instantane_base(session) == avant
    assert client_crm.post(cible, data=n._champs(client_crm), follow_redirects=False).status_code == 303
    for personne in ['employe', 'nathan']:
        n.base.base._connecter(client_crm, personne)
        avant = n.base.base._instantane_base(session)
        r = client_crm.get(cible)
        assert r.status_code == 403 and 'Note fictive' not in r.text
        assert n.base.base._instantane_base(session) == avant


def test_fait_sans_ancre_ne_recoit_pas_de_lien_note_contractuel(client_crm, planning, session):
    """Contrat de rendu fictif uniquement, pas une nouvelle preuve de pointage terrain."""
    from opsys.console import journal_equipes
    from opsys.console.securite import Session
    from opsys.departements import charger_departements

    with session() as cnx:
        vue = journal_equipes.lire(cnx, charger_departements(),
            Session('admin.fictif', frozenset({'admin'}), 'fictif', 4102444800), '2030-06-03')
    total = len(liens(journal_equipes.contenu(vue, '', 50)))
    vue['lignes'].append({'type': 'pointage', 'intervention_id': next(iter(planning[1].values())),
        'instant': '2030-06-03T10:00:00-04:00', 'action': 'arrivee', 'technicien_id': 'technicien.fictif',
        'source_ligne_id': 'source-contractuelle-fictive', 'ancre_visite': None})
    html = journal_equipes.contenu(vue, '', 50)
    assert len(liens(html)) == total and 'Aucune ancre de visite démontrée' in html


def test_historique_notes_trop_volumineux_refuse_sans_ecriture(client_crm, planning, session, monkeypatch):
    n.base.base._connecter(client_crm, 'admin.fictif')
    cible = n._url(session, planning)
    original = n.ui.pages.gabarit
    monkeypatch.setattr(n.ui.pages, 'gabarit', lambda *a, **kw: original(*a, **kw) + 'x' * 131073)
    avant = n.base.base._instantane_base(session)
    r = client_crm.get(cible)
    assert r.status_code == 503 and len(r.content) < 1024
    assert n.base.base._instantane_base(session) == avant
