"""fictif: true — writer humain privé, identités canoniques et transactions SQLite."""
import importlib
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import composition_journaliere as domaine
from m4_field_ops.outils import outils
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys import equipes as equipes_entreprise
from opsys.console import metier
from opsys.departements import charger_departements
from opsys.stockage.schema import JOURNAL, REGISTRES

spec = importlib.util.spec_from_file_location('composition_ecriture_fixture',
    Path(__file__).with_name('test_console_compositions_equipes.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
client_crm, planning = g.client_crm, g.f.planning
base = g.f.f.base
FICTIF = True
NOM = 'm4_declarer_composition_journaliere_console'


def profil(equipes=('eq-a', 'eq-b')):
    return {'liste': [{'id': e, 'membres': ['employe' if e == 'eq-a' else 'admin.fictif'],
        'competences': [], 'depot': {'id': 'depot.fictif', 'latitude_microdegres': 45000000,
                                    'longitude_microdegres': -73000000},
        'quarts': [{'jour': 0, 'debut_min': 480, 'fin_min': 1020}]} for e in equipes]}


@pytest.fixture
def monde(client_crm, session):
    with session() as cnx:
        identite.creer_personne(cnx, 'equipier.inactif', 'Équipier fictif inactif', 'mot-de-passe-fictif',
                               ['employee'], actif=False)
    equipes_entreprise.enregistrer_equipes(profil(), par=g.AUTH.utilisateur)


def args(*, revision=0, membres=None, statut='declaree', jour=g.D, equipe=g.EQUIPE):
    return dict(jour=jour, equipe_id=equipe, membres=['employe', 'equipier.inactif'] if membres is None
                and statut == 'declaree' else membres, revision_attendue=revision, statut_declaration=statut)


def agir(session, arguments=None, *, cle='composition-fictive-1', acteur=g.AUTH):
    with session() as cnx:
        return metier.executer(cnx, charger_departements(), acteur, NOM, args() if arguments is None else arguments,
                              mutation_id=cle)


def lignes(session):
    with session():
        return list(stockage.maillons('m04-field-ops', domaine.REGISTRE))


def code(r):
    return r['resultat']['verdict']['code']


def test_vrai_writer_humain_identites_et_sources_sans_effet_operationnel(planning, monde, session):
    par_nom = {o.nom: o for o in outils()}
    assert par_nom[NOM].autonomie.value == 'T1' and par_nom[NOM].roles_appareil == frozenset()
    avant = dict(base._instantane_base(session))
    fichier = equipes_entreprise.fichier_profil().read_bytes()
    r = agir(session)
    assert r['ok'] is True and r['resultat']['accepte'] is True
    m = lignes(session)[0]
    assert m['membres'] == ['employe', 'equipier.inactif']
    assert m['auteur'] == {'personne': g.AUTH.utilisateur, 'role': 'admin'}
    assert m['horodatage'] == r['resultat']['resultat']['horodatage']
    assert 'membres' not in str(r)
    apres = dict(base._instantane_base(session))
    for table in avant:
        if table not in {REGISTRES.name, JOURNAL.name}:
            assert apres[table] == avant[table], table
    assert fichier == equipes_entreprise.fichier_profil().read_bytes()
    with session() as cnx:
        assert identite.personne(cnx, 'equipier.inactif').actif is False
        principal = list(stockage.maillons('m04-field-ops', 'principal'))
        assert principal and all(x['type_entree'] != domaine.TYPE for x in principal)
    nouvelles = apres[JOURNAL.name][len(avant[JOURNAL.name]):]
    assert nouvelles and all('equipier.inactif' not in str(x) and 'employe' not in str(x) for x in nouvelles)


def test_correction_retrait_redeclaration_et_rejeu_original_apres_disparition_equipe(monde, session):
    premier = agir(session)
    assert agir(session, args(revision=1, membres=[]), cle='m-2')['resultat']['accepte'] is True
    equipes_entreprise.enregistrer_equipes(profil(('eq-b',)), par=g.AUTH.utilisateur)
    avant = base._instantane_base(session)
    rejoue = agir(session)
    assert rejoue['resultat']['rejoue'] is True
    assert rejoue['resultat']['resultat'] == premier['resultat']['resultat']
    assert base._instantane_base(session) == avant
    assert agir(session, args(revision=2, membres=None, statut='retiree'), cle='m-3')['resultat']['accepte'] is True
    assert agir(session, args(revision=3, membres=['employe']), cle='m-4')['resultat']['accepte'] is True
    with session() as cnx:
        r = g.port().lire(cnx, charger_departements(), g.AUTH, g.D, g.EQUIPE)
    assert r['membres'] == ['employe'] and [x['revision'] for x in r['lignes']] == [1, 2, 3, 4]
    assert r['lignes'][2]['membres'] is None and r['lignes'][1]['membres'] == []


@pytest.mark.parametrize('options', [dict(equipe='equipe.inconnue'), dict(membres=['personne.inconnue']),
    dict(membres=['Nom libre']), dict(membres=['employe', 'employe'])])
def test_identites_et_doublons_invalides_sans_ecriture(monde, session, options):
    avant = base._instantane_base(session)
    r = agir(session, args(**options))
    assert r['resultat']['accepte'] is False
    assert base._instantane_base(session) == avant


def test_ancienne_equipe_autre_jour_ne_valide_pas_une_paire_initiale(monde, session):
    agir(session)
    equipes_entreprise.enregistrer_equipes(profil(('eq-b',)), par=g.AUTH.utilisateur)
    avant = base._instantane_base(session)
    assert code(agir(session, args(jour='2030-06-07'), cle='autre-jour')) == 'REJ-COMPOSITION-IDENTITES-NON-CONFIRMEES'
    assert base._instantane_base(session) == avant


def test_cas_intention_modifiee_et_auteur_courant(monde, session):
    agir(session)
    avant = base._instantane_base(session)
    assert code(agir(session, args(membres=[]))) == 'REJ-COMPOSITION-MUTATION-CONFLIT'
    assert code(agir(session, args(), cle='autre-intention')) == 'REJ-COMPOSITION-REVISION-PERIMEE'
    with session() as cnx:
        identite.ajouter_role(cnx, g.AUTH.utilisateur, 'nathan_owner')
        identite.retirer_role(cnx, g.AUTH.utilisateur, 'admin')
    revoque = base._instantane_base(session)
    with pytest.raises(PermissionError):
        agir(session)
    assert base._instantane_base(session) == revoque and len(lignes(session)) == 1
    assert dict(avant)[REGISTRES.name] == dict(revoque)[REGISTRES.name]


@pytest.mark.parametrize('mode', ['panne_audit', 'revocation', 'metadata'])
def test_echec_apres_append_annule_meme_exception_capturee_par_appelant(monde, session, monkeypatch, mode):
    e = importlib.import_module('m4_field_ops.composition_ecriture')
    if mode == 'metadata':
        agir(session)
        arguments = args(revision=1, membres=[])
    else:
        arguments = args()
    avant = base._instantane_base(session)
    original = e.journaliser

    def panne(cnx, *a, **kw):
        if mode == 'panne_audit':
            raise RuntimeError('panne-fictive-apres-append')
        if mode == 'revocation':
            identite.ajouter_role(cnx, g.AUTH.utilisateur, 'nathan_owner')
            identite.retirer_role(cnx, g.AUTH.utilisateur, 'admin')
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


def test_empreinte_profil_est_celle_effectivement_consommee_et_refuse_aba(monde, session, monkeypatch):
    original = equipes_entreprise.charger_equipes
    appels = []

    def aba():
        appels.append(1)
        if len(appels) == 2:
            return equipes_entreprise.normaliser_equipes(profil(('eq-b',))), None
        return original()

    monkeypatch.setattr(equipes_entreprise, 'charger_equipes', aba)
    avant = base._instantane_base(session)
    assert code(agir(session)) == 'REJ-COMPOSITION-SOURCE-MODIFIEE'
    assert base._instantane_base(session) == avant and len(appels) == 2


def test_deux_transactions_concurrentes_une_seule_revision_acceptee(monde, session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    depart = Barrier(2)

    def lancer(cle):
        depart.wait(timeout=5)
        return agir(session, cle=cle)

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(lancer, ['concurrent-a', 'concurrent-b']))
    assert sum(r['resultat']['accepte'] is True for r in resultats) == 1
    assert len(lignes(session)) == 1
    refus = next(r for r in resultats if r['resultat']['accepte'] is False)
    assert code(refus) == 'REJ-COMPOSITION-REVISION-PERIMEE'


@pytest.mark.parametrize('profile', [False, True])
def test_writer_ferme_aux_repartiteurs_generiques_avant_effet(profile):
    from opsys.capacites import Capacites

    def interdite():
        raise AssertionError('factory privée interdite')

    caps = Capacites(charger_departements(), interdite, filtre={'m04-field-ops'}, memoire=False)
    if profile:
        r = caps.appeler_profil_runtime(NOM, object(), None, None, profile_id='profil.fictif',
                                       profile_revision=1, server='opsys_m4')
    else:
        r = caps.appeler(NOM, object())
    assert r == {'ok': False, 'erreur': 'port_console_prive_requis'}



def test_quota_appelant_respecte_avant_append(monde, session):
    avant = base._instantane_base(session)
    with contexte.sortie_bornee(100):
        r = agir(session)
    assert code(r) == 'REJ-COMPOSITION-SORTIE-TROP-VOLUMINEUSE'
    assert base._instantane_base(session) == avant



def test_autorite_sdk_finale_annule_append_apres_retour_du_writer(monde, session, monkeypatch):
    original = metier._executer_annotations
    avant = base._instantane_base(session)

    def retirer(cnx, *a, **kw):
        r = original(cnx, *a, **kw)
        assert r['resultat']['accepte'] is True
        identite.ajouter_role(cnx, g.AUTH.utilisateur, 'nathan_owner')
        identite.retirer_role(cnx, g.AUTH.utilisateur, 'admin')
        return r

    monkeypatch.setattr(metier, '_executer_annotations', retirer)
    with session() as cnx, pytest.raises(PermissionError):
        metier.executer(cnx, charger_departements(), g.AUTH, NOM, args(), mutation_id='sdk-final-fictif')
    assert base._instantane_base(session) == avant


@pytest.mark.parametrize('mode', ['appareil_admin', 'console_sans_intention', 'mcp', 'injection'])
def test_writer_direct_appareil_mcp_absence_intention_ou_injection_refuses(monde, session, mode):
    from m4_field_ops.registre import Registre

    par_nom = {o.nom: o for o in outils(Registre() if mode == 'injection' else None)}
    avant = base._instantane_base(session)
    with session():
        if mode == 'appareil_admin':
            r = g.f.f.terrain._appeler(par_nom, NOM, args(), g.f.f.terrain.ADMIN)
            attendu = 'IDENTITE'
        else:
            options = {k: v for k, v in args().items() if k not in {'jour', 'equipe_id'}}
            if mode == 'mcp':
                with contexte.transport_mcp():
                    r = g.console(par_nom[NOM], **options)
                attendu = 'IDENTITE'
            else:
                r = g.console(par_nom[NOM], **options)
                attendu = 'INSTANCE-NON-QUALIFIEE' if mode == 'injection' else 'MUTATION-ABSENTE'
    assert code(r) == 'REJ-COMPOSITION-' + attendu
    assert base._instantane_base(session) == avant
