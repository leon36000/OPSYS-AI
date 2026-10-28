"""fictif: true — catégories et filtre du projet sans charger les originaux."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import event, update

from opsys import identite

spec = importlib.util.spec_from_file_location('liste_classee_fixture',
    Path(__file__).with_name('test_console_classement_pieces.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
client_crm, piece = g.client_crm, g.piece


def liste(cnx, lead=g.f.LEAD, **kwargs):
    p = g.port()
    assert hasattr(p, 'lister_projet'), 'liste avec catégories courantes et filtre absente'
    return p.lister_projet(cnx, g.charger_departements(), g.f.AUTH, lead, cle=g.f.CLE, **kwargs)


def test_categorie_courante_et_totaux(piece, session):
    with session() as cnx:
        vide = liste(cnx)
        assert vide['pieces'][0]['categorie_courante'] == 'non_classee'
        assert vide['pieces'][0]['revision_classement'] == 0
        g.classer(cnx, piece)
        vue = liste(cnx, categorie='plan')
        assert vue['nombre'] == vue['nombre_total'] == 1
        assert vue['pieces'][0]['piece_id'] == piece and vue['pieces'][0]['categorie_courante'] == 'plan'
        assert vue['pieces'][0]['revision_classement'] == 1
        assert vue['source_calculee'] != vide['source_calculee']
        rien = liste(cnx, categorie='photo')
        assert rien['nombre'] == 0 and rien['nombre_total'] == 1 and rien['pieces'] == []


def test_aucun_original_selectionne_ni_dechiffre(piece, session, monkeypatch):
    p = g.port().pieces
    original = p._dechiffrer
    with session() as cnx:
        def interdire_chiffre(conn, cursor, statement, parameters, context, executemany):
            assert all(c[0] != 'chiffre' for c in (cursor.description or ())), 'original sorti de SQL'
        def verifier(cle, ligne, nature):
            assert nature != 'original', 'original déchiffré dans une liste'
            return original(cle, ligne, nature)
        monkeypatch.setattr(p, '_dechiffrer', verifier)
        event.listen(cnx, 'after_cursor_execute', interdire_chiffre)
        try:
            assert liste(cnx)['nombre'] == 1
        finally:
            event.remove(cnx, 'after_cursor_execute', interdire_chiffre)


def test_filtre_avant_pagination_sans_perte(client_crm, session):
    plans = set()
    with session() as cnx:
        for i in range(41):
            recu = g.f.depot(cnx, mutation=f'{i:032x}')
            categorie = 'plan' if i % 2 == 0 else 'photo'
            g.classer(cnx, recu['piece_id'], categorie, mutation=f'{i:032x}')
            if categorie == 'plan':
                plans.add(recu['piece_id'])
        page = liste(cnx, categorie='plan')
        assert page['nombre'] == 21 and page['nombre_total'] == 41 and len(page['pieces']) == 20
        suite = liste(cnx, categorie='plan', decalage=20, source_attendue=page['source_calculee'])
        assert len(suite['pieces']) == 1 and suite['suivant'] is None
        premier = {r['piece_id'] for r in page['pieces']}
        dernier = {r['piece_id'] for r in suite['pieces']}
        assert premier.isdisjoint(dernier) and premier | dernier == plans
        assert suite['source_calculee'] == page['source_calculee']


@pytest.mark.parametrize('changement', ['classement', 'depot', 'filtre', 'projet'])
def test_empreinte_ne_vaut_pas_snapshot_courant_apres_changement(piece, session, changement):
    p = g.port()
    with session() as cnx:
        token = liste(cnx)['source_calculee']
        args = dict(source_attendue=token)
        if changement == 'classement':
            g.classer(cnx, piece)
        elif changement == 'depot':
            g.f.depot(cnx, mutation='b' * 32)
        elif changement == 'filtre':
            args['categorie'] = 'plan'
        else:
            args['lead'] = 'lead-fictif-002'
        with pytest.raises(p.Refus, match='LISTE-PERIMEE'):
            liste(cnx, **args)


@pytest.mark.parametrize('args', [dict(categorie='INTERNAL'), dict(categorie=''), dict(categorie=True),
    dict(decalage=20), dict(decalage=True), dict(decalage=1), dict(source_attendue='0' * 63)])
def test_arguments_fermes(piece, session, args):
    with session() as cnx, pytest.raises(g.port().Refus):
        liste(cnx, **args)


def test_autre_projet_titres_hors_scope(piece, session):
    with session() as cnx:
        autre = g.f.depot(cnx, lead='lead-fictif-002', mutation='b' * 32, titre='SECRET-AUTRE-PROJET-FICTIF')
        cnx.execute(update(g.f.port().PIECES).where(
            g.f.port().PIECES.c.piece_id == autre['piece_id']).values(titre_chiffre='AAAA'))
        vue = liste(cnx)
        assert len(vue['pieces']) == 1 and vue['pieces'][0]['piece_id'] == piece
        assert 'SECRET-AUTRE-PROJET' not in str(vue)


def test_role_revoque_avant_sources(piece, session, monkeypatch):
    p = g.port()
    def interdit(*args):
        raise AssertionError('compagnon lu avant autorité')
    monkeypatch.setattr(p, '_charger', interdit)
    with session() as cnx:
        identite.retirer_role(cnx, g.f.AUTH.utilisateur, 'admin')
        with pytest.raises(PermissionError):
            liste(cnx)


def test_metadonnees_corrompues_ne_deviennent_pas_zero_du_filtre(piece, session):
    with session() as cnx:
        cnx.execute(update(g.f.port().PIECES).values(titre_chiffre='AAAA'))
        with pytest.raises(g.port().Refus, match='PIECE-CORROMPUE'):
            liste(cnx, categorie='photo')


def test_liste_naffirme_pas_integrite_original_non_lu(piece, session):
    with session() as cnx:
        cnx.execute(update(g.f.port().PIECES).values(chiffre='AAAA'))
        vue = liste(cnx)
        assert vue['nombre'] == 1 and vue['pieces'][0]['statut'] == 'NON_ANALYSE'
        with pytest.raises(g.port().Refus, match='PIECE-CORROMPUE'):
            g.f.port().lire(cnx, g.charger_departements(), g.f.AUTH, g.f.LEAD, piece, cle=g.f.CLE)
