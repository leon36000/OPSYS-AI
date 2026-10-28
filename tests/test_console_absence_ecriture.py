"""fictif: true — vraie déclaration humaine d'absence, sans santé, emploi ou paie déduite."""
import importlib
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import absences_journalieres as domaine
from m4_field_ops.outils import outils
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.console import metier
from opsys.departements import charger_departements
from opsys.stockage.schema import JOURNAL, REGISTRES

spec = importlib.util.spec_from_file_location('absence_writer_fixture',
    Path(__file__).with_name('test_console_absences_personnes.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
client_crm, base = g.client_crm, g.base
FICTIF = True
NOM = 'm4_declarer_absence_journaliere_console'


@pytest.fixture
def monde(client_crm, session):
    with session() as cnx:
        identite.creer_personne(cnx, g.PERSONNE, 'Personne fictive inactive', 'fictif-mot-de-passe',
                               ['employee'], actif=False)


def args(*, revision=0, statut='signalee', jour=g.D, personne=g.PERSONNE):
    return dict(jour=jour, personne_id=personne, statut_declaration=statut, revision_attendue=revision)


def agir(session, arguments=None, *, cle='absence-fictive-1', acteur=g.AUTH):
    with session() as cnx:
        return metier.executer(cnx, charger_departements(), acteur, NOM, args() if arguments is None else arguments,
                              mutation_id=cle)


def lignes(session):
    with session():
        return list(stockage.maillons('m04-field-ops', domaine.REGISTRE))


def code(r):
    return r['resultat']['verdict']['code']


def test_vrai_writer_admin_sujet_inactif_et_accuse_audit_minimises(monde, session):
    outil = {o.nom: o for o in outils()}[NOM]
    assert outil.autonomie.value == 'T1' and outil.roles_appareil == frozenset()
    avant = dict(base._instantane_base(session))
    r = agir(session)
    assert r['ok'] is True and r['resultat']['accepte'] is True
    assert g.PERSONNE not in str(r)
    m = lignes(session)[0]
    assert m['personne_id'] == g.PERSONNE and m['auteur'] == {'personne': g.AUTH.utilisateur, 'role': 'admin'}
    assert m['horodatage'] == r['resultat']['resultat']['horodatage'] and m['jour'] == g.D
    with session() as cnx:
        assert identite.personne(cnx, g.PERSONNE).actif is False
    apres = dict(base._instantane_base(session))
    for table in avant:
        if table not in {REGISTRES.name, JOURNAL.name}:
            assert apres[table] == avant[table], table
    ajouts = apres[JOURNAL.name][len(avant[JOURNAL.name]):]
    assert ajouts and all(g.PERSONNE not in str(x) and 'Personne fictive inactive' not in str(x) for x in ajouts)


@pytest.mark.parametrize('role', ['employee', 'seller', 'manager', 'finance', 'admin', 'nathan_owner'])
def test_role_interne_connu_peut_etre_signale_sans_modification_role(monde, session, role):
    with session() as cnx:
        identite.ajouter_role(cnx, g.PERSONNE, role)
        if role != 'employee':
            identite.retirer_role(cnx, g.PERSONNE, 'employee')
    avant = dict(base._instantane_base(session))
    assert agir(session)['resultat']['accepte'] is True
    apres = dict(base._instantane_base(session))
    for table in avant:
        if table not in {REGISTRES.name, JOURNAL.name}:
            assert apres[table] == avant[table], table


@pytest.mark.parametrize('roles', [['client'], ['system_agent'], ['employee', 'system_agent']])
def test_client_et_agent_meme_combine_ne_valident_pas_premiere_paire(monde, session, roles):
    with session() as cnx:
        for role in roles:
            identite.ajouter_role(cnx, g.PERSONNE, role)
        if 'employee' not in roles:
            identite.retirer_role(cnx, g.PERSONNE, 'employee')
    avant = base._instantane_base(session)
    assert code(agir(session)) == 'REJ-ABSENCE-CIBLE-NON-CONFIRMEE'
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('personne', ['inconnue.fictive', 'Nom libre', ' employe'])
def test_cible_inconnue_ou_identifiant_invalide_necrit_pas(monde, session, personne):
    avant = base._instantane_base(session)
    r = agir(session, args(personne=personne))
    assert r['resultat']['accepte'] is False
    assert base._instantane_base(session) == avant


def test_retrait_redeclaration_et_rejeu_historique_sans_roles_contemporains(monde, session, monkeypatch):
    premier = agir(session)
    assert agir(session, args(revision=1, statut='retiree'), cle='m-2')['resultat']['accepte'] is True
    with session() as cnx:
        identite.ajouter_role(cnx, g.PERSONNE, 'client')
        identite.retirer_role(cnx, g.PERSONNE, 'employee')
    avant = base._instantane_base(session)
    assert code(agir(session, args(jour='2030-06-07'), cle='autre-jour')) == 'REJ-ABSENCE-CIBLE-NON-CONFIRMEE'
    assert base._instantane_base(session) == avant
    e = importlib.import_module('m4_field_ops.absences_ecriture')

    def interdit(*args):
        raise AssertionError('ne pas résoudre le sujet pour un rejeu ou une paire historique')

    monkeypatch.setattr(e, '_cible_initiale', interdit)
    r = agir(session)
    assert r['resultat']['rejoue'] is True and r['resultat']['resultat'] == premier['resultat']['resultat']
    assert base._instantane_base(session) == avant
    assert agir(session, args(revision=2), cle='m-3')['resultat']['accepte'] is True
    assert agir(session, args(revision=3, statut='retiree'), cle='m-4')['resultat']['accepte'] is True
    assert len(lignes(session)) == 4


def test_cas_conflit_intention_et_rejeu_admin_revoque(monde, session):
    agir(session)
    avant = base._instantane_base(session)
    assert code(agir(session, args(jour='2030-06-07'))) == 'REJ-ABSENCE-MUTATION-CONFLIT'
    assert code(agir(session, cle='autre')) == 'REJ-ABSENCE-REVISION-PERIMEE'
    assert base._instantane_base(session) == avant
    with session() as cnx:
        identite.ajouter_role(cnx, g.AUTH.utilisateur, 'nathan_owner')
        identite.retirer_role(cnx, g.AUTH.utilisateur, 'admin')
    avant = base._instantane_base(session)
    with pytest.raises(PermissionError):
        agir(session)
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('mode', ['panne_audit', 'revocation_auteur', 'metadata', 'cible_modifiee'])
def test_echec_apres_append_annule_meme_exception_capturee(monde, session, monkeypatch, mode):
    e = importlib.import_module('m4_field_ops.absences_ecriture')
    arguments = args()
    if mode == 'metadata':
        agir(session)
        arguments = args(revision=1, statut='retiree')
    avant = base._instantane_base(session)
    original = e.journaliser

    def panne(cnx, *a, **kw):
        if mode == 'panne_audit':
            original(cnx, *a, **kw)
            raise RuntimeError('panne-fictive-apres-append')
        if mode == 'revocation_auteur':
            identite.ajouter_role(cnx, g.AUTH.utilisateur, 'nathan_owner')
            identite.retirer_role(cnx, g.AUTH.utilisateur, 'admin')
        elif mode == 'cible_modifiee':
            identite.ajouter_role(cnx, g.PERSONNE, 'client')
            identite.retirer_role(cnx, g.PERSONNE, 'employee')
        else:
            from datetime import timedelta

            condition = (REGISTRES.c.departement == 'm04-field-ops') & (REGISTRES.c.registre == domaine.REGISTRE)
            ligne = cnx.execute(select(REGISTRES).where(condition).order_by(REGISTRES.c.rang).limit(1)).mappings().one()
            cnx.execute(REGISTRES.update().where(condition & (REGISTRES.c.rang == ligne['rang']))
                        .values(cree_le=ligne['cree_le'] + timedelta(seconds=1)))
        return original(cnx, *a, **kw)

    monkeypatch.setattr(e, 'journaliser', panne)
    with session() as cnx:
        if mode == 'panne_audit':
            with pytest.raises(RuntimeError, match='panne-fictive'):
                metier.executer(cnx, charger_departements(), g.AUTH, NOM, arguments, mutation_id='panne-fictive')
        else:
            r = metier.executer(cnx, charger_departements(), g.AUTH, NOM, arguments, mutation_id='panne-fictive')
            assert r['resultat']['accepte'] is False
    assert base._instantane_base(session) == avant


def test_cible_effectivement_consommee_refuse_identite_aba(monde, session, monkeypatch):
    e = importlib.import_module('m4_field_ops.absences_ecriture')
    original, appels = e._cible_initiale, []

    def aba(*args):
        r = original(*args)
        appels.append(1)
        return {**r, 'roles': ['manager']} if len(appels) == 2 else r

    monkeypatch.setattr(e, '_cible_initiale', aba)
    avant = base._instantane_base(session)
    assert code(agir(session)) == 'REJ-ABSENCE-SOURCE-MODIFIEE'
    assert base._instantane_base(session) == avant and len(appels) == 2


def test_accuse_altere_apres_append_ne_confirme_pas_ecriture(monde, session, monkeypatch):
    original, appels = domaine.declarer, []

    def alterer(*args, **kwargs):
        r = original(*args, **kwargs)
        appels.append(1)
        if len(appels) == 2:
            r['resultat']['revision'] = 999
        return r

    monkeypatch.setattr(domaine, 'declarer', alterer)
    avant = base._instantane_base(session)
    assert code(agir(session)) == 'REJ-ABSENCE-SOURCE-MODIFIEE'
    assert base._instantane_base(session) == avant


def test_deux_transactions_sqlite_concurrentes_nacceptent_quune_revision(monde, session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    depart = Barrier(2)

    def lancer(cle):
        depart.wait(timeout=5)
        return agir(session, cle=cle)

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(lancer, ['concurrent-a', 'concurrent-b']))
    assert sum(r['resultat']['accepte'] is True for r in resultats) == 1
    assert code(next(r for r in resultats if not r['resultat']['accepte'])) == 'REJ-ABSENCE-REVISION-PERIMEE'
    assert len(lignes(session)) == 1


@pytest.mark.parametrize('profil', [False, True])
def test_writer_ferme_aux_repartiteurs_avant_effet(profil):
    from opsys.capacites import Capacites

    def interdite():
        raise AssertionError('factory privée interdite')

    caps = Capacites(charger_departements(), interdite, filtre={'m04-field-ops'}, memoire=False)
    if profil:
        r = caps.appeler_profil_runtime(NOM, object(), None, None, profile_id='profil.fictif',
                                       profile_revision=1, server='opsys_m4')
    else:
        r = caps.appeler(NOM, object())
    assert r == {'ok': False, 'erreur': 'port_console_prive_requis'}


def test_quota_sortie_avant_append(monde, session):
    avant = base._instantane_base(session)
    with contexte.sortie_bornee(100):
        assert code(agir(session)) == 'REJ-ABSENCE-SORTIE-TROP-VOLUMINEUSE'
    assert base._instantane_base(session) == avant


def test_autorite_sdk_perdue_apres_retour_writer_annule_append(monde, session, monkeypatch):
    original = metier._executer_annotations
    avant = base._instantane_base(session)

    def revoquer(cnx, *args, **kw):
        r = original(cnx, *args, **kw)
        assert r['resultat']['accepte'] is True
        identite.ajouter_role(cnx, g.AUTH.utilisateur, 'nathan_owner')
        identite.retirer_role(cnx, g.AUTH.utilisateur, 'admin')
        return r

    monkeypatch.setattr(metier, '_executer_annotations', revoquer)
    with session() as cnx, pytest.raises(PermissionError):
        metier.executer(cnx, charger_departements(), g.AUTH, NOM, args(), mutation_id='sdk-final')
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('mode', ['appareil_admin', 'console_sans_intention', 'mcp', 'injection'])
def test_writer_direct_appareil_mcp_sans_intention_et_injection_refuses(monde, session, mode):
    from m4_field_ops.registre import Registre

    outil = {o.nom: o for o in outils(Registre() if mode == 'injection' else None)}[NOM]
    avant = base._instantane_base(session)
    with session():
        if mode == 'appareil_admin':
            r = g.f.f.f.terrain._appeler({NOM: outil}, NOM, args(), g.f.f.f.terrain.ADMIN)
            attendu = 'IDENTITE'
        else:
            options = {k: v for k, v in args().items() if k not in {'jour', 'personne_id'}}
            if mode == 'mcp':
                with contexte.transport_mcp():
                    r = g.console(outil, **options)
                attendu = 'IDENTITE'
            else:
                r = g.console(outil, **options)
                attendu = 'INSTANCE-NON-QUALIFIEE' if mode == 'injection' else 'MUTATION-ABSENTE'
    assert code(r) == 'REJ-ABSENCE-' + attendu
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('champ', ['motif', 'auteur', 'horodatage', 'minutes_payees'])
def test_champs_sensibles_ou_auteur_client_refuses_avant_ecriture(monde, session, champ):
    avant = base._instantane_base(session)
    with pytest.raises(ValueError):
        agir(session, {**args(), champ: 'valeur-fictive-interdite'})
    assert base._instantane_base(session) == avant


def test_resolution_initiale_ne_lit_ni_nom_ni_hash_secret_du_sujet(monde, session):
    from sqlalchemy import event

    e = importlib.import_module('m4_field_ops.absences_ecriture')
    requetes = []

    def enregistrer(cnx, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith('select'):
            requetes.append(statement.lower())

    with session() as cnx:
        event.listen(cnx, 'before_cursor_execute', enregistrer)
        try:
            cible = e._cible_initiale(cnx, g.PERSONNE)
        finally:
            event.remove(cnx, 'before_cursor_execute', enregistrer)
    assert cible == {'identifiant': g.PERSONNE, 'actif': False, 'roles': ['employee']}
    assert requetes and all('personnes.nom' not in sql and 'mot_de_passe_hash' not in sql for sql in requetes)
