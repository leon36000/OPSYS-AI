"""AP annulation N4 fictive, B N3 approuvé et commité indépendamment ; A périmé refusé.

Catégories de test déclarées : aucun fournisseur ni paiement réel.
"""

import importlib.util
import os
import threading
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import comptes_a_payer, outils, registre
from memoire.doubles import postgres_ephemere

from opsys import approbations, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.stockage.maillons import MaillonsDurables

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "canon_ap_pg", ROOT / "departments/m05-financecore/tests/test_comptes_a_payer_outils.py"
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
D = fixtures.DEPARTEMENT


def journal():
    return registre.Registre(stockage.maillons(D, outils._NOM_REGISTRE_COMPTES_A_PAYER))


def demander(dep, numero, montant):
    r = Capacites({D: dep}, stockage.transaction).appeler(
        "m5_saisir_facture_sans_po",
        {
            "fournisseur_id": "Petro-Fictif",
            "categorie": "carburant",
            "numero_facture": numero,
            "date_facture": "2026-10-01",
            "montant_avant_taxes": montant,
            "total_facture": None,
            "horodatage": fixtures.SAISIE,
        },
    )
    assert r["statut"] == "en_attente_approbation"
    return r["demande_id"]


def decider(dep, demande):
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx, demande, True, "finance-fictif", outils_executables({D: dep}, stockage.transaction), {D: dep}
        )


def revision_lue(ident):
    """`corrections` de la ligne sans PO lue avant de proposer ; absent au statut SAISIE : 0."""
    page, verdict = comptes_a_payer.lister_sans_po(journal(), budget_caracteres=6000)
    assert verdict is None, verdict
    (ligne,) = [x for x in page["factures"] if x["facture_fournisseur_id"] == ident]
    if "corrections" not in ligne:
        assert ligne["statut"] == "SAISIE", ligne
        return 0
    return ligne["corrections"]


def demander_annulation(dep, ident):
    r = Capacites({D: dep}, stockage.transaction).appeler(
        "m5_annuler_facture_fournisseur",
        {
            "facture_fournisseur_id": ident,
            "motif": "Annulation finance fictive",
            "horodatage": fixtures.SAISIE,
            "revision_attendue": revision_lue(ident),
        },
    )
    assert r["statut"] == "en_attente_approbation"
    return r["demande_id"]


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
def test_annulation_fournisseur_refuse_a_preserve_b_et_exige_nouvelle_decision(monkeypatch, tmp_path):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        stockage.migrer()
        outils.utiliser_stockage_durable()
        dep = lire_manifeste(ROOT / "departments/m05-financecore")
        with stockage.transaction() as cnx:
            identite.creer_personne(
                cnx, "finance-fictif", "Finance fictive", "mot-de-passe-fixture-fictif", ["finance"]
            )
        manifeste = tmp_path / "department.yaml"
        manifeste.write_text("configuration:\n  categories_depense_sans_po: [carburant, outils]\n")
        monkeypatch.setattr(outils, "_MANIFESTE", manifeste)
        assert journal().taille() == 0 and journal().valider_chaine() == (True, "")
        seed = decider(dep, demander(dep, "INIT-FICTIF", "100.00"))
        assert seed["statut"] == "executee" and seed["reponse"]["resultat"]["accepte"]
        ident = seed["reponse"]["resultat"]["resultat"]["facture"]["facture_fournisseur_id"]
        a_id = demander_annulation(dep, ident)
        b_id = demander(dep, "F-1002", "20.00")
        avant = journal().lire()
        mouvements = list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS))
        calcule = threading.Event()
        reprendre = threading.Event()
        observations = {}
        original = MaillonsDurables.append

        def pauser(self, maillon, *, rang_attendu=None):
            if (self.departement, self.registre) == (D, outils._NOM_REGISTRE_COMPTES_A_PAYER) and maillon.get(
                "type_entree"
            ) == "annulation_facture_fournisseur":
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
                observations["decision_a"] = decider(dep, a_id)
            except BaseException as exc:
                observations["exception_a"] = type(exc).__name__
                calcule.set()

        a = threading.Thread(target=approuver_a, name="m5-ap-annulation-a-fictif")
        monkeypatch.setattr(MaillonsDurables, "append", pauser)
        try:
            a.start()
            assert calcule.wait(10) and "exception_a" not in observations
            assert observations["rang_a"] == 1
            with stockage.transaction() as cnx:
                assert cnx.get_isolation_level() == "READ COMMITTED"
                cnx.exec_driver_sql("SET LOCAL statement_timeout = '3s'")
                cnx.exec_driver_sql("SET LOCAL lock_timeout = '200ms'")
                assert cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one() != observations["pid_a"]
                b = decider(dep, b_id)
                assert b["statut"] == "executee" and b["reponse"]["resultat"]["accepte"]
            avec_b = journal().lire()
            assert avec_b[:1] == avant and len(avec_b) == 2 and avec_b[-1]["numero_facture"] == "F-1002"
            assert journal().valider_chaine() == (True, "")
            reprendre.set()
            a.join(10)
            assert not a.is_alive() and "exception_a" not in observations
            decision = observations["decision_a"]
            assert decision["statut"] == "echec" and decision["reponse"]["erreur"] == "panne_execution"
            assert decision["reponse"]["details"].startswith("EcritureConcurrente:")
            stockage.liberer()
            assert journal().lire() == avec_b and journal().valider_chaine() == (True, "")
            assert list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS)) == mouvements
            with stockage.transaction() as cnx:
                assert approbations.lire(cnx, a_id)["statut"] == "echec"
                assert approbations.lire(cnx, b_id)["statut"] == "executee"
            with pytest.raises(ValueError, match="déjà"):
                decider(dep, a_id)
            assert journal().lire() == avec_b
            monkeypatch.setattr(MaillonsDurables, "append", original)
            suivant = demander_annulation(dep, ident)
            assert suivant != a_id and decider(dep, suivant)["statut"] == "executee"
            stockage.liberer()
            apres = journal().lire()
            assert apres[:2] == avec_b and len(apres) == 3
            assert apres[-1]["precedent_ligne_id"] == avec_b[-1]["ligne_id"]
            assert apres[0]["numero_facture"] == "INIT-FICTIF" and apres[1]["numero_facture"] == "F-1002"
            assert apres[-1]["type_entree"] == "annulation_facture_fournisseur"
            assert type(apres[0]["montant_avant_taxes"]) is Decimal and type(apres[1]["montant_avant_taxes"]) is Decimal
            assert apres[-1]["annule_par"] == "finance-fictif" and apres[-1]["role"] == "finance"
            assert apres[-1]["voie"] == "approbation" and apres[-1]["facture_fournisseur_id"] == ident
            assert journal().valider_chaine() == (True, "")
            assert list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS)) == mouvements
        finally:
            reprendre.set()
            if a.ident is not None:
                a.join(10)
            assert not a.is_alive(), "écrivain fictif non arrêté"
            monkeypatch.setattr(MaillonsDurables, "append", original)
            stockage.liberer()
