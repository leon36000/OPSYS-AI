"""fictif: true — source SQLite réelle et port T0 privé, sans saisie HTTP ni présence prouvée."""
import importlib
import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from m4_field_ops import composition_journaliere as domaine
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

spec = importlib.util.spec_from_file_location('composition_console_fixture',
    Path(__file__).with_name('test_console_journal_equipes.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm = f.client_crm
FICTIF = True
D, EQUIPE = '2030-06-03', 'eq-a'
NOM = 'm4_lire_composition_journaliere_console'
AUTH = f.AUTH


def port():
    return importlib.import_module('opsys.console.compositions_equipes')


def durable():
    return importlib.import_module('m4_field_ops.composition_durable')


def ajouter(session, revision=0, membres=None, cle='m-1', statut='declaree'):
    args = dict(jour=D, equipe_id=EQUIPE, membres=['alice.fictive', 'inactif.fictif'] if membres is None
        and statut == 'declaree' else membres, revision_attendue=revision, statut_declaration=statut)
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', domaine.REGISTRE))
        return domaine.declarer(reg, **args, auteur={'personne': AUTH.utilisateur, 'role': 'admin'},
            mutation={'appareil': 'console.fictive', 'cle': cle, 'empreinte_arguments': encodage.empreinte(args)},
            horodatage='2030-06-10T12:00:00+00:00')


def console(outil, **options):
    with (contexte.appele_par_appareil(contexte.IdentiteAppelante(AUTH.utilisateur, 'admin', source='console')),
          contexte.appeler_en_tant_que('m04-field-ops', origine='console')):
        return executer(outil, dict(jour=D, equipe_id=EQUIPE, **options))


def test_source_canonique_reouverte_vrai_t0_et_port_prive_sans_ecriture(client_crm, session):
    with session() as cnx:
        identite.creer_personne(cnx, 'inactif.fictif', 'Personne fictive inactive', 'fictif-mot-de-passe',
                               ['employee'], actif=False)
    premier = ajouter(session)
    ajouter(session, revision=1, membres=[], cle='m-2')
    par_nom = {o.nom: o for o in outils()}
    assert par_nom[NOM].autonomie.value == 'T0'
    avant = f.f.base._instantane_base(session)
    with session() as cnx:
        r = port().lire(cnx, charger_departements(), AUTH, D, EQUIPE)
        direct = console(par_nom[NOM])
    assert direct['resultat']['accepte'] is True and direct['resultat']['resultat'] == r
    assert r['composition_connue'] is True and r['membres'] == [] and len(r['source_snapshot']) == 64
    assert r['lignes'][0]['source_ligne_id'] == premier['resultat']['declaration_id']
    assert r['lignes'][0]['membres'] == ['alice.fictive', 'inactif.fictif']
    assert f.f.base._instantane_base(session) == avant


@pytest.mark.parametrize('personne,expire', [('employe', 4102444800), ('nathan', 4102444800),
                                          ('admin.fictif', 1)])
def test_admin_sql_courant_session_valide_exiges(client_crm, session, personne, expire):
    ajouter(session)
    avant = f.f.base._instantane_base(session)
    with session() as cnx, pytest.raises(PermissionError):
        port().lire(cnx, charger_departements(), Session(personne, frozenset({'admin'}), 'fictif', expire), D, EQUIPE)
    assert f.f.base._instantane_base(session) == avant


@pytest.mark.parametrize('acteur', [None, f.f.terrain.ADMIN, f.f.terrain.VENDEUR, f.f.terrain.MARC])
def test_agents_et_appareils_directs_refuses_meme_admin(client_crm, session, acteur):
    ajouter(session)
    par_nom = {o.nom: o for o in outils()}
    avant = f.f.base._instantane_base(session)
    r = f.f.terrain._appeler(par_nom, NOM, dict(jour=D, equipe_id=EQUIPE), acteur)
    assert r['resultat']['verdict']['code'] == 'REJ-COMPOSITION-IDENTITE'
    assert 'membres' not in str(r)
    assert f.f.base._instantane_base(session) == avant


def test_mcp_console_et_registre_injecte_fermes(client_crm, session):
    ajouter(session)
    par_nom = {o.nom: o for o in outils()}
    avant = f.f.base._instantane_base(session)
    with session(), contexte.transport_mcp():
        assert console(par_nom[NOM])['resultat']['verdict']['code'] == 'REJ-COMPOSITION-IDENTITE'
    with session() as cnx:
        with cnx.engine.connect() as autre, pytest.raises(lecture.Refus, match='INSTANCE-NON-QUALIFIEE'):
            port().lire(autre, charger_departements(), AUTH, D, EQUIPE)
        injecte = {o.nom: o for o in outils(Registre())}
        assert console(injecte[NOM])['resultat']['verdict']['code'] == 'REJ-COMPOSITION-INSTANCE-NON-QUALIFIEE'
    assert f.f.base._instantane_base(session) == avant


def test_reponse_t0_alteree_refusee_sans_reparation(client_crm, session, monkeypatch):
    ajouter(session)
    p = port()
    original = p._t0

    def alterer(*args):
        r = original(*args)
        r['membres'] = ['fausse.personne']
        return r

    monkeypatch.setattr(p, '_t0', alterer)
    avant = f.f.base._instantane_base(session)
    with session() as cnx, pytest.raises(lecture.Refus, match='SOURCE-REPONSE-INCOHERENTE'):
        p.lire(cnx, charger_departements(), AUTH, D, EQUIPE)
    assert f.f.base._instantane_base(session) == avant


def test_metadonnees_changees_pendant_t0_refusees(client_crm, session, monkeypatch):
    ajouter(session)
    d = durable()
    original = d.projeter

    def alterer(*args, **kwargs):
        r = original(*args, **kwargs)
        cnx = stockage.connexion_courante()
        condition = (REGISTRES.c.departement == 'm04-field-ops') & (REGISTRES.c.registre == domaine.REGISTRE)
        ligne = cnx.execute(select(REGISTRES).where(condition).limit(1)).mappings().one()
        cnx.execute(REGISTRES.update().where(condition & (REGISTRES.c.rang == ligne['rang']))
                    .values(cree_le=ligne['cree_le'] + timedelta(seconds=1)))
        return r

    monkeypatch.setattr(d, 'projeter', alterer)
    with session():
        r = console({o.nom: o for o in outils()}[NOM])
    assert r['resultat']['verdict']['code'] == 'REJ-COMPOSITION-SOURCE-MODIFIEE'
    assert 'membres' not in str(r)


@pytest.mark.parametrize('capture_finale', [2, 4])
def test_revocation_apres_derniere_capture_t0_ou_port(client_crm, session, monkeypatch, capture_finale):
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
        assert r['resultat']['verdict']['code'] == 'REJ-COMPOSITION-IDENTITE'
        assert 'membres' not in str(r)
    else:
        with session() as cnx, pytest.raises(PermissionError):
            port().lire(cnx, charger_departements(), AUTH, D, EQUIPE)
    assert len(appels) == capture_finale


def test_quota_sortie_et_sql_avant_decodage(client_crm, session, monkeypatch):
    ajouter(session)
    outil = {o.nom: o for o in outils()}[NOM]
    avant = f.f.base._instantane_base(session)
    with session(), contexte.sortie_bornee(100):
        assert console(outil)['resultat']['verdict']['code'] == 'REJ-COMPOSITION-SORTIE-TROP-VOLUMINEUSE'
    assert f.f.base._instantane_base(session) == avant
    with session() as cnx:
        condition = (REGISTRES.c.departement == 'm04-field-ops') & (REGISTRES.c.registre == domaine.REGISTRE)
        cnx.execute(REGISTRES.update().where(condition).values(maillon='x' * (domaine.MAX_OCTETS + 1)))

    def interdit(*args, **kwargs):
        raise AssertionError('décodage après quota interdit')

    monkeypatch.setattr(durable(), 'copier_maillons_avec_metadonnees', interdit)
    with session():
        assert console(outil)['resultat']['verdict']['code'] == 'REJ-COMPOSITION-SOURCE-TROP-VOLUMINEUSE'


def test_historique_pagine_puis_retrait_perime_source_sans_ecriture(client_crm, session):
    ajouter(session)
    ajouter(session, revision=1, membres=[], cle='m-2')
    with session() as cnx:
        premier = port().lire(cnx, charger_departements(), AUTH, D, EQUIPE, limite=1)
        suivant = port().lire(cnx, charger_departements(), AUTH, D, EQUIPE, debut=1, limite=1,
                              source_attendue=premier['source'])
    assert premier['suivant'] == 1 and suivant['lignes'][0]['revision'] == 2
    ajouter(session, revision=2, membres=None, cle='m-3', statut='retiree')
    avant = f.f.base._instantane_base(session)
    with session() as cnx, pytest.raises(lecture.Refus, match='SOURCE-INVALIDE'):
        port().lire(cnx, charger_departements(), AUTH, D, EQUIPE, debut=1, limite=1,
                    source_attendue=premier['source'])
    assert f.f.base._instantane_base(session) == avant


@pytest.mark.parametrize('profile', [False, True])
def test_repartiteurs_fermes_avant_factory_normalisation_et_recu(profile):
    from opsys.capacites import Capacites

    def interdite():
        raise AssertionError('factory privée interdite')

    caps = Capacites(charger_departements(), interdite, filtre={'m04-field-ops'},
                     appelant='m04-field-ops', memoire=False)
    if profile:
        r = caps.appeler_profil_runtime(NOM, object(), None, None, profile_id='profil.fictif',
                                       profile_revision=1, server='opsys_m4')
    else:
        r = caps.appeler(NOM, object())
    assert r == {'ok': False, 'erreur': 'port_console_prive_requis'}



def test_page_valide_trop_grande_signale_quota_et_reste_lisible_par_petites_pages(client_crm, session):
    membres = ['membre.fictif.' + str(i).zfill(2) + 'x' * 48 for i in range(50)]
    for i in range(24):
        ajouter(session, revision=i, membres=membres, cle='volume-' + str(i))
    outil = {o.nom: o for o in outils()}[NOM]
    avant = f.f.base._instantane_base(session)
    with session():
        r = console(outil)
        petit = console(outil, limite=1)
    assert r['resultat']['verdict']['code'] == 'REJ-COMPOSITION-SORTIE-TROP-VOLUMINEUSE'
    assert 'membre.fictif.' not in str(r)
    assert petit['resultat']['accepte'] is True
    assert petit['resultat']['resultat']['lignes'][0]['membres'] == membres
    assert f.f.base._instantane_base(session) == avant



@pytest.mark.parametrize('maillon', ['{', '{"invalid":true}'])
def test_source_sql_invalide_refusee_sans_reparation(client_crm, session, maillon):
    ajouter(session)
    with session() as cnx:
        condition = (REGISTRES.c.departement == 'm04-field-ops') & (REGISTRES.c.registre == domaine.REGISTRE)
        cnx.execute(REGISTRES.update().where(condition).values(maillon=maillon))
    avant = f.f.base._instantane_base(session)
    with session():
        r = console({o.nom: o for o in outils()}[NOM])
    assert r['resultat']['verdict']['code'] == 'REJ-COMPOSITION-SOURCE-INVALIDE'
    assert 'membres' not in str(r)
    assert f.f.base._instantane_base(session) == avant
