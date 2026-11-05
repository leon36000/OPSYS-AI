"""Couvertures structurées, migration et lectures (données fictives)."""
import copy

import pytest
from alembic import command
from m8_analytics import catalogue_mesures, entrepot_stockage, jeux_fictifs, moteur_mesures
from sqlalchemy import inspect, text, update

from opsys import stockage
from opsys.pont_bi import jeux, service

INSTANT = "2026-10-30T20:00:00-04:00"


def test_aucune_extension_des_champs_exportables_bi():
    for nom in ('mesures_courantes', 'mesures_historique'):
        for financier in (False, True):
            assert 'couverture' not in {c.nom for c in jeux.JEUX[nom].colonnes_visibles(financier)}


def test_migration_ancien_historique_et_reconstruction(tmp_path):
    url = f"sqlite:///{tmp_path / 'm8.db'}"
    cfg = stockage._config()
    registres = jeux_fictifs.registres_fictifs()
    catalogue = catalogue_mesures.charger()
    empreinte = moteur_mesures.empreinte_registres(registres)
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes['connection'] = cnx
        command.upgrade(cfg, '0087')
        # 0046 utilise le schéma courant. Reproduire le schéma réellement installé avant 0088.
        for table in ('m8_ent_mesures_courantes', 'm8_ent_mesures_hist'):
            cnx.exec_driver_sql(f'ALTER TABLE {table} DROP COLUMN couverture')
        cnx.execute(text("INSERT INTO m8_ent_constructions (construction_id,version_schema,version_catalogue,"
                         "empreinte_registres,construit_le,nb_mesures,comptes) "
                         "VALUES ('ancien',1,:catalogue,:empreinte,:instant,1,'{}')"),
                     {'instant': INSTANT, 'catalogue': catalogue['version_catalogue'], 'empreinte': empreinte})
        cnx.execute(text("INSERT INTO m8_ent_mesures_hist (construction_id,metric_id,construit_le,construit_le_utc,"
                         "statut,valeur,version_definition) VALUES "
                         "('ancien','m8_chantiers_termines',:instant,'2026-10-31T00:00:00.000000000Z',"
                         "'calculee','1','ancienne')"), {'instant': INSTANT})
        command.upgrade(cfg, 'head')
        assert cnx.execute(text("SELECT couverture IS NULL FROM m8_ent_mesures_hist "
                                "WHERE construction_id='ancien'")).scalar_one() == 1
        ancienne = entrepot_stockage.lire_historique(cnx, 'm8_chantiers_termines')
        assert ancienne[0]['couverture'] is None
        assert entrepot_stockage.etat(cnx, registres, catalogue)['statut'] == 'en_retard'
        resultat = entrepot_stockage.reconstruire(cnx, registres, catalogue, INSTANT)
        assert resultat['statut'] == 'construit'
        assert entrepot_stockage.reconstruire(cnx, registres, catalogue, INSTANT)['statut'] == 'inchange'
        lignes = entrepot_stockage.lire_mesures_courantes(cnx)
        assert lignes and all(isinstance(x['couverture'], dict) for x in lignes)
        nouvelle = entrepot_stockage.lire_historique(cnx, 'm8_chantiers_termines')
        assert {x['construction_id'] for x in nouvelle} >= {'ancien', resultat['construction']['construction_id']}
        assert next(x for x in nouvelle if x['construction_id'] == 'ancien')['couverture'] is None
    stockage.liberer()


def test_lectures_et_historique_gardent_toute_la_couverture(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm8.db'}"
    stockage.migrer(url)
    original = moteur_mesures.lire
    couvertures = [
        {'etat': 'complete'},
        {'etat': 'inconnue'},
        {'etat': 'partielle', 'couverts': 2, 'attendus': 3, 'manquants': 1, 'raison': 'un manque'},
        {'etat': 'partielle', 'jours_sans_releve': 2, 'raison': 'relevés absents'},
    ]
    def lire(*args, **kwargs):
        mesures = original(*args, **kwargs)
        for mesure, couverture in zip(mesures, couvertures, strict=False):
            mesure['couverture'] = copy.deepcopy(couverture)
        return mesures
    monkeypatch.setattr(moteur_mesures, 'lire', lire)
    registres = jeux_fictifs.registres_fictifs()
    with stockage.moteur(url).begin() as cnx:
        entrepot_stockage.reconstruire(cnx, registres, catalogue_mesures.charger(), INSTANT)
        lignes = entrepot_stockage.lire_mesures_courantes(cnx)
        valeurs = [ligne['couverture'] for ligne in lignes]
        for couverture in couvertures:
            assert couverture in valeurs
        for ligne in lignes:
            if ligne['couverture'] in couvertures:
                hist = entrepot_stockage.lire_historique(cnx, ligne['metric_id'])
                assert hist[0]['couverture'] == ligne['couverture']
    stockage.liberer()


@pytest.mark.parametrize('table', ['m8_ent_mesures_courantes', 'm8_ent_mesures_hist'])
def test_descente_refusee_si_une_seule_table_contient_des_couvertures(tmp_path, table):
    url = f"sqlite:///{tmp_path / 'm8.db'}"
    stockage.migrer(url)
    cfg = stockage._config()
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes['connection'] = cnx
        entrepot_stockage.reconstruire(cnx, jeux_fictifs.registres_fictifs(), catalogue_mesures.charger(), INSTANT)
        autre = 'm8_ent_mesures_hist' if table == 'm8_ent_mesures_courantes' else 'm8_ent_mesures_courantes'
        cnx.exec_driver_sql(f'UPDATE {autre} SET couverture = NULL')
        avant = cnx.exec_driver_sql(f'SELECT metric_id, couverture FROM {table} ORDER BY metric_id').all()
        assert avant and all(ligne.couverture is not None for ligne in avant)
        with pytest.raises(RuntimeError, match='rétrogradation refusée'):
            command.downgrade(cfg, '0087')
        assert cnx.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one() == '0088'
        assert cnx.exec_driver_sql(f'SELECT metric_id, couverture FROM {table} ORDER BY metric_id').all() == avant
    stockage.liberer()


def test_descente_couvertures_nulles_preserve_les_lignes(tmp_path):
    url = f"sqlite:///{tmp_path / 'm8.db'}"
    stockage.migrer(url)
    cfg = stockage._config()
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes['connection'] = cnx
        entrepot_stockage.reconstruire(cnx, jeux_fictifs.registres_fictifs(), catalogue_mesures.charger(), INSTANT)
        tables = ('m8_ent_mesures_courantes', 'm8_ent_mesures_hist')
        for table in tables:
            cnx.execute(update(entrepot_stockage.tables()[table]).values(couverture=None))
            assert cnx.exec_driver_sql(f'SELECT COUNT(*) FROM {table} WHERE couverture IS NOT NULL').scalar_one() == 0
        avant = {table: cnx.exec_driver_sql(f'SELECT metric_id, statut, valeur FROM {table} ORDER BY metric_id').all()
                 for table in tables}
        assert all(avant.values())
        command.downgrade(cfg, '0087')
        assert cnx.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one() == '0087'
        for table in tables:
            assert 'couverture' not in {colonne['name'] for colonne in inspect(cnx).get_columns(table)}
            apres = cnx.exec_driver_sql(f'SELECT metric_id, statut, valeur FROM {table} ORDER BY metric_id').all()
            assert apres == avant[table]
        command.upgrade(cfg, '0088')
        for table in tables:
            assert 'couverture' in {colonne['name'] for colonne in inspect(cnx).get_columns(table)}
            assert cnx.exec_driver_sql(f'SELECT COUNT(*) FROM {table} WHERE couverture IS NOT NULL').scalar_one() == 0
    stockage.liberer()


def test_exports_bi_effectifs_excluent_la_couverture(tmp_path):
    url = f"sqlite:///{tmp_path / 'm8.db'}"
    stockage.migrer(url)
    with stockage.moteur(url).begin() as cnx:
        entrepot_stockage.reconstruire(cnx, jeux_fictifs.registres_fictifs(), catalogue_mesures.charger(), INSTANT)
        for nom in ('mesures_courantes', 'mesures_historique'):
            for financier in (False, True):
                colonnes, lignes, total = service.lire_jeu(
                    cnx, jeux.JEUX[nom], financier=financier, limite=100, depart=0
                )
                assert total > 0 and lignes
                assert 'couverture' not in {colonne.nom for colonne in colonnes}
                assert all('couverture' not in ligne for ligne in lignes)
                with pytest.raises(service.RefusPontBI, match='select_invalide'):
                    service.lire_jeu(cnx, jeux.JEUX[nom], financier=financier, limite=1, depart=0,
                                     selection=['couverture'])
    stockage.liberer()
