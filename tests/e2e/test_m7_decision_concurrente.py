"""Fictif : deux décisions opposées du propriétaire natif, B commise indépendamment.

PostgreSQL 17 READ COMMITTED ; aucun envoi à une plateforme ni décision réelle.
"""

import importlib.util
import os
import threading
from pathlib import Path

import pytest
from m7_marketing.brand import profil_client
from memoire.doubles import postgres_ephemere

from opsys import identite, stockage
from opsys.stockage.maillons import EcritureConcurrente, MaillonsDurables

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "m7_decision_pg_fictif", ROOT / "departments/m07-marketing/tests/reputation/test_inbox_durable.py"
)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
@pytest.mark.parametrize("decision_a,decision_b", [("rejeter", "approuver"), ("approuver", "rejeter")])
def test_decision_refuse_a_preserve_b_commise_sans_reapprobation(monkeypatch, tmp_path, decision_a, decision_b):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
        monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(f._PROFIL), None))
        stockage.migrer()
        with stockage.transaction() as cnx:
            identite.creer_personne(cnx, "employe", "Employé fictif", "mot-de-passe-fictif", ["employee"])
            identite.creer_personne(
                cnx, "nathan", "Propriétaire fictif", "mot-de-passe-fictif", ["nathan_owner", "admin"]
            )
        avis_id = f._metier(f._appel("m7_importer_avis_manuel", **f._avis()))["avis_id"]
        assert f._lire("reputation_decisions") == []
        calcule = threading.Event()
        reprendre = threading.Event()
        observations = {}
        original = MaillonsDurables.append

        def decider(decision):
            return f._appel(
                "m7_decider_reponse_avis", personne="nathan", role="admin", avis_id=avis_id,
                decision=decision, horodatage=f.HORODATAGE, motif="Motif fictif de décision",
            )

        def pauser(self, maillon, *, rang_attendu=None):
            if (self.departement, self.registre) == ("m07-marketing", "reputation_decisions") and (
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

        def trancher_a():
            try:
                observations["a"] = decider(decision_a)
            except BaseException as exc:
                observations["exception_a"] = exc
                calcule.set()

        a = threading.Thread(target=trancher_a, name="m7-decision-a-fictif")
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
                b = decider(decision_b)
                assert b["ok"] is True and b["resultat"]["accepte"] is True
            avec_b = f._lire("reputation_decisions")
            statut_b = "APPROUVE" if decision_b == "approuver" else "REJETE"
            assert len(avec_b) == 1 and avec_b[0]["decision"] == statut_b
            assert f._metier(b)["statut"] == statut_b
            reprendre.set()
            a.join(10)
            assert not a.is_alive() and "a" not in observations
            assert isinstance(observations["exception_a"], EcritureConcurrente)
            assert str(observations["exception_a"]).startswith("rang attendu 0 devenu 1")
            stockage.liberer()
            assert f._lire("reputation_decisions") == avec_b
            assert f._lire("reputation_exports") == []
            monkeypatch.setattr(MaillonsDurables, "append", original)
            frais = decider(decision_a)
            assert frais["ok"] is True and frais["resultat"]["accepte"] is False
            assert frais["resultat"]["verdict"]["code"] == "REJ-AVIS-DEJA-TRANCHE"
            assert f._lire("reputation_decisions") == avec_b
            export = f._appel(
                "m7_exporter_reponse_avis_manuel", personne="nathan", role="admin", avis_id=avis_id
            )
            assert export["ok"] is True and export["resultat"]["accepte"] is (decision_b == "approuver")
            if decision_b == "rejeter":
                assert export["resultat"]["verdict"]["code"] == "REJ-AVIS-NON-APPROUVE"
            exports = f._lire("reputation_exports")
            assert len(exports) == (1 if decision_b == "approuver" else 0)
            assert f._lire("reputation_decisions") == avec_b
            if decision_b == "approuver":
                assert f._metier(f._appel(
                    "m7_exporter_reponse_avis_manuel", personne="nathan", role="admin", avis_id=avis_id
                ))["deja_exporte"] is True
                assert f._lire("reputation_exports") == exports
        finally:
            reprendre.set()
            if a.ident is not None:
                a.join(10)
            assert not a.is_alive(), "écrivain fictif non arrêté"
            monkeypatch.setattr(MaillonsDurables, "append", original)
            stockage.liberer()
