"""Import QuickBooks sur le VRAI socle : outils, dossier confiné, file d'approbation N4 (correspondance, lot), portée
d'appareil fermée, idempotence, et le parcours complet « exports -> correspondance -> import -> balance OPSYS = Trial
Balance QBO au cent -> export Beancount équilibré ».

Base SQLite temporaire migrée, vrai manifeste de M5 (mode `ombre`), vraies approbations (`Capacites`, `decider`).
Exports QuickBooks FICTIFS (`fixtures/quickbooks/MANIFESTE.yaml`) ; personnes et montants fictifs (AGENTS.md).
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
import shutil
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import analyse, grand_livre, grand_livre_beancount, import_quickbooks
from m5_financecore import registre as registre_module
from sqlalchemy import func, select

from opsys import approbations as opsys_approbations
from opsys import contexte, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.outils import executer_atomique
from opsys.stockage.schema import REGISTRES

FICTIF = True
D = Decimal
_RACINE_M5 = Path(__file__).resolve().parents[1]
F = Path(__file__).resolve().parent / "fixtures" / "quickbooks"
DEPARTEMENT = "m05-financecore"
H = "2026-04-02T10:00:00-04:00"
ADMIN = contexte.IdentiteAppelante(personne="nathan", role="admin")
OUTILS_QBO = ("m5_analyser_exports_quickbooks", "m5_valider_correspondance_quickbooks", "m5_importer_quickbooks",
              "m5_lire_import_quickbooks", "m5_valider_import_quickbooks")
EN = {"fichier_liste_comptes": "account_list.csv", "fichier_balance_ouverture": "trial_balance_2025-12-31.csv",
      "fichier_journal": "journal_2026-01-01_2026-03-31.csv", "fichier_balance_cloture": "trial_balance_2026-03-31.csv"}
FR = {"fichier_liste_comptes": "liste_des_comptes.csv", "fichier_journal": "journal_2026-01-01_2026-02-28.csv",
      "fichier_balance_cloture": "balance_de_verification_2026-02-28.csv"}
MANUELLES_EN = [{"compte_qbo": "Savings", "compte_opsys": "1010"},
                {"compte_qbo": "Office Supplies", "compte_opsys": "5990"}]
MANUELLES_FR = [{"compte_qbo": "Repas et représentation", "compte_opsys": "5990"}]


@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-qbo.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234",
                                ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "comptable", "Une Comptable (fictive)", "mot-de-passe-compta-1234", ["finance"])
    dossier = m5_outils.dossier_imports_quickbooks()
    dossier.mkdir(parents=True)
    for jeu in ("en", "fr"):
        for fichier in (F / jeu).iterdir():
            shutil.copy(fichier, dossier / fichier.name)
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {"fiscal": {"mois_fin_exercice": 12}}}), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    yield url
    stockage.liberer()


@pytest.fixture
def dep():
    return lire_manifeste(_RACINE_M5)


@pytest.fixture
def par_nom():
    return {o.nom: o for o in m5_outils.outils()}


def _appeler(par_nom, nom, arguments, identite_appelante=None):
    if identite_appelante is None:
        return executer_atomique(par_nom[nom], arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _accepte(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    corps = reponse["resultat"]["resultat"]
    assert corps["mention"] == analyse.MENTION_ANALYSE_PREPARATOIRE
    assert corps["mention_comptable"] == "À valider auprès d'un comptable (CPA) / professionnel qualifié."
    return corps


def _verdict(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def _maillons(registre):
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(REGISTRES).where(
            (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == registre))).scalar_one()


def _par_la_file(dep, nom, arguments, decideur="comptable", *, mode=None, attendu="executee"):
    depart = dep if mode is None else dataclasses.replace(dep, mode=mode)
    demande = Capacites({DEPARTEMENT: depart}, stockage.transaction).appeler(nom, arguments)
    assert demande["statut"] == "en_attente_approbation", demande
    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(
            cnx, demande["demande_id"], True, decideur,
            outils_executables({DEPARTEMENT: dep}, stockage.transaction), {DEPARTEMENT: dep})
    assert decision["statut"] == attendu, decision
    return decision["reponse"]


def _valider_correspondance(dep, liste, manuelles):
    reponse = _par_la_file(dep, "m5_valider_correspondance_quickbooks", {
        "fichier_liste_comptes": liste, "correspondances_manuelles": manuelles, "horodatage": H})
    return _accepte(reponse)


def _importer(dep, exports, *, mode="detail", date_reprise, version=1):
    reponse = Capacites({DEPARTEMENT: dep}, stockage.transaction).appeler(
        "m5_importer_quickbooks", {"mode": mode, "date_reprise": date_reprise, "version_correspondance": version,
                                   **exports, "horodatage": H})
    return reponse


def _valider_lot(dep, lot, decideur="comptable", attendu="executee"):
    return _par_la_file(dep, "m5_valider_import_quickbooks", {**lot, "horodatage": H}, decideur, attendu=attendu)


def _soldes_balance(par_nom, au):
    soldes, depart = {}, 0
    while depart is not None:
        page = _accepte(_appeler(par_nom, "m5_lire_balance_verification", {"au": au, "depart": depart, "limite": 20}))
        assert page["equilibree"] is True
        soldes.update({c["compte"]: (c["solde"], c["cote"]) for c in page["comptes"] if c["cote"] != "nul"})
        depart = page["prochain_depart"]
    return soldes


def _balance_qbo_par_compte_opsys(fichier, table):
    """La Trial Balance QBO exportée, relue ICI sans le module d'import, regroupée par compte OPSYS validé."""
    lignes = list(csv.reader(io.StringIO((F / "en" / fichier).read_text(encoding="utf-8-sig"), newline="")))
    soldes: dict[str, Decimal] = {}
    for nom, debit, credit in (ligne for ligne in lignes if len(ligne) == 3 and ligne[0] not in ("", "TOTAL")):
        montant = D((debit or "0").replace(",", "").replace("$", "")) - D((credit or "0").replace(",", "").replace(
            "$", ""))
        soldes[table[nom]] = soldes.get(table[nom], D("0")) + montant
    return {n: (str(abs(s)), "debiteur" if s > 0 else "crediteur") for n, s in soldes.items() if s != 0}


# ============================================================================================= le contrat
def test_les_cinq_outils_ont_leur_niveau_et_aucune_portee_d_appareil(par_nom):
    attendus = {"m5_analyser_exports_quickbooks": ("T0", "N0"), "m5_lire_import_quickbooks": ("T0", "N0"),
                "m5_importer_quickbooks": ("T1", "N1"), "m5_valider_correspondance_quickbooks": ("T2", "N4"),
                "m5_valider_import_quickbooks": ("T2", "N4")}
    for nom, (autonomie, niveau) in attendus.items():
        outil = par_nom[nom]
        assert (outil.autonomie.value, outil.niveau_effectif.value) == (autonomie, niveau), nom
        assert outil.roles_appareil == frozenset() and outil.parametres["additionalProperties"] is False
        assert "À valider auprès d'un comptable (CPA) / professionnel qualifié" in outil.description
    assert set(OUTILS_QBO) <= analyse.SORTIES_COMPTABLES


@pytest.mark.parametrize("nom", OUTILS_QBO)
def test_une_identite_d_appareil_meme_admin_est_refusee_sans_rien_ecrire(par_nom, nom):
    arguments = {
        "m5_analyser_exports_quickbooks": {"fichier_liste_comptes": FR["fichier_liste_comptes"],
                                           "fichier_balance_cloture": FR["fichier_balance_cloture"]},
        "m5_valider_correspondance_quickbooks": {"fichier_liste_comptes": FR["fichier_liste_comptes"],
                                                 "correspondances_manuelles": MANUELLES_FR, "horodatage": H},
        "m5_importer_quickbooks": {"mode": "ouverture", "date_reprise": "2026-02-28", "version_correspondance": 1,
                                   "fichier_liste_comptes": FR["fichier_liste_comptes"],
                                   "fichier_balance_cloture": FR["fichier_balance_cloture"], "horodatage": H},
        "m5_lire_import_quickbooks": {"import_id": "qbi-x"},
        "m5_valider_import_quickbooks": {"import_id": "qbi-x", "nombre_ecritures": 1, "empreinte_lot": "x",
                                         "horodatage": H},
    }[nom]
    assert _verdict(_appeler(par_nom, nom, arguments, ADMIN))["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _maillons("grand_livre") == _maillons("import_quickbooks") == 0


# ============================================================================================= le parcours complet
def test_exports_correspondance_import_balance_au_cent_et_beancount_equilibre(dep, par_nom, tmp_path):
    # 1. Analyse : lecture expliquée, correspondance proposée en brouillon, vérification au cent déjà visible.
    analyse_ = _accepte(_appeler(par_nom, "m5_analyser_exports_quickbooks", EN))
    assert analyse_["lectures"]["journal"]["convention_dates"] == "MM/JJ/AAAA"
    assert analyse_["correspondance_proposee"]["statut"] == "BROUILLON"
    assert analyse_["correspondance_proposee"]["non_apparies"] == ["Office Supplies", "Savings"]
    assert analyse_["verification"]["egale_au_cent"] is True and analyse_["correspondance_validee"] is None
    # 2. L'import est refusé tant qu'aucune correspondance n'est validée.
    assert _verdict(_importer(dep, EN, date_reprise="2026-03-31"))["code"] == "REJ-QBO-CORRESPONDANCE-INTROUVABLE"
    # 3. Correspondance validée par la file (N4), versionnée.
    validee = _valider_correspondance(dep, EN["fichier_liste_comptes"], MANUELLES_EN)
    assert (validee["statut"], validee["version"]) == ("validee", 1)
    assert validee["par_methode"] == {"nom": 12, "manuel": 2}
    # 4. Import : brouillons seulement, vérifiés au cent.
    importe = _accepte(_importer(dep, EN, date_reprise="2026-03-31"))
    assert (importe["statut"], importe["ecritures"], importe["brouillons_crees"]) == ("importe", 8, 8)
    assert importe["verification"]["type"] == "ouverture_et_journal"
    assert importe["verification"]["report_resultats_bnr"] is True
    assert _maillons("grand_livre") == 8
    assert _accepte(_appeler(par_nom, "m5_lire_balance_verification", {"au": "2026-03-31"}))[
        "brouillons_non_comptabilises"] == 8
    # 5. Relecture de l'import puis validation EN LOT (une décision N4 sur le lot exact).
    lu = _accepte(_appeler(par_nom, "m5_lire_import_quickbooks", {"import_id": importe["import_id"]}))
    assert lu["statuts"] == {"BROUILLON": 8} and lu["validation_en_lot"] == importe["validation_en_lot"]
    reponse = _valider_lot(dep, lu["validation_en_lot"])
    lot = _accepte(reponse)
    assert (lot["validees"], lot["premier_numero"], lot["dernier_numero"]) == (8, 1, 8)
    assert lot["validation"] == {"par": "comptable", "role": "finance", "voie": "approbation"}
    # 6. La balance OPSYS au 31 mars = la Trial Balance QBO exportée, au cent, compte par compte.
    with stockage.transaction():
        maillons = registre_module.Registre(maillons=stockage.maillons(DEPARTEMENT, "import_quickbooks")).lire()
    table = next(m for m in maillons if m["type_entree"] == "qbo_correspondance_validee")["table"]
    attendue = _balance_qbo_par_compte_opsys(EN["fichier_balance_cloture"], table)
    assert _soldes_balance(par_nom, "2026-03-31") == attendue
    assert attendue["1010"] == ("21487.00", "debiteur") and attendue["3200"] == ("31702.25", "crediteur")
    assert {(a["compte"], a["solde"], a["cote"]) for a in importe["attendu_opsys_apres_validation"]} == {
        (n, s, c) for n, (s, c) in attendue.items()}
    # 7. Export Beancount : huit transactions, chacune de somme nulle.
    with stockage.transaction():
        etat = grand_livre.etat_grand_livre(
            registre_module.Registre(maillons=stockage.maillons(DEPARTEMENT, "grand_livre")).lire())
    plan, _ = m5_outils._plan_comptable_effectif()
    texte = grand_livre_beancount.ecrire_fichier_beancount(tmp_path / "reprise.beancount", etat, plan).read_text(
        encoding="utf-8")
    transactions = [bloc for bloc in texte.split("\n\n") if " * \"" in bloc]
    assert len(transactions) == 8 and all('piece: "import_quickbooks:qbo:' in t for t in transactions)
    for transaction in transactions:
        montants = [D(ligne.split()[-2]) for ligne in transaction.splitlines() if ligne.endswith(" CAD")]
        assert len(montants) >= 2 and sum(montants) == 0
    # 8. Réimporter les mêmes fichiers ne crée rien ; aucun mouvement d'argent.
    redite = _accepte(_importer(dep, EN, date_reprise="2026-03-31"))
    assert (redite["statut"], redite["brouillons_crees"], redite["deja_importees"]) == ("deja_importe", 0, 8)
    assert _maillons("grand_livre") == 16 and _maillons("principal") == 0
    assert _verdict(_appeler(par_nom, "m5_lire_import_quickbooks", {"import_id": "qbi-inconnu"}))["code"] \
        == "REJ-QBO-IMPORT-INTROUVABLE"


def test_mode_ouverture_francais_une_ecriture_puis_balance_egale(dep, par_nom):
    _valider_correspondance(dep, FR["fichier_liste_comptes"], MANUELLES_FR)
    exports = {k: v for k, v in FR.items() if k != "fichier_journal"}
    importe = _accepte(_importer(dep, exports, mode="ouverture", date_reprise="2026-02-28"))
    assert importe["ecritures"] == 1 and importe["verification"]["type"] == "interne"
    _accepte(_valider_lot(dep, importe["validation_en_lot"], decideur="nathan"))
    assert _soldes_balance(par_nom, "2026-02-28") == {
        "1010": ("13146.81", "debiteur"), "2100": ("80.00", "crediteur"), "2300": ("137.50", "crediteur"),
        "2310": ("274.31", "crediteur"), "3100": ("10000.00", "crediteur"), "4100": ("3000.00", "crediteur"),
        "5400": ("250.00", "debiteur"), "5800": ("15.00", "debiteur"), "5990": ("80.00", "debiteur")}


# ============================================================================================= l'humain exigé
def test_un_agent_seul_ne_valide_ni_la_correspondance_ni_le_lot(dep, par_nom):
    arguments = {"fichier_liste_comptes": FR["fichier_liste_comptes"], "correspondances_manuelles": MANUELLES_FR,
                 "horodatage": H}
    direct = _appeler(par_nom, "m5_valider_correspondance_quickbooks", arguments)
    autonome = Capacites({DEPARTEMENT: dataclasses.replace(dep, mode="autonome")}, stockage.transaction).appeler(
        "m5_valider_correspondance_quickbooks", arguments)
    assert _verdict(direct)["code"] == _verdict(autonome)["code"] == "REJ-GL-HUMAIN-REQUIS"
    assert _maillons("import_quickbooks") == 0
    _valider_correspondance(dep, FR["fichier_liste_comptes"], MANUELLES_FR)
    importe = _accepte(_importer(dep, FR, date_reprise="2026-02-28"))
    lot = _appeler(par_nom, "m5_valider_import_quickbooks", {**importe["validation_en_lot"], "horodatage": H})
    assert _verdict(lot)["code"] == "REJ-GL-HUMAIN-REQUIS"
    demande = Capacites({DEPARTEMENT: dep}, stockage.transaction).appeler(
        "m5_valider_import_quickbooks", {**importe["validation_en_lot"], "horodatage": H})
    assert demande["statut"] == "en_attente_approbation" and _maillons("grand_livre") == 6


def test_le_lot_decide_est_le_lot_exact(dep, par_nom):
    _valider_correspondance(dep, FR["fichier_liste_comptes"], MANUELLES_FR)
    importe = _accepte(_importer(dep, FR, date_reprise="2026-02-28"))
    ancien = importe["validation_en_lot"]
    premiere = _accepte(_appeler(par_nom, "m5_lire_import_quickbooks", {"import_id": importe["import_id"],
                                                                         "limite": 1}))["ecritures"][0]
    _accepte(_par_la_file(dep, "m5_valider_ecriture_comptable", {"ecriture_id": premiere["ecriture_id"],
                                                                 "horodatage": H}))
    perime = _verdict(_valider_lot(dep, ancien, attendu="echec"))
    assert perime["code"] == "REJ-QBO-LOT-PERIME" and _maillons("grand_livre") == 7
    nouveau = _accepte(_appeler(par_nom, "m5_lire_import_quickbooks", {"import_id": importe["import_id"]}))
    assert nouveau["validation_en_lot"]["nombre_ecritures"] == 5 and nouveau["statuts"] == {
        "DEFINITIVE": 1, "BROUILLON": 5}
    assert _accepte(_valider_lot(dep, nouveau["validation_en_lot"]))["validees"] == 5
    assert _verdict(_valider_lot(dep, nouveau["validation_en_lot"], attendu="echec"))["code"] == "REJ-QBO-LOT-PERIME"


# ============================================================================================= refus des outils
@pytest.mark.parametrize("nom", ["../trial_balance_2026-03-31.csv", "sous/dossier.csv", "absent.csv", "liste.exe",
                                 "lien.csv"])
def test_fichier_hors_du_dossier_confine_refuse(par_nom, nom):
    dossier = m5_outils.dossier_imports_quickbooks()
    (dossier / "lien.csv").symlink_to(dossier / "account_list.csv")
    verdict = _verdict(_appeler(par_nom, "m5_analyser_exports_quickbooks", {
        "fichier_liste_comptes": nom, "fichier_balance_cloture": EN["fichier_balance_cloture"]}))
    assert verdict["code"] == "REJ-QBO-FICHIER-INVALIDE" and verdict["fichier"] == "liste"


def test_un_refus_de_lecture_dit_quel_fichier(par_nom):
    dossier = m5_outils.dossier_imports_quickbooks()
    lignes = (dossier / EN["fichier_balance_cloture"]).read_text(encoding="utf-8-sig").replace(
        "Accrual Basis", "Cash Basis")
    (dossier / "tb_caisse.csv").write_text(lignes, encoding="utf-8")
    verdict = _verdict(_appeler(par_nom, "m5_analyser_exports_quickbooks", {
        "fichier_liste_comptes": EN["fichier_liste_comptes"], "fichier_balance_cloture": "tb_caisse.csv"}))
    assert verdict == {"code": "REJ-QBO-METHODE-CAISSE", "detail": verdict["detail"], "fichier": "cloture"}


def test_une_ecart_de_balance_est_rendu_a_l_analyse_et_bloque_l_import(dep, par_nom):
    dossier = m5_outils.dossier_imports_quickbooks()
    texte = (dossier / EN["fichier_balance_cloture"]).read_text(encoding="utf-8-sig")
    texte = texte.replace("Share capital,,100.00", "Share capital,,100.01").replace(
        'Sales,,"3,000.00"', 'Sales,,"2,999.99"')
    (dossier / "tb_ecart.csv").write_text(texte, encoding="utf-8")
    exports = {**EN, "fichier_balance_cloture": "tb_ecart.csv"}
    analyse_ = _accepte(_appeler(par_nom, "m5_analyser_exports_quickbooks", exports))
    assert analyse_["verification"]["refus"]["code"] == "REJ-QBO-BALANCE-ECART"
    _valider_correspondance(dep, EN["fichier_liste_comptes"], MANUELLES_EN)
    verdict = _verdict(_importer(dep, exports, date_reprise="2026-03-31"))
    assert verdict["code"] == "REJ-QBO-BALANCE-ECART" and len(verdict["ecarts"]) == 2
    assert _maillons("grand_livre") == 0


def test_correspondance_identique_non_reecrite_et_ancienne_version_perimee(dep):
    assert _valider_correspondance(dep, FR["fichier_liste_comptes"], MANUELLES_FR)["version"] == 1
    redite = _valider_correspondance(dep, FR["fichier_liste_comptes"], MANUELLES_FR)
    assert (redite["statut"], redite["version"]) == ("deja_validee", 1) and _maillons("import_quickbooks") == 1
    autre = _valider_correspondance(dep, FR["fichier_liste_comptes"], [
        *MANUELLES_FR, {"compte_qbo": "Ventes", "compte_opsys": "4900"}])
    assert autre["version"] == 2
    assert _verdict(_importer(dep, FR, date_reprise="2026-02-28", version=1))["code"] \
        == "REJ-QBO-CORRESPONDANCE-PERIMEE"
    assert _verdict(_importer(dep, FR, date_reprise="2026-02-28", version=3))["code"] \
        == "REJ-QBO-CORRESPONDANCE-INTROUVABLE"
    non_apparies = _par_la_file(dep, "m5_valider_correspondance_quickbooks", {
        "fichier_liste_comptes": FR["fichier_liste_comptes"], "correspondances_manuelles": [], "horodatage": H},
        attendu="echec")
    assert _verdict(non_apparies)["code"] == "REJ-QBO-COMPTES-NON-APPARIES"


def test_meme_numero_autre_contenu_conflit_sans_rien_ecrire(dep):
    _valider_correspondance(dep, FR["fichier_liste_comptes"], MANUELLES_FR)
    assert _accepte(_importer(dep, FR, date_reprise="2026-02-28"))["brouillons_crees"] == 6
    dossier = m5_outils.dossier_imports_quickbooks()
    texte = (dossier / FR["fichier_journal"]).read_text(encoding="cp1252").replace(
        "Frais février (fictif)", "Frais de février corrigés (fictif)")
    (dossier / "journal_modifie.csv").write_text(texte, encoding="cp1252")
    avant = (_maillons("grand_livre"), _maillons("import_quickbooks"))
    verdict = _verdict(_importer(dep, {**FR, "fichier_journal": "journal_modifie.csv"}, date_reprise="2026-02-28"))
    assert verdict["code"] == "REJ-QBO-TRANSACTION-CONFLIT" and verdict["transactions"][0].startswith(
        "Écriture de journal#EJ-2")
    assert (_maillons("grand_livre"), _maillons("import_quickbooks")) == avant


def test_la_saisie_manuelle_ne_fabrique_pas_de_piece_import_quickbooks(par_nom):
    arguments = {"date_effet": "2026-02-28", "libelle": "x", "piece_type": "import_quickbooks",
                 "piece_reference": "qbo:x", "horodatage": H,
                 "lignes": [{"compte": "5990", "debit": "1.00", "credit": None},
                            {"compte": "1010", "debit": None, "credit": "1.00"}]}
    assert _appeler(par_nom, "m5_proposer_ecriture_comptable", arguments)["erreur"] == "arguments_invalides"
    with stockage.transaction():  # et dans le code, si le schéma était contourné
        assert m5_outils.proposer_ecriture_comptable(**arguments)["verdict"]["code"] == "REJ-GL-PIECE-INVALIDE"
    assert _maillons("grand_livre") == 0


def test_une_grande_liste_de_comptes_tient_sous_la_limite_de_sortie(par_nom):
    dossier = m5_outils.dossier_imports_quickbooks()
    lignes = [["Account", "Type", "Detail Type"]] + [
        [f"Dépense fictive numéro {i:03d} à ventiler selon le CPA", "Expenses", "Other Miscellaneous Expense"]
        for i in range(150)] + [["Chequing", "Bank", "Chequing"]]
    tampon = io.StringIO(newline="")
    csv.writer(tampon, lineterminator="\r\n").writerows(lignes)
    (dossier / "grande_liste.csv").write_text(tampon.getvalue(), encoding="utf-8")
    (dossier / "petite_balance.csv").write_text(
        "Trial Balance\r\n\"As of March 31, 2026\"\r\n,Debit,Credit\r\nChequing,10.00,\r\n"
        "Dépense fictive numéro 000 à ventiler selon le CPA,,10.00\r\nTOTAL,10.00,10.00\r\n", encoding="utf-8")
    reponse = _appeler(par_nom, "m5_analyser_exports_quickbooks", {
        "fichier_liste_comptes": "grande_liste.csv", "fichier_balance_cloture": "petite_balance.csv", "limite": 20})
    corps = _accepte(reponse)
    assert len(json.dumps(reponse, ensure_ascii=False)) <= m5_outils.BUDGET_SORTIE
    assert corps["comptes_qbo"] == 151 and corps["correspondance_proposee"]["prochain_depart"] is not None
    assert corps["correspondance_proposee"]["non_apparies_reste"] == 130


def test_codes_de_refus_documentes():
    doc = (_RACINE_M5 / "docs" / "import-quickbooks.md").read_text(encoding="utf-8")
    absents = [code for code in import_quickbooks.CODES_QBO if f"`{code}`" not in doc]
    assert absents == []
