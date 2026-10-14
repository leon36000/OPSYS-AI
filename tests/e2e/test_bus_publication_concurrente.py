"""Bus : la première enveloppe commise décide le rejeu concurrent.

PostgreSQL 17 réel, base éphémère et écritures fictives. Un verrou PostgreSQL
observé prouve que B attend la publication A, sans remplacer le bus natif.
"""
from __future__ import annotations

import os
import threading
import time

import pytest
from memoire.doubles import postgres_ephemere
from sqlalchemy import select, text

from opsys import evenements, stockage
from opsys.outils import Outil, executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
@pytest.mark.parametrize("identique", [True, False], ids=["rejeu-identique", "conflit-charge"])
def test_publication_concurrente_preserve_gagnant_et_atomicite(monkeypatch, identique):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        stockage.migrer()
        pret = threading.Event()
        observations = {}
        ident = "publication-concurrente-fictive"
        charge_a = {"message": "A-fictif"}
        charge_b = charge_a if identique else {"message": "B-fictif"}

        def publier_b():
            cnx = stockage.connexion_courante()
            assert cnx is not None and cnx.get_isolation_level() == "READ COMMITTED"
            cnx.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            cnx.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
            observations["pid_b"] = cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            stockage.maillons("m-demo-concurrence-bus", "fictif").append({"fictif": True})
            pret.set()
            return {"evenement_id": evenements.publier(
                "opsys.demo_complete", "producteur-fictif", charge_b, evenement_id=ident,
            )}

        outil = Outil("m9_test_publication_fictive", "Publication fictive", {"type": "object"}, publier_b)

        def ecrire_b():
            try:
                observations["reponse_b"] = executer_atomique(outil, {})
            except BaseException as exc:
                observations["exception_b"] = type(exc).__name__
                pret.set()

        ecrivain_b = threading.Thread(target=ecrire_b, name="bus-publication-b-fictif")
        try:
            with stockage.transaction() as cnx_a:
                assert cnx_a.get_isolation_level() == "READ COMMITTED"
                pid_a = cnx_a.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
                evenements.publier("opsys.demo_complete", "producteur-fictif", charge_a, evenement_id=ident)
                avant = cnx_a.execute(select(EVENEMENTS_SORTANTS)).one()
                ecrivain_b.start()
                assert pret.wait(5), "B n'a pas atteint le bus natif"
                assert "exception_b" not in observations
                assert observations["pid_b"] != pid_a
                limite = time.monotonic() + 5
                bloque_par_a = False
                while time.monotonic() < limite:
                    bloqueurs = cnx_a.execute(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": observations["pid_b"]},
                    ).scalar_one()
                    if pid_a in bloqueurs:
                        bloque_par_a = True
                        break
                    time.sleep(0.02)
                assert bloque_par_a, "aucune attente réelle du gagnant A observée"
                assert "reponse_b" not in observations
            # COMMIT A releases its unique-key lock. B's SELECT must see this winner.
            ecrivain_b.join(10)
            assert not ecrivain_b.is_alive()
            assert "exception_b" not in observations
            reponse = observations["reponse_b"]
            assert reponse["ok"] is identique
            if not identique:
                assert reponse["erreur"] == "refus_metier" and "charge" in reponse["details"]
            stockage.liberer()
            assert len(stockage.maillons("m-demo-concurrence-bus", "fictif")) == int(identique)
            with stockage.transaction() as cnx:
                assert cnx.execute(select(EVENEMENTS_SORTANTS)).one() == avant
        finally:
            if ecrivain_b.ident is not None:
                ecrivain_b.join(10)
            assert not ecrivain_b.is_alive(), "écrivain fictif non arrêté"
            stockage.liberer()
