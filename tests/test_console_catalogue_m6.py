"""fictif: true — ports privés avec transactions SQLite réelles, sans nouvel écran."""
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from m6_material_control import catalogue_console as port
from m6_material_control import catalogue_materiaux as domaine

from opsys import contexte, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.console import metier
from opsys.console.securite import Session
from opsys.departements import charger_departements

spec = importlib.util.spec_from_file_location('catalogue_m6_fixtures',
                                              Path(__file__).with_name('test_console_modeles_soumission.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
client_crm = m.client_crm
catalogue = m.catalogue
ECRIRE = 'm6_enregistrer_materiau_console'
LIRE = 'm6_lire_materiau_console'
LISTER = 'm6_lister_materiaux_console'
AUTH = Session('admin.fictif', frozenset({'admin'}), 'csrf-fictif', 4102444800)


def args(**kw):
    valeur = dict(materiau_id='mat-fictif', nom='Gouttière FICTIVE', unite='pi', actif=True,
                  raison='Fiche FICTIVE', revision_attendue=0)
    valeur.update(kw)
    return valeur


def executer(session, nom, arguments, cle=None, auth=AUTH, deps=None):
    deps = charger_departements() if deps is None else deps
    with session() as cnx:
        return metier.executer(cnx, deps, auth, nom, arguments, mutation_id=cle)


def direct(session, *, cle='direct-fictif', quota=65536, origine='console', valeur=None):
    now = datetime(2030, 6, 1, tzinfo=UTC)
    meta = idempotence.Meta(cle, 'console:admin.fictif', now.isoformat())
    with (session(), contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source=origine)),
          contexte.appeler_en_tant_que(port.DEPARTEMENT, origine=origine), contexte.sortie_bornee(quota),
          port.contexte_mutation(meta),
          contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, now, now))):
        return port.enregistrer(**(args() if valeur is None else valeur))


def test_crud_versions_rejeu_et_reouverture(catalogue, session):
    r = executer(session, ECRIRE, args(), 'creation-fictive')
    assert r['ok'] and r['resultat']['accepte'], r
    fiche = r['resultat']['resultat']
    assert fiche['auteur'] == 'admin.fictif' and fiche['revision'] == 1
    avant = m.base._instantane_base(session)
    assert executer(session, ECRIRE, args(), 'creation-fictive') == r
    assert m.base._instantane_base(session) == avant
    q = executer(session, ECRIRE, args(nom='Autre FICTIF'), 'creation-fictive')
    assert q['resultat'] == {'accepte': False, 'raison': 'MUTATION-CONFLIT'}
    assert m.base._instantane_base(session) == avant
    stockage.liberer()
    assert executer(session, LIRE, {'materiau_id': 'mat-fictif', 'revision': 0})['resultat']['resultat'] == fiche
    r2 = executer(session, ECRIRE, args(revision_attendue=1, actif=False), 'desactiver-fictif')
    assert r2['resultat']['accepte'], r2
    page = executer(session, LISTER, dict(debut=0, limite=50, actifs_seulement=True))
    assert page['resultat']['resultat']['total'] == 0
    assert executer(session, LIRE, {'materiau_id': 'mat-fictif', 'revision': 1})['resultat']['resultat'] == fiche


@pytest.mark.parametrize('cas', ['quota', 'origine', 'unite', 'revision', 'source'])
def test_refus_et_rollback(catalogue, session, cas):
    assert direct(session)['accepte']
    valeur = args(revision_attendue=1)
    kw = dict(cle='nouvelle-fictive', valeur=valeur)
    if cas == 'quota':
        kw['quota'] = 1
    elif cas == 'origine':
        kw['origine'] = 'm06-material-control'
    elif cas == 'unite':
        valeur['unite'] = 'm'
    elif cas == 'revision':
        valeur['revision_attendue'] = 0
    else:
        with session():
            stockage.maillons(port.DEPARTEMENT, domaine.REGISTRE).append({'nom': 'Corruption FICTIVE'})
    avant = m.base._instantane_base(session)
    assert direct(session, **kw)['accepte'] is False
    assert m.base._instantane_base(session) == avant
    if cas == 'source':
        r = executer(session, LISTER, dict(debut=0, limite=50, actifs_seulement=False))
        assert r['resultat'] == {'accepte': False, 'raison': 'SOURCE-INVALIDE'}


def test_audit_panne_rollback(catalogue, session, monkeypatch):
    from opsys import etat

    avant = m.base._instantane_base(session)
    def panne(*a, **kw):
        raise RuntimeError('audit fictif indisponible')
    with monkeypatch.context() as mp:
        mp.setattr(etat, 'journaliser', panne)
        with pytest.raises(RuntimeError, match='audit fictif'):
            direct(session)
    assert m.base._instantane_base(session) == avant
    assert direct(session)['accepte']  # même intention, aucun reçu fantôme


def test_autorite_revalidee_avant_rejeu(catalogue, session):
    assert direct(session)['accepte']
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = m.base._instantane_base(session)
    assert direct(session) == {'accepte': False, 'raison': 'IDENTITE'}
    with pytest.raises(PermissionError):
        executer(session, LIRE, {'materiau_id': 'mat-fictif', 'revision': 0})
    assert m.base._instantane_base(session) == avant


@pytest.mark.parametrize('auth', [Session('nathan', frozenset({'nathan_owner'}), 'fictif', 4102444800),
                                 Session('admin.fictif', frozenset({'admin'}), 'fictif', 0)])
def test_role_et_session_reels(catalogue, session, auth):
    avant = m.base._instantane_base(session)
    with pytest.raises(PermissionError):
        executer(session, ECRIRE, args(), 'refus-fictif', auth=auth)
    assert m.base._instantane_base(session) == avant


def test_champs_fermes_et_canaux_generiques(session, catalogue):
    avant = m.base._instantane_base(session)
    with pytest.raises(ValueError):
        executer(session, ECRIRE, args(auteur='usurpe'), 'refus-fictif')
    cap = Capacites({}, cnx_factory=session)
    for nom in port.NOMS:
        assert cap.appeler(nom, {}) == {'ok': False, 'erreur': 'port_console_prive_requis'}
        assert cap.appeler_profil_runtime(nom, {}, None, None, profile_id='fictif', profile_revision=1,
                                         server='fictif') == {'ok': False, 'erreur': 'port_console_prive_requis'}
    assert m.base._instantane_base(session) == avant


def test_deux_ecrivains_sqlite_meme_revision(catalogue, session):
    deps = charger_departements()
    assert executer(session, ECRIRE, args(), 'initial-fictif', deps=deps)['resultat']['accepte']
    barriere = Barrier(2)

    def ecrivain(i):
        barriere.wait(timeout=5)
        return executer(session, ECRIRE, args(revision_attendue=1, nom=f'Nom FICTIF {i}'),
                        f'concurrent-fictif-{i}', deps=deps)['resultat']

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(ecrivain, i) for i in range(2)]
        resultats = [f.result(timeout=15) for f in futures]
    assert sum(r['accepte'] for r in resultats) == 1
    assert [r['raison'] for r in resultats if not r['accepte']] == ['REVISION-PERIMEE']
    with session():
        journal = stockage.maillons(port.DEPARTEMENT, domaine.REGISTRE)
        assert len(journal) == 2
        assert domaine.lire(journal, 'mat-fictif')['revision'] == 2


def test_quota_enveloppe_utf8_exacte_et_rejeu(catalogue, session):
    # Le résultat et son enveloppe ont des tailles différentes; coût UTF-8 des accents inclus.
    r = direct(session)
    taille = len(json.dumps({'ok': True, 'resultat': r}, ensure_ascii=False).encode('utf-8'))
    avant = m.base._instantane_base(session)
    assert direct(session, quota=taille - 1) == {'accepte': False, 'raison': 'SORTIE-TROP-VOLUMINEUSE'}
    assert direct(session, quota=taille) == r
    assert m.base._instantane_base(session) == avant
    autre = args(materiau_id='nouveau-fictif')
    assert direct(session, cle='quota-fictif', quota=taille - 1, valeur=autre)['accepte'] is False
    assert m.base._instantane_base(session) == avant
