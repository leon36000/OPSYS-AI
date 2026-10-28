"""fictif: true — originaux reçus avant travaux; port privé, aucun serveur de production."""
import importlib
import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from opsys import fichiers, identite, stockage
from opsys.console.securite import Session
from opsys.departements import charger_departements
from opsys.stockage.schema import JOURNAL, REGISTRES

spec = importlib.util.spec_from_file_location('pieces_crm_fixture', Path(__file__).with_name('test_console_crm.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm = f.client_crm
FICTIF = True
AUTH = Session('admin.fictif', frozenset({'admin'}), 'csrf-fictif', 4102444800)
CLE = b'c' * 32  # Clé de QA fictive uniquement.
PDF = b'%PDF-1.7\nDOCUMENT-CLIENT-FICTIF\n%%EOF'
TITRE = 'Plan toiture FICTIF'
LEAD = 'lead-fictif-001'


def port():
    assert importlib.util.find_spec('opsys.console.pieces_projet') is not None, 'port de pièces reçues absent'
    return importlib.import_module('opsys.console.pieces_projet')


def depot(cnx, *, auth=AUTH, lead=LEAD, mutation='a' * 32, titre=TITRE, mime='application/pdf', contenu=PDF, cle=CLE):
    return port().deposer(cnx, charger_departements(), auth, lead, mutation_id=mutation,
                          titre=titre, type_mime=mime, contenu=contenu, cle=cle)


def test_depot_survit_reconnexion_et_ne_modifie_pas_M2(client_crm, session):
    p = port()
    with session() as cnx:
        avant = cnx.execute(select(REGISTRES)).all()
        recu = depot(cnx)
        assert cnx.execute(select(REGISTRES)).all() == avant
    with session() as cnx:
        page = p.lister(cnx, charger_departements(), AUTH, LEAD, cle=CLE)
        assert page['nombre'] == 1 and page['pieces'] == [recu]
        meta, original = p.lire(cnx, charger_departements(), AUTH, LEAD, recu['piece_id'], cle=CLE)
        assert original == PDF and meta == recu
        assert recu['titre'] == TITRE and recu['auteur'] == AUTH.utilisateur
        assert recu['type_mime'] == 'application/pdf' and recu['statut'] == 'NON_ANALYSE'
        assert recu['taille_octets'] == len(PDF)
        brut = repr(cnx.execute(select(p.PIECES)).mappings().all())
        assert TITRE not in brut and 'DOCUMENT-CLIENT-FICTIF' not in brut
        assert cnx.execute(select(func.count()).select_from(JOURNAL)
                           .where(JOURNAL.c.action == 'crm.piece_recue')).scalar_one() == 1
    assert fichiers.TYPES_MIME_PERMIS == ('image/jpeg', 'image/png')


def test_rejeu_identique_ne_redouble_ni_piece_ni_audit(client_crm, session):
    p = port()
    with session() as cnx:
        recu = depot(cnx)
        assert depot(cnx) == recu
        assert cnx.execute(select(func.count()).select_from(p.PIECES)).scalar_one() == 1
        assert cnx.execute(select(func.count()).select_from(JOURNAL)
                           .where(JOURNAL.c.action == 'crm.piece_recue')).scalar_one() == 1


@pytest.mark.parametrize('changement', [dict(lead='lead-fictif-002'), dict(titre='Autre titre FICTIF'),
    dict(contenu=PDF + b' autre'), dict(type_mime='image/png')])
def test_collision_saisie_refusee(client_crm, session, changement):
    p = port()
    if 'type_mime' in changement:
        changement = dict(mime='image/png', contenu=b'\x89PNG\r\n\x1a\nFICTIF')
    with session() as cnx:
        depot(cnx)
        with pytest.raises(p.Refus, match='SAISIE-CONFLIT'):
            depot(cnx, **changement)
        assert cnx.execute(select(func.count()).select_from(p.PIECES)).scalar_one() == 1


def test_client_identique_projet_distinct_ne_donne_pas_acces(client_crm, session):
    p = port()
    with session() as cnx:
        recu = depot(cnx)
        assert p.lister(cnx, charger_departements(), AUTH, 'lead-fictif-002', cle=CLE)['nombre'] == 0
        with pytest.raises(p.Refus, match='INTROUVABLE'):
            p.lire(cnx, charger_departements(), AUTH, 'lead-fictif-002', recu['piece_id'], cle=CLE)
        with pytest.raises(p.Refus, match='INTROUVABLE'):
            depot(cnx, lead='lead-inexistant-fictif', mutation='b' * 32)


@pytest.mark.parametrize('auth', [replace(AUTH, expire=0), replace(AUTH, utilisateur='employe')])
def test_autorite_SQL_courante_avant_source(client_crm, session, auth, monkeypatch):
    p = port()
    def interdit(*args):
        raise AssertionError('lecture source avant autorité')
    monkeypatch.setattr(p, '_ancre', interdit)
    with session() as cnx, pytest.raises(PermissionError):
        depot(cnx, auth=auth)


def test_role_revoque_dans_SQL(client_crm, session):
    port()
    with session() as cnx:
        identite.retirer_role(cnx, AUTH.utilisateur, 'admin')
        with pytest.raises(PermissionError):
            depot(cnx)


@pytest.mark.parametrize('args', [dict(cle=None), dict(cle=b'court'), dict(titre=''),
    dict(titre='x' * 161), dict(mime='text/html', contenu=b'<script>FICTIF</script>'),
    dict(contenu=b'invalide'), dict(contenu=PDF + b'x' * 1048576), dict(mutation='invalide')])
def test_entrees_invalides_sans_ecriture(client_crm, session, args):
    p = port()
    with session() as cnx:
        with pytest.raises(p.Refus):
            depot(cnx, **args)
        assert cnx.execute(select(func.count()).select_from(p.PIECES)).scalar_one() == 0


@pytest.mark.parametrize('colonne,valeur', [('chiffre', 'AAAA'), ('titre_chiffre', 'AAAA'),
    ('auteur', 'autre.fictif'), ('source_sha256', '0' * 64)])
def test_corruption_refusee_sans_original_partiel(client_crm, session, colonne, valeur):
    p = port()
    with session() as cnx:
        recu = depot(cnx)
        cnx.execute(update(p.PIECES).values(**{colonne: valeur}))
        with pytest.raises(p.Refus):
            p.lire(cnx, charger_departements(), AUTH, LEAD, recu['piece_id'], cle=CLE)


def test_erreur_journal_annule_piece_meme_si_appelant_attrape(client_crm, session, monkeypatch):
    p = port()
    def panne(*args, **kwargs):
        raise RuntimeError('panne-fictive')
    monkeypatch.setattr(p.etat, 'journaliser', panne)
    with session() as cnx:
        with pytest.raises(RuntimeError, match='panne-fictive'):
            depot(cnx)
        assert cnx.execute(select(func.count()).select_from(p.PIECES)).scalar_one() == 0


def test_quota_mesure_avant_dechiffrement(client_crm, session, monkeypatch):
    p = port()
    with session() as cnx:
        depot(cnx)
        cnx.execute(update(p.PIECES).values(chiffre='x' * (p.MAX_CHIFFRE + 1)))
        def interdit(*args):
            raise AssertionError('déchiffrement avant quota')
        monkeypatch.setattr(p, '_dechiffrer', interdit)
        with pytest.raises(p.Refus, match='QUOTA'):
            p.lister(cnx, charger_departements(), AUTH, LEAD, cle=CLE)


def test_pagination_stricte_et_rejeu_au_quota(client_crm, session, monkeypatch):
    p = port()
    with session() as cnx:
        for i in range(21):
            depot(cnx, mutation=f'{i:032x}')
        page = p.lister(cnx, charger_departements(), AUTH, LEAD, cle=CLE)
        suite = p.lister(cnx, charger_departements(), AUTH, LEAD, cle=CLE, decalage=20)
        assert len(page['pieces']) == 20 and page['suivant'] == 20
        assert len(suite['pieces']) == 1 and suite['suivant'] is None
        assert {r['piece_id'] for r in page['pieces']}.isdisjoint(r['piece_id'] for r in suite['pieces'])
        for mauvais in (True, -1, 1, 200, '20'):
            with pytest.raises(p.Refus):
                p.lister(cnx, charger_departements(), AUTH, LEAD, cle=CLE, decalage=mauvais)
        monkeypatch.setattr(p, 'MAX_PIECES', 21)
        assert depot(cnx, mutation='0' * 32) == page['pieces'][0]
        with pytest.raises(p.Refus, match='QUOTA'):
            depot(cnx, mutation='f' * 32)
        assert cnx.execute(select(func.count()).select_from(p.PIECES)).scalar_one() == 21


def test_opportunite_recurrente_native_reste_distincte_de_la_racine(client_crm, session):
    p = port()
    from m2_revenue_crm import clients, registre

    with session() as cnx:
        reg = registre.Registre(stockage.maillons('m02-revenue-crm', 'principal'))
        client = clients.client_de_lead(reg, LEAD)
        resultat = f.outils_m2._ouvrir_nouvelle_opportunite_pour_wct(
            reg, [], LEAD, client, 'wct-fictif-recurrent', f.H2)
        opportunite = resultat['nouvelle_opportunite']
        assert opportunite == LEAD + '~opp~wct-fictif-recurrent'
        recu = depot(cnx, lead=opportunite)
        assert recu['lead_id'] == opportunite
        assert p.lire(cnx, charger_departements(), AUTH, opportunite, recu['piece_id'], cle=CLE)[1] == PDF
        assert p.lister(cnx, charger_departements(), AUTH, LEAD, cle=CLE)['nombre'] == 0
        with pytest.raises(p.Refus, match='INTROUVABLE'):
            p.lire(cnx, charger_departements(), AUTH, LEAD, recu['piece_id'], cle=CLE)


def test_deux_depots_concurrents_meme_saisie_un_seul_recu(client_crm, session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    p = port()
    depart = Barrier(2)
    def ecrire():
        depart.wait(timeout=5)
        with session() as cnx:
            return depot(cnx)
    with ThreadPoolExecutor(max_workers=2) as ouvriers:
        un = ouvriers.submit(ecrire)
        deux = ouvriers.submit(ecrire)
        assert un.result(timeout=10) == deux.result(timeout=10)
    with session() as cnx:
        assert cnx.execute(select(func.count()).select_from(p.PIECES)).scalar_one() == 1
        assert cnx.execute(select(func.count()).select_from(JOURNAL)
                           .where(JOURNAL.c.action == 'crm.piece_recue')).scalar_one() == 1


def test_quota_global_annule_ecriture_et_audit(client_crm, session, monkeypatch):
    p = port()
    monkeypatch.setattr(p, 'MAX_TOTAL', 20)
    with session() as cnx:
        with pytest.raises(p.Refus, match='QUOTA'):
            depot(cnx)
        assert cnx.execute(select(func.count()).select_from(p.PIECES)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(JOURNAL)
                           .where(JOURNAL.c.action == 'crm.piece_recue')).scalar_one() == 0


def test_revocation_en_cours_annule_piece_et_audit(client_crm, session, monkeypatch):
    p = port()
    original = p.etat.journaliser
    def revoquer(cnx, *args, **kwargs):
        original(cnx, *args, **kwargs)
        identite.retirer_role(cnx, AUTH.utilisateur, 'admin')
    monkeypatch.setattr(p.etat, 'journaliser', revoquer)
    with session() as cnx:
        with pytest.raises(PermissionError):
            depot(cnx)
        assert cnx.execute(select(func.count()).select_from(p.PIECES)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(JOURNAL)
                           .where(JOURNAL.c.action == 'crm.piece_recue')).scalar_one() == 0


def test_migration_depuis_0027_preserve_journal_et_schema(tmp_path):
    from alembic import command
    from sqlalchemy import inspect

    from opsys import etat

    url = 'sqlite:///' + str(tmp_path / 'migration-pieces-fictive.db')
    try:
        with stockage.moteur(url).begin() as cnx:
            cfg = stockage._config()
            cfg.attributes['connection'] = cnx
            command.upgrade(cfg, '0027')
            etat.journaliser(cnx, 'admin.fictif', 'fixture.fictive', 'projet-fictif', dict(fictif=True))
            avant = cnx.execute(select(JOURNAL)).all()
            command.upgrade(cfg, '0028')
            assert cnx.execute(select(JOURNAL)).all() == avant
            table = port().PIECES
            assert {c['name'] for c in inspect(cnx).get_columns('pieces_projet')} == set(table.c.keys())
            assert any(i['name'] == 'ix_pieces_projet_lead' for i in inspect(cnx).get_indexes('pieces_projet'))
            command.upgrade(cfg, '0028')
            assert cnx.execute(select(JOURNAL)).all() == avant
            command.downgrade(cfg, '0027')  # Vide uniquement.
            assert 'pieces_projet' not in inspect(cnx).get_table_names()
    finally:
        stockage.liberer()


def test_downgrade_refuse_si_piece_conservee(client_crm, session):
    from alembic import command

    p = port()
    with session() as cnx:
        recu = depot(cnx)
    with session() as cnx:
        cfg = stockage._config()
        cfg.attributes['connection'] = cnx
        with pytest.raises(RuntimeError, match='supprimerait des pièces'):
            command.downgrade(cfg, '0027')
        assert p.lire(cnx, charger_departements(), AUTH, LEAD, recu['piece_id'], cle=CLE)[1] == PDF


def test_source_M2_changee_pendant_depot_annule_tout(client_crm, session, monkeypatch):
    p = port()
    original = p._chiffrer
    def changer(cle, ligne, nature, contenu):
        chiffre = original(cle, ligne, nature, contenu)
        if nature == 'original':
            resultat = f.outils_m2.enregistrer_interaction(LEAD, AUTH.utilisateur, 'Note FICTIVE concurrente', f.H2)
            assert resultat['accepte'], resultat
        return chiffre
    monkeypatch.setattr(p, '_chiffrer', changer)
    with session() as cnx:
        avant = cnx.execute(select(REGISTRES)).all()
        with pytest.raises(p.Refus, match='SOURCE-MODIFIEE'):
            depot(cnx)
        assert cnx.execute(select(REGISTRES)).all() == avant
        assert cnx.execute(select(func.count()).select_from(p.PIECES)).scalar_one() == 0


def test_memes_octets_deux_projets_ne_partagent_pas_reference(client_crm, session):
    p = port()
    with session() as cnx:
        un = depot(cnx)
        deux = depot(cnx, lead='lead-fictif-002', mutation='b' * 32)
        assert un['source_sha256'] == deux['source_sha256']
        assert un['piece_id'] != deux['piece_id']
        lignes = cnx.execute(select(p.PIECES.c.chiffre, p.PIECES.c.nonce)).all()
        assert lignes[0] != lignes[1]
        assert p.lire(cnx, charger_departements(), AUTH, 'lead-fictif-002', deux['piece_id'], cle=CLE)[1] == PDF


def test_cle_erronee_ne_retourne_pas_titre_ni_original(client_crm, session):
    p = port()
    with session() as cnx:
        recu = depot(cnx)
        for operation in (lambda: p.lister(cnx, charger_departements(), AUTH, LEAD, cle=b'z' * 32),
            lambda: p.lire(cnx, charger_departements(), AUTH, LEAD, recu['piece_id'], cle=b'z' * 32),
            lambda: depot(cnx, cle=b'z' * 32)):
            with pytest.raises(p.Refus, match='PIECE-CORROMPUE'):
                operation()


@pytest.mark.parametrize('mime,original', [('image/png', b'\x89PNG\r\n\x1a\nPHOTO-FICTIVE'),
    ('image/jpeg', b'\xff\xd8\xffPHOTO-FICTIVE')])
def test_images_recues_stockees_sans_interpreter_le_contenu(client_crm, session, mime, original):
    p = port()
    with session() as cnx:
        recu = depot(cnx, mime=mime, contenu=original)
        assert recu['statut'] == 'NON_ANALYSE'
        assert p.lire(cnx, charger_departements(), AUTH, LEAD, recu['piece_id'], cle=CLE)[1] == original
