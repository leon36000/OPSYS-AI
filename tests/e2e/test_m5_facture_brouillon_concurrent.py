"""M5 : B commis indépendamment rend A périmé ; journal conservé et reprise.

PG17 réel, écritures fictives. Métadonnée T1 conservée ; admission humaine,
paiement et finalité financière ne sont pas qualifiés par ce composant.
"""

from __future__ import annotations

import os
import threading
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import outils, registre
from memoire.doubles import postgres_ephemere

from opsys import stockage
from opsys.departements import charger_departements
from opsys.outils import Autonomie, executer_atomique
from opsys.stockage.maillons import EcritureConcurrente, MaillonsDurables

D = "m05-financecore"
R = "factures"


def _arguments(montant, source):
    return {
        "facture_id": source,
        "chantier_id": "FICTIF-CHANT-" + source,
        "devis_id": "FICTIF-DEVIS-" + source,
        "client_id": "FICTIF-CLIENT",
        "lignes": [
            {
                "description": "FICTIF",
                "quantite": "1",
                "unite": "forfait",
                "prix_unitaire": montant,
                "reference_ligne_devis": "FICTIF-L1",
            }
        ],
        "horodatage": "2026-08-03T12:00:00+00:00",
    }


def _relire():
    return registre.Registre(stockage.maillons(D, R))


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
def test_brouillon_perime_refuse_preserve_b_et_permet_reprise(monkeypatch):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        stockage.migrer()
        outils.utiliser_stockage_durable()
        dep = charger_departements(Path(__file__).resolve().parents[2] / "departments")[D]
        outil = next(o for o in dep.charger_outils() if o.nom == "m5_creer_facture_brouillon")
        assert outil.autonomie == Autonomie.T1
        assert executer_atomique(outil, _arguments("100.00", "FICTIF-SEED"))["ok"]
        candidat_calcule = threading.Event()
        reprendre = threading.Event()
        observations = {}
        originale = MaillonsDurables.append

        def pauser(self, maillon, *, rang_attendu=None):
            if (self.departement, self.registre) == (D, R) and maillon.get("facture_id") == "FICTIF-A":
                assert threading.current_thread() is ecrivain_a
                cnx = stockage.connexion_courante()
                assert cnx is not None and cnx.get_isolation_level() == "READ COMMITTED"
                cnx.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
                cnx.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
                observations["pid_a"] = cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
                observations["rang_a"] = rang_attendu
                candidat_calcule.set()
                assert reprendre.wait(10), "coordination fictive non libérée"
                assert stockage.connexion_courante() is cnx
            return originale(self, maillon, rang_attendu=rang_attendu)

        def ajouter_a():
            try:
                observations["reponse_a"] = executer_atomique(outil, _arguments("200.00", "FICTIF-A"))
            except EcritureConcurrente:
                observations["concurrence_a"] = True
            except BaseException as exc:
                observations["exception_a"] = type(exc).__name__
                candidat_calcule.set()

        ecrivain_a = threading.Thread(target=ajouter_a, name="m5-brouillon-a-fictif")
        monkeypatch.setattr(MaillonsDurables, "append", pauser)
        try:
            ecrivain_a.start()
            assert candidat_calcule.wait(10), "candidat natif A non atteint"
            assert "exception_a" not in observations and observations["rang_a"] == 1
            with stockage.transaction() as cnx_b:
                assert cnx_b.get_isolation_level() == "READ COMMITTED"
                cnx_b.exec_driver_sql("SET LOCAL statement_timeout = '3s'")
                cnx_b.exec_driver_sql("SET LOCAL lock_timeout = '200ms'")
                assert cnx_b.exec_driver_sql("SELECT pg_backend_pid()").scalar_one() != observations["pid_a"]
                b = executer_atomique(outil, _arguments("300.00", "FICTIF-B"))
                assert b["ok"] and b["resultat"]["accepte"]
            avant_reprise = _relire().lire()
            assert [m["facture_id"] for m in avant_reprise] == ["FICTIF-SEED", "FICTIF-B"]
            assert _relire().valider_chaine() == (True, "")
            reprendre.set()
            ecrivain_a.join(10)
            assert not ecrivain_a.is_alive() and "exception_a" not in observations
            assert observations.get("concurrence_a") is True and "reponse_a" not in observations
            stockage.liberer()
            assert _relire().lire() == avant_reprise and _relire().valider_chaine() == (True, "")
            monkeypatch.setattr(MaillonsDurables, "append", originale)
            a = executer_atomique(outil, _arguments("200.00", "FICTIF-A"))
            assert a["ok"] and a["resultat"]["accepte"]
            stockage.liberer()
            lignes = _relire().lire()
            assert lignes[:2] == avant_reprise and lignes[2]["precedent_ligne_id"] == lignes[1]["ligne_id"]
            assert [m["montant_avant_taxes"] for m in lignes] == [
                Decimal("100.00"),
                Decimal("300.00"),
                Decimal("200.00"),
            ]
            assert _relire().valider_chaine() == (True, "")
            replay = executer_atomique(outil, _arguments("200.00", "FICTIF-A"))
            assert replay["ok"] and replay["resultat"]["accepte"]
            stockage.liberer()
            assert _relire().lire() == lignes
        finally:
            reprendre.set()
            if ecrivain_a.ident is not None:
                ecrivain_a.join(10)
            assert not ecrivain_a.is_alive(), "écrivain fictif non arrêté"
            monkeypatch.setattr(MaillonsDurables, "append", originale)
            stockage.liberer()
