"""Deux oracles PG17 sur une décision N4 proposée avant une correction commise.

Une connexion psycopg indépendante témoigne le commit B avant la décision A.
L'acteur finance reste actif. Aucun paiement, fournisseur ou service réel.
"""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from m5_financecore import outils, registre
from memoire.doubles import postgres_ephemere

from opsys import approbations, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.stockage import codec

ROOT = Path(__file__).resolve().parents[2]
D = "m05-financecore"
T = "2026-10-01T12:00:00-04:00"
ACTEUR = "finance-revision-fictif"
FICTIF = True
pytestmark = pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)


def _proposer(dep, nom, arguments):
    r = Capacites({D: dep}, stockage.transaction).appeler(nom, arguments)
    assert r["statut"] == "en_attente_approbation", r
    return r["demande_id"]


def _decider(dep, demande):
    with stockage.transaction() as cnx:
        assert cnx.get_isolation_level() == "READ COMMITTED"
        cnx.exec_driver_sql("SET LOCAL statement_timeout = '8s'")
        cnx.exec_driver_sql("SET LOCAL lock_timeout = '2s'")
        humain = identite.personne_active(cnx, ACTEUR)
        assert humain is not None and "finance" in humain.roles
        pid = cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
        decision = approbations.decider(
            cnx, demande, True, ACTEUR, outils_executables({D: dep}, stockage.transaction), {D: dep},
        )
    return decision, pid


def _arguments(identifiant, revision, montant=None):
    a = {"facture_fournisseur_id": identifiant, "revision_attendue": revision,
         "motif": "Facture papier relue, correction fictive", "horodatage": T}
    if montant is not None:
        a.update(numero_facture=None, date_facture=None, montant_avant_taxes=montant, total_facture=None)
    return a


def _rows(cnx, nom):
    return cnx.execute(
        "SELECT rang,maillon,cree_le FROM registres_maillons "
        "WHERE departement=%s AND registre=%s ORDER BY rang", (D, nom),
    ).fetchall()


@pytest.mark.parametrize("action", ["correction", "annulation"])
def test_decision_perimee_refusee_apres_commit_autre_correction_et_reprise_courante(action, monkeypatch, tmp_path):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "m5-revision-pg-fictif"))
        monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")
        manifeste = tmp_path / "department-m5-fictif.yaml"
        manifeste.write_text("configuration:\n  categories_depense_sans_po: [carburant, outils]\n")
        monkeypatch.setattr(outils, "_MANIFESTE", manifeste)
        try:
            stockage.migrer()
            monkeypatch.setattr(outils, "_stockage_durable_actif", True)
            dep = lire_manifeste(ROOT / "departments/m05-financecore")
            with stockage.transaction() as cnx:
                identite.creer_personne(
                    cnx, ACTEUR, "Finance fictive", "mot-de-passe-fixture-fictif", ["finance"],
                )
            demande = _proposer(dep, "m5_saisir_facture_sans_po", {
                "fournisseur_id": "Fournisseur-PG-fictif", "categorie": "carburant",
                "numero_facture": "F-REVISION-FICTIF", "date_facture": "2026-10-01",
                "montant_avant_taxes": "100.00", "total_facture": None, "horodatage": T,
            })
            seed, _ = _decider(dep, demande)
            assert seed["statut"] == "executee" and seed["reponse"]["resultat"]["accepte"]
            facture = seed["reponse"]["resultat"]["resultat"]["facture"]
            identifiant = facture["facture_fournisseur_id"]
            revision = facture.get("corrections", 0)
            assert type(revision) is int and revision == 0
            nom = "m5_corriger_facture_fournisseur" if action == "correction" else "m5_annuler_facture_fournisseur"
            args_a = _arguments(identifiant, revision, "310.00" if action == "correction" else None)
            a = _proposer(dep, nom, args_a)
            b = _proposer(dep, "m5_corriger_facture_fournisseur", _arguments(identifiant, revision, "320.00"))
            # L'observateur natif reste ouvert pour être distinct du backend B.
            with psycopg.connect(url, autocommit=True) as observer:
                observer.execute("SET statement_timeout = '8s'")
                pid_c = observer.execute("SELECT pg_backend_pid()").fetchone()[0]
                avant = _rows(observer, outils._NOM_REGISTRE_COMPTES_A_PAYER)
                mouvements = _rows(observer, outils._NOM_REGISTRE_MOUVEMENTS)
                decision_b, pid_b = _decider(dep, b)
                assert pid_b != pid_c and decision_b["statut"] == "executee"
                resultat_b = decision_b["reponse"]["resultat"]
                assert resultat_b["accepte"]
                courante = resultat_b["resultat"]["facture"]["corrections"]
                assert courante == revision + 1
                # B est réellement commise et observable avant toute décision A.
                avec_b = _rows(observer, outils._NOM_REGISTRE_COMPTES_A_PAYER)
                assert len(avec_b) == len(avant) + 1 and avec_b[:-1] == avant
                piece_b = codec.decoder(avec_b[-1][1])
                assert piece_b["type_entree"] == "correction_facture_fournisseur"
                assert piece_b["apres"]["montant_avant_taxes"] == Decimal("320.00")
                assert piece_b["apres"]["montant_apres_taxes"] == Decimal("367.92")
                stockage.liberer()
                decision_a, _ = _decider(dep, a)
                assert decision_a["statut"] == "echec", decision_a
                refus = decision_a["reponse"]["resultat"]
                assert refus["accepte"] is False
                assert refus["verdict"]["code"] == "REJ-AP-FACTURE-REVISION-PERIMEE"
                assert _rows(observer, outils._NOM_REGISTRE_COMPTES_A_PAYER) == avec_b
                assert _rows(observer, outils._NOM_REGISTRE_MOUVEMENTS) == mouvements
                with stockage.transaction() as cnx:
                    assert approbations.lire(cnx, a)["statut"] == "echec"
                    assert approbations.lire(cnx, b)["statut"] == "executee"
                    assert identite.personne_active(cnx, ACTEUR) is not None
                with pytest.raises(ValueError, match="déjà"):
                    _decider(dep, a)
                assert _rows(observer, outils._NOM_REGISTRE_COMPTES_A_PAYER) == avec_b
                # Nouvelle proposition sur la révision effectivement lue, sans enrichir A.
                suivante = _proposer(dep, nom, _arguments(
                    identifiant, courante, "310.00" if action == "correction" else None,
                ))
                assert suivante != a
                decision_suivante, _ = _decider(dep, suivante)
                assert decision_suivante["statut"] == "executee"
                assert decision_suivante["reponse"]["resultat"]["accepte"]
                apres = _rows(observer, outils._NOM_REGISTRE_COMPTES_A_PAYER)
                assert apres[:-1] == avec_b and len(apres) == len(avec_b) + 1
                piece = codec.decoder(apres[-1][1])
                assert piece["type_entree"] == action + "_facture_fournisseur"
                if action == "correction":
                    assert piece["apres"]["montant_avant_taxes"] == Decimal("310.00")
                    assert piece["apres"]["montant_apres_taxes"] == Decimal("356.42")
                assert _rows(observer, outils._NOM_REGISTRE_MOUVEMENTS) == mouvements
                journal = registre.Registre(stockage.maillons(D, outils._NOM_REGISTRE_COMPTES_A_PAYER))
                assert journal.valider_chaine() == (True, "")
        finally:
            stockage.liberer()
