"""M9 : B commis entre calcul et append A, avec les propriétaires natifs.

PostgreSQL 17 éphémère et valeurs fictives, dans le job canonique explicite.
L'isolation READ COMMITTED est vérifiée, jamais modifiée pour obtenir le résultat.
"""
from __future__ import annotations

import os
import threading

import pytest
from m9_strategic_intelligence import outils, registre
from memoire.doubles import postgres_ephemere

from opsys import stockage
from opsys.outils import executer_atomique
from opsys.stockage.maillons import EcritureConcurrente, MaillonsDurables

DEPARTEMENT = "m09-strategic-intelligence"
REGISTRE = "snapshots"


def _snapshot(valeur, source="source-declaree-fictive"):
    return {
        "module_source": source,
        "horodatage": "2026-01-04T12:00:00Z",
        "valeurs": {"prevision": valeur},
    }


def _relire():
    return registre.RegistreSnapshots(stockage.maillons(DEPARTEMENT, REGISTRE))


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
def test_append_intercale_commis_refuse_a_preserve_b_et_permet_reprise(monkeypatch):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        stockage.migrer()
        outil = next(o for o in outils.outils() if o.nom == "m9_etat_consolide")
        assert executer_atomique(outil, {"snapshot": _snapshot("100.00")})["ok"]
        candidat_calcule = threading.Event()
        reprendre = threading.Event()
        observations = {}
        originale = MaillonsDurables.append

        def append_et_pauser(self, maillon, *, rang_attendu=None):
            if (self.departement, self.registre) == (DEPARTEMENT, REGISTRE) and (
                maillon["valeurs"]["prevision"] == "200.00"
            ):
                assert threading.current_thread() is ecrivain_a
                connexion = stockage.connexion_courante()
                assert connexion is not None
                assert connexion.get_isolation_level() == "READ COMMITTED", "précondition d'isolation non qualifiée"
                observations["connexion_a"] = connexion
                candidat_calcule.set()
                assert reprendre.wait(10), "coordination fictive non libérée"
                assert stockage.connexion_courante() is connexion
            return originale(self, maillon, rang_attendu=rang_attendu)

        def ajouter_a():
            try:
                observations["reponse_a"] = executer_atomique(outil, {"snapshot": _snapshot("200.00")})
            except EcritureConcurrente:
                observations["concurrence_a"] = True
            except BaseException as exc:
                observations["exception_inattendue"] = type(exc).__name__

        ecrivain_a = threading.Thread(target=ajouter_a, name="m9-append-a-fictif")
        monkeypatch.setattr(MaillonsDurables, "append", append_et_pauser)
        try:
            ecrivain_a.start()
            assert candidat_calcule.wait(10), "append natif A non atteint"
            # B conserve sa connexion native propre, puis COMMIT avant de reprendre A.
            with stockage.transaction() as connexion_b:
                assert connexion_b is not observations["connexion_a"]
                connexion_b.exec_driver_sql("SET LOCAL statement_timeout = '3s'")
                connexion_b.exec_driver_sql("SET LOCAL lock_timeout = '200ms'")
                reponse_b = executer_atomique(outil, {"snapshot": _snapshot("300.00", "autre-source-fictive")})
                assert reponse_b["ok"] and reponse_b["resultat"]["accepte"]
            avant_reprise_a = _relire().lire()
            assert [m["valeurs"]["prevision"] for m in avant_reprise_a] == ["100.00", "300.00"]
            assert _relire().valider_chaine() == (True, "")
            reprendre.set()
            ecrivain_a.join(10)
            assert not ecrivain_a.is_alive()
            assert "exception_inattendue" not in observations
            assert observations.get("concurrence_a") is True, "A a accepté un candidat calculé avant le commit B"
            assert "reponse_a" not in observations
            assert _relire().lire() == avant_reprise_a  # A annulé, B commis reste intact
            assert _relire().valider_chaine() == (True, "")

            monkeypatch.setattr(MaillonsDurables, "append", originale)
            reprise_a = executer_atomique(outil, {"snapshot": _snapshot("200.00")})
            assert reprise_a["ok"] and reprise_a["resultat"]["accepte"]
            maillons = _relire().lire()
            assert [m["index"] for m in maillons] == [0, 1, 2]
            assert [m["valeurs"]["prevision"] for m in maillons] == ["100.00", "300.00", "200.00"]
            assert _relire().valider_chaine() == (True, "")
        finally:
            reprendre.set()
            if ecrivain_a.ident is not None:
                ecrivain_a.join(10)
            monkeypatch.setattr(MaillonsDurables, "append", originale)
            stockage.liberer()
