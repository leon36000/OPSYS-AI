"""fictif: true — confirmation privée du lot, rollback intégral et rejeu sans effet."""
import importlib
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest
from m6_material_control import prix_console
from sqlalchemy import select

from opsys import contexte, idempotence, stockage
from opsys.capacites import Capacites
from opsys.console import memoire_chantier, metier
from opsys.departements import charger_departements
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS, JOURNAL, MUTATIONS_APPLIQUEES, REGISTRES

spec = importlib.util.spec_from_file_location('batch_price_fixture',
    Path(__file__).with_name('test_console_import_tarifs_m6.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
client_crm, catalogue, sources = p.client_crm, p.catalogue, p.sources
NOM = 'm6_confirmer_import_tarifs_console'
CSV = p.CSV + 'soffite-fictif;pi;2.50;CAD;2026-01-01;note-fictive\n'


def module():
    return importlib.import_module('m6_material_control.import_tarifs_confirmation')


def preparer(session):
    r = p.h.p.c.executer(session, p.h.p.c.ECRIRE,
        p.h.p.c.args(materiau_id='soffite-fictif', nom='Soffite FICTIF'), 'second-fictif')
    assert r['resultat']['accepte'], r
    vue = p.appeler(session, source_csv_utf8=CSV)['resultat']
    return p.args(source_csv_utf8=CSV, source_attendue=vue['source'],
                  preparation_attendue=vue['preparation_sha256'])


def confirmer(session, arguments, cle='lot-fictif'):
    return p.h.p.c.executer(session, NOM, arguments, cle)['resultat']


def instantane(session):
    return p.h.p.c.m.base._instantane_base(session)


def test_t1_prive_lot_deux_tarifs_recu_et_rejeu_exact_apres_changement_source(sources, session):
    outils = {o.nom: o for o in charger_departements()['m06-material-control'].charger_outils()}
    assert NOM in outils, 'confirmation lot privée absente'
    assert outils[NOM].autonomie.value == 'T1' and not outils[NOM].roles_appareil
    a = preparer(session)
    r = confirmer(session, a)
    assert r['accepte'] is True, r
    recu = r['resultat']
    assert recu['nombre_tarifs'] == 2
    assert [ligne['tarif_rang'] for ligne in recu['tarifs']] == [0, 1]
    assert [ligne['prix_unitaire_decimal'] for ligne in recu['tarifs']] == ['15.500000', '2.50']
    assert 'NOTE-PRIVEE-FICTIVE' not in str(r) and 'note-fictive' not in str(r)
    # Une nouvelle écriture rend l'aperçu ancien périmé, sans invalider son reçu historique.
    autre = p.h.p.preparer(session, prix_unitaire='19.00')
    assert p.h.p.c.executer(session, p.h.p.CONFIRMER, autre, 'autre-fictif')['resultat']['accepte']
    avant = instantane(session)
    assert confirmer(session, a) == r
    stockage.liberer()
    assert confirmer(session, a) == r
    assert instantane(session) == avant


def test_refus_deuxieme_ligne_annule_prix_receptions_audit_mutations_et_outbox(sources, session, monkeypatch):
    a = preparer(session)
    avant = instantane(session)
    original = prix_console.confirmer
    appels = []

    def refuser(**kw):
        appels.append(kw['materiau_id'])
        if len(appels) == 2:
            return dict(accepte=False, raison='SOURCE-MODIFIEE')
        return original(**kw)

    monkeypatch.setattr(prix_console, 'confirmer', refuser)
    r = confirmer(session, a)
    assert r == dict(accepte=False, raison='SOURCE-MODIFIEE'), r
    assert len(appels) == 2
    assert instantane(session) == avant


def test_source_et_preparation_obligatoires_et_stale_sans_ecriture(sources, session):
    a = preparer(session)
    avant = instantane(session)
    for champ in ('source_attendue', 'preparation_attendue'):
        r = confirmer(session, dict(a, **{champ: '0' * 64}), 'stale-' + champ)
        assert r['accepte'] is False, r
        assert instantane(session) == avant


def test_nonce_de_lot_ne_peut_servir_autre_document(sources, session):
    a = preparer(session)
    assert confirmer(session, a)['accepte']
    avant = instantane(session)
    assert confirmer(session, dict(a, source_document='autre-fictif.csv')) == dict(
        accepte=False, raison='MUTATION-CONFLIT')
    assert instantane(session) == avant


def test_recu_parent_rechaine_ne_peut_inventer_references_enfants(sources, session):
    a = preparer(session)
    assert confirmer(session, a)['accepte']
    with session() as cnx:
        condition = (MUTATIONS_APPLIQUEES.c.cle_idempotence == 'lot-fictif')
        raw = cnx.execute(select(MUTATIONS_APPLIQUEES.c.reponse).where(condition)).scalar_one()
        enveloppe = codec.decoder(raw)
        recu = enveloppe['resultat']['resultat']
        for ligne in recu['tarifs']:
            ligne['tarif_rang'] += 2
            ligne['tarif_source_sha256'] = 'a' * 64
        recu['preuve_lot_sha256'] = module()._empreinte({k: v for k, v in recu.items() if k != 'preuve_lot_sha256'})
        cnx.execute(MUTATIONS_APPLIQUEES.update().where(condition).values(reponse=codec.encoder(enveloppe)))
    avant = instantane(session)
    assert confirmer(session, a) == dict(accepte=False, raison='RECU-INVALIDE')
    assert instantane(session) == avant


@pytest.mark.parametrize('statut', ['en_cours', 'refus_metier'])
def test_recu_non_clos_refuse_sans_reexecuter(sources, session, statut):
    a = preparer(session)
    assert confirmer(session, a)['accepte']
    with session() as cnx:
        cnx.execute(MUTATIONS_APPLIQUEES.update().where(MUTATIONS_APPLIQUEES.c.cle_idempotence == 'lot-fictif')
                    .values(statut=statut))
    avant = instantane(session)
    assert confirmer(session, a) == dict(accepte=False, raison='RECU-INVALIDE')
    assert instantane(session) == avant


def test_quota_final_annule_deux_enfants_deja_ecrits(sources, session, monkeypatch):
    a = preparer(session)
    avant = instantane(session)
    original = prix_console.confirmer
    appels = []

    def observer(**kw):
        r = original(**kw)
        assert r['accepte'], r
        appels.append(kw['materiau_id'])
        return r

    monkeypatch.setattr(prix_console, 'confirmer', observer)
    with contexte.sortie_bornee(600):
        assert confirmer(session, a) == dict(accepte=False, raison='SORTIE-TROP-VOLUMINEUSE')
    assert len(appels) == 2
    assert instantane(session) == avant


def test_session_finale_expiree_meme_si_appelant_attrape_et_commit(sources, session, monkeypatch):
    a = preparer(session)
    avant = instantane(session)
    appels = []
    original = prix_console.confirmer

    def observer(**kw):
        r = original(**kw)
        assert r['accepte']
        appels.append(kw['materiau_id'])
        return r

    def expirer(*args):
        raise PermissionError('session fictive expirée en fin')

    monkeypatch.setattr(prix_console, 'confirmer', observer)
    monkeypatch.setattr(memoire_chantier, '_admin', expirer)
    with session() as cnx, pytest.raises(PermissionError, match='expirée'):
        metier.executer(cnx, charger_departements(), p.h.p.c.AUTH, NOM, a, mutation_id='expire-fictif')
        # Le caller valide normalement cette transaction extérieure.
    assert len(appels) == 2
    assert instantane(session) == avant


def test_capacite_lot_avant_premier_writer_et_aucune_acceptation_partielle(sources, session, monkeypatch):
    a = preparer(session)
    avant = instantane(session)

    def interdit(**kw):
        raise AssertionError('writer appelé après refus de capacité')

    monkeypatch.setattr(module().import_tarifs_console, 'MAX_SOURCES', 1)
    monkeypatch.setattr(prix_console, 'confirmer', interdit)
    assert confirmer(session, a) == dict(accepte=False, raison='SOURCES-TROP-VOLUMINEUSES')
    assert instantane(session) == avant


def test_enfant_deja_present_ne_rejoue_pas_operation_etrangere(sources, session, monkeypatch):
    a = preparer(session)
    parent = idempotence.Meta('lot-fictif', 'console:admin.fictif', '2030-06-01T00:00:00+00:00')
    enfant = module()._enfant(parent, 1)
    assert len(enfant.cle) < 200 and enfant.cle != parent.cle
    with session() as cnx:
        idempotence.reclamer(cnx, enfant, 'etranger_fictif', {}, p.datetime(2030, 6, 1, tzinfo=p.UTC))
    avant = instantane(session)

    def interdit(**kw):
        raise AssertionError('writer appelé après conflit enfant')

    monkeypatch.setattr(prix_console, 'confirmer', interdit)
    assert confirmer(session, a) == dict(accepte=False, raison='MUTATION-CONFLIT')
    assert instantane(session) == avant


@pytest.mark.parametrize('profil', [False, True])
def test_fermetures_generiques_avant_factory(profil):
    def interdit(*args, **kw):
        raise AssertionError('factory privée appelée')

    cap = Capacites({}, cnx_factory=interdit)
    if profil:
        r = cap.appeler_profil_runtime(NOM, {}, None, None,
            profile_id='fictif', profile_revision=1, server='fictif')
    else:
        r = cap.appeler(NOM, {})
    assert r == dict(ok=False, erreur='port_console_prive_requis')


def test_deux_appels_concurrents_un_seul_lot_et_recu(sources, session):
    a = preparer(session)
    barriere = Barrier(2)

    def appel():
        barriere.wait(timeout=5)
        return confirmer(session, a)

    with ThreadPoolExecutor(max_workers=2) as pool:
        r1, r2 = [f.result(timeout=15) for f in [pool.submit(appel), pool.submit(appel)]]
    assert r1['accepte'] and r1 == r2
    with session():
        assert len(stockage.maillons('m06-material-control', 'livre_prix')) == 2
        assert len(stockage.maillons('m06-material-control', 'receptions_tarifs')) == 2


def direct(session, arguments, *, origine='console', reception=True, mcp=False, meta=True):
    now = p.datetime(2030, 6, 1, tzinfo=p.UTC)
    intention = idempotence.Meta('lot-direct-fictif', 'console:admin.fictif', now.isoformat())
    with (session(), contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source=origine)),
          contexte.appeler_en_tant_que('m06-material-control', origine=origine),
          contexte.receptionne_de(contexte.HorodatageAppareil(intention.appareil, now, now) if reception else None),
          module().acces.contexte_mutation(intention if meta else None)):
        if mcp:
            with contexte.transport_mcp():
                return module().confirmer(**arguments)
        return module().confirmer(**arguments)


@pytest.mark.parametrize('options,code', [({'origine': 'agent'}, 'IDENTITE'),
    ({'mcp': True}, 'IDENTITE'), ({'reception': False}, 'RECEPTION-ABSENTE'),
    ({'meta': False}, 'MUTATION-ABSENTE')])
def test_admission_avant_parseur_et_reclamation(sources, session, monkeypatch, options, code):
    a = preparer(session)
    avant = instantane(session)

    def interdit(*args, **kw):
        raise AssertionError('parseur appelé après admission refusée')

    monkeypatch.setattr(module(), '_preparer', interdit)
    assert direct(session, a, **options) == dict(accepte=False, raison=code)
    assert instantane(session) == avant


def test_csv_borne_type_exact_avant_encodage_et_reclamation(sources, session, monkeypatch):
    a = preparer(session)
    avant = instantane(session)

    class TexteInterdit(str):
        def encode(self, *args, **kw):
            raise AssertionError('encodage avant type exact')

    assert direct(session, dict(a, source_csv_utf8=TexteInterdit(CSV))) == dict(accepte=False, raison='ARGUMENTS')
    assert direct(session, dict(a, source_csv_utf8='x' * 1048577)) == dict(
        accepte=False, raison='SOURCE_TROP_VOLUMINEUSE')
    assert instantane(session) == avant


@pytest.mark.parametrize('cible', ['parent', 'enfant'])
def test_reponse_durable_trop_grande_refuse_avant_decode(sources, session, cible):
    a = preparer(session)
    assert confirmer(session, a)['accepte']
    cle = 'lot-fictif'
    if cible == 'enfant':
        cle = module()._enfant(idempotence.Meta(cle, 'console:admin.fictif', '2030-06-01T00:00:00+00:00'), 1).cle
    with session() as cnx:
        cnx.execute(MUTATIONS_APPLIQUEES.update().where(MUTATIONS_APPLIQUEES.c.cle_idempotence == cle)
                    .values(reponse='x' * 65537))
    avant = instantane(session)
    assert confirmer(session, a) == dict(accepte=False, raison='RECU-INVALIDE')
    assert instantane(session) == avant


@pytest.mark.parametrize('cas', ['vide', 'bool'])
def test_recu_enfant_corrompu_ne_valide_pas_parent_intact(sources, session, cas):
    a = preparer(session)
    assert confirmer(session, a)['accepte']
    enfant = module()._enfant(idempotence.Meta('lot-fictif', 'console:admin.fictif', '2030-06-01T00:00:00+00:00'), 2)
    with session() as cnx:
        condition = MUTATIONS_APPLIQUEES.c.cle_idempotence == enfant.cle
        reponse = codec.decoder(cnx.execute(select(MUTATIONS_APPLIQUEES.c.reponse).where(condition)).scalar_one())
        if cas == 'vide':
            reponse['resultat']['resultat'] = {}
        else:
            reponse['resultat']['resultat']['tarif_rang'] = True
        cnx.execute(MUTATIONS_APPLIQUEES.update().where(condition).values(reponse=codec.encoder(reponse)))
    avant = instantane(session)
    assert confirmer(session, a) == dict(accepte=False, raison='RECU-INVALIDE')
    assert instantane(session) == avant


@pytest.mark.parametrize('registre', ['catalogue_materiaux', 'fournisseurs', 'livre_prix'])
def test_mutation_metadata_apres_ecritures_annule_lot(sources, session, monkeypatch, registre):
    p.h.semer(session)
    a = preparer(session)
    avant = instantane(session)
    original = prix_console.confirmer
    appels = []

    def alterer(**kw):
        r = original(**kw)
        assert r['accepte'], r
        appels.append(True)
        if len(appels) == 2:
            cnx = stockage.connexion_courante()
            condition = ((REGISTRES.c.departement == 'm06-material-control')
                         & (REGISTRES.c.registre == registre) & (REGISTRES.c.rang == 0))
            date = cnx.execute(select(REGISTRES.c.cree_le).where(condition)).scalar_one()
            cnx.execute(REGISTRES.update().where(condition).values(cree_le=date + timedelta(seconds=1)))
        return r

    monkeypatch.setattr(prix_console, 'confirmer', alterer)
    assert confirmer(session, a) == dict(accepte=False, raison='SOURCE-MODIFIEE')
    assert len(appels) == 2 and instantane(session) == avant


def test_panne_publication_memoire_annule_aussi_prix_audit_et_reclamations(sources, session, monkeypatch):
    from opsys import catalogues_memoire

    a = preparer(session)
    avant = instantane(session)
    original = catalogues_memoire.publier
    appels = []

    def panne(*args, **kw):
        appels.append(True)
        if len(appels) == 2:
            raise RuntimeError('panne fictive publication')
        return original(*args, **kw)

    monkeypatch.setattr(catalogues_memoire, 'publier', panne)
    with pytest.raises(RuntimeError, match='panne fictive'):
        confirmer(session, a)
    assert len(appels) == 2 and instantane(session) == avant


def test_frontiere_native_9999_plus_un_et_plus_deux(sources, session):
    p.h.semer(session)
    with session() as cnx:
        condition = (REGISTRES.c.departement == 'm06-material-control') & (REGISTRES.c.registre == 'livre_prix')
        ligne = dict(cnx.execute(select(REGISTRES).where(condition).limit(1)).mappings().one())
        cnx.execute(REGISTRES.insert(), [dict(ligne, rang=i) for i in range(2, 9999)])
    a = preparer(session)
    avant = instantane(session)
    assert confirmer(session, a) == dict(accepte=False, raison='SOURCES-TROP-VOLUMINEUSES')
    assert instantane(session) == avant
    vue = p.appeler(session)['resultat']
    un = p.args(source_attendue=vue['source'], preparation_attendue=vue['preparation_sha256'])
    r = confirmer(session, un, 'derniere-place-fictive')
    assert r['accepte'], r
    assert r['resultat']['tarifs'][0]['tarif_rang'] == 9999
    with session():
        assert len(stockage.maillons('m06-material-control', 'livre_prix')) == 10000
    assert confirmer(session, un, 'derniere-place-fictive') == r


def test_quota_post_ecritures_avant_premier_recodage_sources(sources, session, monkeypatch):
    a = preparer(session)
    avant = instantane(session)
    original = prix_console.confirmer
    appels = []

    def interdit(*args, **kw):
        raise AssertionError('décodage après quota postécriture')

    def observer(**kw):
        r = original(**kw)
        appels.append(True)
        if len(appels) == 2:
            monkeypatch.setattr(module().import_tarifs_console, 'MAX_OCTETS', 1)
            monkeypatch.setattr(module().import_tarifs_console, 'copier_maillons_avec_metadonnees', interdit)
        return r

    monkeypatch.setattr(prix_console, 'confirmer', observer)
    assert confirmer(session, a) == dict(accepte=False, raison='SOURCES-TROP-VOLUMINEUSES')
    assert len(appels) == 2 and instantane(session) == avant


def test_lot_partiellement_invalide_ne_commence_aucune_ligne(sources, session, monkeypatch):
    preparer(session)
    csv = CSV.replace('soffite-fictif;pi;', 'soffite-fictif;cm;')
    vue = p.appeler(session, source_csv_utf8=csv)['resultat']
    a = p.args(source_csv_utf8=csv, source_attendue=vue['source'], preparation_attendue=vue['preparation_sha256'])
    avant = instantane(session)

    def interdit(**kw):
        raise AssertionError('première ligne écrite malgré lot partiellement invalide')

    monkeypatch.setattr(prix_console, 'confirmer', interdit)
    assert confirmer(session, a) == dict(accepte=False, raison='LOT-A-CORRIGER')
    assert instantane(session) == avant


def test_lot_receptions_audit_outbox_et_references_m10_natives(sources, session):
    spec = importlib.util.spec_from_file_location('batch_m10_fixture',
        Path(__file__).with_name('test_cascade_tarifs_m10.py'))
    cascade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cascade)
    a = preparer(session)
    avant = dict(instantane(session))
    r = confirmer(session, a)
    assert r['accepte'], r
    apres = dict(instantane(session))
    assert len(apres[JOURNAL.name]) - len(avant[JOURNAL.name]) == 2
    assert len(apres[MUTATIONS_APPLIQUEES.name]) - len(avant[MUTATIONS_APPLIQUEES.name]) == 3
    assert len(apres[EVENEMENTS_SORTANTS.name]) - len(avant[EVENEMENTS_SORTANTS.name]) == 2
    publications = cascade.publications(session)
    assert len(publications) == 2 and cascade.souvenirs() == []
    total = cascade.m.b._drainer(charger_departements(), cascade.m.INSTANT)
    assert total['echecs'] == total['quarantaines'] == 0, total
    stockage.liberer()
    souvenirs = cascade.souvenirs()
    assert len(souvenirs) == 2
    for eid, _, _ in publications:
        assert cascade.m.b._recu(eid, 'm10-memoire')['statut'] == 'traite'
    for prive in ('15.500000', '2.50', 'fourn-fictif', 'mat-fictif', 'liste-fictive.csv', 'lot-fictif'):
        assert prive not in str([publications, souvenirs])
    avant = instantane(session)
    assert confirmer(session, a) == r
    assert instantane(session) == avant
