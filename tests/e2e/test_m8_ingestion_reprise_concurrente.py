"""M8 : reprise publique après un candidat périmé par un commit B indépendant.

PostgreSQL 17 réel, données fictives et connexions natives READ COMMITTED.
A utilise le répartiteur public ; B le véritable outil de rapport M8.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest
from m8_analytics import outils, registre
from memoire.doubles import postgres_ephemere
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import EVENEMENTS_RECUS

DEPARTEMENT = "m08-analytics"
REGISTRE = "snapshots"


def _arguments(valeur):
    return {
        "dictionnaire": {"source-declaree-fictive": {"mesure-fictive": {}}},
        "snapshot": {"module_source": "source-declaree-fictive", "horodatage": "2026-10-14T12:00:00Z",
                     "valeurs": {"mesure-fictive": valeur}},
        "metric_ids": [], "horodatage_reference": "2026-10-14T12:00:00Z", "n_minimal": 1,
    }


def _wct():
    return {
        "wct_id": "wct-ingestion-fictif", "intervention_id": "intervention-fictive",
        "lead_id": "lead-fictif", "technicien_id": "technicien-fictif",
        "horodatage_completion": "2026-10-14T12:00:00Z", "fix_gps_completion": {},
        "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None,
        "hash_maillon": "a" * 64, "consommateurs_cibles": ["M8"],
        "devis_id": None, "statut": "completed_verified",
    }


def _relire():
    return registre.RegistreSnapshots(stockage.maillons(DEPARTEMENT, REGISTRE))


def _recu(ident):
    with stockage.transaction() as cnx:
        return dict(cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == ident) &
            (EVENEMENTS_RECUS.c.consommateur == DEPARTEMENT)
        )).mappings().one())


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
def test_consommateur_refuse_rang_perime_preserve_b_et_rejoue_entree(monkeypatch):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        stockage.migrer()
        outil = next(o for o in outils.outils() if o.nom == "m8_rapport_metriques")
        assert executer_atomique(outil, _arguments("100.00"))["ok"]
        charge = _wct()
        ident = charge["wct_id"]
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id=ident)
        dep = charger_departements(Path(__file__).resolve().parents[2] / "departments")[DEPARTEMENT]
        candidat_calcule = threading.Event()
        reprendre = threading.Event()
        observations = {}
        originale = MaillonsDurables.append

        def append_et_pauser(self, maillon, *, rang_attendu=None):
            if (self.departement, self.registre) == (DEPARTEMENT, REGISTRE) and (
                maillon["valeurs"].get("m4_wct_id") == ident
            ):
                assert threading.current_thread() is ecrivain_a
                cnx = stockage.connexion_courante()
                assert cnx is not None and cnx.get_isolation_level() == "READ COMMITTED"
                cnx.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
                cnx.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
                observations["pid_a"] = cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
                observations["index_a"] = maillon["index"]
                candidat_calcule.set()
                assert reprendre.wait(10), "coordination fictive non libérée"
                assert stockage.connexion_courante() is cnx
            return originale(self, maillon, rang_attendu=rang_attendu)

        def livrer_a():
            try:
                observations["reponse_a"] = evenements.repartir(
                    {DEPARTEMENT: dep}, maintenant="2026-10-14T12:01:00Z",
                )
            except BaseException as exc:
                observations["exception_a"] = type(exc).__name__
                candidat_calcule.set()

        ecrivain_a = threading.Thread(target=livrer_a, name="m8-consommateur-a-fictif")
        monkeypatch.setattr(MaillonsDurables, "append", append_et_pauser)
        try:
            ecrivain_a.start()
            assert candidat_calcule.wait(10), "candidat natif A non atteint"
            assert "exception_a" not in observations and observations["index_a"] == 1
            with stockage.transaction() as cnx_b:
                assert cnx_b.get_isolation_level() == "READ COMMITTED"
                cnx_b.exec_driver_sql("SET LOCAL statement_timeout = '3s'")
                cnx_b.exec_driver_sql("SET LOCAL lock_timeout = '200ms'")
                assert cnx_b.exec_driver_sql("SELECT pg_backend_pid()").scalar_one() != observations["pid_a"]
                reponse_b = executer_atomique(outil, _arguments("300.00"))
                assert reponse_b["ok"] and reponse_b["resultat"]["accepte"]
            # B a réellement commis avant la libération de A.
            avant_reprise = _relire().lire()
            assert [m["valeurs"]["mesure-fictive"] for m in avant_reprise] == ["100.00", "300.00"]
            assert _relire().valider_chaine() == (True, "")
            reprendre.set()
            ecrivain_a.join(10)
            assert not ecrivain_a.is_alive() and "exception_a" not in observations
            assert observations["reponse_a"]["echecs"] == 1
            assert observations["reponse_a"]["quarantaines"] == 0
            stockage.liberer()
            assert _relire().lire() == avant_reprise and _relire().valider_chaine() == (True, "")
            assert len(stockage.maillons(DEPARTEMENT, "faits_chantier")) == 0
            assert evenements.charge_publiee("m4.travaux_termines", ident) == charge
            recu = _recu(ident)
            assert recu["statut"] == "echec" and recu["tentatives"] == 1
            assert recu["prochaine_tentative"] == "2026-10-14T12:01:02+00:00"
            assert recu["derniere_erreur"].startswith("EcritureConcurrente:")
            monkeypatch.setattr(MaillonsDurables, "append", originale)
            assert evenements.repartir({DEPARTEMENT: dep}, maintenant="2026-10-14T12:01:01Z")["livres"] == 0
            reprise = evenements.repartir({DEPARTEMENT: dep}, maintenant="2026-10-14T12:01:03Z")
            assert reprise["traites"] == 1 and reprise["echecs"] == 0
            stockage.liberer()
            maillons = _relire().lire()
            assert maillons[:2] == avant_reprise and [m["index"] for m in maillons] == [0, 1, 2]
            assert maillons[2]["valeurs"]["m4_wct_id"] == ident
            assert _relire().valider_chaine() == (True, "")
            assert len(stockage.maillons(DEPARTEMENT, "faits_chantier")) == 1
            assert _recu(ident)["statut"] == "traite" and _recu(ident)["tentatives"] == 2
            assert evenements.repartir({DEPARTEMENT: dep}, maintenant="2026-10-14T12:01:04Z")["livres"] == 0
        finally:
            reprendre.set()
            if ecrivain_a.ident is not None:
                ecrivain_a.join(10)
            assert not ecrivain_a.is_alive(), "écrivain fictif non arrêté"
            monkeypatch.setattr(MaillonsDurables, "append", originale)
            stockage.liberer()
