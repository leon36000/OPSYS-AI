"""Dossier CPA : paquet déterministe, scellé, liste de contrôle honnête, injection de formule neutralisée. Fictif."""

from __future__ import annotations

import csv
import io
import json
import random
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import (
    dossier_cpa,
    grand_livre,
    plan_comptable,
    taux_fiscaux,
)
from m5_financecore import (
    operations_comptables as oc,
)
from m5_financecore import (
    operations_registre as ore,
)
from m5_financecore import registre as registre_module

FICTIF = True
D = Decimal
_M5 = Path(__file__).resolve().parents[1]
H = "2026-11-02T10:00:00-04:00"
HUMAIN = {"par": "comptable", "role": "finance", "voie": "approbation"}
TETES = {"grand_livre": "t1", "operations": "t2"}


@pytest.fixture
def plan():
    base, refus = plan_comptable.charger_plan(_M5 / "contracts" / "plan_comptable_pme_qc.v1.yaml")
    assert refus is None
    return base


@pytest.fixture(scope="module")
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_M5 / "contracts" / "taux_fiscaux.v1.yaml")
    assert erreurs == []
    return dictionnaire


def ecrire(gl, plan, ref, jour, lignes, libelle="Écriture (fictive)", valider=True, piece="manuelle"):
    resultat, refus = grand_livre.proposer_ecriture(
        gl,
        plan,
        cle_piece=f"saisie:{piece}:{ref}",
        piece={"type": piece, "reference": ref},
        nature="saisie",
        date_effet=jour,
        libelle=libelle,
        lignes_brutes=lignes,
        horodatage=H,
        origine="saisie",
    )
    assert refus is None, refus
    ident = resultat["ecriture"]["ecriture_id"]
    if valider:
        assert grand_livre.valider_ecriture(gl, plan, ecriture_id=ident, humain=HUMAIN, horodatage=H)[1] is None
    return ident


def L(compte, debit=None, credit=None):
    return {"compte": compte, "debit": debit, "credit": credit}


@pytest.fixture
def monde(plan):
    gl, ops = registre_module.Registre(), registre_module.Registre()
    ecrire(gl, plan, "CAP", "2026-09-01", [L("1010", "5000.00"), L("3100", credit="5000.00")], "Capital initial")
    ecrire(
        gl,
        plan,
        "V1",
        "2026-10-05",
        [L("1100", "114.98"), L("4100", credit="100.00"), L("2300", credit="5.00"), L("2310", credit="9.98")],
        "Facture V1",
    )
    ecrire(
        gl,
        plan,
        "A1",
        "2026-10-09",
        [L("5400", "100.00"), L("1400", "5.00"), L("1410", "9.98"), L("2100", credit="114.98")],
        "Achat carburant",
    )
    ecrire(gl, plan, "FORM", "2026-10-12", [L("5990", "10.00"), L("1010", credit="10.00")], '=HYPERLINK("http://x")')
    ecrire(gl, plan, "BROU", "2026-10-20", [L("5990", "3.00"), L("1010", credit="3.00")], "Brouillon", valider=False)
    ecrire(gl, plan, "HORS", "2026-11-03", [L("5990", "99.00"), L("1010", credit="99.00")], "Hors période")
    return gl, ops


def construire(gl, ops, plan, **changes):
    args = {
        "debut": "2026-10-01",
        "fin": "2026-10-31",
        "date_reference": "2026-11-02",
        "etat_gl": grand_livre.etat_grand_livre(gl.lire()),
        "plan": plan,
        "etat_ops": ore.etat_operations(ops.lire()),
        "factures_clients": [],
        "factures_fournisseurs": [],
        "controle_taxes": None,
        "resume_base_fiscale": None,
        "tetes": TETES,
    }
    args.update(changes)
    resultat, refus = dossier_cpa.construire_dossier(**args)
    assert refus is None, refus
    return resultat


def lire_csv(octets):
    return list(csv.reader(io.StringIO(octets.decode("utf-8"))))


def test_les_quatorze_fichiers_et_le_manifeste_sont_la(monde, plan):
    d = construire(*monde, plan)
    assert set(d["fichiers"]) == set(dossier_cpa.noms_fichiers()) | {"MANIFESTE.json"}
    assert {f["nom"] for f in d["manifeste"]["fichiers"]} == set(dossier_cpa.noms_fichiers())
    assert d["manifeste"]["statut"] == "BROUILLON_POUR_CPA" and d["scelle"] == d["manifeste"]["scelle"]


def test_balance_grand_livre_et_periode_sont_justes(monde, plan):
    d = construire(*monde, plan)
    balance = {r[0]: r for r in lire_csv(d["fichiers"]["01-balance-verification.csv"])[1:]}
    assert balance["TOTAL"][3] == balance["TOTAL"][4]  # débits = crédits (cumul au 31 octobre)
    assert balance["1010"][5] == "4990.00" and balance["2100"][6] == "114.98"
    assert "99.00" not in d["fichiers"]["01-balance-verification.csv"].decode()  # écriture de novembre exclue
    lignes = lire_csv(d["fichiers"]["03-grand-livre.csv"])[1:]
    assert {ligne[0] for ligne in lignes} <= {f"2026-10-{j:02d}" for j in range(1, 32)} and len(lignes) == 4 + 4 + 2
    ouverture = {r[0]: r for r in lire_csv(d["fichiers"]["02-soldes-ouverture.csv"])[1:]}
    assert ouverture["1010"][2] == "5000.00" and ouverture["3100"][3] == "5000.00"
    brouillons = lire_csv(d["fichiers"]["04-brouillons-en-attente.csv"])[1:]
    assert len(brouillons) == 1 and brouillons[0][4] == "3.00"


def test_deterministe_octet_pour_octet_quel_que_soit_l_ordre_des_listes(monde, plan):
    premier = construire(*monde, plan)
    autre = construire(*monde, plan)
    assert premier["fichiers"] == autre["fichiers"] and premier["scelle"] == autre["scelle"]
    # l'ordre d'entrée des factures n'y change rien
    fournisseurs = [
        {
            "facture_fournisseur_id": f"ff-{i}",
            "fournisseur_id": "F",
            "numero_facture": str(i),
            "date_facture": "2026-10-03",
            "po_id": None,
            "montant_avant_taxes": D("10.00"),
            "total_taxes": D("1.50"),
            "montant_apres_taxes": D("11.50"),
            "statut": "SAISIE",
            "modifications": [],
        }
        for i in range(5)
    ]
    a = construire(*monde, plan, factures_fournisseurs=fournisseurs)
    melange = list(fournisseurs)
    random.Random(7).shuffle(melange)
    b = construire(*monde, plan, factures_fournisseurs=melange)
    assert a["scelle"] == b["scelle"] and a["fichiers"] == b["fichiers"]


def test_le_sceau_couvre_les_fichiers_les_tetes_de_registre_et_la_periode(monde, plan):
    d = construire(*monde, plan)
    assert construire(*monde, plan, tetes={"grand_livre": "t1-autre", "operations": "t2"})["scelle"] != d["scelle"]
    assert construire(*monde, plan, fin="2026-11-05")["scelle"] != d["scelle"]
    contenus = {nom: d["fichiers"][nom] for nom in dossier_cpa.noms_fichiers()}
    assert dossier_cpa.verifier_fichiers(d["manifeste"], contenus)["conforme"] is True
    truque = {
        **contenus,
        "01-balance-verification.csv": contenus["01-balance-verification.csv"].replace(b"4990.00", b"9990.00"),
    }
    verdict = dossier_cpa.verifier_fichiers(d["manifeste"], truque)
    assert verdict["conforme"] is False and verdict["alteres"] == ["01-balance-verification.csv"]
    manquant = {n: c for n, c in contenus.items() if n != "03-grand-livre.csv"}
    assert dossier_cpa.verifier_fichiers(d["manifeste"], manquant)["manquants"] == ["03-grand-livre.csv"]
    surplus = {**contenus, "99-extra.txt": b"x"}
    assert dossier_cpa.verifier_fichiers(d["manifeste"], surplus)["inattendus"] == ["99-extra.txt"]
    # un manifeste qui MENT sur ses empreintes ne trompe pas : le sceau est recalculé depuis les fichiers réels
    menteur = json.loads(json.dumps(d["manifeste"]))
    menteur["fichiers"][0]["sha256"] = "0" * 64
    assert dossier_cpa.verifier_fichiers(menteur, contenus)["conforme"] is False


def test_les_cellules_de_formule_sont_neutralisees_dans_les_csv(monde, plan):
    d = construire(*monde, plan)
    texte = d["fichiers"]["03-grand-livre.csv"].decode()
    assert "'=HYPERLINK" in texte
    for nom, octets in d["fichiers"].items():
        if nom.endswith(".csv"):
            for ligne in lire_csv(octets)[1:]:
                for cellule in ligne:
                    assert not cellule.startswith(("=", "+", "@", "\t", "\r")), (nom, cellule)


def test_releves_de_taxes_prepares_sans_ligne_de_formulaire_officiel(monde, plan):
    d = construire(*monde, plan)
    releve = json.loads(d["fichiers"]["06-releves-taxes-preparees.json"])
    assert releve["mois"][0]["mois"] == "2026-10" and releve["total"]["tps_nette"] == "0.00"
    assert releve["total"]["tps_percue"] == "5.00" and releve["total"]["tvq_rti"] == "9.98"
    assert releve["lignes_du_formulaire_officiel"] == "non renseigné — source officielle requise"
    assert "pas une déclaration" in releve["nature"] and "CPA" in releve["mention"]


def test_liste_de_controle_ne_pretend_jamais_a_une_attestation(monde, plan):
    d = construire(*monde, plan)
    par_id = {i["id"]: i for i in d["liste_de_controle"]}
    assert par_id["mission_et_attestation"]["statut"] == "A_FAIRE"
    assert "juridiques" in par_id["mission_et_attestation"]["detail"]
    assert (
        par_id["periode_close"]["statut"] == "A_FAIRE" and par_id["aucun_brouillon_en_attente"]["statut"] == "A_FAIRE"
    )
    assert par_id["balance_equilibree"]["statut"] == "FAIT"
    assert par_id["rapprochement_bancaire_confirme"]["statut"] == "A_FAIRE"
    assert par_id["regles_fiscales_du_depot"]["statut"] == "A_VERIFIER"
    lisez = d["fichiers"]["00-LISEZ-MOI.txt"].decode()
    assert "ni une compilation, ni un examen, ni un audit" in lisez and "juridiques" in lisez
    assert "À valider auprès d'un comptable (CPA) / professionnel qualifié" in lisez


def test_la_liste_passe_a_fait_quand_les_gestes_humains_sont_faits(monde, plan):
    gl, ops = monde
    # on retire le brouillon et la écriture hors période de l'équation : on clôt octobre après avoir validé le brouillon
    etat = grand_livre.etat_grand_livre(gl.lire())
    brouillons = [i for i, e in etat["ecritures"].items() if e["statut"] == "BROUILLON"]
    for ident in brouillons:
        assert grand_livre.valider_ecriture(gl, plan, ecriture_id=ident, humain=HUMAIN, horodatage=H)[1] is None
    # la écriture de novembre (déjà validée) empêche de clore novembre, mais octobre se clôt
    assert grand_livre.clore_periode(gl, periode="2026-10", humain=HUMAIN, horodatage=H)[1] is None
    rap = ore.ajouter_operation(
        ops,
        ore.etat_operations(ops.lire()),
        "op_rapprochement_prepare",
        "r:1",
        {
            "periode_debut": "2026-10-01",
            "periode_fin": "2026-10-31",
            "etat": "EQUILIBRE",
            "ecart": "0.00",
            "solde_releve": "1.00",
            "solde_livre": "1.00",
            "releve": {"nom": "x.csv"},
            "depots_en_transit": "0.00",
            "cheques_en_circulation": "0.00",
            "non_comptabilise": "0.00",
            "appariements": 3,
            "recu_empreinte": "e" * 64,
        },
        H,
    )[0]["operation"]
    ore.ajouter_operation(
        ops,
        ore.etat_operations(ops.lire()),
        "op_rapprochement_confirme",
        "c:1",
        {"rapprochement_vise": rap["rapprochement_id"], "par": "comptable", "role": "finance", "motif_ecart": None},
        H,
    )
    d = construire(gl, ops, plan, controle_taxes={"verdict": "CONCORDANT"})
    par_id = {i["id"]: i["statut"] for i in d["liste_de_controle"]}
    assert par_id["periode_close"] == par_id["aucun_brouillon_en_attente"] == "FAIT"
    assert par_id["rapprochement_bancaire_confirme"] == par_id["taxes_rapprochees"] == "FAIT"
    assert par_id["mission_et_attestation"] == "A_FAIRE"  # jamais « fait » par OPSYS
    rapprochements = json.loads(d["fichiers"]["05-rapprochements-bancaires.json"])["rapprochements"]
    assert rapprochements[0]["confirme"]["par"] == "comptable"


def test_journal_des_corrections_reunit_contre_passations_corrections_et_notes_de_credit(monde, plan, taux):
    gl, ops = monde
    ident = [
        i for i, e in grand_livre.etat_grand_livre(gl.lire())["ecritures"].items() if e["piece"]["reference"] == "FORM"
    ][0]
    assert (
        grand_livre.proposer_contre_passation(
            gl, plan, ecriture_id=ident, date_effet="2026-10-15", motif="erreur de saisie", horodatage=H
        )[1]
        is None
    )
    facture_f = {
        "facture_fournisseur_id": "ff-1",
        "fournisseur_id": "F",
        "numero_facture": "1",
        "date_facture": "2026-10-03",
        "po_id": None,
        "montant_avant_taxes": D("10.00"),
        "total_taxes": D("1.50"),
        "montant_apres_taxes": D("11.50"),
        "statut": "CORRIGEE",
        "modifications": [
            {
                "modification_id": "m1",
                "type": "CORRECTION",
                "par": "comptable",
                "role": "finance",
                "voie": "appareil",
                "motif": "montant mal lu",
                "horodatage": "2026-10-20T10:00:00-04:00",
            }
        ],
    }
    d = construire(gl, ops, plan, factures_fournisseurs=[facture_f])
    genres = [(r[1], r[3]) for r in lire_csv(d["fichiers"]["09-journal-des-corrections.csv"])[1:]]
    assert ("contre_passation", genres[0][1]) in genres or genres[0][0] == "contre_passation"
    assert any(g == "correction_facture_fournisseur" and m == "montant mal lu" for g, m in genres)


def test_periode_invalide_ou_demesuree_refusee(monde, plan):
    gl, ops = monde
    for changes in (
        {"debut": "2026-10-31", "fin": "2026-10-01"},
        {"debut": "2026-13-01"},
        {"fin": "demain"},
        {"date_reference": "2026-02-30"},
        {"debut": "2020-01-01", "fin": "2026-10-31"},
    ):
        resultat, refus = dossier_cpa.construire_dossier(
            **{
                "debut": "2026-10-01",
                "fin": "2026-10-31",
                "date_reference": "2026-11-02",
                "etat_gl": grand_livre.etat_grand_livre(gl.lire()),
                "plan": plan,
                "etat_ops": ore.etat_operations(ops.lire()),
                "factures_clients": [],
                "factures_fournisseurs": [],
                "controle_taxes": None,
                "resume_base_fiscale": None,
                "tetes": TETES,
                **changes,
            }
        )
        assert resultat is None and refus["code"] == "REJ-DOSSIER-PERIODE-INVALIDE"


def test_un_grand_livre_altere_refuse_le_dossier(monde, plan):
    gl, ops = monde
    maillons = gl.lire()
    maillons[0] = {**maillons[0], "libelle": "truqué"}
    etat = grand_livre.etat_grand_livre(maillons)
    resultat, refus = dossier_cpa.construire_dossier(
        debut="2026-10-01",
        fin="2026-10-31",
        date_reference="2026-11-02",
        etat_gl=etat,
        plan=plan,
        etat_ops=ore.etat_operations([]),
        factures_clients=[],
        factures_fournisseurs=[],
        controle_taxes=None,
        resume_base_fiscale=None,
        tetes=TETES,
    )
    assert resultat is None and refus["code"] == "REJ-GL-CHAINE-INVALIDE"
    ops_alteres = ore.etat_operations([{"type_entree": "op_piece_liee", "piece_id": "pie-x", "cle": "k"}])
    resultat, refus = dossier_cpa.construire_dossier(
        debut="2026-10-01",
        fin="2026-10-31",
        date_reference="2026-11-02",
        etat_gl=grand_livre.etat_grand_livre(gl.lire()),
        plan=plan,
        etat_ops=ops_alteres,
        factures_clients=[],
        factures_fournisseurs=[],
        controle_taxes=None,
        resume_base_fiscale=None,
        tetes=TETES,
    )
    assert resultat is None and refus["code"] == "REJ-OPS-CHAINE-INVALIDE"


def test_beancount_cumulatif_et_equilibre(monde, plan):
    d = construire(*monde, plan)
    texte = d["fichiers"]["12-grand-livre.beancount"].decode()
    assert 'option "operating_currency" "CAD"' in texte and "Hors période" not in texte
    # chaque transaction a une somme nulle
    somme = D("0")
    bloc = 0
    for ligne in texte.splitlines():
        if ligne and ligne[0].isdigit() and " * " in ligne:
            assert somme == 0
            bloc += 1
        elif ligne.startswith("  ") and "CAD" in ligne:
            somme += D(ligne.split()[-2])
    assert somme == 0 and bloc == 4


def test_pieces_requises_manquantes_sont_signalees_puis_liees(monde, plan):
    gl, ops = monde
    d = construire(gl, ops, plan)
    lignes = lire_csv(d["fichiers"]["07-liste-des-pieces.csv"])[1:]
    manquantes = [r for r in lignes if r[6] == "MANQUANTE"]
    assert len(manquantes) == 5  # les cinq écritures manuelles datées au plus tard le 31 octobre (novembre exclu)
    cible = manquantes[0][1]
    oc.lier_piece(
        ops,
        ore.etat_operations(ops.lire()),
        cible_type="ecriture",
        cible_id=cible,
        cibles_connues={"ecriture": [cible]},
        nom="p.pdf",
        sha256="ab" * 32,
        taille=5,
        lie_par="c",
        horodatage=H,
    )
    d2 = construire(gl, ops, plan)
    assert sum(1 for r in lire_csv(d2["fichiers"]["07-liste-des-pieces.csv"])[1:] if r[6] == "MANQUANTE") == 4
