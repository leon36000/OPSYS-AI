"""Bout en bout : facture d'onboarding déposée -> brouillon AP -> saisie par décision humaine (N3) -> brouillon GL ->
validation N4 -> balance et rapprochement CTI/RTI exacts au cent -> export Beancount équilibré.

Vrai socle (base SQLite migrée, vrai manifeste de M5 en mode `ombre`, vraie file d'approbation, fournisseur
d'extraction SIMULÉ déclaré et sélectionné, comme `test_ingestion_onboarding_bout_en_bout.py`). Le seul substitut : le
worker PDF natif exécuté dans le processus de test (bubblewrap manque dans le bac à sable). Corpus fictif :
F1 (Quincaillerie Fictive Laval, 2026-09-15 : 304.00 + TPS 15.20 + TVQ 30.32 = 349.52, catégorie `materiaux`) et F2
(Matériaux Fictifs Rive-Sud, 2026-08-30 : 100.50 + TPS 5.03 + TVQ 10.02 = 115.55, catégorie `outils`).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import ingestion_onboarding_qa as qa
import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import grand_livre, grand_livre_beancount
from m5_financecore import registre as registre_module

from opsys import approbations, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.ingestion_onboarding import extraction_texte

FICTIF = True
D = Decimal
RACINE = Path(__file__).resolve().parents[1]
M5 = "m05-financecore"
QUAND = "2026-10-31T11:00:00-04:00"
MENTION_CPA = "À valider auprès d'un comptable (CPA) / professionnel qualifié."


@pytest.fixture
def instance(tmp_path, monkeypatch):
    url = qa.preparer_instance(tmp_path, monkeypatch)
    monkeypatch.setattr(extraction_texte, "extracteur_pdf_isole", qa.extracteur_pdf_en_processus)
    manifeste = tmp_path / "m5-department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {"categories_depense_sans_po": ["materiaux", "outils"]}}),
                         encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    m5_outils.utiliser_stockage_durable()
    return url


@pytest.fixture
def deps():
    return {M5: lire_manifeste(RACINE / "departments" / M5)}


@pytest.fixture
def capacites(deps):
    return Capacites(deps, stockage.transaction)


def _accepte(reponse):
    if "ok" in reponse and "accepte" not in reponse:
        assert reponse["ok"] is True, reponse
        reponse = reponse["resultat"]
    assert reponse.get("accepte") is True, reponse
    return reponse["resultat"]


def _decider(deps, demande):
    assert demande["statut"] == "en_attente_approbation", demande
    with stockage.transaction() as cnx:
        decision = approbations.decider(cnx, demande["demande_id"], True, "nathan",
                                        outils_executables(deps, stockage.transaction), deps, role="nathan_owner")
    assert decision["statut"] == "executee", decision
    return _accepte(decision["reponse"])


def _brouillons_ap(capacites):
    qa.deposer_fichier("onboarding-ap.zip", qa.zip_onboarding({
        "factures/F1-quincaillerie.pdf": qa.pdf_texte(qa.texte_corpus("factures/F1-quincaillerie.txt")),
        "factures/F2-materiaux.pdf": qa.pdf_texte(qa.texte_corpus("factures/F2-materiaux.txt")),
    }))
    lot = _accepte(capacites.appeler("m5_deposer_lot_onboarding",
                                     {"fichier": "onboarding-ap.zip", "mutation_id": "onboarding-gl-1"}))
    avance = _accepte(capacites.appeler("m5_avancer_lot_onboarding", {"lot_id": lot["lot_id"], "budget": 100}))
    assert avance["statut"] == "TERMINE", avance["compteurs"]
    page = _accepte(capacites.appeler("m5_lire_lot_onboarding", {"lot_id": lot["lot_id"], "vue": "brouillons"}))
    index = {}
    for brouillon in page["brouillons"]:
        lu = _accepte(capacites.appeler("m5_lire_lot_onboarding", {"lot_id": lot["lot_id"],
                                                                   "brouillon_id": brouillon["brouillon_id"]}))
        index[lu["brouillon"]["contenu"]["validation"]["facture"]["fournisseur"]] = brouillon
    assert {nom: b["statut"] for nom, b in index.items()} == {
        "Quincaillerie Fictive Laval inc.": "PRET", "Matériaux Fictifs Rive-Sud": "PRET"}
    return index


def _maillons(registre):
    with stockage.transaction():
        return list(stockage.maillons(M5, registre))


def test_facture_d_onboarding_validee_jusqu_au_grand_livre_definitif(instance, deps, capacites, tmp_path):
    ap = _brouillons_ap(capacites)
    for fournisseur, categorie in (("Quincaillerie Fictive Laval inc.", "materiaux"),
                                   ("Matériaux Fictifs Rive-Sud", "outils")):
        brouillon = ap[fournisseur]
        _decider(deps, capacites.appeler("m5_valider_brouillon_onboarding_ap", {
            "brouillon_id": brouillon["brouillon_id"], "revision_attendue": brouillon["revision"],
            "decision": "valider", "categorie": categorie, "motif": None, "horodatage": QUAND}))
    assert len(_maillons("comptes_a_payer")) == 2 and _maillons("grand_livre") == []

    generation = _accepte(capacites.appeler("m5_generer_brouillons_comptables", {"horodatage": QUAND}))
    assert generation["mention_comptable"] == MENTION_CPA
    assert len(generation["brouillons_crees"]) == 2 and generation["sources_ignorees"] == []
    assert sorted(b["total"] for b in generation["brouillons_crees"]) == ["115.55", "349.52"]
    for brouillon in generation["brouillons_crees"]:
        ecriture = _decider(deps, capacites.appeler("m5_valider_ecriture_comptable", {
            "ecriture_id": brouillon["ecriture_id"], "horodatage": QUAND}))["ecriture"]
        assert ecriture["statut"] == "DEFINITIVE" and ecriture["validation"]["role"] == "nathan_owner"

    balance = _accepte(capacites.appeler("m5_lire_balance_verification", {"au": "2026-09-30"}))
    assert balance["mention_comptable"] == MENTION_CPA
    assert balance["equilibree"] and balance["total_debits"] == balance["total_credits"] == "465.07"
    assert {c["compte"]: c["solde"] for c in balance["comptes"]} == {
        "1400": "20.23", "1410": "40.34", "2100": "465.07", "5100": "304.00", "5500": "100.50"}

    rapprochement = _accepte(capacites.appeler("m5_rapprocher_grand_livre",
                                               {"debut": "2026-08-01", "fin": "2026-09-30"}))
    assert rapprochement["mention_comptable"] == MENTION_CPA and rapprochement["verdict"] == "CONCORDANT"
    assert (rapprochement["intrants"]["tps_cti"]["attendu_factures_fournisseurs"],
            rapprochement["intrants"]["tps_cti"]["au_grand_livre"]) == ("20.23", "20.23")
    assert (rapprochement["intrants"]["tvq_rti"]["attendu_factures_fournisseurs"],
            rapprochement["intrants"]["tvq_rti"]["au_grand_livre"]) == ("40.34", "40.34")
    # Août seul : la facture F2 et rien d'autre.
    aout = _accepte(capacites.appeler("m5_rapprocher_grand_livre", {"debut": "2026-08-01", "fin": "2026-08-31"}))
    assert aout["intrants"]["tps_cti"]["au_grand_livre"] == "5.03" and aout["verdict"] == "CONCORDANT"

    plan, _ = m5_outils._plan_comptable_effectif()
    with stockage.transaction():
        etat = grand_livre.etat_grand_livre(registre_module.Registre(maillons=stockage.maillons(M5, "grand_livre"))
                                            .lire())
    texte = grand_livre_beancount.ecrire_fichier_beancount(tmp_path / "onboarding.beancount", etat, plan).read_text(
        encoding="utf-8")
    transactions = [bloc for bloc in texte.split("\n\n") if " * " in bloc]
    assert len(transactions) == 2 and "Expenses:C5100-Materiaux-Utilises" in texte
    for transaction in transactions:
        assert sum(D(ligne.split()[-2]) for ligne in transaction.splitlines()
                   if ligne.startswith("  ") and ligne.endswith(" CAD")) == 0
    assert _maillons("principal") == [], "aucun mouvement d'argent"
