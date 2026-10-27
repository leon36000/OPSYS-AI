"""fictif: true — liste privée quotidienne des déclarations, aucune présence reconstituée."""
import importlib
import importlib.util
import logging
import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from m4_field_ops import absences_durables as durable
from m4_field_ops import absences_journalieres as domaine
from m4_field_ops.outils import outils
from m4_field_ops.registre import Registre

from opsys import contexte, identite
from opsys.console import journal_equipes
from opsys.console import preparation_chantier as lecture
from opsys.console.securite import Session
from opsys.departements import charger_departements
from opsys.outils import executer

spec = importlib.util.spec_from_file_location('absence_day_fixture',
    Path(__file__).with_name('test_console_absences_personnes.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
client_crm, planning = g.client_crm, g.f.f.f.planning
base = g.base
FICTIF = True
NOM = 'm4_lire_absences_jour_console'
URL = '/crm/journal-equipes/absences?jour=2030-06-03'


def port():
    return importlib.import_module('opsys.console.absences_quotidiennes')


def connecter(client, personne='admin.fictif'):
    base._connecter(client, personne)


def console(outil, **options):
    with (contexte.appele_par_appareil(contexte.IdentiteAppelante(g.AUTH.utilisateur, 'admin', source='console')),
          contexte.appeler_en_tant_que('m04-field-ops', origine='console')):
        return executer(outil, dict(jour=g.D, **options))


def suivante(html):
    m = re.search(r'href="([^"]+)"[^>]*>Page suivante</a>', html)
    return unescape(m[1]).removeprefix(base.PREFIXE) if m else None


def test_t0_sql_et_vue_lient_derniers_signalements_a_histoire_exacte(client_crm, session):
    g.ajouter(session, personne='bruno.fictif')
    g.ajouter(session, personne='alice.fictive', cle='m-2')
    retrait = g.ajouter(session, personne='alice.fictive', revision=1, statut='retiree', cle='m-3')
    outil = {o.nom: o for o in outils()}[NOM]
    assert outil.autonomie.value == 'T0'
    avant = base._instantane_base(session)
    with session() as cnx:
        vue = port().lire(cnx, charger_departements(), g.AUTH, g.D)
        r = console(outil)
    assert r['resultat']['resultat'] == vue and vue['total'] == 2
    connecter(client_crm)
    page = client_crm.get(URL)
    assert page.status_code == 200, page.text
    assert retrait['resultat']['declaration_id'] in page.text and 'Retiré — présence inconnue' in page.text
    assert page.headers['cache-control'] == 'no-store' and 'content-security-policy' in page.headers
    liens = [unescape(x).removeprefix(base.PREFIXE) for x in
             re.findall(r'href="([^"]+)"[^>]*>Historique individuel</a>', page.text)]
    assert [parse_qs(urlparse(x).query) for x in liens] == [
        {'jour': [g.D], 'personne_id': [p]} for p in ['alice.fictive', 'bruno.fictif']]
    assert all(client_crm.get(lien).status_code == 200 for lien in liens)
    assert client_crm.post(URL).status_code == 405
    assert base._instantane_base(session) == avant


def test_http_jour_vide_ne_dit_pas_tous_presents(client_crm, session):
    connecter(client_crm)
    avant = base._instantane_base(session)
    r = client_crm.get(URL)
    assert r.status_code == 200 and 'Aucun signalement documenté pour cette journée' in r.text
    assert 'Aucune présence, heure travaillée ou paie déduite' in r.text
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('query', ['', 'jour=20300603', 'jour=2030-06-03&jour=2030-06-07',
    'jour=2030-06-03&personne_id=bruno.fictif', 'jour=2030-06-03&debut=1',
    'jour=2030-06-03&limite=101'])
def test_parametres_fermes(query, client_crm, session):
    connecter(client_crm)
    avant = base._instantane_base(session)
    assert client_crm.get('/crm/journal-equipes/absences?' + query).status_code == 400
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('personne,expire', [('employe', 4102444800), ('nathan', 4102444800), ('admin.fictif', 1)])
def test_sql_admin_et_session_courante_exiges(personne, expire, client_crm, session):
    g.ajouter(session)
    with session() as cnx, pytest.raises(PermissionError):
        port().lire(cnx, charger_departements(), Session(personne, frozenset({'admin'}), 'fictif', expire), g.D)
    if personne != 'admin.fictif':
        connecter(client_crm, personne)
        assert client_crm.get(URL).status_code == 403


def test_appareil_mcp_registre_injecte_et_quota_refuses(client_crm, session, monkeypatch):
    g.ajouter(session)
    outil = {o.nom: o for o in outils()}[NOM]
    avant = base._instantane_base(session)
    r = g.f.f.f.terrain._appeler({NOM: outil}, NOM, dict(jour=g.D), g.f.f.f.terrain.ADMIN)
    assert r['resultat']['verdict']['code'] == 'REJ-ABSENCE-IDENTITE'
    with session(), contexte.transport_mcp():
        assert console(outil)['resultat']['verdict']['code'] == 'REJ-ABSENCE-IDENTITE'
    with session():
        injecte = {o.nom: o for o in outils(Registre())}[NOM]
        assert console(injecte)['resultat']['verdict']['code'] == 'REJ-ABSENCE-INSTANCE-NON-QUALIFIEE'
    with session(), contexte.sortie_bornee(100):
        assert console(outil)['resultat']['verdict']['code'] == 'REJ-ABSENCE-SORTIE-TROP-VOLUMINEUSE'
    assert base._instantane_base(session) == avant
    monkeypatch.setattr(domaine, 'MAX_SOURCES', 0)

    def interdit(*args, **kwargs):
        raise AssertionError('ne pas décoder après quota')

    monkeypatch.setattr(durable, 'copier_maillons_avec_metadonnees', interdit)
    with session():
        assert console(outil)['resultat']['verdict']['code'] == 'REJ-ABSENCE-SOURCE-TROP-VOLUMINEUSE'


@pytest.mark.parametrize('profil', [False, True])
def test_repartiteurs_generiques_fermes_avant_factory(profil):
    from opsys.capacites import Capacites

    def interdite():
        raise AssertionError('factory interdite')

    caps = Capacites(charger_departements(), interdite, filtre={'m04-field-ops'}, memoire=False)
    if profil:
        r = caps.appeler_profil_runtime(NOM, object(), None, None, profile_id='profil.fictif',
                                       profile_revision=1, server='opsys_m4')
    else:
        r = caps.appeler(NOM, object())
    assert r == {'ok': False, 'erreur': 'port_console_prive_requis'}


def test_reponse_t0_alteree_ne_passe_pas_comparaison(client_crm, session, monkeypatch):
    g.ajouter(session)
    p = port()
    original = p._t0

    def alterer(*args):
        r = original(*args)
        r['lignes'].clear()
        return r

    monkeypatch.setattr(p, '_t0', alterer)
    with session() as cnx, pytest.raises(lecture.Refus, match='SOURCE-REPONSE-INCOHERENTE'):
        p.lire(cnx, charger_departements(), g.AUTH, g.D)


@pytest.mark.parametrize('mutation', ['autorite', 'source'])
def test_mutation_pendant_rendu_ne_divulgue_pas_liste(mutation, client_crm, session, monkeypatch):
    from opsys.console import pages

    g.ajouter(session, personne='bruno.fictif')
    connecter(client_crm)
    original = pages.gabarit

    def changer(*args, **kwargs):
        html = original(*args, **kwargs)
        if mutation == 'autorite':
            with session() as cnx:
                identite.ajouter_role(cnx, g.AUTH.utilisateur, 'nathan_owner')
                identite.retirer_role(cnx, g.AUTH.utilisateur, 'admin')
        else:
            g.ajouter(session, personne='bruno.fictif', revision=1, statut='retiree', cle='m-2')
        return html

    monkeypatch.setattr(pages, 'gabarit', changer)
    r = client_crm.get(URL)
    assert r.status_code == (403 if mutation == 'autorite' else 503) and 'bruno.fictif' not in r.text


def test_pages_fin_vide_source_perimee_et_echappement(client_crm, session, monkeypatch):
    g.ajouter(session, personne='membre.<script>')
    g.ajouter(session, personne='bruno.fictif', cle='m-2')
    connecter(client_crm)
    a = client_crm.get(URL + '&limite=1')
    lien = suivante(a.text)
    assert lien
    b = client_crm.get(lien)
    assert b.status_code == 200 and 'membre.&lt;script&gt;' in b.text and 'membre.<script>' not in b.text
    with session() as cnx:
        vue = port().lire(cnx, charger_departements(), g.AUTH, g.D)
    fin = client_crm.get(URL + '&debut=2&source_attendue=' + vue['source'])
    assert fin.status_code == 200 and 'Aucune déclaration sur cette page' in fin.text
    assert 'Aucun signalement documenté pour cette journée' not in fin.text
    g.ajouter(session, personne='alice.fictive', cle='m-3')
    assert client_crm.get(lien).status_code == 503
    monkeypatch.setattr(port(), 'contenu', lambda *args: 'x' * 131073)
    assert client_crm.get(URL).status_code == 503


def test_lien_du_journal_sans_copie_des_absences(client_crm, planning, session):
    connecter(client_crm)
    with session() as cnx:
        avant = journal_equipes.lire(cnx, charger_departements(), g.AUTH, g.D)
    g.ajouter(session)
    with session() as cnx:
        assert journal_equipes.lire(cnx, charger_departements(), g.AUTH, g.D) == avant
    r = client_crm.get('/crm/journal-equipes?jour=' + g.D)
    assert 'inactif.fictif' not in r.text and 'name="personne_id"' in r.text
    assert base.PREFIXE + URL in unescape(r.text)


@pytest.mark.parametrize('slash', ['', '/'])
def test_logs_vue_quotidienne_masquent_query(slash):
    from uvicorn.logging import AccessFormatter

    from opsys.console.journaux_http import MasquerRecherche

    target = '/opsys/crm/journal-equipes/absences' + slash + '?jour=2030-06-03&source_attendue=source-fictive'
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s - "%s %s HTTP/%s" %d',
                              ('127.0.0.1', 'GET', target, '1.1', 200), None)
    MasquerRecherche().filter(record)
    ligne = AccessFormatter(fmt='%(request_line)s %(status_code)s', use_colors=False).format(record)
    assert '2030-06-03' not in ligne and 'source-fictive' not in ligne
    assert '[MASQUE]' in ligne and '/opsys/crm/journal-equipes/absences' in ligne and '200' in ligne
