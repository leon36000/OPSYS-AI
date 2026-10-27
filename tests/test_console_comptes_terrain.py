"""fictif: true — choix de comptes actuels séparé des déclarations historiques."""
import importlib
import importlib.util
import logging
import re
from html import unescape
from pathlib import Path

import pytest
from sqlalchemy import event

from opsys import identite
from opsys.console.securite import Session
from opsys.stockage.schema import PERSONNES

spec = importlib.util.spec_from_file_location('comptes_terrain_fixture',
    Path(__file__).with_name('test_console_absence_ecriture.py'))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
client_crm, monde, base = w.client_crm, w.monde, w.base
FICTIF = True
URL = '/crm/journal-equipes/comptes?jour=2030-06-03'


def module():
    return importlib.import_module('opsys.console.comptes_terrain')


def connecter(client, personne='admin.fictif'):
    base._connecter(client, personne)


def ajouter_compte(session, identifiant, nom, roles):
    with session() as cnx:
        identite.creer_personne(cnx, identifiant, nom, 'fictif-mot-de-passe', roles)


def test_source_canonique_minimisee_et_roles_sans_doublons(monde, session):
    ajouter_compte(session, 'client.seul', 'CLIENT FICTIF NE PAS CHARGER', ['client'])
    ajouter_compte(session, 'agent.mixte', 'AGENT FICTIF NE PAS CHARGER', ['employee', 'system_agent'])
    with session() as cnx:
        identite.ajouter_role(cnx, w.g.PERSONNE, 'manager')
    avant = base._instantane_base(session)
    with session() as cnx:
        requetes = []

        def noter(cnx, cursor, statement, parameters, context, executemany):
            if statement.lstrip().lower().startswith('select'):
                requetes.append(statement.lower())

        event.listen(cnx, 'before_cursor_execute', noter)
        try:
            module()._capturer(cnx)
        finally:
            event.remove(cnx, 'before_cursor_execute', noter)
        # La garde d’authentification existante est hors de la mesure du répertoire.
        vue = module().lire(cnx, w.g.AUTH, w.g.D)
    ids = [x['personne_id'] for x in vue['lignes']]
    assert w.g.PERSONNE in ids and ids.count(w.g.PERSONNE) == 1
    assert 'client.seul' not in ids and 'agent.mixte' not in ids
    inactive = next(x for x in vue['lignes'] if x['personne_id'] == w.g.PERSONNE)
    assert inactive['actif'] is False and inactive['nom_actuel'] == 'Personne fictive inactive'
    assert all(set(x) == {'personne_id', 'nom_actuel', 'actif'} for x in vue['lignes'])
    cible_sql = [x for x in requetes if 'personnes.nom' in x and 'count(' not in x]
    assert cible_sql and all('exists' in sql for sql in cible_sql)
    assert all('mot_de_passe_hash' not in sql for sql in requetes)
    assert base._instantane_base(session) == avant


def test_pages_source_et_renommage_ne_modifient_pas_histoire(monde, session):
    assert w.agir(session)['resultat']['accepte'] is True
    avant_registre = w.lignes(session)
    with session() as cnx:
        premier = module().lire(cnx, w.g.AUTH, w.g.D, limite=1)
        suivant = module().lire(cnx, w.g.AUTH, w.g.D, debut=1, limite=1, source_attendue=premier['source'])
    assert premier['suivant'] == 1 and suivant['lignes'] != premier['lignes']
    with session() as cnx:
        cnx.execute(PERSONNES.update().where(PERSONNES.c.identifiant == w.g.PERSONNE)
                    .values(nom='Nom ACTUEL changé fictif'))
    with session() as cnx, pytest.raises(ValueError, match='SOURCE-PERIMEE'):
        module().lire(cnx, w.g.AUTH, w.g.D, debut=1, source_attendue=premier['source'])
    assert w.lignes(session) == avant_registre


@pytest.mark.parametrize('personne,expire', [('employe', 4102444800), ('nathan', 4102444800), ('admin.fictif', 1)])
def test_sql_admin_session_et_connexion_exiges(monde, session, personne, expire):
    with session() as cnx, pytest.raises(PermissionError):
        module().lire(cnx, Session(personne, frozenset({'admin'}), 'fictif', expire), w.g.D)
    with session() as cnx, cnx.engine.connect() as autre, pytest.raises(ValueError, match='INSTANCE-NON-QUALIFIEE'):
        module().lire(autre, w.g.AUTH, w.g.D)


@pytest.mark.parametrize('quota', ['comptes', 'octets', 'roles'])
def test_quotas_avant_chargement_noms_ou_roles(monde, session, monkeypatch, quota):
    m = module()
    monkeypatch.setattr(m, {'comptes': 'MAX_COMPTES', 'octets': 'MAX_OCTETS', 'roles': 'MAX_ROLES'}[quota], 0)

    def interdit(*args):
        raise AssertionError('chargement après quota interdit')

    monkeypatch.setattr(m, '_lignes', interdit)
    with session() as cnx, pytest.raises(ValueError, match='SOURCE-TROP-VOLUMINEUSE'):
        m.lire(cnx, w.g.AUTH, w.g.D)


def test_quota_sortie_et_corps_http(monde, client_crm, session, monkeypatch):
    from opsys import contexte

    avant = base._instantane_base(session)
    with session() as cnx, contexte.sortie_bornee(10), pytest.raises(ValueError, match='SORTIE-TROP-VOLUMINEUSE'):
        module().lire(cnx, w.g.AUTH, w.g.D)
    connecter(client_crm)
    monkeypatch.setattr(module(), 'contenu', lambda *args: 'x' * 131073)
    assert client_crm.get(URL).status_code == 503
    assert base._instantane_base(session) == avant


def test_nom_actuel_echappe_liens_id_et_ancien_compte_non_eligible_reste_consultable(monde, client_crm, session):
    assert w.agir(session)['resultat']['accepte'] is True
    with session() as cnx:
        cnx.execute(PERSONNES.update().where(PERSONNES.c.identifiant == w.g.PERSONNE)
                    .values(nom='<script>nom fictif</script>'))
    connecter(client_crm)
    avant = base._instantane_base(session)
    page = client_crm.get(URL)
    assert page.status_code == 200, page.text
    assert '&lt;script&gt;nom fictif&lt;/script&gt;' in page.text and '<script>nom fictif</script>' not in page.text
    assert 'Nom actuel du compte' in page.text and 'Compte désactivé' in page.text
    liens = [unescape(x).removeprefix(base.PREFIXE)
             for x in re.findall(r'href="([^"]+)"[^>]*>Consulter ce compte</a>', page.text)]
    cible = next(x for x in liens if 'personne_id=inactif.fictif' in x)
    historique = client_crm.get(cible)
    assert historique.status_code == 200 and 'Révision 1' in historique.text
    assert 'nom fictif' not in historique.text
    assert page.headers['cache-control'] == 'no-store' and 'content-security-policy' in page.headers
    assert client_crm.post(URL).status_code == 405
    assert base._instantane_base(session) == avant
    with session() as cnx:
        identite.ajouter_role(cnx, w.g.PERSONNE, 'client')
        identite.retirer_role(cnx, w.g.PERSONNE, 'employee')
    assert w.g.PERSONNE not in client_crm.get(URL).text
    assert client_crm.get(cible).status_code == 200


@pytest.mark.parametrize('query', ['', 'jour=20300603', 'jour=2030-06-03&jour=2030-06-07',
    'jour=2030-06-03&personne_id=employe', 'jour=2030-06-03&debut=1', 'jour=2030-06-03&limite=101'])
def test_parametres_fermes(query, monde, client_crm):
    connecter(client_crm)
    assert client_crm.get('/crm/journal-equipes/comptes?' + query).status_code == 400


@pytest.mark.parametrize('mutation', ['autorite', 'nom', 'role'])
def test_rendu_apres_mutation_refuse_ancien_repertoire(monde, client_crm, session, monkeypatch, mutation):
    from opsys.console import pages

    connecter(client_crm)
    original = pages.gabarit

    def changer(*args, **kwargs):
        html = original(*args, **kwargs)
        with session() as cnx:
            if mutation == 'autorite':
                identite.ajouter_role(cnx, w.g.AUTH.utilisateur, 'nathan_owner')
                identite.retirer_role(cnx, w.g.AUTH.utilisateur, 'admin')
            elif mutation == 'nom':
                cnx.execute(PERSONNES.update().where(PERSONNES.c.identifiant == w.g.PERSONNE)
                    .values(nom='Nom fictif changé'))
            else:
                identite.ajouter_role(cnx, w.g.PERSONNE, 'system_agent')
        return html

    monkeypatch.setattr(pages, 'gabarit', changer)
    r = client_crm.get(URL)
    assert r.status_code == (403 if mutation == 'autorite' else 503)
    assert 'Personne fictive inactive' not in r.text


def test_navigation_separee_et_fallback_id_conserve(monde, client_crm, session):
    connecter(client_crm)
    for route in ('/crm/journal-equipes?jour=' + w.g.D, '/crm/journal-equipes/absences?jour=' + w.g.D):
        r = client_crm.get(route)
        assert r.status_code == 200
        assert base.PREFIXE + URL in unescape(r.text)
        assert 'name="personne_id"' in r.text and 'Personne fictive inactive' not in r.text


@pytest.mark.parametrize('slash', ['', '/'])
def test_logs_selecteur_masquent_query_privee(slash):
    from uvicorn.logging import AccessFormatter

    from opsys.console.journaux_http import MasquerRecherche

    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s - "%s %s HTTP/%s" %d',
        ('127.0.0.1', 'GET', '/opsys/crm/journal-equipes/comptes' + slash + '?jour=2030-06-03', '1.1', 200), None)
    MasquerRecherche().filter(record)
    ligne = AccessFormatter(fmt='%(request_line)s %(status_code)s', use_colors=False).format(record)
    assert '2030-06-03' not in ligne and '[MASQUE]' in ligne and '200' in ligne


def test_homonymes_pages_terminales_et_jour_lie_au_curseur(monde, session):
    ajouter_compte(session, 'homonyme.b', 'Même nom fictif', ['seller'])
    ajouter_compte(session, 'homonyme.a', 'Même nom fictif', ['finance'])
    with session() as cnx:
        vue = module().lire(cnx, w.g.AUTH, w.g.D)
        ids = [x['personne_id'] for x in vue['lignes'] if x['nom_actuel'] == 'Même nom fictif']
        assert ids == ['homonyme.a', 'homonyme.b']
        fin = module().lire(cnx, w.g.AUTH, w.g.D, debut=vue['total'], source_attendue=vue['source'])
        assert fin['lignes'] == [] and fin['total'] == vue['total'] and fin['suivant'] is None
        with pytest.raises(ValueError, match='SOURCE-PERIMEE'):
            module().lire(cnx, w.g.AUTH, '2030-06-04', debut=1, source_attendue=vue['source'])


@pytest.mark.parametrize('mutation', ['role', 'activation', 'secret'])
def test_curseur_suit_attributs_utiles_seulement(monde, session, mutation):
    with session() as cnx:
        vue = module().lire(cnx, w.g.AUTH, w.g.D, limite=1)
    with session() as cnx:
        if mutation == 'role':
            identite.ajouter_role(cnx, w.g.PERSONNE, 'manager')
        elif mutation == 'activation':
            cnx.execute(PERSONNES.update().where(PERSONNES.c.identifiant == w.g.PERSONNE).values(actif=True))
        else:
            cnx.execute(PERSONNES.update().where(PERSONNES.c.identifiant == w.g.PERSONNE)
                        .values(mot_de_passe_hash='fictif-hash-jamais-lu-par-le-repertoire'))
    with session() as cnx:
        if mutation != 'secret':
            with pytest.raises(ValueError, match='SOURCE-PERIMEE'):
                module().lire(cnx, w.g.AUTH, w.g.D, debut=1, source_attendue=vue['source'])
        else:
            suite = module().lire(cnx, w.g.AUTH, w.g.D, debut=1, source_attendue=vue['source'])
            assert suite['source'] == vue['source'] and suite['total'] == vue['total']
