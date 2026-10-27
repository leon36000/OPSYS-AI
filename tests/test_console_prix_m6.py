"""fictif: true — saisir un tarif n'engage aucun achat, fournisseur ou paiement."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from m6_material_control import catalogue_console, fournisseurs, prix_console

from opsys import contexte, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements

spec = importlib.util.spec_from_file_location(
    'fixture_tarif_ports', Path(__file__).with_name('test_console_catalogue_m6.py'))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
client_crm = c.client_crm
catalogue = c.catalogue
PREPARER = 'm6_preparer_tarif_console'
CONFIRMER = 'm6_confirmer_tarif_console'
LISTER = 'm6_lister_fournisseurs_tarif_console'


@pytest.fixture
def sources(catalogue, session):
    assert c.direct(session)['accepte']
    with session():
        _, refus = fournisseurs.enregistrer_fournisseur('fourn-fictif', 'Fournisseur FICTIF',
                      '2026-01-01T00:00:00+00:00', stockage.maillons('m06-material-control', 'fournisseurs'))
        assert refus is None


def args(**kw):
    a = dict(materiau_id='mat-fictif', fournisseur_id='fourn-fictif', prix_unitaire='12.500001',
             date_effet='2026-01-01', source_document='tarif-fictif.pdf')
    a.update(kw)
    return a


def preparer(session, **kw):
    a = args(**kw)
    avant = c.m.base._instantane_base(session)
    r = c.executer(session, PREPARER, a)
    assert r['resultat']['accepte'], r
    assert c.m.base._instantane_base(session) == avant
    return dict(a, **{k: r['resultat']['resultat'][k] for k in prix_console._ANCRE})


def direct(session, a, *, quota=65536, cle='direct-prix-fictif', origine='console'):
    now = datetime(2030, 6, 1, tzinfo=UTC)
    meta = idempotence.Meta(cle, 'console:admin.fictif', now.isoformat())
    with (session(), contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source=origine)),
          contexte.appeler_en_tant_que('m06-material-control', origine=origine), contexte.sortie_bornee(quota),
          catalogue_console.contexte_mutation(meta),
          contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, now, now))):
        return prix_console.confirmer(**a)


def test_prepare_confirme_decimal_source_et_rejeu(sources, session):
    a = preparer(session)
    assert a['tarif_rang'] == -1
    r = c.executer(session, CONFIRMER, a, 'tarif-fictif')
    assert r['resultat']['accepte'], r
    assert r['resultat']['resultat']['prix_unitaire_decimal'] == '12.500001'
    stockage.liberer()
    with session():
        livre = list(stockage.maillons('m06-material-control', 'livre_prix'))
        assert len(livre) == 1 and str(livre[0]['prix_unitaire']) == '12.500001'
        assert livre[0]['unite'] == 'pi' and livre[0]['devise'] == 'CAD'
    avant = c.m.base._instantane_base(session)
    assert c.executer(session, CONFIRMER, a, 'tarif-fictif') == r
    assert c.m.base._instantane_base(session) == avant
    b = preparer(session, prix_unitaire='14')
    assert b['tarif_rang'] == 0
    assert c.executer(session, CONFIRMER, b, 'tarif-fictif-2')['resultat']['accepte']
    assert c.executer(session, CONFIRMER, a, 'tarif-fictif') == r  # reçu original après nouveau prix


@pytest.mark.parametrize('kw', [dict(prix_unitaire='0'), dict(prix_unitaire='NaN'), dict(prix_unitaire='1e2'),
                                dict(prix_unitaire='-1'), dict(prix_unitaire='1\n'),
                                dict(prix_unitaire='1000000000'), dict(prix_unitaire='0.1234567'),
                                dict(date_effet='2099-01-01'), dict(date_effet='2026-02-30'),
                                dict(fournisseur_id='inconnu'), dict(source_document='\n')])
def test_preparation_invalide_sans_ecriture(sources, session, kw):
    avant = c.m.base._instantane_base(session)
    try:
        r = c.executer(session, PREPARER, args(**kw))
    except ValueError:
        pass  # schéma fermé du dispatcher refuse avant le domaine
    else:
        assert r['resultat']['accepte'] is False
    assert c.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('cas', ['prix', 'materiau', 'fournisseur', 'quota', 'origine', 'unite_injectee'])
def test_confirmation_perimee_ou_interdite_sans_effet(sources, session, cas):
    a = preparer(session)
    if cas == 'prix':
        b = preparer(session, prix_unitaire='14')
        assert c.executer(session, CONFIRMER, b, 'autre-fictif')['resultat']['accepte']
    elif cas == 'materiau':
        assert c.direct(session, cle='mat-inactif', valeur=c.args(revision_attendue=1, actif=False))['accepte']
    elif cas == 'fournisseur':
        with session():
            _, refus = fournisseurs.enregistrer_fournisseur('fourn-fictif', 'Fournisseur corrigé FICTIF',
                          '2026-01-02T00:00:00+00:00', stockage.maillons('m06-material-control', 'fournisseurs'))
            assert refus is None
    avant = c.m.base._instantane_base(session)
    if cas == 'unite_injectee':
        with pytest.raises(ValueError):
            c.executer(session, CONFIRMER, {**a, 'unite': 'm'}, 'interdit-fictif')
    else:
        r = direct(session, a, quota=1 if cas == 'quota' else 65536,
                   origine='agent' if cas == 'origine' else 'console')
        assert r['accepte'] is False
    assert c.m.base._instantane_base(session) == avant


def test_rollback_audit_et_revocation_au_rejeu(sources, session, monkeypatch):
    from opsys import etat

    a = preparer(session)
    avant = c.m.base._instantane_base(session)
    def panne(*args, **kw):
        raise RuntimeError('audit prix fictif')
    with monkeypatch.context() as mp:
        mp.setattr(etat, 'journaliser', panne)
        with pytest.raises(RuntimeError, match='audit prix fictif'):
            direct(session, a)
    assert c.m.base._instantane_base(session) == avant
    assert direct(session, a)['accepte']
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = c.m.base._instantane_base(session)
    assert direct(session, a) == {'accepte': False, 'raison': 'IDENTITE'}
    assert c.m.base._instantane_base(session) == avant


def test_liste_noms_sans_pii_et_canaux_fermes(sources, session):
    r = c.executer(session, LISTER, dict(debut=0, limite=25))['resultat']['resultat']
    assert r['fournisseurs'] == [{'fournisseur_id': 'fourn-fictif', 'nom': 'Fournisseur FICTIF'}]
    cap = Capacites({}, cnx_factory=session)
    for nom in prix_console.NOMS:
        assert cap.appeler(nom, {}) == {'ok': False, 'erreur': 'port_console_prive_requis'}
        assert cap.appeler_profil_runtime(nom, {}, None, None, profile_id='fictif', profile_revision=1,
                                         server='fictif') == {'ok': False, 'erreur': 'port_console_prive_requis'}


def test_confirmation_concurrente_une_seule_entree(sources, session):
    a = preparer(session)
    deps = charger_departements()
    barriere = Barrier(2)
    def ecrivain(i):
        barriere.wait(timeout=5)
        return c.executer(session, CONFIRMER, a, f'tarif-concurrent-{i}', deps=deps)['resultat']
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(ecrivain, i) for i in range(2)]
        resultat = [f.result(timeout=15) for f in futures]
    assert sum(r['accepte'] for r in resultat) == 1
    assert [r['raison'] for r in resultat if not r['accepte']] == ['SOURCE-MODIFIEE']
    with session():
        assert len(stockage.maillons('m06-material-control', 'livre_prix')) == 1
