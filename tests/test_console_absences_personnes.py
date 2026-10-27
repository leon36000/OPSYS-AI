"""fictif: true — vraie lecture T0/SQLite privée des absences administratives déclarées."""
import importlib
import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from m4_field_ops import absences_journalieres as domaine
from m4_field_ops import encodage
from m4_field_ops.outils import outils
from m4_field_ops.registre import Registre
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.console import preparation_chantier as lecture
from opsys.console.securite import Session
from opsys.departements import charger_departements
from opsys.outils import executer
from opsys.stockage.schema import REGISTRES

spec = importlib.util.spec_from_file_location('absence_console_fixture',
    Path(__file__).with_name('test_console_compositions_equipes.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm = f.client_crm
base = f.f.f.base
AUTH, D, PERSONNE = f.AUTH, f.D, 'inactif.fictif'
FICTIF = True
NOM = 'm4_lire_absence_journaliere_console'


def port():
    return importlib.import_module('opsys.console.absences_personnes')


def durable():
    return importlib.import_module('m4_field_ops.absences_durables')


def ajouter(session, *, revision=0, statut='signalee', cle='m-1', personne=PERSONNE, jour=D):
    args = dict(jour=jour, personne_id=personne, revision_attendue=revision, statut_declaration=statut)
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', domaine.REGISTRE))
        return domaine.declarer(reg, **args, auteur={'personne': AUTH.utilisateur, 'role': 'admin'},
            mutation={'appareil': 'console.fictive', 'cle': cle, 'empreinte_arguments': encodage.empreinte(args)},
            horodatage='2030-06-10T12:00:00+00:00')


def console(outil, **options):
    with (contexte.appele_par_appareil(contexte.IdentiteAppelante(AUTH.utilisateur, 'admin', source='console')),
          contexte.appeler_en_tant_que('m04-field-ops', origine='console')):
        return executer(outil, dict(jour=D, personne_id=PERSONNE, **options))


def test_vrai_t0_reouvert_et_projection_privee_sans_reactivation_ou_autres_ecritures(client_crm, session):
    with session() as cnx:
        identite.creer_personne(cnx, PERSONNE, 'Personne fictive inactive', 'fictif-mot-de-passe',
                               ['employee'], actif=False)
    premier = ajouter(session)
    ajouter(session, revision=1, statut='retiree', cle='m-2')
    par_nom = {o.nom: o for o in outils()}
    assert par_nom[NOM].autonomie.value == 'T0'
    avant = base._instantane_base(session)
    with session() as cnx:
        r = port().lire(cnx, charger_departements(), AUTH, D, PERSONNE)
        direct = console(par_nom[NOM])
        assert identite.personne(cnx, PERSONNE).actif is False
        inconnu = port().lire(cnx, charger_departements(), AUTH, D, 'autre.fictif')
    assert direct['resultat']['accepte'] is True and direct['resultat']['resultat'] == r
    assert r['etat_declaration'] == 'retiree' and len(r['source_snapshot']) == 64
    assert r['lignes'][0]['source_ligne_id'] == premier['resultat']['declaration_id']
    assert r['lignes'][0]['personne_id'] == PERSONNE and r['lignes'][0]['statut_declaration'] == 'signalee'
    assert r['lignes'][0]['jour'] == D and r['lignes'][0]['horodatage'].startswith('2030-06-10')
    assert inconnu['etat_declaration'] == 'aucun_signalement'
    assert 'Personne fictive inactive' not in str(r) and 'mutation' not in str(r)
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('personne,expire', [('employe', 4102444800), ('nathan', 4102444800),
                                          ('admin.fictif', 1)])
def test_sql_admin_actif_et_session_non_forgee(client_crm, session, personne, expire):
    ajouter(session)
    avant = base._instantane_base(session)
    with session() as cnx, pytest.raises(PermissionError):
        port().lire(cnx, charger_departements(), Session(personne, frozenset({'admin'}), 'fictif', expire), D, PERSONNE)
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('acteur', [None, f.f.f.terrain.ADMIN, f.f.f.terrain.VENDEUR, f.f.f.terrain.MARC])
def test_admin_appareil_ou_agent_nest_pas_console_privee(client_crm, session, acteur):
    ajouter(session)
    par_nom = {o.nom: o for o in outils()}
    avant = base._instantane_base(session)
    r = f.f.f.terrain._appeler(par_nom, NOM, dict(jour=D, personne_id=PERSONNE), acteur)
    assert r['resultat']['verdict']['code'] == 'REJ-ABSENCE-IDENTITE'
    assert PERSONNE not in str(r)
    assert base._instantane_base(session) == avant


def test_mcp_connexion_et_registre_injectes_refuses(client_crm, session):
    ajouter(session)
    outil = {o.nom: o for o in outils()}[NOM]
    avant = base._instantane_base(session)
    with session(), contexte.transport_mcp():
        assert console(outil)['resultat']['verdict']['code'] == 'REJ-ABSENCE-IDENTITE'
    with session() as cnx:
        with cnx.engine.connect() as autre, pytest.raises(lecture.Refus, match='INSTANCE-NON-QUALIFIEE'):
            port().lire(autre, charger_departements(), AUTH, D, PERSONNE)
        injecte = {o.nom: o for o in outils(Registre())}[NOM]
        assert console(injecte)['resultat']['verdict']['code'] == 'REJ-ABSENCE-INSTANCE-NON-QUALIFIEE'
    assert base._instantane_base(session) == avant


def test_reponse_t0_et_source_independante_ne_peuvent_diverger(client_crm, session, monkeypatch):
    ajouter(session)
    p = port()
    original = p._t0

    def falsifier(*args):
        r = original(*args)
        r['etat_declaration'] = 'retiree'
        return r

    monkeypatch.setattr(p, '_t0', falsifier)
    avant = base._instantane_base(session)
    with session() as cnx, pytest.raises(lecture.Refus, match='SOURCE-REPONSE-INCOHERENTE'):
        p.lire(cnx, charger_departements(), AUTH, D, PERSONNE)
    assert base._instantane_base(session) == avant


def test_metadonnees_mutantes_pendant_t0_refusees(client_crm, session, monkeypatch):
    ajouter(session)
    d = durable()
    original = d.projeter

    def falsifier(*args, **kwargs):
        r = original(*args, **kwargs)
        cnx = stockage.connexion_courante()
        condition = (REGISTRES.c.departement == 'm04-field-ops') & (REGISTRES.c.registre == domaine.REGISTRE)
        ligne = cnx.execute(select(REGISTRES).where(condition).limit(1)).mappings().one()
        cnx.execute(REGISTRES.update().where(condition & (REGISTRES.c.rang == ligne['rang']))
                    .values(cree_le=ligne['cree_le'] + timedelta(seconds=1)))
        return r

    monkeypatch.setattr(d, 'projeter', falsifier)
    with session():
        r = console({o.nom: o for o in outils()}[NOM])
    assert r['resultat']['verdict']['code'] == 'REJ-ABSENCE-SOURCE-MODIFIEE'
    assert PERSONNE not in str(r)


@pytest.mark.parametrize('capture_finale', [2, 4])
def test_revocation_apres_derniere_capture_est_refusee(client_crm, session, monkeypatch, capture_finale):
    ajouter(session)
    d = durable()
    original, appels = d.capturer, []

    def retirer(cnx):
        r = original(cnx)
        appels.append(1)
        if len(appels) == capture_finale:
            identite.ajouter_role(cnx, AUTH.utilisateur, 'nathan_owner')
            identite.retirer_role(cnx, AUTH.utilisateur, 'admin')
        return r

    monkeypatch.setattr(d, 'capturer', retirer)
    if capture_finale == 2:
        with session():
            r = console({o.nom: o for o in outils()}[NOM])
        assert r['resultat']['verdict']['code'] == 'REJ-ABSENCE-IDENTITE'
        assert PERSONNE not in str(r)
    else:
        with session() as cnx, pytest.raises(PermissionError):
            port().lire(cnx, charger_departements(), AUTH, D, PERSONNE)
    assert len(appels) == capture_finale


@pytest.mark.parametrize('quota', ['octets', 'nombre'])
def test_quota_sql_avant_decodage_et_sortie_sans_fuite(client_crm, session, monkeypatch, quota):
    ajouter(session)
    outil = {o.nom: o for o in outils()}[NOM]
    avant = base._instantane_base(session)
    with session(), contexte.sortie_bornee(100):
        assert console(outil)['resultat']['verdict']['code'] == 'REJ-ABSENCE-SORTIE-TROP-VOLUMINEUSE'
    assert base._instantane_base(session) == avant
    if quota == 'octets':
        with session() as cnx:
            condition = (REGISTRES.c.departement == 'm04-field-ops') & (REGISTRES.c.registre == domaine.REGISTRE)
            cnx.execute(REGISTRES.update().where(condition).values(maillon='x' * (domaine.MAX_OCTETS + 1)))
    else:
        monkeypatch.setattr(domaine, 'MAX_SOURCES', 0)

    def interdit(*args, **kwargs):
        raise AssertionError('décodage après quota interdit')

    monkeypatch.setattr(durable(), 'copier_maillons_avec_metadonnees', interdit)
    with session():
        assert console(outil)['resultat']['verdict']['code'] == 'REJ-ABSENCE-SOURCE-TROP-VOLUMINEUSE'


def test_pages_et_histoire_retraitee_sans_ecriture(client_crm, session):
    ajouter(session)
    ajouter(session, revision=1, statut='retiree', cle='m-2')
    with session() as cnx:
        premier = port().lire(cnx, charger_departements(), AUTH, D, PERSONNE, limite=1)
        suivant = port().lire(cnx, charger_departements(), AUTH, D, PERSONNE, debut=1, limite=1,
                              source_attendue=premier['source'])
    assert premier['suivant'] == 1 and suivant['lignes'][0]['revision'] == 2
    ajouter(session, revision=2, cle='m-3')
    avant = base._instantane_base(session)
    with session() as cnx, pytest.raises(lecture.Refus, match='SOURCE-INVALIDE'):
        port().lire(cnx, charger_departements(), AUTH, D, PERSONNE, debut=1, limite=1,
                    source_attendue=premier['source'])
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('profil', [False, True])
def test_repartiteurs_fermes_avant_factory_normalisation_et_recu(profil):
    from opsys.capacites import Capacites

    def interdite():
        raise AssertionError('factory privée interdite')

    caps = Capacites(charger_departements(), interdite, filtre={'m04-field-ops'},
                     appelant='m04-field-ops', memoire=False)
    if profil:
        r = caps.appeler_profil_runtime(NOM, object(), None, None, profile_id='profil.fictif',
                                       profile_revision=1, server='opsys_m4')
    else:
        r = caps.appeler(NOM, object())
    assert r == {'ok': False, 'erreur': 'port_console_prive_requis'}


@pytest.mark.parametrize('maillon', ['{', '{"invalid":true}'])
def test_json_ou_schema_sql_invalide_refuse_sans_reparation(client_crm, session, maillon):
    ajouter(session)
    with session() as cnx:
        condition = (REGISTRES.c.departement == 'm04-field-ops') & (REGISTRES.c.registre == domaine.REGISTRE)
        cnx.execute(REGISTRES.update().where(condition).values(maillon=maillon))
    avant = base._instantane_base(session)
    with session():
        r = console({o.nom: o for o in outils()}[NOM])
    assert r['resultat']['verdict']['code'] == 'REJ-ABSENCE-SOURCE-INVALIDE'
    assert PERSONNE not in str(r)
    assert base._instantane_base(session) == avant
