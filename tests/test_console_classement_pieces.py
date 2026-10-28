"""fictif: true — classement manuel indépendant du chiffré original et des droits M10."""
import importlib
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from opsys import identite
from opsys.departements import charger_departements
from opsys.stockage.schema import JOURNAL

spec = importlib.util.spec_from_file_location('classement_piece_fixture',
    Path(__file__).with_name('test_console_pieces_projet.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm = f.client_crm


def port():
    assert importlib.util.find_spec('opsys.console.classement_pieces') is not None, 'classement des pièces absent'
    return importlib.import_module('opsys.console.classement_pieces')


@pytest.fixture
def piece(client_crm, session):
    with session() as cnx:
        return f.depot(cnx)['piece_id']


def lire(cnx, piece, **kwargs):
    return port().lire(cnx, charger_departements(), f.AUTH, f.LEAD, piece, cle=f.CLE, **kwargs)


def classer(cnx, piece, categorie='plan', revision=0, mutation='a' * 32, motif='organisation_dossier', **kwargs):
    return port().classer(cnx, charger_departements(), f.AUTH, f.LEAD, piece, cle=f.CLE,
                         categorie=categorie, revision_attendue=revision, mutation_id=mutation, motif=motif, **kwargs)


def test_classement_durable_sans_modifier_original(piece, session):
    p = port()
    with session() as cnx:
        avant = cnx.execute(select(f.port().PIECES)).all()
        vide = lire(cnx, piece)
        assert vide['categorie_courante'] == 'non_classee' and vide['revision_courante'] == 0
        assert vide['historique'] == []
        recu = classer(cnx, piece)
        assert recu['rejoue'] is False and recu['recu']['categorie'] == 'plan'
        assert recu['recu']['avant'] == 'non_classee' and recu['recu']['auteur'] == f.AUTH.utilisateur
        assert cnx.execute(select(f.port().PIECES)).all() == avant
    with session() as cnx:
        vue = lire(cnx, piece)
        assert vue['categorie_courante'] == 'plan' and vue['revision_courante'] == 1
        assert vue['historique'] == [recu['recu']]
        assert f.port().lire(cnx, charger_departements(), f.AUTH, f.LEAD, piece, cle=f.CLE)[1] == f.PDF
        assert cnx.execute(select(func.count()).select_from(p.CLASSEMENTS)).scalar_one() == 1


def test_rejeu_ancien_reste_historique_apres_correction(piece, session):
    with session() as cnx:
        premier = classer(cnx, piece)
        second = classer(cnx, piece, 'materiaux', 1, 'b' * 32, 'correction_erreur')
        assert second['recu']['avant'] == 'plan'
        historique = classer(cnx, piece)
        assert historique['rejoue'] is True and historique['recu'] == premier['recu']
        assert lire(cnx, piece)['categorie_courante'] == 'materiaux'
        assert cnx.execute(select(func.count()).select_from(JOURNAL)
            .where(JOURNAL.c.action == 'crm.piece_classee')).scalar_one() == 2


@pytest.mark.parametrize('args,code', [(dict(categorie='autre'), 'SAISIE-CONFLIT'),
    (dict(mutation='b' * 32), 'REVISION-PERIMEE'), (dict(categorie='plan', revision=1, mutation='b' * 32), 'INCHANGE')])
def test_conflits_sans_modification(piece, session, args, code):
    p = port()
    with session() as cnx:
        classer(cnx, piece)
        with pytest.raises(p.Refus, match=code):
            classer(cnx, piece, **args)
        assert len(lire(cnx, piece)['historique']) == 1


@pytest.mark.parametrize('args', [dict(categorie='FINANCIAL'), dict(categorie='INTERNAL'),
    dict(categorie='inconnue'), dict(revision=True), dict(revision=-1), dict(revision='0'),
    dict(motif='texte libre FICTIF'), dict(mutation='invalide')])
def test_entrees_fermees(piece, session, args):
    p = port()
    with session() as cnx:
        with pytest.raises(p.Refus):
            classer(cnx, piece, **args)
        assert lire(cnx, piece)['historique'] == []


def test_autre_projet_meme_client_refuse(piece, session):
    p = port()
    with session() as cnx:
        for action in (lambda: p.lire(cnx, charger_departements(), f.AUTH, 'lead-fictif-002', piece, cle=f.CLE),
            lambda: p.classer(cnx, charger_departements(), f.AUTH, 'lead-fictif-002', piece, cle=f.CLE,
                             categorie='plan', revision_attendue=0, mutation_id='a' * 32,
                             motif='organisation_dossier')):
            with pytest.raises(p.Refus, match='INTROUVABLE'):
                action()


@pytest.mark.parametrize('champ,valeur', [('categorie', 'autre'), ('source_sha256', '0' * 64),
    ('precedent', 'f' * 64), ('auteur', 'autre.fictif')])
def test_compagnon_corrompu_ne_devient_pas_categorie(piece, session, champ, valeur):
    p = port()
    with session() as cnx:
        classer(cnx, piece)
        cnx.execute(update(p.CLASSEMENTS).values(**{champ: valeur}))
        with pytest.raises(p.Refus):
            lire(cnx, piece)
        assert f.port().lire(cnx, charger_departements(), f.AUTH, f.LEAD, piece, cle=f.CLE)[1] == f.PDF


def test_panne_audit_annule_classement(piece, session, monkeypatch):
    p = port()
    def panne(*args, **kwargs):
        raise RuntimeError('panne-fictive')
    monkeypatch.setattr(p.etat, 'journaliser', panne)
    with session() as cnx:
        with pytest.raises(RuntimeError, match='panne-fictive'):
            classer(cnx, piece)
        assert lire(cnx, piece)['revision_courante'] == 0


def test_role_revoque_avant_original(piece, session, monkeypatch):
    p = port()
    def interdit(*args, **kwargs):
        raise AssertionError('original lu avant autorité')
    monkeypatch.setattr(p.pieces, 'lire', interdit)
    with session() as cnx:
        identite.retirer_role(cnx, f.AUTH.utilisateur, 'admin')
        with pytest.raises(PermissionError):
            lire(cnx, piece)


def test_historique_plafonne_malgre_nouvelle_correction(piece, session):
    with session() as cnx:
        for i in range(21):
            classer(cnx, piece, 'plan' if i % 2 == 0 else 'photo', i, f'{i:032x}')
        page = lire(cnx, piece)
        assert page['revision_max'] == 21 and len(page['historique']) == 20 and page['suivant'] == 20
        classer(cnx, piece, 'autre', 21, 'f' * 32)
        suite = lire(cnx, piece, decalage=20, revision_max=page['revision_max'])
        assert len(suite['historique']) == 1 and suite['historique'][0]['revision'] == 21
        assert suite['revision_courante'] == 22 and suite['categorie_courante'] == 'autre'


def test_deux_CAS_concurrents_un_seul_classement(piece, session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    p = port()
    depart = Barrier(2)
    def ecrire(categorie, mutation):
        depart.wait(timeout=5)
        try:
            with session() as cnx:
                return classer(cnx, piece, categorie, 0, mutation)
        except p.Refus as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        un = pool.submit(ecrire, 'plan', 'a' * 32)
        deux = pool.submit(ecrire, 'photo', 'b' * 32)
        resultats = [un.result(timeout=10), deux.result(timeout=10)]
    assert sum(type(r) is dict for r in resultats) == 1 and 'REVISION-PERIMEE' in resultats


def test_rejeu_revalide_compagnon_apres_fermeture_source(piece, session, monkeypatch):
    p = port()
    with session() as cnx:
        classer(cnx, piece)
        fermer = p._fermer
        def corrompre(*args, **kwargs):
            fermer(*args, **kwargs)
            cnx.execute(update(p.CLASSEMENTS).values(categorie='autre'))
        monkeypatch.setattr(p, '_fermer', corrompre)
        with pytest.raises(p.Refus):
            classer(cnx, piece)


def test_quota_avant_lecture_compagnon(piece, session, monkeypatch):
    p = port()
    with session() as cnx:
        classer(cnx, piece)
        cnx.execute(update(p.CLASSEMENTS).values(auteur='x' * 801))
        def interdit(*args):
            raise AssertionError('maillon décodé avant quota')
        monkeypatch.setattr(p, '_hash', interdit)
        with pytest.raises(p.Refus, match='QUOTA'):
            lire(cnx, piece)


def test_quota_apres_ecriture_annule_audit(piece, session, monkeypatch):
    p = port()
    monkeypatch.setattr(p, 'MAX_OCTETS', 1)
    with session() as cnx:
        with pytest.raises(p.Refus, match='QUOTA'):
            classer(cnx, piece)
        assert cnx.execute(select(func.count()).select_from(p.CLASSEMENTS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(JOURNAL)
            .where(JOURNAL.c.action == 'crm.piece_classee')).scalar_one() == 0


def test_rejeu_possible_au_plafond_revision(piece, session, monkeypatch):
    p = port()
    monkeypatch.setattr(p, 'MAX_REVISIONS', 2)
    with session() as cnx:
        premier = classer(cnx, piece)
        classer(cnx, piece, 'photo', 1, 'b' * 32)
        with pytest.raises(p.Refus, match='QUOTA'):
            classer(cnx, piece, 'autre', 2, 'c' * 32)
        assert classer(cnx, piece)['recu'] == premier['recu']


def test_revocation_pendant_ecriture_annule_classement(piece, session, monkeypatch):
    p = port()
    journal = p.etat.journaliser
    def revoquer(cnx, *args, **kwargs):
        journal(cnx, *args, **kwargs)
        identite.retirer_role(cnx, f.AUTH.utilisateur, 'admin')
    monkeypatch.setattr(p.etat, 'journaliser', revoquer)
    with session() as cnx:
        with pytest.raises(PermissionError):
            classer(cnx, piece)
        assert lire(cnx, piece)['revision_courante'] == 0


def test_migration_0028_0029_preserve_original_et_protege_historique(piece, session):
    from alembic import command

    port()
    with session() as cnx:
        avant = cnx.execute(select(f.port().PIECES)).all()
        cfg = f.stockage._config()
        cfg.attributes['connection'] = cnx
        command.downgrade(cfg, '0028')  # Compagnon vide, original conservé.
        assert cnx.execute(select(f.port().PIECES)).all() == avant
        command.upgrade(cfg, '0029')
        command.upgrade(cfg, '0029')
        assert lire(cnx, piece)['revision_courante'] == 0
        assert cnx.execute(select(f.port().PIECES)).all() == avant
        classer(cnx, piece)
        with pytest.raises(RuntimeError, match='supprimerait l’historique'):
            command.downgrade(cfg, '0028')
        assert lire(cnx, piece)['revision_courante'] == 1
