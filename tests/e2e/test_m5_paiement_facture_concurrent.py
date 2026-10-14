"""Paiement constaté N5 approuvé fictif : B indépendant commité, A refusé, nouvelle décision requise.

Aucun envoi externe ni paiement réel. PostgreSQL 17 READ COMMITTED uniquement.
"""

import os
import threading
from pathlib import Path

import pytest
from m5_financecore import facturation, outils, registre
from memoire.doubles import postgres_ephemere

from opsys import approbations, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.maillons import MaillonsDurables

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


def _demander(dep):
    r = Capacites({D: dep}, stockage.transaction).appeler(
        "m5_enregistrer_paiement_facture",
        {"facture_id": "FICTIF-A", "horodatage": "2026-08-03T12:00:00+00:00",
         "montant_paye": format(facturation._etat_facture(_relire(), "FICTIF-A")["montant_apres_taxes"], "f"),
         "approbateur": "Propriétaire fictif"},
    )
    assert r["statut"] == "en_attente_approbation"
    return r["demande_id"]


def _decider(dep, demande):
    disponibles = outils_executables({D: dep}, stockage.transaction)
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx, demande, True, "nathan-fictif", disponibles, {D: dep},
            attestation={"nom": "CPA fictif", "profession": "CPA", "reference_document": "FICTIF-DEPOT"},
        )


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
def test_paiement_approuve_refuse_a_preserve_b_exige_nouvelle_decision(monkeypatch):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        stockage.migrer()
        outils.utiliser_stockage_durable()
        dep = charger_departements(Path(__file__).resolve().parents[2] / "departments")[D]
        creer = next(o for o in dep.charger_outils() if o.nom == "m5_creer_facture_brouillon")
        assert executer_atomique(creer, _arguments("100.00", "FICTIF-A"))["resultat"]["accepte"]
        with stockage.transaction() as cnx:
            identite.creer_personne(
                cnx, "finance-fictif", "Finance fictive", "mot-de-passe-fixture-fictif", ["finance"]
            )
        with stockage.transaction() as cnx:
            identite.creer_personne(
                cnx, "nathan-fictif", "Propriétaire fictif", "mot-de-passe-fixture-fictif", ["nathan_owner"]
            )
        envoi = Capacites({D: dep}, stockage.transaction).appeler(
            "m5_envoyer_facture", {"facture_id": "FICTIF-A", "horodatage": "2026-08-03T12:00:00+00:00"}
        )
        assert envoi["statut"] == "en_attente_approbation"
        with stockage.transaction() as cnx:
            decision_envoi = approbations.decider(
                cnx, envoi["demande_id"], True, "finance-fictif",
                outils_executables({D: dep}, stockage.transaction), {D: dep},
            )
        assert decision_envoi["statut"] == "executee"
        assert facturation._etat_facture(_relire(), "FICTIF-A")["statut"] == "ENVOYEE"
        demande = _demander(dep)
        avant_mouvements = list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS))
        calcule = threading.Event()
        reprendre = threading.Event()
        observations = {}
        original = MaillonsDurables.append

        def pauser(self, maillon, *, rang_attendu=None):
            if (self.departement, self.registre) == (D, R) and maillon.get("statut") == "PAYEE":
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

        def approuver_a():
            try:
                observations["decision"] = _decider(dep, demande)
            except BaseException as exc:
                observations["exception"] = type(exc).__name__
                calcule.set()

        a = threading.Thread(target=approuver_a, name="m5-paiement-n5-a-fictif")
        monkeypatch.setattr(MaillonsDurables, "append", pauser)
        try:
            a.start()
            assert calcule.wait(10) and "exception" not in observations
            assert observations["rang_a"] == 2
            with stockage.transaction() as cnx:
                assert cnx.get_isolation_level() == "READ COMMITTED"
                cnx.exec_driver_sql("SET LOCAL statement_timeout = '3s'")
                cnx.exec_driver_sql("SET LOCAL lock_timeout = '200ms'")
                assert cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one() != observations["pid_a"]
                b = executer_atomique(creer, _arguments("300.00", "FICTIF-B"))
                assert b["resultat"]["accepte"]
            avant = _relire().lire()
            assert [m["facture_id"] for m in avant] == ["FICTIF-A", "FICTIF-A", "FICTIF-B"]
            assert _relire().valider_chaine() == (True, "")
            reprendre.set()
            a.join(10)
            assert not a.is_alive() and "exception" not in observations
            decision = observations["decision"]
            assert decision["statut"] == "echec" and decision["reponse"]["erreur"] == "panne_execution"
            assert decision["reponse"]["details"].startswith("EcritureConcurrente:")
            stockage.liberer()
            assert _relire().lire() == avant and _relire().valider_chaine() == (True, "")
            assert facturation._etat_facture(_relire(), "FICTIF-A")["statut"] == "ENVOYEE"
            assert list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS)) == avant_mouvements
            with stockage.transaction() as cnx:
                assert approbations.lire(cnx, demande)["statut"] == "echec"
            with pytest.raises(ValueError, match="déjà"):
                _decider(dep, demande)
            assert _relire().lire() == avant
            monkeypatch.setattr(MaillonsDurables, "append", original)
            suivante = _demander(dep)
            assert suivante != demande and _decider(dep, suivante)["statut"] == "executee"
            stockage.liberer()
            apres = _relire().lire()
            assert apres[:3] == avant and len(apres) == 4
            assert apres[3]["precedent_ligne_id"] == avant[2]["ligne_id"]
            assert _relire().valider_chaine() == (True, "")
            assert facturation._etat_facture(_relire(), "FICTIF-A")["statut"] == "PAYEE"
            assert list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS)) == avant_mouvements
            with pytest.raises(ValueError, match="déjà"):
                _decider(dep, suivante)
            assert _relire().lire() == apres
        finally:
            reprendre.set()
            if a.ident is not None:
                a.join(10)
            assert not a.is_alive(), "écrivain fictif non arrêté"
            monkeypatch.setattr(MaillonsDurables, "append", original)
            stockage.liberer()
