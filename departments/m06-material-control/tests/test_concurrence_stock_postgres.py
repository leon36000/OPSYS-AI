"""Régression PostgreSQL READ COMMITTED des mises à jour de stock M6.

Le conteneur PostgreSQL est jetable; seules des quantités et identifiants fictifs sont utilisés.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import m6_material_control.outils as m6_outils
import pytest
from m6_material_control import reservations as reservations_module
from m6_material_control import stock as stock_module

from opsys import stockage
from opsys.outils import executer_atomique

_RACINE = Path(__file__).resolve().parents[3]
_DOUBLES = _RACINE / "tests" / "fixtures" / "memoire" / "doubles.py"
_SPEC = importlib.util.spec_from_file_location("doubles_postgres_m6_stock", _DOUBLES)
_DOUBLES_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _DOUBLES_MOD
_SPEC.loader.exec_module(_DOUBLES_MOD)


def test_postgres_ajustement_lot_et_individuel_serialisent_avant_lecture(monkeypatch):
    raison = _DOUBLES_MOD.raison_sans_docker()
    if raison is not None:
        pytest.skip(f"PostgreSQL éphémère indisponible : {raison}")

    with _DOUBLES_MOD.postgres_ephemere() as url_brut:
        url = url_brut.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        stockage.migrer(url)
        try:
            spec = importlib.util.spec_from_file_location(
                "aide_reservation_postgres_m6_stock",
                _RACINE / "departments" / "m06-material-control" / "tests" / "test_reservation_outils.py",
            )
            aide = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(aide)
            outils = {outil.nom: outil for outil in m6_outils.outils()}
            aide._recevoir(outils, aide.GOUTTIERE, 10.0, "PO-PG-COURSE-STOCK-FICTIF")
            monkeypatch.setattr(m6_outils, "_seuil_ajustement_stock", lambda: Decimal("100"))

            a_lu = threading.Event()
            b_a_commence = threading.Event()
            b_a_lu = threading.Event()
            liberer_a = threading.Event()
            appels_verrou = {
                "ajustement-suivant": threading.Event(),
                "reception-suivante": threading.Event(),
            }
            verrou_original = m6_outils._verrouiller_stock_durable

            def observer_verrou():
                evenement = appels_verrou.get(threading.current_thread().name)
                if evenement is not None:
                    evenement.set()
                verrou_original()

            monkeypatch.setattr(m6_outils, "_verrouiller_stock_durable", observer_verrou)
            original = stock_module.deriver_stock_articles

            def deriver_synchronise(*args, **kwargs):
                resultat = original(*args, **kwargs)
                nom = threading.current_thread().name
                if nom == "ajustement-retarde":
                    a_lu.set()
                    if not liberer_a.wait(timeout=20):
                        raise TimeoutError("l'ajustement A attendait encore")
                elif nom == "ajustement-suivant":
                    b_a_lu.set()
                return resultat

            monkeypatch.setattr(stock_module, "deriver_stock_articles", deriver_synchronise)

            ligne_lot = {
                "ajustement_id": "AJUST-PG-LOT-FICTIF",
                "materiau_id": aide.GOUTTIERE,
                "motif": "inventaire_physique",
                "quantite_apres": 8,
                "horodatage": "2026-11-04T12:00:00-05:00",
            }
            ligne_individuelle = {
                "ajustement_id": "AJUST-PG-INDIVIDUEL-FICTIF",
                "materiau_id": aide.GOUTTIERE,
                "motif": "correction",
                "quantite_apres": 7,
                "horodatage": "2026-11-04T12:00:01-05:00",
            }

            def appel_lot():
                threading.current_thread().name = "ajustement-retarde"
                return executer_atomique(outils["m6_clore_inventaire_physique"], {"ajustements": [ligne_lot]})

            def appel_individuel():
                threading.current_thread().name = "ajustement-suivant"
                b_a_commence.set()
                return executer_atomique(outils["m6_ajuster_stock"], {"ajustement": ligne_individuelle})

            with ThreadPoolExecutor(max_workers=2) as pool:
                futur_a = pool.submit(appel_lot)
                assert a_lu.wait(timeout=20), "A n'a pas atteint son snapshot de stock"
                futur_b = pool.submit(appel_individuel)
                assert b_a_commence.wait(timeout=5)
                assert appels_verrou["ajustement-suivant"].wait(timeout=5), "B n'a pas demandé le verrou commun"
                b_a_lu_avant_liberation = b_a_lu.wait(timeout=0.5)
                liberer_a.set()
                reponse_a = futur_a.result(timeout=30)
                reponse_b = futur_b.result(timeout=30)

            monkeypatch.setattr(stock_module, "deriver_stock_articles", original)
            audit_a = reponse_a["resultat"]["ajustements"][0]["ajustement"]
            audit_b = reponse_b["resultat"]["ajustement"]
            assert b_a_lu_avant_liberation is False, "B a lu le stock pendant que A détenait le verrou"
            assert (audit_a["quantite_avant"], audit_a["quantite_apres"]) == ("10", "8")
            assert (audit_b["quantite_avant"], audit_b["quantite_apres"]) == ("8", "7")
            with stockage.transaction():
                disponibilite = m6_outils.lire_disponibilite([aide.GOUTTIERE])
                mouvements = list(stockage.maillons("m06-material-control", "principal"))
            assert disponibilite["resultat"]["articles"][0]["stock_theorique"] == "7"
            assert [m["ajustement"]["quantite_avant"] for m in mouvements if "ajustement" in m] == ["10", "8"]

            # La réception est additive, mais elle partage le même verrou : sinon elle pourrait
            # s'intercaler après le snapshot d'un ajustement et invalider l'ordre métier du comptage.
            materiau_reception = "MAT-PG-RECEPTION-FICTIF"
            aide._recevoir(outils, materiau_reception, 10.0, "PO-PG-RECEPTION-BASE-FICTIF")
            appels_verrou["reception-suivante"].clear()
            monkeypatch.setattr(stock_module, "deriver_stock_articles", deriver_synchronise)
            a_lu.clear()
            liberer_a.clear()
            b_a_commence.clear()
            reception_terminee = threading.Event()

            def appel_ajustement_reception():
                threading.current_thread().name = "ajustement-retarde"
                return executer_atomique(outils["m6_ajuster_stock"], {"ajustement": {
                    "ajustement_id": "AJUST-PG-AVANT-RECEPTION-FICTIF",
                    "materiau_id": materiau_reception,
                    "motif": "correction",
                    "quantite_apres": 8,
                    "horodatage": "2026-11-04T12:01:00-05:00",
                }})

            def appel_reception():
                threading.current_thread().name = "reception-suivante"
                b_a_commence.set()
                resultat = aide._recevoir(outils, materiau_reception, 5.0, "PO-PG-RECEPTION-SUIVANTE-FICTIF")
                reception_terminee.set()
                return resultat

            with ThreadPoolExecutor(max_workers=2) as pool:
                futur_ajustement = pool.submit(appel_ajustement_reception)
                assert a_lu.wait(timeout=20), "l'ajustement n'a pas atteint son snapshot de stock"
                futur_reception = pool.submit(appel_reception)
                assert b_a_commence.wait(timeout=5)
                assert appels_verrou["reception-suivante"].wait(timeout=5), (
                    "la réception n'a pas demandé le verrou commun"
                )
                reception_terminee_while_locked = reception_terminee.wait(timeout=0.5)
                liberer_a.set()
                resultat_ajustement = futur_ajustement.result(timeout=30)
                resultat_reception = futur_reception.result(timeout=30)
            monkeypatch.setattr(stock_module, "deriver_stock_articles", original)
            assert resultat_ajustement["resultat"]["accepte"] is True
            assert resultat_reception["accepte"] is True
            assert reception_terminee_while_locked is False, "la réception s'est intercalée avant le commit du comptage"
            with stockage.transaction():
                disponibilite_reception = m6_outils.lire_disponibilite([materiau_reception])
            assert disponibilite_reception["resultat"]["articles"][0]["stock_theorique"] == "13"

            # Une exception de refus tardif annule aussi le verrou transactionnel; l'appel suivant
            # peut reprendre le verrou et voit toujours l'état d'avant le lot.
            materiau_rollback = "MAT-PG-ROLLBACK-FICTIF"
            aide._recevoir(outils, materiau_rollback, 10.0, "PO-PG-ROLLBACK-BASE-FICTIF")
            monkeypatch.setattr(m6_outils, "_seuil_ajustement_stock", lambda: Decimal("1"))
            reponse_refus = executer_atomique(outils["m6_clore_inventaire_physique"], {"ajustements": [
                    {"ajustement_id": "AJUST-PG-ROLLBACK-1", "materiau_id": materiau_rollback,
                     "motif": "inventaire_physique", "quantite_apres": 9.5,
                     "horodatage": "2026-11-04T12:02:00-05:00"},
                    {"ajustement_id": "AJUST-PG-ROLLBACK-2", "materiau_id": "MAT-PG-2-FICTIF",
                     "motif": "inventaire_physique", "quantite_apres": 5,
                     "horodatage": "2026-11-04T12:02:01-05:00"},
                ]})
            assert reponse_refus["ok"] is False, reponse_refus
            with stockage.transaction():
                apres_refus = m6_outils.lire_disponibilite([materiau_rollback])
            assert apres_refus["resultat"]["articles"][0]["stock_theorique"] == "10"
            monkeypatch.setattr(m6_outils, "_seuil_ajustement_stock", lambda: Decimal("100"))
            reprise = executer_atomique(outils["m6_ajuster_stock"], {"ajustement": {
                "ajustement_id": "AJUST-PG-APRES-ROLLBACK", "materiau_id": materiau_rollback,
                "motif": "correction", "quantite_apres": 9,
                "horodatage": "2026-11-04T12:03:00-05:00",
            }})
            assert reprise["ok"] is True and reprise["resultat"]["accepte"] is True
        finally:
            stockage.liberer(url)


def test_postgres_reservation_et_ajustement_preservent_reserve_inferieur_ou_egal_en_main(monkeypatch):
    raison = _DOUBLES_MOD.raison_sans_docker()
    if raison is not None:
        pytest.skip(f"PostgreSQL éphémère indisponible : {raison}")

    with _DOUBLES_MOD.postgres_ephemere() as url_brut:
        url = url_brut.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        stockage.migrer(url)
        try:
            spec = importlib.util.spec_from_file_location(
                "aide_reservation_ajustement_postgres_m6",
                _RACINE / "departments" / "m06-material-control" / "tests" / "test_reservation_outils.py",
            )
            aide = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(aide)
            outils = {outil.nom: outil for outil in m6_outils.outils()}
            materiau = aide.GOUTTIERE
            aide._recevoir(outils, materiau, 10.0, "PO-PG-RESERVATION-BASE-FICTIF")
            aide._outil(outils, "m6_enregistrer_besoins_prevus", {
                "chantier_id": "CH-PG-RESERVATION-FICTIF",
                "devis_id": "DEVIS-PG-RESERVATION-FICTIF",
                "lignes": [{"materiau_id": materiau, "quantite_estimee": 10.0, "unite": "pi"}],
            })
            monkeypatch.setattr(m6_outils, "_seuil_ajustement_stock", lambda: Decimal("100"))

            reservation_a_lu_stock = threading.Event()
            finir_reservation = threading.Event()
            ajustement_demande_verrou = threading.Event()
            ajustement_termine = threading.Event()
            reserver_original = reservations_module.reserver
            verrou_original = m6_outils._verrouiller_stock_durable

            def reserver_barriere(*args, **kwargs):
                if threading.current_thread().name == "reservation-retardee":
                    # _reserver_pour_devis a déjà lu en_main et les faits actifs avant cet appel.
                    reservation_a_lu_stock.set()
                    if not finir_reservation.wait(timeout=20):
                        raise TimeoutError("la réservation fictive attendait encore")
                return reserver_original(*args, **kwargs)

            def observer_verrou():
                if threading.current_thread().name == "ajustement-apres-reservation":
                    ajustement_demande_verrou.set()
                verrou_original()

            monkeypatch.setattr(reservations_module, "reserver", reserver_barriere)
            monkeypatch.setattr(m6_outils, "_verrouiller_stock_durable", observer_verrou)

            def reserver():
                threading.current_thread().name = "reservation-retardee"
                return executer_atomique(outils["m6_reserver_materiel"], {
                    "devis_id": "DEVIS-PG-RESERVATION-FICTIF",
                    "horodatage": "2026-11-04T12:10:00-05:00",
                })

            def ajuster():
                threading.current_thread().name = "ajustement-apres-reservation"
                resultat = executer_atomique(outils["m6_ajuster_stock"], {"ajustement": {
                    "ajustement_id": "AJUST-PG-RESERVATION-FICTIF",
                    "materiau_id": materiau,
                    "motif": "correction",
                    "quantite_apres": 8,
                    "horodatage": "2026-11-04T12:10:01-05:00",
                }})
                ajustement_termine.set()
                return resultat

            with ThreadPoolExecutor(max_workers=2) as pool:
                futur_reservation = pool.submit(reserver)
                assert reservation_a_lu_stock.wait(timeout=20), "la réservation n'a pas lu le stock"
                futur_ajustement = pool.submit(ajuster)
                assert ajustement_demande_verrou.wait(timeout=5), "l'ajustement n'a pas demandé le verrou commun"
                termine_avant_commit_reservation = ajustement_termine.wait(timeout=0.5)
                finir_reservation.set()
                reponse_reservation = futur_reservation.result(timeout=30)
                reponse_ajustement = futur_ajustement.result(timeout=30)

            assert termine_avant_commit_reservation is False
            assert reponse_reservation["ok"] is True and reponse_reservation["resultat"]["accepte"] is True
            assert reponse_ajustement["ok"] is True and reponse_ajustement["resultat"]["accepte"] is True
            with stockage.transaction():
                dispo = m6_outils.lire_disponibilite([materiau])["resultat"]["articles"][0]
                faits_reservation = list(stockage.maillons("m06-material-control", "reservations"))
            assert (dispo["en_main"], dispo["reserve"], dispo["disponible"]) == ("8", "8", "0")
            etat = reservations_module.etat("DEVIS-PG-RESERVATION-FICTIF", faits_reservation)
            assert etat["actif"] is True
            assert etat["lignes"][0]["quantite_reservee"] == "8"
        finally:
            stockage.liberer(url)
