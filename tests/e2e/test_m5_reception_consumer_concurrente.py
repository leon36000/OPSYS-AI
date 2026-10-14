"""Fictif : livraison publique A, réception B native commise indépendamment.

PostgreSQL 17 READ COMMITTED ; aucun matériel ou paiement réel.
"""

import importlib.util
import os
import threading
from pathlib import Path

import pytest
from m5_financecore import outils, registre
from memoire.doubles import postgres_ephemere
from sqlalchemy import select

from opsys import stockage
from opsys.departements import lire_manifeste
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import EVENEMENTS_RECUS

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "ap_reception_pg_fictif", ROOT / "departments/m05-financecore/tests/test_comptes_a_payer_outils.py"
)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
D = f.DEPARTEMENT


def journal():
    return registre.Registre(stockage.maillons(D, outils._NOM_REGISTRE_COMPTES_A_PAYER))


def recu():
    with stockage.transaction() as cnx:
        return dict(
            cnx.execute(
                select(EVENEMENTS_RECUS).where(
                    (EVENEMENTS_RECUS.c.evenement_id == "A-FICTIF") & (EVENEMENTS_RECUS.c.consommateur == D)
                )
            )
            .mappings()
            .one()
        )


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
def test_reception_refuse_a_preserve_b_et_rejoue_le_recu(monkeypatch):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        stockage.migrer()
        outils.utiliser_stockage_durable()
        dep = lire_manifeste(ROOT / "departments/m05-financecore")
        charge_a = f._charge(evenement_id="A-FICTIF")
        charge_b = f._charge(evenement_id="B-FICTIF", gouttiere="0", vis="40", horodatage=f.LIVRAISON_2)
        f._publier(charge_a)
        avant = journal().lire()
        mouvements = list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS))
        calcule = threading.Event()
        reprendre = threading.Event()
        observations = {}
        original = MaillonsDurables.append

        def pauser(self, maillon, *, rang_attendu=None):
            if (self.departement, self.registre) == (D, outils._NOM_REGISTRE_COMPTES_A_PAYER) and (
                maillon.get("evenement_id") == "A-FICTIF"
            ):
                assert threading.current_thread() is a
                cnx = stockage.connexion_courante()
                assert cnx.get_isolation_level() == "READ COMMITTED"
                cnx.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
                cnx.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
                observations["pid_a"] = cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
                observations["rang_a"] = rang_attendu
                calcule.set()
                assert reprendre.wait(10), "coordination fictive non libérée"
            return original(self, maillon, rang_attendu=rang_attendu)

        def livrer_a():
            try:
                observations["bus_a"] = f._drainer(dep)
            except BaseException as exc:
                observations["exception_a"] = type(exc).__name__
                calcule.set()

        a = threading.Thread(target=livrer_a, name="m5-reception-a-fictif")
        monkeypatch.setattr(MaillonsDurables, "append", pauser)
        try:
            a.start()
            assert calcule.wait(10) and "exception_a" not in observations
            assert observations["rang_a"] == 0
            with stockage.transaction() as cnx:
                assert cnx.get_isolation_level() == "READ COMMITTED"
                cnx.exec_driver_sql("SET LOCAL statement_timeout = '3s'")
                cnx.exec_driver_sql("SET LOCAL lock_timeout = '200ms'")
                assert cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one() != observations["pid_a"]
                assert outils._recevoir_reception_enregistree(charge_b)["statut"] == "recue"
            avec_b = journal().lire()
            assert avec_b[:0] == avant and len(avec_b) == 1 and avec_b[-1]["evenement_id"] == "B-FICTIF"
            assert journal().valider_chaine() == (True, "")
            reprendre.set()
            a.join(10)
            assert not a.is_alive() and "exception_a" not in observations
            assert observations["bus_a"]["echecs"] == 1 and observations["bus_a"]["traites"] == 0
            stockage.liberer()
            assert journal().lire() == avec_b and journal().valider_chaine() == (True, "")
            receipt = recu()
            assert receipt["statut"] == "echec" and receipt["tentatives"] == 1
            assert receipt["derniere_erreur"].startswith("EcritureConcurrente:")
            assert receipt["prochaine_tentative"] == "2026-09-29T12:00:02+00:00"
            monkeypatch.setattr(MaillonsDurables, "append", original)
            assert f._drainer(dep, heure="2026-09-29T12:00:01+00:00")["livres"] == 0
            assert journal().lire() == avec_b
            assert f._drainer(dep, heure="2026-09-29T12:00:03+00:00")["traites"] == 1
            stockage.liberer()
            apres = journal().lire()
            assert apres[:1] == avec_b and len(apres) == 2
            assert apres[-1]["precedent_ligne_id"] == avec_b[-1]["ligne_id"]
            assert [m["evenement_id"] for m in apres] == ["B-FICTIF", "A-FICTIF"]
            assert journal().valider_chaine() == (True, "")
            receipt = recu()
            assert receipt["statut"] == "traite" and receipt["tentatives"] == 2
            assert receipt["prochaine_tentative"] is None
            with stockage.transaction():
                assert outils._recevoir_reception_enregistree(charge_a)["statut"] == "deja_recue"
            assert journal().lire() == apres
            assert list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS)) == mouvements
        finally:
            reprendre.set()
            if a.ident is not None:
                a.join(10)
            assert not a.is_alive(), "écrivain fictif non arrêté"
            monkeypatch.setattr(MaillonsDurables, "append", original)
            stockage.liberer()
