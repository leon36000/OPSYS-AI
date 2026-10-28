"""fictif: true — journal privé SQL, vrais outils M4, aucune action terrain réelle."""
import importlib.util
from importlib import import_module
from pathlib import Path

import pytest
from m4_field_ops import journal_durable
from m4_field_ops.outils import outils
from m4_field_ops.registre import Registre
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.console import preparation_chantier as lecture
from opsys.console.securite import Session
from opsys.departements import charger_departements
from opsys.outils import executer
from opsys.stockage.schema import REGISTRES

spec = importlib.util.spec_from_file_location('journal_sql_fixture', Path(__file__).with_name('test_console_cedule.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, planning = f.client_crm, f.planning
FICTIF = True
AUTH = Session('admin.fictif', frozenset({'admin'}), 'csrf-fictif', 4102444800)
JOUR = '2030-06-03'
NOM = 'm4_lire_journal_quotidien'


def test_journal_sql_reel_sans_effet_et_source_snapshot(planning, session):
    port = import_module('opsys.console.journal_equipes')
    _, ids, confirmation, _ = planning
    avant = f.base._instantane_base(session)
    with session() as cnx:
        r = port.lire(cnx, charger_departements(), AUTH, JOUR)
    assert r['total'] == len(ids) and r['jour'] == JOUR
    assert {x['intervention_id'] for x in r['lignes']} == set(ids.values())
    assert all(x['source_ligne_id'] == confirmation['ligne_id'] for x in r['lignes'])
    assert len(r['source_snapshot']) == 64
    assert f.base._instantane_base(session) == avant


def test_outil_t0_journal_est_declenchement_proprietaire(planning):
    par_nom, _, _, _ = planning
    assert NOM in par_nom
    assert par_nom[NOM].autonomie.value == 'T0'


def _console(outil, **kwargs):
    with (contexte.appele_par_appareil(contexte.IdentiteAppelante(AUTH.utilisateur, 'admin', source='console')),
          contexte.appeler_en_tant_que('m04-field-ops', origine='console')):
        return executer(outil, dict(jour=JOUR, **kwargs))


@pytest.mark.parametrize('acteur', [None, f.terrain.ADMIN, f.terrain.VENDEUR, f.terrain.MARC, f.terrain.FANTOME])
def test_agents_mcp_appareil_direct_refuses_meme_admin(planning, session, acteur):
    par_nom, _, _, _ = planning
    avant = f.base._instantane_base(session)
    r = f.terrain._appeler(par_nom, NOM, dict(jour=JOUR), acteur)
    assert r['resultat']['accepte'] is False
    assert r['resultat']['verdict']['code'] == 'REJ-JOURNAL-IDENTITE'
    assert 'lignes' not in r['resultat']
    assert f.base._instantane_base(session) == avant


@pytest.mark.parametrize('personne,expire', [('employe', 4102444800), ('nathan', 4102444800),
                                         ('admin.fictif', 1)])
def test_role_session_port_courants_exiges(planning, session, personne, expire):
    port = import_module('opsys.console.journal_equipes')
    avant = f.base._instantane_base(session)
    with session() as cnx, pytest.raises(PermissionError):
        port.lire(cnx, charger_departements(), Session(personne, frozenset({'admin'}), 'fictif', expire), JOUR)
    assert f.base._instantane_base(session) == avant


def test_connexion_etrangere_et_registre_injecte_refuses(planning, session):
    port = import_module('opsys.console.journal_equipes')
    avant = f.base._instantane_base(session)
    with session() as cnx:
        with cnx.engine.connect() as autre, pytest.raises(lecture.Refus, match='INSTANCE-NON-QUALIFIEE'):
            port.lire(autre, charger_departements(), AUTH, JOUR)
        injectes = {o.nom: o for o in outils(Registre())}
        r = _console(injectes[NOM])
        assert r['resultat']['verdict']['code'] == 'REJ-JOURNAL-INSTANCE-NON-QUALIFIEE'
    assert f.base._instantane_base(session) == avant


def test_reponse_t0_alteree_refusee_sans_reparation(planning, session, monkeypatch):
    port = import_module('opsys.console.journal_equipes')
    original = port._t0

    def alterer(*args):
        r = original(*args)
        r['lignes'][0]['equipe_planifiee'] = 'fausse.equipe.fictive'
        return r

    monkeypatch.setattr(port, '_t0', alterer)
    avant = f.base._instantane_base(session)
    with session() as cnx, pytest.raises(lecture.Refus, match='SOURCE-REPONSE-INCOHERENTE'):
        port.lire(cnx, charger_departements(), AUTH, JOUR)
    assert f.base._instantane_base(session) == avant


def test_derniere_capture_revoque_admin_port_refuse(planning, session, monkeypatch):
    port = import_module('opsys.console.journal_equipes')
    original, appels = journal_durable.capturer, []

    def capture(cnx):
        r = original(cnx)
        appels.append(1)
        if len(appels) == 4:
            identite.ajouter_role(cnx, AUTH.utilisateur, 'nathan_owner')
            identite.retirer_role(cnx, AUTH.utilisateur, 'admin')
        return r

    monkeypatch.setattr(journal_durable, 'capturer', capture)
    with session() as cnx, pytest.raises(PermissionError):
        port.lire(cnx, charger_departements(), AUTH, JOUR)
    assert len(appels) == 4


def test_t0_recontrole_autorite_apres_derniere_capture(planning, session, monkeypatch):
    par_nom, _, _, _ = planning
    original, appels = journal_durable.capturer, []

    def capture(cnx):
        r = original(cnx)
        appels.append(1)
        if len(appels) == 2:
            identite.ajouter_role(cnx, AUTH.utilisateur, 'nathan_owner')
            identite.retirer_role(cnx, AUTH.utilisateur, 'admin')
        return r

    monkeypatch.setattr(journal_durable, 'capturer', capture)
    with session():
        r = _console(par_nom[NOM])
    assert r['resultat']['verdict']['code'] == 'REJ-JOURNAL-IDENTITE'
    assert 'lignes' not in r['resultat']


def test_metadonnees_source_modifiees_durant_t0_refusees(planning, session, monkeypatch):
    from datetime import timedelta

    par_nom, _, _, _ = planning
    original = journal_durable.projeter

    def changer(*args, **kwargs):
        r = original(*args, **kwargs)
        cnx = stockage.connexion_courante()
        condition = (REGISTRES.c.departement == 'm04-field-ops') & (REGISTRES.c.registre == 'principal')
        ligne = cnx.execute(select(REGISTRES).where(condition).limit(1)).mappings().one()
        cnx.execute(REGISTRES.update().where(condition & (REGISTRES.c.rang == ligne['rang']))
                    .values(cree_le=ligne['cree_le'] + timedelta(seconds=1)))
        return r

    monkeypatch.setattr(journal_durable, 'projeter', changer)
    with session():
        r = _console(par_nom[NOM])
    assert r['resultat']['verdict']['code'] == 'REJ-JOURNAL-SOURCE-MODIFIEE'
    assert 'lignes' not in r['resultat']


def test_quota_sql_avant_decodage_et_borne_sortie(planning, session, monkeypatch):
    par_nom, _, _, _ = planning
    avant = f.base._instantane_base(session)
    with session(), contexte.sortie_bornee(100):
        r = _console(par_nom[NOM])
        assert r['resultat']['verdict']['code'] == 'REJ-JOURNAL-SORTIE-TROP-VOLUMINEUSE'
    assert f.base._instantane_base(session) == avant

    def interdit(*args, **kwargs):
        raise AssertionError('décodage après quota interdit')

    with session() as cnx:
        condition = (REGISTRES.c.departement == 'm04-field-ops') & (REGISTRES.c.registre == 'principal')
        ligne = cnx.execute(select(REGISTRES.c.rang).where(condition).limit(1)).scalar_one()
        cnx.execute(REGISTRES.update().where(condition & (REGISTRES.c.rang == ligne))
                    .values(maillon='x' * (8 * 1024 * 1024 + 1)))
    monkeypatch.setattr(journal_durable, 'copier_maillons_avec_metadonnees', interdit)
    with session():
        r = _console(par_nom[NOM])
        assert r['resultat']['verdict']['code'] == 'REJ-JOURNAL-SOURCE-TROP-VOLUMINEUSE'


def test_continuation_sql_ancienne_tete_refuse_sans_ecriture(planning, session):
    from m4_field_ops import etats

    port = import_module('opsys.console.journal_equipes')
    _, ids, _, _ = planning
    with session() as cnx:
        premier = port.lire(cnx, charger_departements(), AUTH, JOUR, limite=1)
        assert premier['suivant'] == 1
        assert etats.transitionner(next(iter(ids.values())), 'reportee', f.terrain._registre(),
                                  JOUR + 'T10:00:00-04:00', motif='meteo')[1] is None
    avant = f.base._instantane_base(session)
    with session() as cnx, pytest.raises(lecture.Refus, match='SOURCE-JOURNAL-INVALIDE'):
        port.lire(cnx, charger_departements(), AUTH, JOUR, debut=1, limite=1,
                  source_attendue=premier['source'])
    assert f.base._instantane_base(session) == avant


@pytest.mark.parametrize('profile', [False, True])
def test_capacites_generiques_refusent_avant_factory_et_normalisation(profile):
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


def test_transport_mcp_refuse_meme_identite_console(planning, session):
    par_nom, _, _, _ = planning
    avant = f.base._instantane_base(session)
    with session(), contexte.transport_mcp():
        r = _console(par_nom[NOM])
    assert r['resultat']['verdict']['code'] == 'REJ-JOURNAL-IDENTITE'
    assert f.base._instantane_base(session) == avant
