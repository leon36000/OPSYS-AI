"""fictif: true — consultation réelle T0/SQLite/HTTP des temps pointés, sans paie."""
import importlib
import importlib.util
import logging
from pathlib import Path

import pytest
from m4_field_ops import journal_durable, journal_quotidien
from m4_field_ops.outils import outils
from m4_field_ops.registre import Registre
from sqlalchemy import event

from opsys import contexte, identite, stockage
from opsys.console import preparation_chantier as lecture
from opsys.console.securite import Session
from opsys.departements import charger_departements
from opsys.stockage.schema import PERSONNES

spec = importlib.util.spec_from_file_location('temps_fixture', Path(__file__).with_name('test_console_crm.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
client_crm = base.client_crm
FICTIF = True
AUTH = Session('admin.fictif', frozenset({'admin'}), 'fictif-csrf', 4102444800)
JOUR = '2030-06-03'
PERSONNE = 'employe'
URL = '/crm/journal-equipes/temps?jour=' + JOUR + '&personne_id=' + PERSONNE
NOM = 'm4_previsualiser_heures_regulieres'


def port():
    return importlib.import_module('opsys.console.temps_pointes')


def sources(session, *, incomplet=False, dst=False):
    iid = 'chantier.<script>FICTIF</script>'
    moments = ['2030-06-03T12:45:00+00:00', '2030-06-03T13:00:00+00:00',
               '2030-06-03T15:00:00+00:00']
    if dst:
        moments = ['2026-11-01T05:00:00+00:00', '2026-11-01T05:30:00+00:00', '2026-11-01T06:30:00+00:00']
    lignes = [dict(type_entree='transition_statut', intervention_id=iid, statut='en_route',
                   technicien_id=PERSONNE, horodatage=moments[0]),
               dict(type_entree='pointage', intervention_id=iid, technicien_id=PERSONNE, action='arrivee',
                    horodatage=moments[1], latitude=45.123456, longitude=-73.654321)]
    if not dst:
        lignes += [dict(type_entree='pointage', intervention_id=iid, technicien_id=PERSONNE, action=a,
                        horodatage=h) for a, h in [('pause_debut', '2030-06-03T14:00:00+00:00'),
                                                 ('pause_fin', '2030-06-03T14:30:00+00:00')]]
    if not incomplet:
        lignes.append(dict(type_entree='pointage', intervention_id=iid, technicien_id=PERSONNE,
                           action='depart', horodatage=moments[2]))
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        for ligne in lignes:
            reg.ajouter(ligne)


def lire(session, **options):
    with session() as cnx:
        return port().lire(cnx, charger_departements(), AUTH, JOUR, PERSONNE, **options)


def connecter(client, personne='admin.fictif'):
    base._connecter(client, personne)


def test_vrai_t0_port_http_minutes_sans_doubles_comptes_ou_gps(client_crm, session):
    sources(session)
    avant = base._instantane_base(session)
    with session() as cnx:
        resultat = port().lire(cnx, charger_departements(), AUTH, JOUR, PERSONNE)
        outil = {o.nom: o for o in outils()}[NOM]
        brut = port()._t0(charger_departements(), AUTH, dict(technicien_id=PERSONNE, debut=JOUR,
                         fin=JOUR, fuseau='America/Montreal'))
    assert outil.autonomie.value == 'T0' and brut['accepte'] is True
    assert resultat['proposition'] == brut['resultat'] and resultat['etat'] == 'calcul_disponible'
    assert resultat['proposition']['categories_minutes'] == dict(travail=90, deplacement=15, pause=30)
    assert len(resultat['source_snapshot']) == 64 and len(resultat['source_identite']) == 64
    assert 'latitude' not in str(resultat) and 'longitude' not in str(resultat)
    connecter(client_crm)
    r = client_crm.get(URL)
    assert r.status_code == 200, r.text
    assert 'Aperçu des temps pointés' in r.text and 'America/Montreal' in r.text
    assert '90' in r.text and '30' in r.text and '15' in r.text and 'Minutes de travail net' in r.text
    assert '&lt;script&gt;FICTIF&lt;/script&gt;' in r.text and '<script>FICTIF</script>' not in r.text
    assert '45.123456' not in r.text and '-73.654321' not in r.text and 'Employé FICTIF' not in r.text
    assert '09:00:00-04:00' in r.text and '11:00:00-04:00' in r.text
    assert r.headers['cache-control'] == 'no-store' and 'content-security-policy' in r.headers
    assert client_crm.post(URL).status_code == 405
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('incomplet', [False, True])
def test_sans_source_ou_sequence_incomplete_pas_zero_heure(client_crm, session, incomplet):
    if incomplet:
        sources(session, incomplet=True)
    attendu = 'REJ-POINTAGES-AMBIGUS' if incomplet else 'REJ-SOURCES-ABSENTES'
    avant = base._instantane_base(session)
    resultat = lire(session)
    assert resultat['etat'] == 'indisponible' and resultat['code'] == attendu
    assert 'proposition' not in resultat and 'categories_minutes' not in str(resultat)
    connecter(client_crm)
    r = client_crm.get(URL)
    assert r.status_code == 200 and attendu in r.text and 'Aucun total déduit' in r.text
    assert 'Minutes de travail net' not in r.text
    assert base._instantane_base(session) == avant


def test_jour_hors_source_et_utc_pendant_repli_dst(client_crm, session):
    sources(session, dst=True)
    assert lire(session)['code'] == 'REJ-SOURCES-ABSENTES'
    with session() as cnx:
        vue = port().lire(cnx, charger_departements(), AUTH, '2026-11-01', PERSONNE)
    assert vue['proposition']['categories_minutes'] == dict(travail=60, deplacement=30, pause=0)
    d = vue['proposition']['details_intervalles'][0]['travail']
    assert d['debut'].endswith('-04:00') and d['fin'].endswith('-05:00')


@pytest.mark.parametrize('personne,expire', [('employe', 4102444800), ('nathan', 4102444800), ('admin.fictif', 1)])
def test_autorite_courante_et_connexion_exacte(client_crm, session, personne, expire):
    sources(session)
    avant = base._instantane_base(session)
    with session() as cnx, pytest.raises(PermissionError):
        auth = Session(personne, frozenset({'admin'}), 'fictif', expire)
        port().lire(cnx, charger_departements(), auth, JOUR, PERSONNE)
    with session() as cnx, cnx.engine.connect() as autre, pytest.raises(ValueError, match='INSTANCE-NON-QUALIFIEE'):
        port().lire(autre, charger_departements(), AUTH, JOUR, PERSONNE)
    if personne != 'admin.fictif':
        connecter(client_crm, personne)
        assert client_crm.get(URL).status_code == 403
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('mutation', ['inactif', 'client', 'agent'])
def test_cible_courante_admissible_avant_lecture_registre(client_crm, session, monkeypatch, mutation):
    with session() as cnx:
        if mutation == 'inactif':
            cnx.execute(PERSONNES.update().where(PERSONNES.c.identifiant == PERSONNE).values(actif=False))
        elif mutation == 'client':
            identite.ajouter_role(cnx, PERSONNE, 'client')
            identite.retirer_role(cnx, PERSONNE, 'employee')
        else:
            identite.ajouter_role(cnx, PERSONNE, 'system_agent')
    avant = base._instantane_base(session)

    def interdit(*args):
        raise AssertionError('lecture temps après refus cible')

    monkeypatch.setattr(journal_durable, 'capturer', interdit)
    with pytest.raises(lecture.Refus, match='CIBLE-NON-ADMISSIBLE'):
        lire(session)
    assert base._instantane_base(session) == avant


def test_resolution_cible_ne_charge_nom_ni_secret(client_crm, session):
    requetes = []

    def noter(cnx, cursor, statement, parameters, context, executemany):
        requetes.append(statement.lower())

    with session() as cnx:
        event.listen(cnx, 'before_cursor_execute', noter)
        try:
            cible = port()._cible(cnx, PERSONNE)
        finally:
            event.remove(cnx, 'before_cursor_execute', noter)
    assert set(cible) == {'identifiant', 'actif', 'roles'} and cible['roles'] == ['employee']
    assert requetes and all('personnes.nom' not in sql and 'mot_de_passe_hash' not in sql for sql in requetes)


def test_quota_source_avant_decodage_et_quota_sortie(client_crm, session, monkeypatch):
    sources(session)
    avant = base._instantane_base(session)
    with session() as cnx, contexte.sortie_bornee(10), pytest.raises(lecture.Refus, match='SORTIE-TROP-VOLUMINEUSE'):
        port().lire(cnx, charger_departements(), AUTH, JOUR, PERSONNE)
    monkeypatch.setattr(journal_quotidien, 'MAX_SOURCES', 0)

    def interdit(*args, **kwargs):
        raise AssertionError('décodage après quota')

    monkeypatch.setattr(journal_durable, 'copier_maillons_avec_metadonnees', interdit)
    with pytest.raises(ValueError, match='SOURCE-TROP-VOLUMINEUSE'):
        lire(session)
    assert base._instantane_base(session) == avant


def test_reponse_t0_alteree_et_source_changee_refusees(client_crm, session, monkeypatch):
    sources(session)
    original = port()._t0

    def alterer(*args):
        r = original(*args)
        r['resultat']['categories_minutes']['travail'] = 999
        return r

    monkeypatch.setattr(port(), '_t0', alterer)
    with pytest.raises(ValueError, match='SOURCE-REPONSE-INCOHERENTE'):
        lire(session)

    def changer(*args):
        r = original(*args)
        with session():
            Registre(stockage.maillons('m04-field-ops', 'principal')).ajouter(dict(
                type_entree='transition_statut', intervention_id='autre.fictif', statut='en_route',
                technicien_id=PERSONNE, horodatage='2030-06-04T12:00:00+00:00'))
        return r

    monkeypatch.setattr(port(), '_t0', changer)
    with pytest.raises(ValueError, match='SOURCE-MODIFIEE'):
        lire(session)


@pytest.mark.parametrize('mutation', ['autorite', 'source', 'cible'])
def test_rendu_tardif_ne_divulgue_pas_ancien_contenu(client_crm, session, monkeypatch, mutation):
    from opsys.console import pages

    sources(session)
    connecter(client_crm)
    original = pages.gabarit

    def changer(*args, **kwargs):
        html = original(*args, **kwargs)
        with session() as cnx:
            if mutation == 'autorite':
                identite.retirer_role(cnx, AUTH.utilisateur, 'admin')
            elif mutation == 'cible':
                identite.ajouter_role(cnx, PERSONNE, 'manager')
            else:
                Registre(stockage.maillons('m04-field-ops', 'principal')).ajouter(dict(
                    type_entree='transition_statut', intervention_id='autre.fictif', statut='en_route',
                    horodatage='2030-06-04T12:00:00+00:00'))
        return html

    monkeypatch.setattr(pages, 'gabarit', changer)
    r = client_crm.get(URL)
    assert r.status_code == (403 if mutation == 'autorite' else 503)
    assert 'FICTIF&lt;/script&gt;' not in r.text and '90' not in r.text


@pytest.mark.parametrize('query', ['', 'jour=20300603&personne_id=employe',
    'jour=2030-06-03&personne_id=employe&personne_id=nathan', 'jour=2030-06-03&personne_id=employe&debut=0',
    'jour=2030-06-03', 'jour=2030-06-03&personne_id=Nom libre'])
def test_parametres_stricts(query, client_crm):
    connecter(client_crm)
    assert client_crm.get('/crm/journal-equipes/temps?' + query).status_code == 400


def test_html_borne_et_navigation_sans_temps_copies(client_crm, session, monkeypatch):
    from opsys.console import absences_personnes

    sources(session)
    connecter(client_crm)
    html = absences_personnes.formulaire_consultation(JOUR, base.PREFIXE)
    assert 'formaction="' + base.PREFIXE + '/crm/journal-equipes/temps"' in html
    assert 'name="jour"' in html and 'name="personne_id"' in html and '90' not in html
    avant = base._instantane_base(session)
    monkeypatch.setattr(port(), 'contenu', lambda *args: 'x' * 131073)
    assert client_crm.get(URL).status_code == 503
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('slash', ['', '/'])
def test_logs_temps_masquent_query_entiere(slash):
    from uvicorn.logging import AccessFormatter

    from opsys.console.journaux_http import MasquerRecherche

    r = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s - "%s %s HTTP/%s" %d',
        ('127.0.0.1', 'GET', '/opsys/crm/journal-equipes/temps' + slash + '?jour=2030-06-03', '1.1', 200), None)
    MasquerRecherche().filter(r)
    ligne = AccessFormatter(fmt='%(request_line)s %(status_code)s', use_colors=False).format(r)
    assert '2030-06-03' not in ligne and '[MASQUE]' in ligne and '200' in ligne


@pytest.mark.parametrize('mutation', ['float', 'extra', 'booleen'])
def test_contrat_t0_refuse_types_equivalents_et_champs_supplementaires(client_crm, session, monkeypatch, mutation):
    sources(session)
    original = port()._t0

    def alterer(*args):
        r = original(*args)
        if mutation == 'float':
            r['resultat']['categories_minutes']['travail'] = 90.0
        elif mutation == 'extra':
            r['resultat']['latitude'] = 45.123456
        else:
            r['accepte'] = 1
        return r

    monkeypatch.setattr(port(), '_t0', alterer)
    avant = base._instantane_base(session)
    with pytest.raises(ValueError, match='SOURCE-REPONSE-INCOHERENTE'):
        lire(session)
    assert base._instantane_base(session) == avant


def test_chaine_corrompue_refuse_avant_vrai_t0_sans_reparation(client_crm, session, monkeypatch):
    from sqlalchemy import select

    from opsys.stockage import codec
    from opsys.stockage.schema import REGISTRES

    sources(session)
    with session() as cnx:
        condition = (REGISTRES.c.departement == 'm04-field-ops') & (REGISTRES.c.registre == 'principal')
        requete = select(REGISTRES).where(condition).order_by(REGISTRES.c.rang.desc()).limit(1)
        ligne = cnx.execute(requete).mappings().one()
        maillon = codec.decoder(ligne['maillon'])
        maillon['horodatage'] = '2030-06-03T16:00:00+00:00'
        cnx.execute(REGISTRES.update().where(condition & (REGISTRES.c.rang == ligne['rang']))
                    .values(maillon=codec.encoder(maillon)))
    avant = base._instantane_base(session)

    def interdit(*args):
        raise AssertionError('T0 après chaîne invalide')

    monkeypatch.setattr(port(), '_t0', interdit)
    with pytest.raises(ValueError):
        lire(session)
    connecter(client_crm)
    r = client_crm.get(URL)
    assert r.status_code == 503 and '90' not in r.text
    assert base._instantane_base(session) == avant


def test_metadonnees_ont_leur_propre_recapture_apres_t0(client_crm, session, monkeypatch):
    from datetime import timedelta

    from sqlalchemy import select

    from opsys.stockage.schema import REGISTRES

    sources(session)
    original = port()._t0

    def alterer(*args):
        r = original(*args)
        with session() as cnx:
            condition = (REGISTRES.c.departement == 'm04-field-ops') & (REGISTRES.c.registre == 'principal')
            ligne = cnx.execute(select(REGISTRES).where(condition).limit(1)).mappings().one()
            cnx.execute(REGISTRES.update().where(condition & (REGISTRES.c.rang == ligne['rang']))
                        .values(cree_le=ligne['cree_le'] + timedelta(seconds=1)))
        return r

    monkeypatch.setattr(port(), '_t0', alterer)
    with pytest.raises(ValueError, match='SOURCE-MODIFIEE'):
        lire(session)


def test_vrai_t0_ne_recharge_pas_nom_ou_secret_du_sujet(client_crm, session):
    sources(session)
    requetes = []

    def noter(cnx, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith('select') and PERSONNE in parameters:
            requetes.append(statement.lower())

    with session() as cnx:
        event.listen(cnx, 'before_cursor_execute', noter)
        try:
            r = port()._t0(charger_departements(), AUTH, dict(technicien_id=PERSONNE, debut=JOUR,
                          fin=JOUR, fuseau='America/Montreal'))
        finally:
            event.remove(cnx, 'before_cursor_execute', noter)
    assert r['accepte'] is True and requetes
    assert all('personnes.nom' not in sql and 'mot_de_passe_hash' not in sql for sql in requetes)


@pytest.mark.parametrize('revision', [{'latitude': 45.123456}, True, -1])
def test_revision_validation_rechainee_ne_devient_pas_payload_t0_ou_crm(client_crm, session, revision):
    sources(session)
    with session():
        Registre(stockage.maillons('m04-field-ops', 'principal')).ajouter(dict(
            type_entree='heures_regulieres_validees', technicien_id=PERSONNE,
            horodatage='2030-06-03T16:00:00+00:00',
            periode=dict(debut=JOUR, fin=JOUR, fuseau='America/Montreal'), revision=revision))
    avant = base._instantane_base(session)
    with session():
        brut = port()._t0(charger_departements(), AUTH, dict(technicien_id=PERSONNE, debut=JOUR,
                         fin=JOUR, fuseau='America/Montreal'))
    assert brut['accepte'] is False and brut['verdict']['code'] == 'REJ-VALIDATION-INCOHERENTE'
    with pytest.raises(ValueError, match='SOURCE-INVALIDE'):
        lire(session)
    connecter(client_crm)
    r = client_crm.get(URL)
    assert r.status_code == 503 and '45.123456' not in r.text
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('mutation', ['revision', 'categorie', 'intervalle'])
def test_schema_port_refuse_charge_partagee_par_domaine_et_t0(client_crm, session, monkeypatch, mutation):
    from m4_field_ops import heures_regulieres

    sources(session)
    original = heures_regulieres.previsualiser

    def alterer(*args, **kwargs):
        r = original(*args, **kwargs)
        if mutation == 'revision':
            r['resultat']['validation_precedente'] = dict(revision={'latitude': 45.123456}, ligne_id='a' * 64)
        elif mutation == 'categorie':
            r['resultat']['categories_minutes']['pause'] = False
        else:
            r['resultat']['details_intervalles'][0]['travail']['latitude'] = 45.123456
        return r

    monkeypatch.setattr(heures_regulieres, 'previsualiser', alterer)
    avant = base._instantane_base(session)
    with session():
        brut = port()._t0(charger_departements(), AUTH, dict(technicien_id=PERSONNE, debut=JOUR,
                         fin=JOUR, fuseau='America/Montreal'))
    assert brut['accepte'] is True  # Une simple comparaison au domaine accepterait la même charge.
    with pytest.raises(ValueError, match='SOURCE-REPONSE-INCOHERENTE'):
        lire(session)
    connecter(client_crm)
    r = client_crm.get(URL)
    assert r.status_code == 503 and '45.123456' not in r.text
    assert base._instantane_base(session) == avant
