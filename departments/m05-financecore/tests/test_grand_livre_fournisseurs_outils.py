"""Bout en bout sur le VRAI socle : facture fournisseur saisie -> brouillon GL -> validation N4 -> balance,
rapprochement CTI/RTI exacts au cent -> export Beancount équilibré.

Base SQLite temporaire migrée, vrai manifeste de M5 (mode `ombre`), vrai bus (`m6.reception_enregistree`), vrais outils
de saisie (`m5_saisir_facture_fournisseur`, `m5_saisir_facture_sans_po`, jeton d'appareil `admin` de la comptable),
vraie génération (`m5_generer_brouillons_comptables`) et vraie file d'approbation N4. Personnes, fournisseurs,
identifiants et montants fictifs (AGENTS.md).
"""

from __future__ import annotations

import contextlib
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import analyse, grand_livre, grand_livre_beancount
from m5_financecore import registre as registre_module
from sqlalchemy import func, select

from opsys import approbations as opsys_approbations
from opsys import contexte, evenements, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.outils import executer_atomique
from opsys.stockage.schema import REGISTRES

FICTIF = True
D = Decimal
_RACINE_M5 = Path(__file__).resolve().parents[1]
DEPARTEMENT = "m05-financecore"
H = "2026-10-25T10:00:00-04:00"
SAISIE = "2026-10-08T10:00:00-04:00"
COMPTABLE = contexte.IdentiteAppelante(personne="comptable", role="admin")
OCTOBRE = {"debut": "2026-10-01", "fin": "2026-10-31"}
CATEGORIES = ["carburant", "outils", "location"]
LOCATION = {"numero": "5450", "nom": "Location d'équipement", "type": "charges"}


@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-gl-ap.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234",
                                ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "comptable", "Une Comptable (fictive)", "mot-de-passe-compta-1234",
                                ["finance", "admin"])
    yield url
    stockage.liberer()


@pytest.fixture
def dep():
    return lire_manifeste(_RACINE_M5)


@pytest.fixture
def par_nom():
    return {o.nom: o for o in m5_outils.outils()}


@pytest.fixture
def declare(tmp_path, monkeypatch):
    def _declarer(configuration):
        manifeste = tmp_path / "department.yaml"
        manifeste.write_text(yaml.safe_dump({"configuration": configuration}, allow_unicode=True), encoding="utf-8")
        monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    return _declarer


def _recevoir(dep):
    charge = {
        "evenement_id": "evt-1", "po_id": "PO-1", "fournisseur_id": "gentek", "chantier_id": "CH-1",
        "horodatage_reception": "2026-09-29T09:15:00-04:00", "verdict_reception": "CONFORME", "statut_po": "received",
        "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [{"materiau_id": "gouttiere-5po", "quantite_demandee": "60", "quantite_recue": "60",
                    "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                    "prix_unitaire_reception": None, "verdict_prix_reception": "INDETERMINE",
                    "ecart_prix_critique": None}],
    }
    with stockage.transaction():
        evenements.publier("m6.reception_enregistree", "m06-material-control", charge,
                           evenement_id=charge["evenement_id"])
    resume = evenements.repartir({DEPARTEMENT: dep}, maintenant="2026-09-29T12:00:00+00:00")
    assert resume["traites"] >= 1 and resume["echecs"] == 0, resume


def _appeler(par_nom, nom, arguments, identite_appelante=None):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        return executer_atomique(par_nom[nom], arguments)


def _accepte_ap(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _accepte(reponse):
    """Une sortie du grand livre : acceptée, avec les DEUX mentions (analyse préparatoire et CPA)."""
    corps = _accepte_ap(reponse)
    assert corps["mention"] == analyse.MENTION_ANALYSE_PREPARATOIRE
    assert corps["mention_comptable"] == "À valider auprès d'un comptable (CPA) / professionnel qualifié."
    return corps


def _maillons(registre):
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(REGISTRES).where(
            (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == registre))).scalar_one()


def _generer(dep):
    return _accepte(Capacites({DEPARTEMENT: dep}, stockage.transaction).appeler(
        "m5_generer_brouillons_comptables", {"horodatage": H}))


def _valider_par_la_file(dep, ecriture_id):
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    demande = capacites.appeler("m5_valider_ecriture_comptable", {"ecriture_id": ecriture_id, "horodatage": H})
    assert demande["statut"] == "en_attente_approbation", demande
    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(
            cnx, demande["demande_id"], True, "comptable",
            outils_executables({DEPARTEMENT: dep}, stockage.transaction), {DEPARTEMENT: dep})
    assert decision["statut"] == "executee", decision
    return _accepte(decision["reponse"])["ecriture"]


def _saisir(dep, par_nom):
    """PO-1 reçu (60 × 5.00), F-1001 sur PO (300.00), C-4001 carburant (100.00), L-1 location (80.00) : leurs ids."""
    _recevoir(dep)
    po = _accepte_ap(_appeler(par_nom, "m5_saisir_facture_fournisseur", {
        "po_id": "PO-1", "fournisseur_id": "gentek", "numero_facture": "F-1001", "date_facture": "2026-10-02",
        "montant_avant_taxes": "300.00", "total_facture": "344.93", "horodatage": SAISIE}, COMPTABLE))
    ids = {"po": po["facture"]["facture_fournisseur_id"]}
    for cle, categorie, numero, montant in (("carburant", "carburant", "C-4001", "100.00"),
                                            ("location", "location", "L-1", "80.00")):
        sans_po = _accepte_ap(_appeler(par_nom, "m5_saisir_facture_sans_po", {
            "fournisseur_id": "Fournisseur Fictif", "categorie": categorie, "numero_facture": numero,
            "date_facture": "2026-10-01", "montant_avant_taxes": montant, "total_facture": None,
            "horodatage": SAISIE}, COMPTABLE))
        ids[cle] = sans_po["facture"]["facture_fournisseur_id"]
    return ids


def test_facture_fournisseur_saisie_jusqu_a_la_balance_au_rapprochement_cti_rti_et_a_l_export(
        dep, par_nom, declare, tmp_path):
    declare({"categories_depense_sans_po": CATEGORIES})
    ids = _saisir(dep, par_nom)
    assert _maillons("grand_livre") == 0, "la saisie ne passe aucune écriture"

    generation = _generer(dep)
    assert len(generation["brouillons_crees"]) == 2
    assert [(i["facture_fournisseur_id"], i["code"]) for i in generation["sources_ignorees"]] == [
        (ids["location"], "REJ-GL-CATEGORIE-SANS-COMPTE")], "jamais un compte supposé pour « location »"
    assert generation["categories_sans_compte"] == ["location"]
    balance = _accepte(_appeler(par_nom, "m5_lire_balance_verification", {"au": "2026-10-31"}))
    assert balance["comptes"] == [] and balance["brouillons_non_comptabilises"] == 2, "un brouillon ne compte pas"

    for brouillon in generation["brouillons_crees"]:
        ecriture = _valider_par_la_file(dep, brouillon["ecriture_id"])
        assert ecriture["statut"] == "DEFINITIVE" and ecriture["validation"]["par"] == "comptable"
        assert ecriture["piece"]["type"] == "facture_fournisseur"

    balance = _accepte(_appeler(par_nom, "m5_lire_balance_verification", {"au": "2026-10-31"}))
    assert balance["equilibree"] and balance["total_debits"] == balance["total_credits"] == "459.91"
    assert {c["compte"]: (c["solde"], c["cote"]) for c in balance["comptes"]} == {
        "1400": ("20.00", "debiteur"), "1410": ("39.91", "debiteur"), "2100": ("459.91", "crediteur"),
        "5100": ("300.00", "debiteur"), "5400": ("100.00", "debiteur")}

    # La facture de location (sans compte) est attendue au rapprochement : un écart nommé, au cent.
    rapprochement = _accepte(_appeler(par_nom, "m5_rapprocher_grand_livre", OCTOBRE))
    assert rapprochement["verdict"] == "ECART"
    assert rapprochement["intrants"]["tps_cti"]["ecarts"] == [
        {"facture_fournisseur_id": ids["location"], "attendu_facture": "4.00", "au_grand_livre": "0.00",
         "raison": "sans écriture définitive"}]
    assert rapprochement["intrants"]["tvq_rti"]["ecarts"][0]["attendu_facture"] == "7.98"

    # Le client déclare le compte de la location : la génération suivante en tire le brouillon, et lui seul.
    declare({"categories_depense_sans_po": CATEGORIES, "grand_livre": {
        "comptes_ajoutes": [LOCATION], "correspondance_charges": {"categories_depense": {"location": "5450"}}}})
    suite = _generer(dep)
    assert suite["deja_proposes"] == 2 and suite["sources_ignorees"] == [] and suite["categories_sans_compte"] == []
    [location] = suite["brouillons_crees"]
    ecriture = _valider_par_la_file(dep, location["ecriture_id"])
    assert ecriture["plan_comptable_version"].startswith("2026-v2+client.")
    assert [(li["compte"], li["debit"], li["credit"]) for li in ecriture["lignes"]] == [
        ("5450", "80.00", None), ("1400", "4.00", None), ("1410", "7.98", None), ("2100", None, "91.98")]

    rapprochement = _accepte(_appeler(par_nom, "m5_rapprocher_grand_livre", OCTOBRE))
    assert rapprochement["verdict"] == "CONCORDANT" and rapprochement["equilibre"]["verdict"] == "EQUILIBRE"
    cti, rti = rapprochement["intrants"]["tps_cti"], rapprochement["intrants"]["tvq_rti"]
    assert (cti["attendu_factures_fournisseurs"], cti["au_grand_livre"], cti["verdict"]) == (
        "24.00", "24.00", "CONCORDANT")
    assert (rti["attendu_factures_fournisseurs"], rti["au_grand_livre"], rti["verdict"]) == (
        "47.89", "47.89", "CONCORDANT")
    livre = _accepte(_appeler(par_nom, "m5_lire_grand_livre_compte", {"compte": "2100", **OCTOBRE}))
    assert livre["solde_cloture_debiteur"] == "-551.89" and livre["lignes_total"] == 3

    # Rejouer la génération ne recrée rien.
    redite = _generer(dep)
    assert redite["brouillons_crees"] == [] and redite["deja_proposes"] == 3

    # L'export Beancount du registre durable : trois transactions équilibrées, les charges sous Expenses.
    plan, _ = m5_outils._plan_comptable_effectif()
    with stockage.transaction():
        etat = grand_livre.etat_grand_livre(
            registre_module.Registre(maillons=stockage.maillons(DEPARTEMENT, "grand_livre")).lire())
    texte = grand_livre_beancount.ecrire_fichier_beancount(tmp_path / "ap.beancount", etat, plan).read_text(
        encoding="utf-8")
    assert "À valider auprès d'un comptable (CPA)" in texte and "Expenses:C5450-Location-D-Equipement" in texte
    transactions = [bloc for bloc in texte.split("\n\n") if " * " in bloc]
    assert len(transactions) == 3
    for transaction in transactions:
        assert sum(D(ligne.split()[-2]) for ligne in transaction.splitlines()
                   if ligne.startswith("  ") and ligne.endswith(" CAD")) == 0
    # Aucun mouvement d'argent : le registre des mouvements reste vide.
    assert _maillons("principal") == 0


def test_annuler_une_facture_deja_comptabilisee_se_voit_au_rapprochement(dep, par_nom, declare):
    declare({"categories_depense_sans_po": CATEGORIES})
    ids = _saisir(dep, par_nom)
    for brouillon in _generer(dep)["brouillons_crees"]:
        _valider_par_la_file(dep, brouillon["ecriture_id"])
    assert _accepte_ap(_appeler(par_nom, "m5_annuler_facture_fournisseur", {
        "facture_fournisseur_id": ids["carburant"], "motif": "Facture d'un autre client (fictif)",
        "revision_attendue": 0, "horodatage": H}, contexte.IdentiteAppelante(personne="nathan", role="admin")))
    assert _generer(dep)["brouillons_crees"] == [], "une annulée ne donne aucun brouillon"
    rapprochement = _accepte(_appeler(par_nom, "m5_rapprocher_grand_livre", OCTOBRE))
    raisons = {e["facture_fournisseur_id"]: e["raison"] for e in rapprochement["intrants"]["tps_cti"]["ecarts"]}
    assert raisons[ids["carburant"]] == "mouvement de taxe sans facture fournisseur vivante datée dans la période"
    assert rapprochement["verdict"] == "ECART"


def test_une_correspondance_du_client_invalide_ferme_le_grand_livre_sans_rien_ecrire(dep, par_nom, declare):
    declare({"categories_depense_sans_po": CATEGORIES, "grand_livre": {"comptes_desactives": ["5400"]}})
    reponse = _appeler(par_nom, "m5_generer_brouillons_comptables", {"horodatage": H})
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-GL-CORRESPONDANCE-INVALIDE"
    assert _maillons("grand_livre") == 0
