"""Import QuickBooks Online par les exports standard (`import_quickbooks.py`) : lecture, correspondance, vérification
au cent, idempotence. Module pur, registre en mémoire. Exports FICTIFS (`fixtures/quickbooks/MANIFESTE.yaml`, fictif:
true) et variantes construites ici à partir d'eux.
"""

from __future__ import annotations

import csv
import io
import zipfile
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
import yaml
from m5_financecore import grand_livre, plan_comptable
from m5_financecore import import_quickbooks as qbo
from m5_financecore import registre as registre_module

FICTIF = True
D = Decimal
_RACINE = Path(__file__).resolve().parents[1]
F = Path(__file__).resolve().parent / "fixtures" / "quickbooks"
H = "2026-04-02T10:00:00-04:00"
MANUELLES_EN = [{"compte_qbo": "Savings", "compte_opsys": "1010"},
                {"compte_qbo": "Office Supplies", "compte_opsys": "5990"}]
MANUELLES_FR = [{"compte_qbo": "Repas et représentation", "compte_opsys": "5990"}]


@pytest.fixture(scope="module")
def plan():
    base, refus = plan_comptable.charger_plan(_RACINE / "contracts" / "plan_comptable_pme_qc.v1.yaml")
    assert refus is None
    effectif, refus = plan_comptable.appliquer_extension(base, None)
    assert refus is None
    return effectif


def _octets(jeu, nom):
    return (F / jeu / nom).read_bytes()


def _csv(lignes, sep=",", enc="utf-8", bom=False):
    tampon = io.StringIO(newline="")
    csv.writer(tampon, delimiter=sep, lineterminator="\r\n").writerows(lignes)
    return (b"\xef\xbb\xbf" if bom else b"") + tampon.getvalue().encode(enc)


def _lignes(jeu, nom, enc="utf-8-sig", sep=","):
    return list(csv.reader(io.StringIO(_octets(jeu, nom).decode(enc), newline=""), delimiter=sep))


def _ok(couple):
    resultat, refus = couple
    assert refus is None, refus
    return resultat


def _code(couple):
    resultat, refus = couple
    assert resultat is None and refus is not None, resultat
    assert refus["code"] in qbo.CODES_QBO or refus["code"].startswith("REJ-GL-")
    return refus["code"]


EN = {"liste": "account_list.csv", "ouverture": "trial_balance_2025-12-31.csv",
      "journal": "journal_2026-01-01_2026-03-31.csv", "cloture": "trial_balance_2026-03-31.csv"}
FR = {"liste": "liste_des_comptes.csv", "journal": "journal_2026-01-01_2026-02-28.csv",
      "cloture": "balance_de_verification_2026-02-28.csv"}


def _rapports(jeu, **remplacements):
    noms = EN if jeu == "en" else FR
    octets = {role: _octets(jeu, nom) for role, nom in noms.items()}
    octets.update(remplacements)
    return {
        "liste": _ok(qbo.analyser_liste_comptes(octets["liste"])),
        "cloture": _ok(qbo.analyser_balance(octets["cloture"])),
        "journal": _ok(qbo.analyser_journal(octets["journal"])) if octets.get("journal") else None,
        "ouverture": _ok(qbo.analyser_balance(octets["ouverture"])) if octets.get("ouverture") else None,
    }


def _preparer(plan, rapports, manuelles, *, mode="detail", mois=12, date_reprise=None):
    correspondance = _ok(qbo.valider_correspondance(rapports["liste"], plan, manuelles))
    return qbo.preparer_import(
        liste=rapports["liste"], cloture=rapports["cloture"], journal=rapports["journal"],
        ouverture=rapports["ouverture"], correspondance=correspondance, plan=plan, mode=mode,
        date_reprise=date_reprise or rapports["cloture"]["date"], mois_fin_exercice=mois)


def _xlsx(lignes, nombres=True):
    """Un classeur .xlsx minimal (première feuille) : texte en chaînes partagées, montants en nombres si `nombres`."""
    partages: list[str] = []
    cellules_xml = []
    for r, ligne in enumerate(lignes, start=1):
        cellules = []
        for c, valeur in enumerate(ligne):
            if valeur == "":
                continue
            ref = f"{chr(65 + c)}{r}"
            brut = valeur.replace("$", "").replace(",", "")
            if nombres and brut.replace(".", "", 1).replace("-", "", 1).isdigit() and any(ch.isdigit() for ch in brut):
                cellules.append(f'<c r="{ref}"><v>{brut}</v></c>')
            else:
                partages.append(valeur)
                cellules.append(f'<c r="{ref}" t="s"><v>{len(partages) - 1}</v></c>')
        cellules_xml.append(f'<row r="{r}">{"".join(cellules)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as archive:
        archive.writestr("xl/workbook.xml", f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/'
                         'officeDocument/2006/relationships"><sheets><sheet name="Rapport" sheetId="1" r:id="rId1"/>'
                         '</sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/'
                         'package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" '
                         'Type="worksheet"/></Relationships>')
        archive.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(
            f"<si><t>{escape(t)}</t></si>" for t in partages) + "</sst>")
        archive.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{''.join(cellules_xml)}"
                         "</sheetData></worksheet>")
    return tampon.getvalue()


# ============================================================================================== lecture
def test_les_fixtures_sont_declarees_fictives():
    manifeste = yaml.safe_load((F / "MANIFESTE.yaml").read_text(encoding="utf-8"))
    assert manifeste["fictif"] is True
    for jeu, description in manifeste["jeux"].items():
        assert sorted(description["fichiers"]) == sorted(p.name for p in (F / jeu).iterdir())


def test_lecture_anglaise_utf8_bom_virgule_point_decimal():
    liste = _ok(qbo.analyser_liste_comptes(_octets("en", EN["liste"])))
    assert liste["lecture"]["encodage"] == "UTF-8 (BOM)" and liste["lecture"]["separateur"] == "virgule"
    assert len(liste["comptes"]) == 14 and liste["lecture"]["colonnes_ignorees"] == ["Description", "Balance"]
    classes = {c["nom"]: c["classe"] for c in liste["comptes"]}
    assert classes["Subcontractors"] == "charges" and classes["GST/HST Payable"] == "passif"
    cloture = _ok(qbo.analyser_balance(_octets("en", EN["cloture"])))
    assert cloture["date"] == "2026-03-31" and cloture["total_debits"] == D("40399.25")
    assert cloture["soldes"]["Retained Earnings"] == D("-31702.25") and cloture["soldes"]["Chequing"] == D("15487.00")
    assert cloture["lecture"]["methode"] == "exercice" and cloture["lecture"]["convention_montants"] == "point"
    assert cloture["lecture"]["lignes_ignorees"] == {"titre": 3, "pied": 1, "vides": 2, "totaux": 1}
    journal = _ok(qbo.analyser_journal(_octets("en", EN["journal"])))
    assert journal["lecture"]["convention_dates"] == "MM/JJ/AAAA" and len(journal["transactions"]) == 7
    assert journal["lecture"]["lignes_ignorees"]["totaux"] == 8  # sept totaux de transaction et le TOTAL final
    facture = journal["transactions"][0]
    assert (facture["cle"], facture["date"], facture["nom"]) == ("Invoice#1001", "2026-01-15", "Client Fictif A")
    assert [ligne["montant"] for ligne in facture["lignes"]] == [D("2299.50"), D("-2000.00"), D("-100.00"),
                                                                  D("-199.50")]


def test_lecture_francaise_cp1252_point_virgule_virgule_decimale():
    liste = _ok(qbo.analyser_liste_comptes(_octets("fr", FR["liste"])))
    assert liste["lecture"]["encodage"] == "Windows-1252" and liste["lecture"]["separateur"] == "point-virgule"
    assert liste["lecture"]["lignes_ignorees"]["titre"] == 2
    numeros = {c["nom"]: c["numero"] for c in liste["comptes"]}
    assert numeros["Comptes clients"] == "1100" and numeros["Desjardins — opérations"] is None
    cloture = _ok(qbo.analyser_balance(_octets("fr", FR["cloture"])))
    assert cloture["date"] == "2026-02-28" and cloture["lecture"]["convention_montants"] == "virgule"
    assert cloture["soldes"]["3100 Capital-actions"] == D("-10000.00")
    assert cloture["soldes"]["Desjardins — opérations"] == D("13146.81")
    journal = _ok(qbo.analyser_journal(_octets("fr", FR["journal"])))
    assert journal["lecture"]["convention_dates"] == "JJ/MM/AAAA"
    assert [t["date"] for t in journal["transactions"]][:2] == ["2026-01-02", "2026-01-15"]
    assert journal["total_debits"] == journal["total_credits"] == D("17280.94")


@pytest.mark.parametrize(("texte", "attendu", "convention"), [
    ("1,234.56", D("1234.56"), "point"), ("$1,234.56", D("1234.56"), "point"), ("1 234,56 $", D("1234.56"), "virgule"),
    ("1 234,56", D("1234.56"), "virgule"), ("1.234,56", D("1234.56"), "virgule"), ("(1,234.56)", D("-1234.56"),
                                                                                       "point"),
    ("-$45.00", D("-45.00"), "point"), ("$-45.00", D("-45.00"), "point"), ("(45,5 $)", D("-45.50"), "virgule"),
    ("1234", D("1234.00"), None), ("1,234", D("1234.00"), "point"), ("12,5", D("12.50"), "virgule"),
])
def test_montants_qbo(texte, attendu, convention):
    assert qbo._montant(texte) == (attendu, convention, None)


@pytest.mark.parametrize("texte", ["12.3456", "1,23,4", "abc", "--5", "(-5)", "12 $ 3", "1.2.3", "$", "5-"])
def test_montants_illisibles(texte):
    assert qbo._montant(texte)[2] is not None


def test_xlsx_lu_comme_le_csv_avec_artefacts_binaires_au_cent():
    lignes = _lignes("en", EN["cloture"])
    lignes[5][1] = "15486.999999999998"  # artefact de représentation binaire d'un nombre Excel : 15 487,00
    classeur = _ok(qbo.analyser_balance(_xlsx(lignes)))
    csv_ = _ok(qbo.analyser_balance(_octets("en", EN["cloture"])))
    assert classeur["lecture"]["format"] == "xlsx" and classeur["soldes"] == csv_["soldes"]
    journal = _lignes("en", EN["journal"])
    journal[5][1] = "46037"  # numéro de série Excel du 15 janvier 2026
    lu = _ok(qbo.analyser_journal(_xlsx(journal)))
    assert lu["transactions"][0]["date"] == "2026-01-15" and len(lu["transactions"]) == 7
    lignes[6][1] = "6000.004"  # pas un artefact : trois décimales réelles
    assert _code(qbo.analyser_balance(_xlsx(lignes))) == "REJ-QBO-MONTANT-INVALIDE"


# ============================================================================================== refus de lecture
def test_fichier_invalide_vide_ou_trop_gros():
    assert _code(qbo.analyser_balance(b"")) == "REJ-QBO-FICHIER-INVALIDE"
    assert _code(qbo.analyser_balance(b"x" * (qbo.OCTETS_MAX + 1))) == "REJ-QBO-FICHIER-INVALIDE"


@pytest.mark.parametrize("octets", [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 20, b"%PDF-1.7 ...",
                                    b"PK\x03\x04pas un classeur"])
def test_format_non_pris_en_charge(octets):
    assert _code(qbo.analyser_balance(octets)) == "REJ-QBO-FORMAT-NON-PRIS-EN-CHARGE"


def test_encodage_et_csv_illisibles():
    assert _code(qbo.analyser_balance(b"Account,Debit\x81\x8d\xff")) == "REJ-QBO-ENCODAGE"
    assert _code(qbo.analyser_balance(b'"a"b,c\n')) == "REJ-QBO-CSV-ILLISIBLE"


def test_utf16_avec_bom_accepte():
    texte = _octets("en", EN["cloture"]).decode("utf-8-sig")
    assert _ok(qbo.analyser_balance(texte.encode("utf-16")))["lecture"]["encodage"] == "UTF-16 (BOM)"


def test_entetes_inconnues_et_separateur_ambigu():
    resultats = _csv([["Toitures (fictif)"], ["Profit and Loss"], ["", "Total"], ["Sales", "3,000.00"]])
    assert _code(qbo.analyser_balance(resultats)) == "REJ-QBO-ENTETES-INCONNUES"
    ambigu = b"Compte;Type\r\nAccount,Type\r\nChequing,Bank\r\n"
    assert _code(qbo.analyser_liste_comptes(ambigu)) == "REJ-QBO-SEPARATEUR-AMBIGU"


def test_lignes_incomprises_nommees_par_leur_numero():
    lignes = _lignes("en", EN["cloture"])
    lignes.insert(7, ["", "10.00", ""])
    verdict = qbo.analyser_balance(_csv(lignes))[1]
    assert verdict["code"] == "REJ-QBO-LIGNE-INCOMPRISE" and verdict["ligne"] == 8
    lignes = _lignes("en", EN["cloture"])
    lignes[1] = ["Trial Balance", "en double"]
    assert _code(qbo.analyser_balance(_csv(lignes))) == "REJ-QBO-LIGNE-INCOMPRISE"
    journal = _lignes("en", EN["journal"])
    journal.insert(6, ["", "", "", "", "texte libre sans compte", "", "", "", ""])
    assert _code(qbo.analyser_journal(_csv(journal))) == "REJ-QBO-LIGNE-INCOMPRISE"


def test_montants_invalides_et_ambigus():
    lignes = _lignes("en", EN["cloture"])
    lignes[5][1] = "15,487.001"
    assert _code(qbo.analyser_balance(_csv(lignes))) == "REJ-QBO-MONTANT-INVALIDE"
    lignes = _lignes("en", EN["cloture"])
    lignes[5][2] = "1.00"
    assert _code(qbo.analyser_balance(_csv(lignes))) == "REJ-QBO-MONTANT-INVALIDE"  # débit ET crédit
    lignes = _lignes("en", EN["cloture"])
    lignes[17][1] = "12,50"  # virgule décimale dans un fichier au point décimal
    assert _code(qbo.analyser_balance(_csv(lignes))) == "REJ-QBO-MONTANT-AMBIGU"


def test_parentheses_negatives_dans_la_balance():
    lignes = _lignes("en", EN["cloture"])
    lignes[13] = ["Retained Earnings", "($31,702.25)", ""]  # un solde créditeur écrit en débit négatif
    lignes[18] = ["TOTAL", "$8,697.00", "$8,697.00"]  # le TOTAL de QBO additionne les colonnes telles qu'écrites
    cloture = _ok(qbo.analyser_balance(_csv(lignes)))
    assert cloture["soldes"]["Retained Earnings"] == D("-31702.25")
    lignes[18] = ["TOTAL", "$40,399.25", "$40,399.25"]
    assert _code(qbo.analyser_balance(_csv(lignes))) == "REJ-QBO-TOTAL-INCOHERENT"


def test_dates_invalides_ambigues_ou_introuvables():
    journal = _lignes("en", EN["journal"])
    journal[5][1] = "2026-02-30"
    assert _code(qbo.analyser_journal(_csv(journal))) == "REJ-QBO-DATE-INVALIDE"
    ambigu = _csv([["Date", "Transaction Type", "Num", "Account", "Debit", "Credit"],
                   ["01/02/2026", "Journal Entry", "1", "Chequing", "5.00", ""],
                   ["", "", "", "Sales", "", "5.00"],
                   ["03/04/2026", "Journal Entry", "2", "Chequing", "5.00", ""],
                   ["", "", "", "Sales", "", "5.00"]])
    assert _code(qbo.analyser_journal(ambigu)) == "REJ-QBO-DATE-AMBIGUE"
    explicite = _ok(qbo.analyser_journal(ambigu, "JJ/MM/AAAA"))
    assert [t["date"] for t in explicite["transactions"]] == ["2026-02-01", "2026-04-03"]
    melange = _csv([["Date", "Transaction Type", "Num", "Account", "Debit", "Credit"],
                    ["13/02/2026", "Journal Entry", "1", "Chequing", "5.00", ""], ["", "", "", "Sales", "", "5.00"],
                    ["02/13/2026", "Journal Entry", "2", "Chequing", "5.00", ""], ["", "", "", "Sales", "", "5.00"]])
    assert _code(qbo.analyser_journal(melange)) == "REJ-QBO-DATE-AMBIGUE"
    lignes = _lignes("en", EN["cloture"])
    lignes[2] = ["Prepared for the owner"]
    assert _code(qbo.analyser_balance(_csv(lignes))) == "REJ-QBO-DATE-INTROUVABLE"
    assert _code(qbo.analyser_journal(ambigu, "jj-mm")) == "REJ-QBO-CHAMP-INVALIDE"


def test_totaux_absent_incoherent_et_balance_desequilibree():
    lignes = _lignes("en", EN["cloture"])
    sans_total = [ligne for ligne in lignes if ligne[:1] != ["TOTAL"]]
    assert _code(qbo.analyser_balance(_csv(sans_total))) == "REJ-QBO-TOTAL-ABSENT"
    lignes[18] = ["TOTAL", "$40,399.26", "$40,399.25"]
    assert _code(qbo.analyser_balance(_csv(lignes))) == "REJ-QBO-TOTAL-INCOHERENT"
    lignes = _lignes("en", EN["cloture"])
    lignes[5][1] = "15,487.01"
    lignes[18] = ["TOTAL", "$40,399.26", "$40,399.25"]
    assert _code(qbo.analyser_balance(_csv(lignes))) == "REJ-QBO-BALANCE-DESEQUILIBREE"
    journal = _lignes("en", EN["journal"])
    journal[9] = ["", "", "", "", "", "", "", "$2,299.50", "$2,299.49"]  # total de la facture 1001 altéré
    assert _code(qbo.analyser_journal(_csv(journal))) == "REJ-QBO-TOTAL-INCOHERENT"


def test_methode_de_caisse_et_devise_refusees():
    lignes = _lignes("en", EN["cloture"])
    lignes[-1] = ["Cash Basis Thursday, April 2, 2026 09:10 AM GMT-04:00"]
    assert _code(qbo.analyser_balance(_csv(lignes))) == "REJ-QBO-METHODE-CAISSE"
    liste = _lignes("en", EN["liste"])
    liste[0].append("Currency")
    for ligne in liste[1:]:
        ligne.append("CAD")
    assert _ok(qbo.analyser_liste_comptes(_csv(liste)))
    liste[2][-1] = "USD"
    assert _code(qbo.analyser_liste_comptes(_csv(liste))) == "REJ-QBO-DEVISE-NON-GEREE"


def test_liste_type_inconnu_et_doublons():
    liste = _lignes("en", EN["liste"])
    liste[3][1] = "Crypto Wallet"
    verdict = qbo.analyser_liste_comptes(_csv(liste))[1]
    assert verdict["code"] == "REJ-QBO-TYPE-COMPTE-INCONNU" and verdict["comptes"] == [
        "Accounts Receivable (A/R) (Crypto Wallet)"]
    liste = _lignes("en", EN["liste"])
    liste.append(liste[1])
    assert _code(qbo.analyser_liste_comptes(_csv(liste))) == "REJ-QBO-COMPTE-DUPLIQUE"
    lignes = _lignes("en", EN["cloture"])
    lignes.insert(6, ["Chequing", "0.00", ""])
    assert _code(qbo.analyser_balance(_csv(lignes))) == "REJ-QBO-COMPTE-DUPLIQUE"


def _journal_minimal(lignes, entete=("Date", "Transaction Type", "Num", "Account", "Debit", "Credit")):
    return _csv([list(entete), *lignes])


def test_transactions_sans_numero_dupliquees_desequilibrees_trop_longues_ou_champ_trop_long():
    sans = _journal_minimal([["2026-01-05", "Deposit", "", "Chequing", "5.00", ""], ["", "", "", "Sales", "", "5.00"]])
    assert _code(qbo.analyser_journal(sans)) == "REJ-QBO-TRANSACTION-SANS-NUMERO"
    doublon = _journal_minimal([["2026-01-05", "Deposit", "D1", "Chequing", "5.00", ""],
                                ["", "", "", "Sales", "", "5.00"],
                                ["2026-01-06", "Deposit", "D1", "Chequing", "5.00", ""],
                                ["", "", "", "Sales", "", "5.00"]])
    assert _code(qbo.analyser_journal(doublon)) == "REJ-QBO-TRANSACTION-DUPLIQUEE"
    autre_type = _journal_minimal([["2026-01-05", "Deposit", "D1", "Chequing", "5.00", ""],
                                   ["", "", "", "Sales", "", "5.00"],
                                   ["2026-01-06", "Invoice", "D1", "Chequing", "5.00", ""],
                                   ["", "", "", "Sales", "", "5.00"]])
    assert len(_ok(qbo.analyser_journal(autre_type))["transactions"]) == 2
    boiteuse = _journal_minimal([["2026-01-05", "Deposit", "D1", "Chequing", "5.00", ""],
                                 ["", "", "", "Sales", "", "4.99"]])
    assert _code(qbo.analyser_journal(boiteuse)) == "REJ-QBO-TRANSACTION-DESEQUILIBREE"
    longue = [["2026-01-05", "Journal Entry", "JE-1", "Chequing", "51.00", ""]]
    longue += [["", "", "", "Sales", "", "1.00"] for _ in range(51)]
    assert _code(qbo.analyser_journal(_journal_minimal(longue))) == "REJ-QBO-TRANSACTION-TROP-LONGUE"
    long_num = _journal_minimal([["2026-01-05", "Deposit", "N" * 41, "Chequing", "5.00", ""],
                                 ["", "", "", "Sales", "", "5.00"]])
    assert _code(qbo.analyser_journal(long_num)) == "REJ-QBO-CHAMP-INVALIDE"


def test_lignes_et_transactions_nulles_ignorees_explicitement():
    journal = _journal_minimal([["2026-01-05", "Deposit", "D1", "Chequing", "5.00", ""],
                                ["", "", "", "Discounts", "0.00", ""], ["", "", "", "Sales", "", "5.00"],
                                ["2026-01-06", "Invoice", "0", "Accounts Receivable (A/R)", "0.00", ""],
                                ["", "", "", "Sales", "", "0.00"]])
    lu = _ok(qbo.analyser_journal(journal))
    assert len(lu["transactions"]) == 1 and len(lu["transactions"][0]["lignes"]) == 2
    assert lu["lecture"]["lignes_ignorees"]["lignes_nulles"] == 3
    assert lu["lecture"]["lignes_ignorees"]["transactions_nulles"] == 1


# ============================================================================================== correspondance
def test_correspondance_proposee_deterministe_et_expliquee(plan):
    anglais = _rapports("en")["liste"]
    proposition = qbo.proposer_correspondance(anglais, plan)
    assert proposition == qbo.proposer_correspondance(anglais, plan) and proposition["statut"] == "BROUILLON"
    par_nom = {ligne["compte_qbo"]: ligne for ligne in proposition["correspondances"]}
    assert (par_nom["Chequing"]["compte_opsys"], par_nom["Chequing"]["methode"]) == ("1010", "nom")
    assert par_nom["Subcontractors"]["compte_opsys"] == "5200" and "qbo-synonymes-v1" in par_nom["Sales"]["explication"]
    # Deux comptes de type Bank : la règle par type ne s'applique pas, Savings reste à choisir (jamais « divers »).
    assert par_nom["Savings"]["compte_opsys"] is None and "2 comptes QBO de type « Bank »" in par_nom["Savings"][
        "explication"]
    assert proposition["non_apparies"] == ["Office Supplies", "Savings"]
    francais = qbo.proposer_correspondance(_rapports("fr")["liste"], plan)
    par_nom = {ligne["compte_qbo"]: ligne for ligne in francais["correspondances"]}
    assert (par_nom["Comptes clients"]["compte_opsys"], par_nom["Comptes clients"]["methode"]) == ("1100", "numero")
    assert (par_nom["Desjardins — opérations"]["compte_opsys"], par_nom["Desjardins — opérations"]["methode"]) == (
        "1010", "type")
    assert francais["non_apparies"] == ["Repas et représentation"]


def test_correspondance_respecte_le_plan_effectif(plan):
    sans_loyer, _ = plan_comptable.appliquer_extension(plan, {"comptes_desactives": ["5600"]})
    proposition = qbo.proposer_correspondance(_rapports("en")["liste"], sans_loyer)
    assert "Rent or Lease" in proposition["non_apparies"]


def test_correspondance_validee_refuse_les_non_apparies_et_les_choix_invalides(plan):
    liste = _rapports("en")["liste"]
    verdict = qbo.valider_correspondance(liste, plan, [])[1]
    assert verdict["code"] == "REJ-QBO-COMPTES-NON-APPARIES" and verdict["comptes"] == ["Office Supplies", "Savings"]
    for manuelles in (
        [{"compte_qbo": "Savings", "compte_opsys": "9999"}],
        [{"compte_qbo": "Savings", "compte_opsys": "4100"}],  # un actif vers un compte de produits
        [{"compte_qbo": "Inconnu", "compte_opsys": "1010"}],
        [{"compte_qbo": "Savings", "compte_opsys": "1010"}, {"compte_qbo": "Savings", "compte_opsys": "1020"}],
        [{"compte_qbo": "Savings"}],
        "pas une liste",
    ):
        assert _code(qbo.valider_correspondance(liste, plan, manuelles)) == "REJ-QBO-CORRESPONDANCE-INVALIDE"
    validee = _ok(qbo.valider_correspondance(liste, plan, MANUELLES_EN))
    assert validee["table"]["Savings"] == "1010" and validee["table"]["Office Supplies"] == "5990"
    remplace = _ok(qbo.valider_correspondance(liste, plan, [*MANUELLES_EN, {"compte_qbo": "Sales",
                                                                             "compte_opsys": "4900"}]))
    assert remplace["table"]["Sales"] == "4900" and remplace["empreinte_correspondance"] != validee[
        "empreinte_correspondance"]


def test_empreinte_de_liste_stable_au_reexport_et_sensible_aux_comptes():
    liste = _lignes("en", EN["liste"])
    base = qbo.empreinte_liste(_ok(qbo.analyser_liste_comptes(_csv(liste))))
    liste[1][4] = "99.99"  # solde différent : même ensemble de comptes
    assert qbo.empreinte_liste(_ok(qbo.analyser_liste_comptes(_csv(liste)))) == base
    liste.append(["Fuel", "Expenses", "Auto", "", ""])
    assert qbo.empreinte_liste(_ok(qbo.analyser_liste_comptes(_csv(liste)))) != base


# ============================================================================================== vérification et import
def test_detail_anglais_ouverture_reportee_aux_bnr_egale_la_balance_au_cent(plan):
    prepare = _ok(_preparer(plan, _rapports("en"), MANUELLES_EN))
    verification = prepare["verification"]
    assert verification["type"] == "ouverture_et_journal" and verification["egale_au_cent"] is True
    assert verification["report_resultats_bnr"] is True and verification["transactions"] == 7
    assert verification["total_debits_recalcule"] == verification["total_debits_balance_qbo"] == "40399.25"
    ouverture = prepare["propositions"][0]
    assert ouverture["date_effet"] == "2025-12-31" and ouverture["piece"]["type"] == "import_quickbooks"
    # 2025 : produits 60 000,00 - charges 37 297,75 = 22 702,25 reportés aux BNR (9 000,00 + 22 702,25).
    assert {"compte": "3200", "debit": None, "credit": "31702.25"} in ouverture["lignes_brutes"]
    assert not any(ligne["compte"] in ("4100", "5200", "5600", "5800", "5990") for ligne in ouverture["lignes_brutes"])
    facture = prepare["propositions"][1]
    assert facture["cle_piece"] == "import_quickbooks:transaction:Invoice#1001"
    assert facture["piece"]["reference"].startswith("qbo:Invoice#1001@")
    assert facture["libelle"] == "QuickBooks Invoice n° 1001 — Client Fictif A"
    assert prepare["attendu_opsys"]["1010"] == D("21487.00")  # Chequing + Savings regroupés par choix manuel


def test_detail_francais_depuis_l_ouverture_de_l_entreprise(plan):
    prepare = _ok(_preparer(plan, _rapports("fr"), MANUELLES_FR))
    assert prepare["verification"]["type"] == "journal" and len(prepare["propositions"]) == 6
    assert prepare["attendu_opsys"] == {"1010": D("13146.81"), "2100": D("-80.00"), "2300": D("-137.50"),
                                        "2310": D("-274.31"), "3100": D("-10000.00"), "4100": D("-3000.00"),
                                        "5400": D("250.00"), "5800": D("15.00"), "5990": D("80.00")}


def test_mode_ouverture_une_seule_ecriture_au_solde_de_la_balance(plan):
    sans_journal = _rapports("fr", journal=None)
    prepare = _ok(_preparer(plan, sans_journal, MANUELLES_FR, mode="ouverture"))
    assert prepare["verification"]["type"] == "interne" and prepare["verification"]["egale_au_cent"] is False
    (ecriture,) = prepare["propositions"]
    assert ecriture["date_effet"] == "2026-02-28" and ecriture["cle_piece"] == "import_quickbooks:ouverture:2026-02-28"
    assert {"compte": "1010", "debit": "13146.81", "credit": None} in ecriture["lignes_brutes"]
    avec_journal = _ok(_preparer(plan, _rapports("fr"), MANUELLES_FR, mode="ouverture"))
    assert avec_journal["verification"]["type"] == "journal" and len(avec_journal["propositions"]) == 1


def test_un_ecart_compte_par_compte_bloque_meme_si_les_totaux_concordent(plan):
    lignes = _lignes("en", EN["cloture"])
    lignes[12] = ["Share capital", "", "100.01"]  # +0,01 ici,
    lignes[14] = ["Sales", "", "2,999.99"]  # -0,01 là : totaux inchangés
    rapports = _rapports("en", cloture=_csv(lignes))
    verdict = _preparer(plan, rapports, MANUELLES_EN)[1]
    assert verdict["code"] == "REJ-QBO-BALANCE-ECART"
    assert verdict["ecarts"] == [
        {"compte_qbo": "Sales", "balance_qbo": "-2999.99", "recalcule": "-3000.00", "ecart": "-0.01"},
        {"compte_qbo": "Share capital", "balance_qbo": "-100.01", "recalcule": "-100.00", "ecart": "0.01"}]


def test_un_compte_absent_de_la_balance_est_un_ecart(plan):
    lignes = [ligne for ligne in _lignes("en", EN["cloture"]) if ligne[:1] != ["Bank Charges"]]
    lignes[5] = ["Chequing", "15,499.50", ""]  # la balance reste équilibrée, le journal ne concorde plus avec elle
    verdict = _preparer(plan, _rapports("en", cloture=_csv(lignes)), MANUELLES_EN)[1]
    assert verdict["code"] == "REJ-QBO-BALANCE-ECART"
    assert {e["compte_qbo"] for e in verdict["ecarts"]} == {"Bank Charges", "Chequing"}


def test_sans_report_aux_bnr_l_ouverture_de_l_exercice_ne_concorde_pas(plan):
    # Une ouverture au 30 novembre (pas une fin d'exercice) : rien n'est reporté, et la balance du 31 mars ne
    # concorde pas (les résultats de 2025 resteraient dans les comptes de résultats).
    lignes = _lignes("en", EN["ouverture"])
    lignes[2] = ["As of November 30, 2025"]
    verdict = _preparer(plan, _rapports("en", ouverture=_csv(lignes)), MANUELLES_EN, mois=12)[1]
    assert verdict["code"] == "REJ-QBO-BALANCE-ECART"
    assert "Retained Earnings" in {e["compte_qbo"] for e in verdict["ecarts"]}


def test_refus_de_mode_de_date_et_d_exercice(plan):
    anglais = _rapports("en")
    assert _code(_preparer(plan, anglais, MANUELLES_EN, mode="tout")) == "REJ-QBO-MODE-INVALIDE"
    assert _code(_preparer(plan, {**anglais, "journal": None}, MANUELLES_EN)) == "REJ-QBO-MODE-INVALIDE"
    assert _code(_preparer(plan, {**anglais, "journal": None}, MANUELLES_EN, mode="ouverture")) \
        == "REJ-QBO-MODE-INVALIDE"  # une balance d'ouverture sans journal ne prouve rien
    assert _code(_preparer(plan, anglais, MANUELLES_EN, date_reprise="2026-03-30")) \
        == "REJ-QBO-DATE-REPRISE-DIFFERENTE"
    assert _code(_preparer(plan, anglais, MANUELLES_EN, mois=None)) == "REJ-QBO-EXERCICE-INCONNU"
    assert _code(_preparer(plan, anglais, MANUELLES_EN, mois=13)) == "REJ-QBO-EXERCICE-INCONNU"
    francais = _rapports("fr")
    assert _code(_preparer(plan, francais, MANUELLES_FR, mois=1)) == "REJ-QBO-EXERCICES-MULTIPLES"
    assert _ok(_preparer(plan, francais, MANUELLES_FR, mois=None))  # sans exercice déclaré, l'égalité tranche
    tardive = _lignes("en", EN["journal"])
    tardive[-7][1] = "04/01/2026"  # JE-7 daté après la balance de clôture
    assert _code(_preparer(plan, _rapports("en", journal=_csv(tardive)), MANUELLES_EN)) == "REJ-QBO-DATE-HORS-PERIODE"
    ouverture = _lignes("en", EN["ouverture"])
    ouverture[2] = ["As of March 31, 2026"]
    assert _code(_preparer(plan, _rapports("en", ouverture=_csv(ouverture)), MANUELLES_EN)) \
        == "REJ-QBO-DATE-HORS-PERIODE"


def test_bnr_introuvable_pour_le_report(plan):
    liste = _lignes("en", EN["liste"])
    liste[9] = ["Owner Equity", "Equity", "Owner's Equity", "", ""]
    lignes_ouv = [["Owner Equity" if c == "Retained Earnings" else c for c in ligne]
                  for ligne in _lignes("en", EN["ouverture"])]
    lignes_clo = [["Owner Equity" if c == "Retained Earnings" else c for c in ligne]
                  for ligne in _lignes("en", EN["cloture"])]
    rapports = _rapports("en", liste=_csv(liste), ouverture=_csv(lignes_ouv), cloture=_csv(lignes_clo))
    manuelles = [*MANUELLES_EN, {"compte_qbo": "Owner Equity", "compte_opsys": "3200"}]
    assert _code(_preparer(plan, rapports, manuelles)) == "REJ-QBO-BNR-INTROUVABLE"


def test_compte_hors_liste_et_correspondance_perimee(plan):
    lignes = [["Petty Cash" if c == "Bank Charges" else c for c in ligne] for ligne in _lignes("en", EN["cloture"])]
    assert _code(_preparer(plan, _rapports("en", cloture=_csv(lignes)), MANUELLES_EN)) == "REJ-QBO-COMPTE-HORS-LISTE"
    anglais = _rapports("en")
    correspondance = _ok(qbo.valider_correspondance(anglais["liste"], plan, MANUELLES_EN))
    liste = _lignes("en", EN["liste"])
    liste.append(["Fuel", "Expenses", "Auto", "", ""])
    autre_liste = _ok(qbo.analyser_liste_comptes(_csv(liste)))
    arguments = {"cloture": anglais["cloture"], "journal": anglais["journal"], "ouverture": anglais["ouverture"],
                 "plan": plan, "mode": "detail", "date_reprise": "2026-03-31", "mois_fin_exercice": 12}
    assert _code(qbo.preparer_import(liste=autre_liste, correspondance=correspondance, **arguments)) \
        == "REJ-QBO-CORRESPONDANCE-PERIMEE"
    sans_loyer, _ = plan_comptable.appliquer_extension(plan, {"comptes_desactives": ["5600"]})
    assert _code(qbo.preparer_import(liste=anglais["liste"], correspondance=correspondance,
                                     **{**arguments, "plan": sans_loyer})) == "REJ-QBO-CORRESPONDANCE-PERIMEE"


def test_ecriture_d_ouverture_de_plus_de_cinquante_comptes_refusee():
    base, _ = plan_comptable.charger_plan(_RACINE / "contracts" / "plan_comptable_pme_qc.v1.yaml")
    ajoutes = [{"numero": f"6{index:03d}", "nom": f"Charge fictive {index}", "type": "charges"} for index in range(60)]
    grand, _ = plan_comptable.appliquer_extension(base, {"comptes_ajoutes": ajoutes})
    liste = [["Account", "Type"], ["Chequing", "Bank"]] + [[f"Charge {i}", "Expenses"] for i in range(55)]
    balance = [["Trial Balance"], ["As of 2026-03-31"], ["", "Debit", "Credit"], ["Chequing", "", "55.00"]]
    balance += [[f"Charge {i}", "1.00", ""] for i in range(55)] + [["TOTAL", "55.00", "55.00"]]
    rapports = {"liste": _ok(qbo.analyser_liste_comptes(_csv(liste))),
                "cloture": _ok(qbo.analyser_balance(_csv(balance))), "journal": None, "ouverture": None}
    manuelles = [{"compte_qbo": f"Charge {i}", "compte_opsys": f"6{i:03d}"} for i in range(55)]
    assert _code(_preparer(grand, rapports, manuelles, mode="ouverture")) == "REJ-QBO-ECRITURE-TROP-LONGUE"


# ============================================================================================== idempotence
def _importer(registre, plan, prepare):
    etat = grand_livre.etat_grand_livre(registre.lire())
    compare, refus = qbo.comparer_au_grand_livre(prepare["propositions"], etat, plan)
    if refus is not None:
        return None, refus
    return grand_livre.proposer_ecritures_lot(registre, plan, propositions=compare["nouvelles"], horodatage=H,
                                              origine="import_quickbooks")


def test_reimporter_le_meme_fichier_ou_un_reexport_identique_ne_cree_rien(plan):
    registre = registre_module.Registre()
    premier = _ok(_importer(registre, plan, _ok(_preparer(plan, _rapports("fr"), MANUELLES_FR))))
    assert len(premier["proposees"]) == 6 and registre.taille() == 6
    assert premier["proposees"][0]["piece"]["verification"] == "declaree_non_verifiee"
    redite = _ok(_importer(registre, plan, _ok(_preparer(plan, _rapports("fr"), MANUELLES_FR))))
    assert redite["proposees"] == [] and registre.taille() == 6
    journal = _lignes("fr", FR["journal"], enc="cp1252", sep=";")
    journal[-1] = ["Comptabilité d'exercice vendredi 6 mars 2026 14 h 02 HNE"]  # nouvel export : autre empreinte
    reexport = _rapports("fr", journal=_csv(journal, sep=";", enc="cp1252"))
    assert reexport["journal"]["lecture"]["sha256"] != _rapports("fr")["journal"]["lecture"]["sha256"]
    assert _ok(_importer(registre, plan, _ok(_preparer(plan, reexport, MANUELLES_FR))))["proposees"] == []
    assert registre.taille() == 6


def test_meme_numero_de_transaction_autre_contenu_est_un_conflit_type(plan):
    registre = registre_module.Registre()
    _ok(_importer(registre, plan, _ok(_preparer(plan, _rapports("fr"), MANUELLES_FR))))
    journal = _lignes("fr", FR["journal"], enc="cp1252", sep=";")
    journal[5][4] = "Mise de fonds corrigée (fictif)"  # EJ-1 : même numéro, autre mémo
    modifie = _rapports("fr", journal=_csv(journal, sep=";", enc="cp1252"))
    verdict = _importer(registre, plan, _ok(_preparer(plan, modifie, MANUELLES_FR)))[1]
    assert verdict["code"] == "REJ-QBO-TRANSACTION-CONFLIT" and verdict["transactions"][0].startswith(
        "Écriture de journal#EJ-1")
    assert registre.taille() == 6, "tout ou rien : aucun brouillon de plus"


def test_lot_tout_ou_rien_et_validation_en_lot(plan):
    registre = registre_module.Registre()
    prepare = _ok(_preparer(plan, _rapports("fr"), MANUELLES_FR))
    boiteux = [*prepare["propositions"][:2], {**prepare["propositions"][2], "date_effet": "2026-02-31"}]
    assert _code(_importer(registre, plan, {"propositions": boiteux})) == "REJ-GL-DATE-INVALIDE"
    assert registre.taille() == 0
    ecrit = _ok(_importer(registre, plan, prepare))
    ids = [e["ecriture_id"] for e in ecrit["proposees"]]
    etat = grand_livre.etat_grand_livre(registre.lire())
    brouillons, empreinte = qbo.empreinte_lot(etat, ids)
    assert brouillons == ids
    humain = {"par": "comptable", "role": "finance", "voie": "approbation"}
    resultat = _ok(grand_livre.valider_ecritures_lot(registre, plan, ecriture_ids=ids, humain=humain, horodatage=H))
    assert (resultat["validees"], resultat["premier_numero"], resultat["dernier_numero"]) == (6, 1, 6)
    etat = grand_livre.etat_grand_livre(registre.lire())
    assert qbo.empreinte_lot(etat, ids)[0] == [] and qbo.empreinte_lot(etat, ids)[1] != empreinte
    balance = _ok(grand_livre.balance_verification(etat, plan, "2026-02-28", limite=50))
    soldes = {c["compte"]: (c["solde"], c["cote"]) for c in balance["comptes"]}
    assert soldes["1010"] == ("13146.81", "debiteur") and soldes["2310"] == ("274.31", "crediteur")
    assert _code(grand_livre.valider_ecritures_lot(registre, plan, ecriture_ids=ids, humain=humain,
                                                   horodatage=H)) == "REJ-GL-ECRITURE-DEJA-VALIDEE"


def test_catalogue_ferme():
    with pytest.raises(qbo.CodeImportQuickbooksInconnu):
        qbo.construire_verdict("REJ-QBO-INVENTE")
    assert len(set(qbo.CODES_QBO)) == len(qbo.CODES_QBO)
