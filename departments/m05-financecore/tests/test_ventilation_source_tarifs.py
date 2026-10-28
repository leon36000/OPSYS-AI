"""Tarifs fictifs : transactions et identité réelles en SQLite."""
import importlib.util
from contextlib import contextmanager
from pathlib import Path

import pytest
from m5_financecore import outils

from opsys import contexte, identite, stockage

spec = importlib.util.spec_from_file_location('fixtures_tarifs_m5', Path(__file__).with_name('test_evenements_m5.py'))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
base_durable = fixtures.base_durable


@contextmanager
def admin():
    with (contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')),
          contexte.appeler_en_tant_que('m05-financecore', origine='console')):
        yield


@pytest.fixture
def base_admin(base_durable):
    with stockage.transaction(base_durable) as cnx:
        identite.creer_personne(cnx, 'admin.fictif', 'Admin fictif', 'Fictif#12345678', roles=['admin'])
    return base_durable


def tarif(**changes):
    return dict(equipe_id='FICTIF-A', taux='100.00', unite='heure-equipe', devise='CAD',
                source='FICTIF-doc', version='v1', date_effet='2030-01-01', date_fin='2030-12-31',
                remplace_id=None) | changes


def test_admission_concurrence_rejeu_revision_et_rollback(base_admin):
    with admin(), stockage.transaction(base_admin):
        vide = outils._lire_tarifs_equipes()
        assert vide['lignes'] == []
        a = outils._inscrire_tarif_equipe(tarif(), mutation_id='FICTIF-1', source_attendue=vide['source'])
        actuel = outils._lire_tarifs_equipes()
        assert len(actuel['lignes']) == 1 and actuel['source'] != vide['source']
        assert outils._inscrire_tarif_equipe(tarif(), mutation_id='FICTIF-1', source_attendue=vide['source']) == a
        with pytest.raises(ValueError):
            outils._inscrire_tarif_equipe(tarif(taux='101'), mutation_id='FICTIF-1', source_attendue=actuel['source'])
        with pytest.raises(ValueError):
            outils._inscrire_tarif_equipe(tarif(), mutation_id='FICTIF-2', source_attendue=vide['source'])
        with pytest.raises(ValueError):
            outils._inscrire_tarif_equipe(tarif(version='v2'), mutation_id='FICTIF-2', source_attendue=actuel['source'])
        b = outils._inscrire_tarif_equipe(tarif(version='v2', taux='120', remplace_id=a['ligne_id']),
                                          mutation_id='FICTIF-3', source_attendue=actuel['source'])
        assert b['ligne_id'] != a['ligne_id']
        apres = outils._lire_tarifs_equipes()
        assert len(apres['historique']) == 2 and apres['lignes'][0]['taux'] == '120'
    with pytest.raises(RuntimeError), admin(), stockage.transaction(base_admin):
        avant = outils._lire_tarifs_equipes()
        outils._inscrire_tarif_equipe(tarif(equipe_id='FICTIF-B'), mutation_id='FICTIF-4',
                                       source_attendue=avant['source'])
        raise RuntimeError('rollback fictif')
    with admin(), stockage.transaction(base_admin):
        assert outils._lire_tarifs_equipes() == apres


def test_refuse_hors_admin_console_et_champs_invalides(base_admin):
    with stockage.transaction(base_admin), pytest.raises(PermissionError):
        outils._lire_tarifs_equipes()
    with admin(), stockage.transaction(base_admin):
        source = outils._lire_tarifs_equipes()['source']
        for modification in ({'taux': 'NaN'}, {'unite': 'heure-personne'}, {'source': ''},
                             {'date_fin': '2029-12-31'}, {'taux': 100}):
            with pytest.raises(ValueError):
                outils._inscrire_tarif_equipe(tarif(**modification), mutation_id='FICTIF-MAUVAIS',
                                               source_attendue=source)
        assert outils._lire_tarifs_equipes()['lignes'] == []


def test_origine_mcp_et_role_non_admin_refuses(base_admin):
    with stockage.transaction(base_admin) as cnx:
        identite.creer_personne(cnx, 'employe.fictif', 'Employé fictif', 'Fictif#12345678', roles=['employee'])
    with (contexte.appele_par_appareil(contexte.IdentiteAppelante('employe.fictif', 'employee', source='console')),
          contexte.appeler_en_tant_que('m05-financecore', origine='console'), stockage.transaction(base_admin),
          pytest.raises(PermissionError)):
        outils._lire_tarifs_equipes()
    with admin(), contexte.transport_mcp(), stockage.transaction(base_admin), pytest.raises(PermissionError):
        outils._lire_tarifs_equipes()


def test_falsification_de_maillon_et_reouverture_refusees(base_admin):
    from sqlalchemy import update

    from opsys.stockage.schema import REGISTRES

    with admin(), stockage.transaction(base_admin):
        source = outils._lire_tarifs_equipes()['source']
        outils._inscrire_tarif_equipe(tarif(), mutation_id='FICTIF-1', source_attendue=source)
    stockage.liberer()
    with admin(), stockage.transaction(base_admin):
        assert len(outils._lire_tarifs_equipes()['lignes']) == 1
    with stockage.transaction(base_admin) as cnx:
        cnx.execute(update(REGISTRES).where((REGISTRES.c.departement == 'm05-financecore') &
            (REGISTRES.c.registre == 'tarifs_equipes')).values(maillon='{}'))
    with admin(), stockage.transaction(base_admin), pytest.raises(ValueError):
        outils._lire_tarifs_equipes()


def test_ecritures_simultanees_meme_source_ne_creent_pas_deux_tarifs(base_admin):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    with admin(), stockage.transaction(base_admin):
        source = outils._lire_tarifs_equipes()['source']
    barriere = Barrier(2)

    def ecrire(numero):
        barriere.wait(timeout=10)
        try:
            with admin(), stockage.transaction(base_admin):
                outils._inscrire_tarif_equipe(tarif(taux=str(100 + numero)), mutation_id=f'FICTIF-{numero}',
                                               source_attendue=source)
            return 'accepte'
        except ValueError:
            return 'perime'

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(ecrire, (1, 2)))
    assert sorted(resultats) == ['accepte', 'perime']
    with admin(), stockage.transaction(base_admin):
        assert len(outils._lire_tarifs_equipes()['historique']) == 1


def test_role_revoque_et_origine_non_console_refuses(base_admin):
    with (contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')),
          contexte.appeler_en_tant_que('m05-financecore', origine='m05-financecore'),
          stockage.transaction(base_admin), pytest.raises(PermissionError)):
        outils._lire_tarifs_equipes()
    with stockage.transaction(base_admin) as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    with admin(), stockage.transaction(base_admin), pytest.raises(PermissionError):
        outils._lire_tarifs_equipes()


def test_revision_conservee_exige_une_nouvelle_version_de_source(base_admin):
    with admin(), stockage.transaction(base_admin):
        vide = outils._lire_tarifs_equipes()
        premier = outils._inscrire_tarif_equipe(tarif(), mutation_id='FICTIF-1', source_attendue=vide['source'])
        source = outils._lire_tarifs_equipes()['source']
        with pytest.raises(ValueError):
            outils._inscrire_tarif_equipe(tarif(taux='120', remplace_id=premier['ligne_id']),
                                          mutation_id='FICTIF-2', source_attendue=source)
        assert len(outils._lire_tarifs_equipes()['historique']) == 1


def test_revision_qui_reduit_la_periode_est_refusee_sans_perdre_historique(base_admin):
    with admin(), stockage.transaction(base_admin):
        source = outils._lire_tarifs_equipes()['source']
        ancien = outils._inscrire_tarif_equipe(tarif(), mutation_id='FICTIF-ANNUEL', source_attendue=source)
        avant = outils._lire_tarifs_equipes()
        revision = tarif(version='v2', date_effet='2030-06-01', date_fin='2030-06-30',
                         remplace_id=ancien['ligne_id'])
        with pytest.raises(ValueError):
            outils._inscrire_tarif_equipe(revision, mutation_id='FICTIF-JUIN', source_attendue=avant['source'])
        assert outils._lire_tarifs_equipes() == avant


def test_source_tarif_est_liee_a_l_instance_durable(base_admin):
    from sqlalchemy import update

    from opsys.stockage.schema import OPSYS_INSTANCE

    with admin(), stockage.transaction(base_admin) as cnx:
        premiere = outils._lire_tarifs_equipes()['source']
        cnx.execute(update(OPSYS_INSTANCE).where(OPSYS_INSTANCE.c.id == 1)
                    .values(instance_id='00000000-0000-4000-8000-000000000099'))
        seconde = outils._lire_tarifs_equipes()['source']
        assert premiere != seconde


def test_revocation_tardive_annule_l_ecriture_et_la_transaction_interposee(base_admin, monkeypatch):
    from opsys.stockage.maillons import MaillonsDurables

    original = MaillonsDurables.append

    def interposer(self, maillon, *, rang_attendu=None):
        resultat = original(self, maillon, rang_attendu=rang_attendu)
        if (self.departement, self.registre) == ('m05-financecore', 'tarifs_equipes'):
            identite.retirer_role(stockage.connexion_courante(), 'admin.fictif', 'admin')
        return resultat

    with admin(), stockage.transaction(base_admin):
        avant = outils._lire_tarifs_equipes()
        monkeypatch.setattr(MaillonsDurables, 'append', interposer)
        with pytest.raises(PermissionError):
            outils._inscrire_tarif_equipe(tarif(), mutation_id='FICTIF-REVOCATION', source_attendue=avant['source'])
        assert outils._lire_tarifs_equipes() == avant
