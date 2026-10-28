"""fictif: true — PATCH humain de fiche, sans courriel ni commande fournisseur."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from m6_material_control import catalogue_console, fournisseurs, fournisseurs_console

from opsys import contexte, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements

spec = importlib.util.spec_from_file_location(
    'fixture_fournisseurs_ports', Path(__file__).with_name('test_console_catalogue_m6.py'))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
client_crm = c.client_crm
catalogue = c.catalogue
ECRIRE = 'm6_enregistrer_fournisseur_console'
LIRE = 'm6_lire_fournisseur_console'


def args(**kw):
    a = dict(fournisseur_id='fourn-fictif', modifications={'nom': 'Fournisseur FICTIF'}, source_attendue='')
    a.update(kw)
    return a


def direct(session, a, *, cle='fournisseur-fictif', quota=65536, origine='console'):
    now = datetime(2030, 6, 1, tzinfo=UTC)
    meta = idempotence.Meta(cle, 'console:admin.fictif', now.isoformat())
    with (session(), contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source=origine)),
          contexte.appeler_en_tant_que('m06-material-control', origine=origine), contexte.sortie_bornee(quota),
          catalogue_console.contexte_mutation(meta),
          contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, now, now))):
        return fournisseurs_console.enregistrer(**a)


def test_patch_preserve_options_et_rejeu(catalogue, session):
    a = args(modifications=dict(nom='Fournisseur FICTIF', telephone='+15145550142',
             courriel_commande='commandes@fournisseur-fictif.test', categories_vendues=['Gouttières FICTIVES'],
             delai_habituel_jours=3, format_commande_prefere='Brouillon FICTIF'))
    r = c.executer(session, ECRIRE, a, 'creation-fictive')
    assert r['resultat']['accepte'], r
    fiche = r['resultat']['resultat']
    avant = c.m.base._instantane_base(session)
    assert c.executer(session, ECRIRE, a, 'creation-fictive') == r
    assert c.m.base._instantane_base(session) == avant
    b = args(modifications={'nom': 'Nom corrigé FICTIF'}, source_attendue=fiche['source_empreinte'])
    resultat = c.executer(session, ECRIRE, b, 'correction-fictive')['resultat']['resultat']
    assert resultat['nom'] == 'Nom corrigé FICTIF'
    for cle in ('telephone', 'courriel_commande', 'categories_vendues',
                'delai_habituel_jours', 'format_commande_prefere'):
        assert resultat[cle] == fiche[cle]
    effacer = args(modifications={'telephone': None}, source_attendue=resultat['source_empreinte'])
    assert c.executer(session, ECRIRE, effacer, 'effacer-fictif')['resultat']['accepte']
    stockage.liberer()
    lu = c.executer(session, LIRE, {'fournisseur_id': 'fourn-fictif'})['resultat']['resultat']
    assert lu['telephone'] is None and lu['courriel_commande'] == fiche['courriel_commande']
    avant = c.m.base._instantane_base(session)
    assert c.executer(session, ECRIRE, a, 'creation-fictive') == r
    assert c.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('modifications', [{}, {'nom': ''}, {'nom': 'x\ny'}, {'prix': 1},
    {'courriel_commande': 'invalide'}, {'telephone': 'x'*81}, {'delai_habituel_jours': True},
    {'categories_vendues': ['x'*101]}, {'format_commande_prefere': '\n'}, {'delai_habituel_jours': 3651},
    {'categories_vendues': ['FICTIF'] * 26}])
def test_patch_invalide_sans_effet(catalogue, session, modifications):
    assert direct(session, args())['accepte']
    fiche = c.executer(session, LIRE, {'fournisseur_id': 'fourn-fictif'})['resultat']['resultat']
    avant = c.m.base._instantane_base(session)
    r = direct(session, args(modifications=modifications, source_attendue=fiche['source_empreinte']), cle='invalide')
    assert r['accepte'] is False
    assert c.m.base._instantane_base(session) == avant


def test_cas_origine_quota_audit_et_revocation(catalogue, session, monkeypatch):
    from opsys import etat

    a = args()
    avant = c.m.base._instantane_base(session)
    assert direct(session, a, origine='agent')['accepte'] is False
    assert direct(session, a, quota=1)['accepte'] is False
    assert c.m.base._instantane_base(session) == avant
    def panne(*args, **kw):
        raise RuntimeError('audit fournisseur fictif')
    with monkeypatch.context() as mp:
        mp.setattr(etat, 'journaliser', panne)
        with pytest.raises(RuntimeError, match='audit fournisseur fictif'):
            direct(session, a)
    assert c.m.base._instantane_base(session) == avant
    r = direct(session, a)
    assert r['accepte']
    avant = c.m.base._instantane_base(session)
    assert direct(session, args(modifications={'nom': 'autre'}), cle='conflit')['raison'] == 'SOURCE-MODIFIEE'
    assert c.m.base._instantane_base(session) == avant
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = c.m.base._instantane_base(session)
    assert direct(session, a)['raison'] == 'IDENTITE'
    assert c.m.base._instantane_base(session) == avant


def test_identite_historique_unicode_preservee(catalogue, session):
    ident = 'fournisseur-fictif-Québec'
    with session():
        _, refus = fournisseurs.enregistrer_fournisseur(ident, 'FICTIF', '2026-01-01T00:00:00+00:00',
                        stockage.maillons('m06-material-control', 'fournisseurs'), telephone='+15145550142')
        assert refus is None
    fiche = c.executer(session, LIRE, {'fournisseur_id': ident})['resultat']['resultat']
    r = direct(session, args(fournisseur_id=ident, modifications={'nom': 'Corrigé FICTIF'},
                             source_attendue=fiche['source_empreinte']))
    assert r['accepte'] and r['resultat']['telephone'] == '+15145550142'


def test_canaux_generiques_fermes(session):
    cap = Capacites({}, cnx_factory=session)
    for nom in fournisseurs_console.NOMS:
        assert cap.appeler(nom, {}) == {'ok': False, 'erreur': 'port_console_prive_requis'}
        assert cap.appeler_profil_runtime(nom, {}, None, None, profile_id='fictif', profile_revision=1,
                                         server='fictif') == {'ok': False, 'erreur': 'port_console_prive_requis'}


def test_deux_correcteurs_une_seule_modification(catalogue, session):
    premier = direct(session, args())['resultat']
    deps, barriere = charger_departements(), Barrier(2)
    def corriger(i):
        barriere.wait(timeout=5)
        return c.executer(session, ECRIRE, args(modifications={'nom': f'Nom FICTIF {i}'},
                         source_attendue=premier['source_empreinte']), f'concurrent-{i}', deps=deps)['resultat']
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(corriger, i) for i in range(2)]
        resultats = [f.result(timeout=15) for f in futures]
    assert sum(r['accepte'] for r in resultats) == 1
    assert [r['raison'] for r in resultats if not r['accepte']] == ['SOURCE-MODIFIEE']
    with session():
        assert len(stockage.maillons('m06-material-control', 'fournisseurs')) == 2


def test_champs_historiques_riches_restent_lisibles_et_preserves(catalogue, session):
    options = dict(categories_vendues=[f'Catégorie FICTIVE {i}' for i in range(26)],
                   telephone='FICTIF-' + '1' * 90, courriel_commande='ancien format FICTIF',
                   delai_habituel_jours=4000, format_commande_prefere='FICTIF ' * 40)
    with session():
        _, refus = fournisseurs.enregistrer_fournisseur('ancien-fictif', 'FICTIF ' * 40,
            '2026-01-01T00:00:00+00:00', stockage.maillons('m06-material-control', 'fournisseurs'), **options)
        assert refus is None
    fiche = c.executer(session, LIRE, {'fournisseur_id': 'ancien-fictif'})['resultat']['resultat']
    modifications = dict(nom='Corrigé FICTIF', telephone=options['telephone'],
                         courriel_commande=options['courriel_commande'])
    r = direct(session, args(fournisseur_id='ancien-fictif', modifications=modifications,
                             source_attendue=fiche['source_empreinte']))
    assert r['accepte'], r
    assert r['resultat']['nom'] == 'Corrigé FICTIF'
    assert all(r['resultat'][k] == v for k, v in options.items())
    avant = c.m.base._instantane_base(session)
    liste = c.executer(session, 'm6_lister_fournisseurs_console', {'debut': 0, 'limite': 25})
    assert liste['resultat']['resultat']['fournisseurs'] == [
        {'fournisseur_id': 'ancien-fictif', 'nom': 'Corrigé FICTIF'}]
    assert c.m.base._instantane_base(session) == avant
    avant = c.m.base._instantane_base(session)
    refus = direct(session, args(fournisseur_id='ancien-fictif',
        modifications={'categories_vendues': options['categories_vendues'] + ['nouvelle FICTIVE']},
        source_attendue=r['resultat']['source_empreinte']), cle='nouveau-trop-grand-fictif')
    assert refus['accepte'] is False and refus['raison'] == 'ARGUMENTS'
    assert c.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('debut,limite', [(-1, 25), (0, 51), (True, 1), (0, False)])
def test_liste_bornee(catalogue, session, debut, limite):
    avant = c.m.base._instantane_base(session)
    if isinstance(debut, bool) or isinstance(limite, bool):
        with pytest.raises(ValueError, match='fiche matériau invalide'):
            c.executer(session, 'm6_lister_fournisseurs_console', dict(debut=debut, limite=limite))
    else:
        r = c.executer(session, 'm6_lister_fournisseurs_console', dict(debut=debut, limite=limite))
        assert r['resultat']['accepte'] is False
    assert c.m.base._instantane_base(session) == avant
