"""fictif: true — vrai T0 privé et SQLite canonique, aucun écran livré par ce test."""
import importlib
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from m6_material_control import historique_prix, livre_prix
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.console import metier
from opsys.console.securite import Session
from opsys.stockage.schema import REGISTRES

spec = importlib.util.spec_from_file_location('history_price_fixture',
    Path(__file__).with_name('test_console_prix_m6.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
client_crm, catalogue, sources = p.client_crm, p.catalogue, p.sources
FICTIF = True
NOM = 'm6_lire_historique_prix_console'


def module():
    return importlib.import_module('m6_material_control.historique_prix_console')


def args(**kw):
    return dict(dict(materiau_id='mat-fictif', fournisseur_id='fourn-fictif', debut=0,
                     limite=25, source_attendue=None), **kw)


def semer(session):
    for i, (prix, jour) in enumerate([('12.500001', '2026-01-01'), ('14', '2025-01-01')]):
        prepare = p.preparer(session, prix_unitaire=prix, date_effet=jour)
        r = p.c.executer(session, p.CONFIRMER, prepare, 'history-price-fictif-' + str(i))
        assert r['resultat']['accepte'] is True


def appeler(session, **options):
    return p.c.executer(session, NOM, args(**options))['resultat']


def direct(session, *, origine='console', reception=True, mcp=False, **options):
    instant = datetime(2030, 6, 1, tzinfo=UTC)
    horodatage = contexte.HorodatageAppareil('console:admin.fictif', instant, instant)
    with (session(), contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source=origine)),
          contexte.appeler_en_tant_que('m06-material-control', origine=origine),
          contexte.receptionne_de(horodatage if reception else None)):
        if mcp:
            with contexte.transport_mcp():
                return module().lire(**args(**options))
        return module().lire(**args(**options))


def test_vrai_t0_dispatcher_sql_reouvert_et_comparaison_pure(sources, session):
    semer(session)
    deps = p.charger_departements()
    outil = next(o for o in deps['m06-material-control'].charger_outils() if o.nom == NOM)
    assert outil.autonomie.value == 'T0' and not outil.roles_appareil
    avant = p.c.m.base._instantane_base(session)
    with session() as cnx:
        snapshot = module().capturer(cnx)
        attendu = historique_prix.lire([(x.rang, x.maillon) for x in snapshot.lignes], 'mat-fictif', 'fourn-fictif')
    r = appeler(session)
    assert r['accepte'] is True
    vue = r['resultat']
    assert vue['source_sql'] == snapshot.empreinte_snapshot_calculee
    assert {k: v for k, v in vue.items() if k != 'source_sql'} == attendu
    assert vue['lignes'][-1]['date_effet'] == '2025-01-01'
    assert vue['lignes'][-1]['prix_unitaire_decimal'] == '14.0' and vue['lignes'][-1]['derniere_ecriture'] is True
    stockage.liberer()
    assert appeler(session) == r
    assert appeler(session, fournisseur_id='absent.fictif')['resultat']['total'] == 0
    assert p.c.m.base._instantane_base(session) == avant


def test_pages_et_source_perimee_apres_autre_couple_sans_ecriture_lecture(sources, session):
    semer(session)
    premier = appeler(session, limite=1)['resultat']
    seconde = appeler(session, debut=1, limite=1, source_attendue=premier['source'])['resultat']
    assert seconde['lignes'][0]['version_du_couple'] == 2 and seconde['suivant'] is None
    with session():
        _, refus = livre_prix.enregistrer_prix('autre.fictif', 'fourn-fictif', 33, 'CAD', '2026-01-01',
            stockage.maillons('m06-material-control', 'livre_prix'), unite='pi')
        assert refus is None
    avant = p.c.m.base._instantane_base(session)
    assert appeler(session, debut=1, source_attendue=premier['source']) == dict(accepte=False, raison='SOURCE-PERIMEE')
    assert p.c.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('origine,reception,mcp', [('agent', True, False), ('appareil', True, False),
    ('console', False, False), ('console', True, True)])
def test_origine_et_reception_verifiees_avant_source(sources, session, monkeypatch, origine, reception, mcp):
    def interdit(*args):
        raise AssertionError('capture après admission refusée')

    monkeypatch.setattr(module(), 'capturer', interdit)
    r = direct(session, origine=origine, reception=reception, mcp=mcp)
    assert r == dict(accepte=False, raison='RECEPTION-ABSENTE' if not reception else 'IDENTITE')


@pytest.mark.parametrize('profile', [False, True])
def test_deux_fermetures_generiques_avant_factory_et_arguments(profile):
    def interdit(*args, **kwargs):
        raise AssertionError('factory privée appelée')

    class ArgumentsInterdits:
        def items(self):
            raise AssertionError('arguments privés lus')

    capacites = Capacites({}, cnx_factory=interdit)
    if profile:
        r = capacites.appeler_profil_runtime(NOM, ArgumentsInterdits(), None, None,
                                             profile_id='fictif', profile_revision=1, server='fictif')
    else:
        r = capacites.appeler(NOM, ArgumentsInterdits())
    assert r == {'ok': False, 'erreur': 'port_console_prive_requis'}


@pytest.mark.parametrize('personne,expire', [('employe', 4102444800), ('nathan', 4102444800), ('admin.fictif', 1)])
def test_admin_sql_session_courants_et_connexion_canonique(sources, session, personne, expire):
    auth = Session(personne, frozenset({'admin'}), 'fictif', expire)
    with pytest.raises(PermissionError):
        p.c.executer(session, NOM, args(), auth=auth)
    with session() as cnx, cnx.engine.connect() as autre, pytest.raises(ValueError, match='INSTANCE-NON-QUALIFIEE'):
        module().capturer(autre)


@pytest.mark.parametrize('quota', ['lignes', 'octets'])
def test_quota_brut_avant_decodage(sources, session, monkeypatch, quota):
    semer(session)
    monkeypatch.setattr(historique_prix, 'MAX_SOURCES' if quota == 'lignes' else 'MAX_OCTETS', 0)

    def interdit(*args, **kwargs):
        raise AssertionError('décodage après quota')

    monkeypatch.setattr(module(), 'copier_maillons_avec_metadonnees', interdit)
    avant = p.c.m.base._instantane_base(session)
    assert appeler(session) == dict(accepte=False, raison='SOURCES-TROP-VOLUMINEUSES')
    assert p.c.m.base._instantane_base(session) == avant


def test_quota_enveloppe_et_source_corrompue_hors_page(sources, session):
    semer(session)
    with session():
        with contexte.sortie_bornee(10):
            r = direct(session)
        assert r == dict(accepte=False, raison='SORTIE-TROP-VOLUMINEUSE')
        stockage.maillons('m06-material-control', 'livre_prix').append(dict(
            materiau_id='autre.fictif', fournisseur_id='fourn-fictif', prix_unitaire=True,
            devise='CAD', date_effet='2026-01-01'))
    avant = p.c.m.base._instantane_base(session)
    assert appeler(session, limite=1) == dict(accepte=False, raison='SOURCE-INVALIDE')
    assert p.c.m.base._instantane_base(session) == avant


def test_metadonnees_modifiees_pendant_projection_refusees(sources, session, monkeypatch):
    semer(session)
    original = module().projeter

    def alterer(*arguments, **options):
        r = original(*arguments, **options)
        cnx = stockage.connexion_courante()
        condition = (REGISTRES.c.departement == 'm06-material-control') & (REGISTRES.c.registre == 'livre_prix')
        ligne = cnx.execute(select(REGISTRES).where(condition).limit(1)).mappings().one()
        cnx.execute(REGISTRES.update().where(condition & (REGISTRES.c.rang == ligne['rang']))
                    .values(cree_le=ligne['cree_le'] + timedelta(seconds=1)))
        return r

    monkeypatch.setattr(module(), 'projeter', alterer)
    assert appeler(session) == dict(accepte=False, raison='SOURCE-MODIFIEE')


def test_derniere_capture_revoque_admin_et_aucun_resultat_restitue(sources, session, monkeypatch):
    semer(session)
    original = module().capturer
    appels = []

    def capture(cnx):
        r = original(cnx)
        appels.append(True)
        if len(appels) == 2:
            identite.retirer_role(cnx, 'admin.fictif', 'admin')
        return r

    monkeypatch.setattr(module(), 'capturer', capture)
    r = direct(session)
    assert len(appels) == 2 and r == dict(accepte=False, raison='IDENTITE')


def test_expiration_session_apres_execution_t0_refuse_dans_dispatcher(sources, session, monkeypatch):
    semer(session)
    original = metier.executer_atomique
    auth = Session('admin.fictif', frozenset({'admin'}), 'fictif', 4102444800)

    def expirer(*arguments, **options):
        r = original(*arguments, **options)
        object.__setattr__(auth, 'expire', 1)
        return r

    monkeypatch.setattr(metier, 'executer_atomique', expirer)
    avant = p.c.m.base._instantane_base(session)
    with pytest.raises(PermissionError):
        p.c.executer(session, NOM, args(), auth=auth)
    assert p.c.m.base._instantane_base(session) == avant


def test_source_substituee_et_mutation_id_interdits(sources, session):
    with pytest.raises(ValueError):
        p.c.executer(session, NOM, dict(args(), lignes=[]))
    with pytest.raises(ValueError):
        p.c.executer(session, NOM, args(), 'mutation-interdite')


def test_dispatcher_ne_peut_elargir_quota_deja_impose(sources, session):
    semer(session)
    avant = p.c.m.base._instantane_base(session)
    with contexte.sortie_bornee(10):
        r = appeler(session)
    assert r == dict(accepte=False, raison='SORTIE-TROP-VOLUMINEUSE')
    assert p.c.m.base._instantane_base(session) == avant
