"""Fictif : import A par outil, import B commis sur une connexion indépendante.

PostgreSQL 17 READ COMMITTED ; aucune plateforme, session installée ou donnée réelle.
"""

import importlib.util
import os
import threading
from pathlib import Path

import pytest
from m7_marketing import outils
from m7_marketing.brand import profil_client
from memoire.doubles import postgres_ephemere

from opsys import identite, stockage
from opsys.stockage.maillons import EcritureConcurrente, MaillonsDurables

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "m7_inbox_pg_fictif", ROOT / "departments/m07-marketing/tests/reputation/test_inbox_durable.py"
)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
@pytest.mark.parametrize("source_b", ["review-8841", "autre-avis-fictif"])
def test_import_refuse_a_preserve_b_commis_et_rejoue(monkeypatch, tmp_path, source_b):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
        monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(f._PROFIL), None))
        stockage.migrer()
        with stockage.transaction() as cnx:
            identite.creer_personne(cnx, "employe", "Employé fictif", "mot-de-passe-fictif", ["employee"])
        assert f._lire("reputation_avis") == []
        calcule = threading.Event()
        reprendre = threading.Event()
        observations = {}
        original = MaillonsDurables.append

        def pauser(self, maillon, *, rang_attendu=None):
            if (self.departement, self.registre) == ("m07-marketing", "reputation_avis") and (
                threading.current_thread() is a
            ):
                cnx = stockage.connexion_courante()
                assert cnx.get_isolation_level() == "READ COMMITTED"
                cnx.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
                cnx.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
                observations["pid_a"] = cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
                observations["rang_a"] = rang_attendu
                calcule.set()
                assert reprendre.wait(10), "coordination fictive non libérée"
            return original(self, maillon, rang_attendu=rang_attendu)

        def importer_a():
            try:
                observations["a"] = f._appel("m7_importer_avis_manuel", **f._avis())
            except BaseException as exc:
                observations["exception_a"] = exc
                calcule.set()

        a = threading.Thread(target=importer_a, name="m7-import-a-fictif")
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
                b = f._metier(f._appel("m7_importer_avis_manuel", **f._avis(avis_source_id=source_b)))
                assert b["deja_importe"] is False
            avec_b = f._lire("reputation_avis")
            assert len(avec_b) == 1 and avec_b[0]["avis_id"] == b["avis_id"]
            assert avec_b[0]["avis_source_id"] == source_b
            reprendre.set()
            a.join(10)
            assert not a.is_alive() and "a" not in observations
            assert isinstance(observations["exception_a"], EcritureConcurrente)
            assert str(observations["exception_a"]).startswith("rang attendu 0 devenu 1")
            stockage.liberer()
            assert f._lire("reputation_avis") == avec_b
            assert outils.calculer_metriques_reputation()["m7_rep_total_avis"] == 1
            monkeypatch.setattr(MaillonsDurables, "append", original)
            reprise = f._metier(f._appel("m7_importer_avis_manuel", **f._avis()))
            assert reprise["deja_importe"] is (source_b == "review-8841")
            apres = f._lire("reputation_avis")
            assert apres[:1] == avec_b and len(apres) == (1 if source_b == "review-8841" else 2)
            assert len({avis["avis_id"] for avis in apres}) == len(apres)
            assert outils.calculer_metriques_reputation()["m7_rep_total_avis"] == len(apres)
            assert f._metier(f._appel("m7_importer_avis_manuel", **f._avis()))["deja_importe"] is True
            assert f._lire("reputation_avis") == apres
            conflit = f._metier(f._appel("m7_importer_avis_manuel", **f._avis(texte="Modification fictive")))
            assert conflit["accepte"] is False and conflit["verdict"]["code"] == "CONFLIT-AVIS-SOURCE"
            assert f._lire("reputation_avis") == apres
        finally:
            reprendre.set()
            if a.ident is not None:
                a.join(10)
            assert not a.is_alive(), "écrivain fictif non arrêté"
            monkeypatch.setattr(MaillonsDurables, "append", original)
            stockage.liberer()
