"""fictif: true — vrai T0 privé de préparation CSV, aucune application de prix."""
import importlib
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from m6_material_control import fournisseurs, import_tarifs_csv, livre_prix
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.console import metier
from opsys.console.securite import Session
from opsys.stockage.schema import REGISTRES

spec = importlib.util.spec_from_file_location('import_price_private_fixture',
    Path(__file__).with_name('test_console_historique_prix_m6.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
client_crm, catalogue, sources = h.client_crm, h.catalogue, h.sources
NOM = 'm6_preparer_import_tarifs_console'
MAPPING = dict(materiau_id='SKU', unite='Unite', prix_unitaire_decimal='Prix', devise='Devise', date_effet='Date')
CSV = 'SKU;Unite;Prix;Devise;Date;Note\nmat-fictif;pi;15.500000;CAD;2026-01-01;NOTE-PRIVEE-FICTIVE\n'


def module():
    return importlib.import_module('m6_material_control.import_tarifs_console')


def args(**kw):
    return dict(dict(source_csv_utf8=CSV, mapping_colonnes=MAPPING, separateur=';',
                     fournisseur_id='fourn-fictif', source_document='liste-fictive.csv', source_attendue=None), **kw)


def appeler(session, **kw):
    return h.p.c.executer(session, NOM, args(**kw))['resultat']


def direct(session, *, origine='console', reception=True, mcp=False, **kw):
    instant = datetime(2030, 6, 1, tzinfo=UTC)
    meta = contexte.HorodatageAppareil('console:admin.fictif', instant, instant)
    with (session(), contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source=origine)),
          contexte.appeler_en_tant_que('m06-material-control', origine=origine),
          contexte.receptionne_de(meta if reception else None)):
        if mcp:
            with contexte.transport_mcp():
                return module().preparer(**args(**kw))
        return module().preparer(**args(**kw))


def test_vrai_t0_prive_revalide_csv_et_reproduit_prepare_existant_sans_ecrire(sources, session):
    h.semer(session)
    deps = h.p.charger_departements()
    outils = {o.nom: o for o in deps['m06-material-control'].charger_outils()}
    assert NOM in outils, 'T0 import privé absent'
    assert outils[NOM].autonomie.value == 'T0' and not outils[NOM].roles_appareil
    a = args()
    attendu = h.p.c.executer(session, h.p.PREPARER, h.p.args(prix_unitaire='15.500000',
        source_document=a['source_document']))['resultat']['resultat']
    avant = h.p.c.m.base._instantane_base(session)
    r = appeler(session)
    assert r['accepte'] is True, r
    vue = r['resultat']
    assert vue['statut'] == 'A_REVOIR' and vue['candidats_revalides'] == 1
    assert vue['lignes'][0]['preparation_saisie'] == attendu
    assert 'NOTE-PRIVEE-FICTIVE' not in str(vue) and 'CONFIRMATION_EXPLICITE_REQUISE' in vue['avertissements']
    with session() as cnx:
        snapshots = module().capturer(cnx)
        prep = import_tarifs_csv.preparer(CSV.encode(), mapping_colonnes=MAPPING, separateur=';',
            fournisseur_id=a['fournisseur_id'], source_document=a['source_document'],
            jour_reference=vue['jour_reference'])
        assert module().projeter(snapshots, prep, vue['jour_reference']) == vue
    stockage.liberer()
    assert appeler(session, source_attendue=vue['source']) == r
    assert h.p.c.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('cas,code', [('unite', 'UNITE_CATALOGUE_DIFFERENTE'),
    ('materiau', 'MATERIAU_INCONNU'), ('inactif', 'MATERIAU_INACTIF'),
    ('fournisseur', 'FOURNISSEUR_INCONNU'), ('nom_legacy', 'REPERTOIRE_HORS_CONTRAT_SAISIE')])
def test_revalidation_canonique_sans_creer_fiche_ni_prix(sources, session, cas, code):
    options = {}
    if cas == 'unite':
        options['source_csv_utf8'] = CSV.replace(';pi;', ';cm;')
    elif cas == 'materiau':
        options['source_csv_utf8'] = CSV.replace('mat-fictif', 'inconnu-fictif')
    elif cas == 'fournisseur':
        options['fournisseur_id'] = 'inconnu-fictif'
    elif cas == 'inactif':
        r = h.p.c.executer(session, h.p.c.ECRIRE, h.p.c.args(revision_attendue=1, actif=False), 'inactif-import-fictif')
        assert r['resultat']['accepte']
    else:
        with session():
            _, refus = fournisseurs.enregistrer_fournisseur('ancien-fictif', 'FICTIF-' + 'é' * 201,
                '2026-01-01T00:00:00+00:00', stockage.maillons('m06-material-control', 'fournisseurs'))
            assert refus is None
    avant = h.p.c.m.base._instantane_base(session)
    vue = appeler(session, **options)['resultat']
    assert vue['statut'] == 'A_CORRIGER' and code in vue['lignes'][0]['erreurs']
    assert vue['lignes'][0]['preparation_saisie'] is None and vue['candidats_revalides'] == 0
    assert h.p.c.m.base._instantane_base(session) == avant


def test_dernier_prix_inutilisable_ne_reprend_pas_ancien_et_source_perimee(sources, session):
    h.semer(session)
    premiere = appeler(session)['resultat']
    with session():
        _, refus = livre_prix.enregistrer_prix('mat-fictif', 'fourn-fictif', 99, 'USD', '2026-01-01',
            stockage.maillons('m06-material-control', 'livre_prix'), unite='pi')
        assert refus is None
    assert appeler(session, source_attendue=premiere['source']) == dict(accepte=False, raison='SOURCE-PERIMEE')
    nouvelle = appeler(session)['resultat']['lignes'][0]['preparation_saisie']
    assert nouvelle['ancien_tarif'] is None and nouvelle['ancien_indisponible'] == 'devise_non_supportee'


@pytest.mark.parametrize('origine,reception,mcp', [('agent', True, False), ('appareil', True, False),
    ('console', False, False), ('console', True, True)])
def test_admission_avant_capture(sources, session, monkeypatch, origine, reception, mcp):
    def interdit(*a, **kw):
        raise AssertionError('source après admission refusée')

    monkeypatch.setattr(module(), 'capturer', interdit)
    assert direct(session, origine=origine, reception=reception, mcp=mcp) == dict(
        accepte=False, raison='RECEPTION-ABSENTE' if not reception else 'IDENTITE')


@pytest.mark.parametrize('profil', [False, True])
def test_deux_fermetures_generiques_avant_factory_et_arguments(profil):
    def interdit(*a, **kw):
        raise AssertionError('factory privée appelée')

    class ArgumentsInterdits:
        def items(self):
            raise AssertionError('arguments privés lus')

    cap = Capacites({}, cnx_factory=interdit)
    if profil:
        r = cap.appeler_profil_runtime(NOM, ArgumentsInterdits(), None, None,
                                     profile_id='fictif', profile_revision=1, server='fictif')
    else:
        r = cap.appeler(NOM, ArgumentsInterdits())
    assert r == dict(ok=False, erreur='port_console_prive_requis')


@pytest.mark.parametrize('registre', ['catalogue_materiaux', 'fournisseurs', 'livre_prix'])
def test_trois_quotas_bruts_avant_tout_decodage(sources, session, monkeypatch, registre):
    h.semer(session)
    monkeypatch.setattr(module(), 'MAX_OCTETS', 1024)
    with session() as cnx:
        condition = (REGISTRES.c.departement == 'm06-material-control') & (REGISTRES.c.registre == registre)
        ligne = cnx.execute(select(REGISTRES).where(condition).limit(1)).mappings().one()
        cnx.execute(REGISTRES.update().where(condition & (REGISTRES.c.rang == ligne['rang']))
                    .values(maillon='x' * 1025))

    def interdit(*a, **kw):
        raise AssertionError('décodage après quota')

    monkeypatch.setattr(module(), 'copier_maillons_avec_metadonnees', interdit)
    assert appeler(session) == dict(accepte=False, raison='SOURCES-TROP-VOLUMINEUSES')


def test_corruption_livre_hors_couple_refuse_et_cnx_canonique(sources, session):
    h.semer(session)
    with session() as cnx, cnx.engine.connect() as autre, pytest.raises(ValueError, match='INSTANCE-NON-QUALIFIEE'):
        module().capturer(autre)
    with session():
        stockage.maillons('m06-material-control', 'livre_prix').append(dict(materiau_id='autre-fictif',
            fournisseur_id='fourn-fictif', prix_unitaire=True, devise='CAD', date_effet='2026-01-01'))
    assert appeler(session) == dict(accepte=False, raison='SOURCE-INVALIDE')


def test_metadonnees_changees_pendant_projection_et_revocation_derniere_capture(sources, session, monkeypatch):
    h.semer(session)
    original = module().projeter

    def alterer(*a, **kw):
        r = original(*a, **kw)
        cnx = stockage.connexion_courante()
        condition = (REGISTRES.c.departement == 'm06-material-control') & (REGISTRES.c.registre == 'fournisseurs')
        ligne = cnx.execute(select(REGISTRES).where(condition).limit(1)).mappings().one()
        cnx.execute(REGISTRES.update().where(condition & (REGISTRES.c.rang == ligne['rang']))
                    .values(cree_le=ligne['cree_le'] + timedelta(seconds=1)))
        return r

    monkeypatch.setattr(module(), 'projeter', alterer)
    assert appeler(session) == dict(accepte=False, raison='SOURCE-MODIFIEE')
    monkeypatch.setattr(module(), 'projeter', original)
    capturer = module().capturer
    appels = []

    def revoquer(cnx):
        r = capturer(cnx)
        appels.append(True)
        if len(appels) == 2:
            identite.retirer_role(cnx, 'admin.fictif', 'admin')
        return r

    monkeypatch.setattr(module(), 'capturer', revoquer)
    assert direct(session) == dict(accepte=False, raison='IDENTITE') and len(appels) == 2


def test_quota_herite_et_expiration_apres_t0(sources, session, monkeypatch):
    with contexte.sortie_bornee(10):
        assert appeler(session) == dict(accepte=False, raison='SORTIE-TROP-VOLUMINEUSE')
    original = metier.executer_atomique
    auth = Session('admin.fictif', frozenset({'admin'}), 'csrf-fictif', 4102444800)

    def expirer(*a, **kw):
        r = original(*a, **kw)
        object.__setattr__(auth, 'expire', 1)
        return r

    monkeypatch.setattr(metier, 'executer_atomique', expirer)
    with pytest.raises(PermissionError):
        h.p.c.executer(session, NOM, args(), auth=auth)


def test_bom_crlf_et_arguments_serveur_non_fournis_par_appelant(sources, session):
    source = '\ufeff' + CSV.replace('\n', '\r\n')
    vue = appeler(session, source_csv_utf8=source)['resultat']
    import hashlib

    assert vue['source_sha256'] == hashlib.sha256(source.encode()).hexdigest()
    for ajout in [dict(jour_reference='1999-01-01'), dict(sources_sql={})]:
        with pytest.raises(ValueError):
            h.p.c.executer(session, NOM, dict(args(), **ajout))


def test_csv_trop_long_refuse_avant_encode_et_parse(sources, session, monkeypatch):
    def interdit(*a, **kw):
        raise AssertionError('CSV surdimensionné transmis au parseur')

    monkeypatch.setattr(import_tarifs_csv, 'preparer', interdit)
    assert direct(session, source_csv_utf8='x' * 1048577) == dict(
        accepte=False, raison='SOURCE_TROP_VOLUMINEUSE')

    class TexteInterdit(str):
        def encode(self, *a, **kw):
            raise AssertionError('encodage avant validation du type exact')

    assert direct(session, source_csv_utf8=TexteInterdit(CSV)) == dict(accepte=False, raison='ARGUMENTS')


def test_capacite_dix_mille_prix_ne_promet_pas_preparation_refusee_par_writer(sources, session):
    h.semer(session)
    with session() as cnx:
        condition = (REGISTRES.c.departement == 'm06-material-control') & (REGISTRES.c.registre == 'livre_prix')
        ligne = dict(cnx.execute(select(REGISTRES).where(condition).limit(1)).mappings().one())
        cnx.execute(REGISTRES.insert(), [dict(ligne, rang=i) for i in range(2, 10000)])
    attendu = h.p.c.executer(session, h.p.PREPARER, h.p.args())['resultat']
    assert attendu == dict(accepte=False, raison='SOURCES-TROP-VOLUMINEUSES')
    assert appeler(session) == attendu


def test_curseur_forme_invalide_refuse_avant_sources(sources, session, monkeypatch):
    def interdit(*a, **kw):
        raise AssertionError('source lue malgré un curseur invalide')

    monkeypatch.setattr(module(), 'capturer', interdit)
    assert direct(session, source_attendue='invalide') == dict(accepte=False, raison='ARGUMENTS')
