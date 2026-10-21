"""M5 : deux ordres devis/WCT, refus du brouillon périmé et reprise publique.

PostgreSQL 17 réel, données fictives et connexions natives READ COMMITTED.
A utilise le répartiteur public ; B le véritable outil T1 de brouillon ; aucune admission M3/M4 ou finalité financière.
"""

from __future__ import annotations

import importlib.util
import os
import threading
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import outils, registre
from memoire.doubles import postgres_ephemere
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import Autonomie, executer_atomique
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import EVENEMENTS_RECUS

DEPARTEMENT = "m05-financecore"
REGISTRE = "factures"


def _support():
    chemin = (
        Path(__file__).resolve().parents[2]
        / "departments/m05-financecore/tests/test_facture_consommateur_concurrente.py"
    )
    spec = importlib.util.spec_from_file_location("m5_consumer_canonical_support", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _relire():
    return registre.Registre(stockage.maillons(DEPARTEMENT, REGISTRE))


def _recu(ident):
    with stockage.transaction() as cnx:
        return dict(
            cnx.execute(
                select(EVENEMENTS_RECUS).where(
                    (EVENEMENTS_RECUS.c.evenement_id == ident) & (EVENEMENTS_RECUS.c.consommateur == DEPARTEMENT)
                )
            )
            .mappings()
            .one()
        )


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
@pytest.mark.parametrize("devis_premier", [True, False])
def test_brouillon_consommateur_refuse_preserve_pieces_et_rejoue(monkeypatch, devis_premier):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        stockage.migrer()
        outils.utiliser_stockage_durable()
        support = _support()
        dep = charger_departements(Path(__file__).resolve().parents[2] / "departments")[DEPARTEMENT]
        outil = next(o for o in dep.charger_outils() if o.nom == "m5_creer_facture_brouillon")
        assert outil.autonomie == Autonomie.T1
        assert executer_atomique(outil, support._arguments("100.00", "FICTIF-SEED"))["resultat"]["accepte"]
        pieces = [
            ("m3.devis_accepte", "m03-estimation", support.fixtures._devis_accepte()),
            ("m4.travaux_termines", "m04-field-ops", support.fixtures._wct()),
        ]
        if not devis_premier:
            pieces.reverse()
        for i, (typ, producteur, charge) in enumerate(pieces):
            evenements.publier(typ, producteur, charge, evenement_id=f"FICTIF-PIECE-{i}")
            if i == 0:
                assert evenements.repartir({DEPARTEMENT: dep}, maintenant="2026-10-14T12:01:00Z")["traites"] == 1
        avant_traces = list(stockage.maillons(DEPARTEMENT, outils._NOM_REGISTRE_RENTABILITE))
        avant_publications = support._publications_rentabilite()
        ident = "FICTIF-PIECE-1"
        premier_registre = "devis_recus" if devis_premier else "wct_recus"
        second_registre = "wct_recus" if devis_premier else "devis_recus"
        candidat_calcule = threading.Event()
        reprendre = threading.Event()
        observations = {}
        originale = MaillonsDurables.append

        def append_et_pauser(self, maillon, *, rang_attendu=None):
            if (self.departement, self.registre) == (DEPARTEMENT, REGISTRE) and (
                maillon.get("facture_id") == "fac-DEVIS-1"
            ):
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

        def livrer_a():
            try:
                observations["reponse_a"] = evenements.repartir(
                    {DEPARTEMENT: dep},
                    maintenant="2026-10-14T12:01:00Z",
                )
            except BaseException as exc:
                observations["exception_a"] = type(exc).__name__
                candidat_calcule.set()

        ecrivain_a = threading.Thread(target=livrer_a, name="m5-facture-consommateur-a-fictif")
        monkeypatch.setattr(MaillonsDurables, "append", append_et_pauser)
        try:
            ecrivain_a.start()
            assert candidat_calcule.wait(10), "candidat natif A non atteint"
            assert "exception_a" not in observations and observations["rang_a"] == 1
            with stockage.transaction() as cnx_b:
                assert cnx_b.get_isolation_level() == "READ COMMITTED"
                cnx_b.exec_driver_sql("SET LOCAL statement_timeout = '3s'")
                cnx_b.exec_driver_sql("SET LOCAL lock_timeout = '200ms'")
                assert cnx_b.exec_driver_sql("SELECT pg_backend_pid()").scalar_one() != observations["pid_a"]
                reponse_b = executer_atomique(outil, support._arguments("300.00", "FICTIF-B"))
                assert reponse_b["ok"] and reponse_b["resultat"]["accepte"]
            # B a réellement commis avant la libération de A.
            avant_reprise = _relire().lire()
            assert [m["facture_id"] for m in avant_reprise] == ["FICTIF-SEED", "FICTIF-B"]
            assert _relire().valider_chaine() == (True, "")
            reprendre.set()
            ecrivain_a.join(10)
            assert not ecrivain_a.is_alive() and "exception_a" not in observations
            assert observations["reponse_a"]["echecs"] == 1
            assert observations["reponse_a"]["quarantaines"] == 0
            stockage.liberer()
            assert _relire().lire() == avant_reprise and _relire().valider_chaine() == (True, "")
            assert len(stockage.maillons(DEPARTEMENT, premier_registre)) == 1
            assert len(stockage.maillons(DEPARTEMENT, second_registre)) == 0
            assert _recu("FICTIF-PIECE-0")["statut"] == "traite"
            assert list(stockage.maillons(DEPARTEMENT, outils._NOM_REGISTRE_RENTABILITE)) == avant_traces
            assert support._publications_rentabilite() == avant_publications
            for i, (typ, _, charge) in enumerate(pieces):
                assert evenements.charge_publiee(typ, f"FICTIF-PIECE-{i}") == charge
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
            assert maillons[:2] == avant_reprise and len(maillons) == 3
            assert maillons[2]["precedent_ligne_id"] == maillons[1]["ligne_id"]
            assert maillons[2]["facture_id"] == "fac-DEVIS-1"
            assert type(maillons[2]["montant_avant_taxes"]) is Decimal
            assert maillons[2]["montant_avant_taxes"] == Decimal("600.00")
            assert maillons[2]["montant_apres_taxes"] == Decimal("689.85")
            assert _relire().valider_chaine() == (True, "")
            assert len(stockage.maillons(DEPARTEMENT, "devis_recus")) == 1
            assert len(stockage.maillons(DEPARTEMENT, "wct_recus")) == 1
            traces = list(stockage.maillons(DEPARTEMENT, outils._NOM_REGISTRE_RENTABILITE))
            assert len(traces) == 1 and traces[0]["verdict"] == "PARTIELLE"
            assert traces[0]["rentabilite"]["cout_reel"]["complet"] is False
            publications = support._publications_rentabilite()
            assert len(publications) == 1
            assert _recu(ident)["statut"] == "traite" and _recu(ident)["tentatives"] == 2
            assert evenements.repartir({DEPARTEMENT: dep}, maintenant="2026-10-14T12:01:04Z")["livres"] == 0
            assert list(stockage.maillons(DEPARTEMENT, outils._NOM_REGISTRE_RENTABILITE)) == traces
            assert support._publications_rentabilite() == publications
        finally:
            reprendre.set()
            if ecrivain_a.ident is not None:
                ecrivain_a.join(10)
            assert not ecrivain_a.is_alive(), "écrivain fictif non arrêté"
            monkeypatch.setattr(MaillonsDurables, "append", originale)
            stockage.liberer()
