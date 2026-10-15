"""Bus : enveloppes immuables et fraîcheur du reçu de retry concurrent.

PostgreSQL 17 réel, base éphémère et écritures fictives. Les verrous observés
prouvent B attendant la publication A, puis A attendant le claim de retry B,
sans remplacer la publication, le répartiteur ni le consommateur M8 natifs.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
import time
from pathlib import Path

import pytest
from m8_analytics import outils as m8_outils
from m8_analytics import registre
from memoire.doubles import postgres_ephemere
from sqlalchemy import event, insert, select, text

from opsys import evenements, stockage
from opsys.outils import Outil, executer_atomique
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS


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


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
def test_claim_retry_concurrent_revalide_recu_apres_attente_postgresql(monkeypatch, tmp_path):
    """A lit avant B ; son UPDATE attend B et doit refuser le compteur/backoff devenus frais."""
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "instance-fictive"))
        racine = tmp_path / "departments"
        racine.mkdir()
        m8 = "m08-analytics"
        (racine / m8).symlink_to(Path(__file__).resolve().parents[2] / "departments" / m8,
                               target_is_directory=True)
        monkeypatch.setenv("OPSYS_DEPARTMENTS", str(racine))
        from opsys.departements import charger_departements

        departements = charger_departements()
        stockage.migrer()
        instant = dt.datetime(2026, 10, 15, 12, tzinfo=dt.UTC)
        ident = "wct-claim-retry-postgresql-fictif"
        evenements.publier("m4.travaux_termines", "m04-field-ops", {
            "wct_id": ident, "intervention_id": "intervention-fictive", "lead_id": "lead-fictif",
            "technicien_id": "technicien-fictif", "horodatage_completion": instant.isoformat(),
            "fix_gps_completion": {}, "duree_reelle_minutes": 120, "ecart_signale": False,
            "revue_id": None, "hash_maillon": "a" * 64, "consommateurs_cibles": ["M8"],
            "devis_id": None, "statut": "completed_verified",
        }, evenement_id=ident)
        with stockage.transaction() as cnx:
            cnx.execute(insert(EVENEMENTS_RECUS).values(
                evenement_id=ident, consommateur=m8, statut="echec", tentatives=0,
                prochaine_tentative=None, resultat=None, derniere_erreur=None,
            ))
        b_a_ecrit = threading.Event()
        liberer_b = threading.Event()
        observations = {}
        appels = []
        mesure_native = m8_outils._mesurer_et_publier
        moteur = stockage.moteur()

        def mesurer_et_suspendre_b(wct_id, faits):
            resultat = mesure_native(wct_id, faits)
            appels.append(threading.current_thread().name)
            if threading.current_thread() is ecrivain_b:
                cnx = stockage.connexion_courante()
                assert cnx is not None and cnx.get_isolation_level() == "READ COMMITTED"
                cnx.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
                cnx.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
                observations["pid_b"] = cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
                assert len(stockage.maillons(m8, "snapshots")) == 1
                assert len(stockage.maillons(m8, "faits_chantier")) == 1
                b_a_ecrit.set()
                assert liberer_b.wait(8), "B n'a pas reçu sa libération contrôlée"
                observations["panne_controlee"] = True
                raise RuntimeError("panne transitoire fictive après écritures M8")
            return resultat

        monkeypatch.setattr(m8_outils, "_mesurer_et_publier", mesurer_et_suspendre_b)

        def repartir_natif(nom):
            try:
                observations["reponse_" + nom] = evenements.repartir(
                    departements, limite=1, maintenant=instant.isoformat(),
                )
            except BaseException as exc:
                observations["exception_" + nom] = type(exc).__name__
                b_a_ecrit.set()

        ecrivain_a = threading.Thread(target=repartir_natif, args=("a",), name="bus-claim-a-fictif")
        ecrivain_b = threading.Thread(target=repartir_natif, args=("b",), name="bus-claim-b-fictif")

        def interposer_b_avant_claim_a(cnx, curseur, instruction, parametres, contexte_sql, executemany):
            commande = getattr(getattr(contexte_sql, "compiled", None), "statement", None)
            if (threading.current_thread() is ecrivain_b and not observations.get("b_avant_claim")
                    and getattr(commande, "is_update", False)
                    and getattr(commande, "table", None) is EVENEMENTS_RECUS):
                observations["b_avant_claim"] = True
                cnx.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
                cnx.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
                return
            if (threading.current_thread() is not ecrivain_a or observations.get("a_avant_claim")
                    or not getattr(commande, "is_update", False)
                    or getattr(commande, "table", None) is not EVENEMENTS_RECUS):
                return
            observations["a_avant_claim"] = True  # garde avant les requêtes imbriquées
            assert cnx.get_isolation_level() == "READ COMMITTED"
            cnx.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            cnx.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
            observations["pid_a"] = cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            ecrivain_b.start()
            assert b_a_ecrit.wait(5), "B n'a pas atteint ses vraies écritures M8"
            assert "exception_b" not in observations

        event.listen(moteur, "before_cursor_execute", interposer_b_avant_claim_a)
        try:
            ecrivain_a.start()
            assert b_a_ecrit.wait(5), "A/B n'ont pas atteint l'interposition native"
            assert "exception_a" not in observations and "exception_b" not in observations
            assert observations["pid_a"] != observations["pid_b"]
            with moteur.connect() as observateur:
                assert observateur.get_isolation_level() == "READ COMMITTED"
                observateur.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
                pid_observateur = observateur.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
                assert pid_observateur not in {observations["pid_a"], observations["pid_b"]}
                limite = time.monotonic() + 5
                attente_reelle = False
                while time.monotonic() < limite:
                    bloqueurs = observateur.execute(text("SELECT pg_blocking_pids(:pid)"), {
                        "pid": observations["pid_a"],
                    }).scalar_one()
                    if observations["pid_b"] in bloqueurs:
                        attente_reelle = True
                        break
                    time.sleep(0.02)
                assert attente_reelle, "le vrai UPDATE de A n'a pas attendu B sur PostgreSQL"
                assert "reponse_a" not in observations and "reponse_b" not in observations
            liberer_b.set()
            ecrivain_b.join(12)
            ecrivain_a.join(12)
            assert not ecrivain_a.is_alive() and not ecrivain_b.is_alive()
            assert "exception_a" not in observations and "exception_b" not in observations
            assert observations["panne_controlee"] is True
            assert observations["reponse_b"]["echecs"] == 1
            assert observations["reponse_a"] == {
                "livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 1,
            }
            assert appels == [ecrivain_b.name], "A a appelé M8 malgré l'état frais de B"
        finally:
            liberer_b.set()
            for ecrivain in (ecrivain_b, ecrivain_a):
                if ecrivain.ident is not None:
                    ecrivain.join(12)
            event.remove(moteur, "before_cursor_execute", interposer_b_avant_claim_a)
            stockage.liberer()
            assert not ecrivain_a.is_alive() and not ecrivain_b.is_alive(), "écrivain natif non arrêté"

        try:
            with stockage.transaction() as cnx:
                recu = cnx.execute(select(EVENEMENTS_RECUS)).mappings().one()
                assert recu["statut"] == "echec" and recu["tentatives"] == 1
                assert dt.datetime.fromisoformat(recu["prochaine_tentative"]) == instant + dt.timedelta(seconds=2)
            assert len(stockage.maillons(m8, "snapshots")) == 0
            assert len(stockage.maillons(m8, "faits_chantier")) == 0
            legitime = evenements.repartir(
                departements, limite=1, maintenant=(instant + dt.timedelta(seconds=2)).isoformat(),
            )
            assert legitime["traites"] == legitime["livres"] == 1
            chaine = registre.RegistreSnapshots(stockage.maillons(m8, "snapshots"))
            assert chaine.valider_chaine() == (True, "") and len(chaine.lire()) == 1
            assert len(stockage.maillons(m8, "faits_chantier")) == 1
            with stockage.transaction() as cnx:
                recu = cnx.execute(select(EVENEMENTS_RECUS)).mappings().one()
                assert recu["statut"] == "traite" and recu["tentatives"] == 2
            assert evenements.repartir(
                departements, limite=1, maintenant=(instant + dt.timedelta(seconds=2)).isoformat(),
            )["livres"] == 0
            assert len(stockage.maillons(m8, "snapshots")) == 1
            assert len(stockage.maillons(m8, "faits_chantier")) == 1
        finally:
            stockage.liberer()
