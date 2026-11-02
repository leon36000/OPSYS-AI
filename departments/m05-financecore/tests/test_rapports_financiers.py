"""Rapports financiers (M5-RAPPORTS-1), noyau pur : état des résultats, bilan, budget contre réel, rentabilité par axe,
rapport de direction, reçu rejouable. Sur un grand livre RÉEL en mémoire (le même code que la production : propositions,
validations humaines, contre-passation, clôture), jamais sur un état fabriqué à la main.

Chaque chiffre attendu est calculé À LA MAIN dans le commentaire du jeu de données ; aucun n'est tiré du code testé.
Cas positifs ET négatifs : brouillon exclu, période décalée, produit rangé en charge, compte hors plan, chaîne altérée,
budget absent, mois sans budget, dimension absente, coût partiel. Données fictives (AGENTS.md).
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import (
    budgets,
    grand_livre,
    plan_comptable,
    rapports_financiers,
    recu_calcul,
    verdicts_rapports,
)
from m5_financecore import registre as registre_module

FICTIF = True
D = Decimal
_M5 = Path(__file__).resolve().parents[1]
H = "2026-02-28T10:00:00-05:00"
HUMAIN = {"par": "nathan", "role": "nathan_owner", "voie": "approbation"}


@pytest.fixture
def plan():
    base, refus = plan_comptable.charger_plan(_M5 / "contracts" / "plan_comptable_pme_qc.v1.yaml")
    assert refus is None, refus
    return base


def L(compte, debit=None, credit=None):
    return {"compte": compte, "debit": debit, "credit": credit}


def ecrire(reg, plan, ref, jour, lignes, *, definitive=True, piece_type="manuelle"):
    resultat, refus = grand_livre.proposer_ecriture(
        reg,
        plan,
        cle_piece=f"essai:{ref}",
        piece={"type": piece_type, "reference": ref},
        nature="saisie",
        date_effet=jour,
        libelle=f"Écriture fictive {ref}",
        lignes_brutes=lignes,
        horodatage=H,
        origine="essai",
    )
    assert refus is None, refus
    ident = resultat["ecriture"]["ecriture_id"]
    if definitive:
        _, refus = grand_livre.valider_ecriture(reg, plan, ecriture_id=ident, humain=HUMAIN, horodatage=H)
        assert refus is None, refus
    return ident


@pytest.fixture
def livre(plan):
    """Deux mois de grand livre. Janvier : capital 5 000 (E1, 01-02) ; vente 1 000,00 + TPS 50,00 + TVQ 99,75 (E2,
    01-10) ;
    achat de matériaux 400,00 + CTI 20,00 + RTI 39,90 (E3, 01-15) ; encaissement de la vente (E4, 01-20).
    Février : vente 2 000,00 + 100,00 + 199,50 (E5, 02-10) ; loyer 800,00 (E6, 02-12) ; salaires 700,00 (E7, 02-25) ;
    frais divers 25,00 (E8, 02-26, hors budget) ; BROUILLON frais 50,00 (E9, 02-27, jamais compté)."""
    reg = registre_module.Registre()
    ecrire(reg, plan, "E1", "2026-01-02", [L("1010", "5000.00"), L("3100", credit="5000.00")])
    ecrire(
        reg,
        plan,
        "E2",
        "2026-01-10",
        [L("1100", "1149.75"), L("4100", credit="1000.00"), L("2300", credit="50.00"), L("2310", credit="99.75")],
    )
    ecrire(
        reg,
        plan,
        "E3",
        "2026-01-15",
        [L("5100", "400.00"), L("1400", "20.00"), L("1410", "39.90"), L("2100", credit="459.90")],
    )
    ecrire(reg, plan, "E4", "2026-01-20", [L("1010", "1149.75"), L("1100", credit="1149.75")])
    ecrire(
        reg,
        plan,
        "E5",
        "2026-02-10",
        [L("1100", "2299.50"), L("4100", credit="2000.00"), L("2300", credit="100.00"), L("2310", credit="199.50")],
    )
    ecrire(reg, plan, "E6", "2026-02-12", [L("5600", "800.00"), L("1010", credit="800.00")])
    ecrire(reg, plan, "E7", "2026-02-25", [L("5300", "700.00"), L("1010", credit="700.00")])
    ecrire(reg, plan, "E8", "2026-02-26", [L("5990", "25.00"), L("1010", credit="25.00")])
    ecrire(reg, plan, "E9", "2026-02-27", [L("5990", "50.00"), L("1010", credit="50.00")], definitive=False)
    return reg


def etat(reg):
    return grand_livre.etat_grand_livre(reg.lire())


def mouvements(reg, plan, debut, fin):
    resultat, refus = rapports_financiers.extraire_mouvements(
        etat(reg), plan, None if debut is None else rapports_financiers._jour(debut), rapports_financiers._jour(fin)
    )
    assert refus is None, refus
    return resultat


def resultats(reg, plan, debut, fin, couts_directs=None):
    m = mouvements(reg, plan, debut, fin)
    entrees = {
        "debut": debut,
        "fin": fin,
        "comptes": m["comptes"],
        "couts_directs": couts_directs,
        "ecritures_definitives": m["ecritures_definitives"],
        "brouillons": m["brouillons"],
        "periode_close": m["periode_close"],
        "plan_comptable_version": m["plan_comptable_version"],
    }
    return rapports_financiers.calculer_etat_des_resultats(entrees, {"debut": debut, "fin": fin})


def bilan(reg, plan, au):
    m = mouvements(reg, plan, None, au)
    entrees = {
        "au": au,
        "comptes": m["comptes"],
        "ecritures_definitives": m["ecritures_definitives"],
        "brouillons": m["brouillons"],
        "plan_comptable_version": m["plan_comptable_version"],
    }
    return rapports_financiers.calculer_bilan(entrees, {"au": au})


def ligne(rapport, compte):
    return next(x for x in rapport["etat"]["lignes"] if x["compte"] == compte)


# =============================================================================================== état des résultats
def test_etat_des_resultats_de_janvier_chiffres_a_la_main(livre, plan):
    r = resultats(livre, plan, "2026-01-01", "2026-01-31")["etat"]
    assert (r["total_produits"], r["total_charges"], r["resultat_avant_impots"]) == ("1000.00", "400.00", "600.00")
    assert [(x["section"], x["compte"], x["montant"]) for x in r["lignes"]] == [
        ("produits", "4100", "1000.00"),
        ("charges", "5100", "400.00"),
    ]
    assert r["statut"] == "BROUILLON" and r["mention_brouillon"].startswith("Brouillon préparatoire")
    assert "CPA" in r["mention_brouillon"] and r["devise"] == "CAD"


def test_etat_des_resultats_de_fevrier_le_brouillon_n_est_pas_additionne_mais_compte(livre, plan):
    r = resultats(livre, plan, "2026-02-01", "2026-02-28")
    e = r["etat"]
    # produits 2 000,00 ; charges 800 + 700 + 25 = 1 525,00 (le brouillon de 50,00 est exclu) ; net 475,00
    assert (e["total_produits"], e["total_charges"], e["resultat_avant_impots"]) == ("2000.00", "1525.00", "475.00")
    assert e["completude"] == {"ecritures_definitives": 4, "brouillons_non_comptabilises": 1, "periode_close": False}
    assert ligne(r, "5990")["montant"] == "25.00"
    assert any("brouillon" in a for a in r["recu"]["avertissements"])


def test_etat_sur_deux_mois_est_la_somme_exacte_des_deux(livre, plan):
    e = resultats(livre, plan, "2026-01-01", "2026-02-28")["etat"]
    assert (e["total_produits"], e["total_charges"], e["resultat_avant_impots"]) == ("3000.00", "1925.00", "1075.00")


def test_une_taxe_a_percevoir_n_est_jamais_un_produit(livre, plan):
    comptes = {x["compte"] for x in resultats(livre, plan, "2026-01-01", "2026-02-28")["etat"]["lignes"]}
    assert comptes == {"4100", "5100", "5600", "5300", "5990"}
    assert "2300" not in comptes and "1400" not in comptes
    assert resultats(livre, plan, "2026-01-01", "2026-02-28")["etat"]["comptes_de_bilan_mouvementes"] == 8


def test_un_produit_n_est_pas_range_en_charge_le_sens_est_credit_moins_debit(livre, plan):
    # contre-passation d'une vente : le produit baisse (crédit − débit), il ne devient pas une charge
    avant = resultats(livre, plan, "2026-01-01", "2026-01-31")["etat"]
    resultat, refus = grand_livre.proposer_contre_passation(
        livre,
        plan,
        ecriture_id=next(i for i, e in etat(livre)["ecritures"].items() if e["piece"]["reference"] == "E2"),
        date_effet="2026-01-31",
        motif="Vente annulée (fictif)",
        horodatage=H,
    )
    assert refus is None
    grand_livre.valider_ecriture(
        livre, plan, ecriture_id=resultat["ecriture"]["ecriture_id"], humain=HUMAIN, horodatage=H
    )
    apres = resultats(livre, plan, "2026-01-01", "2026-01-31")["etat"]
    assert avant["total_produits"] == "1000.00" and apres["total_produits"] == "0.00"
    assert apres["total_charges"] == "400.00" and apres["resultat_avant_impots"] == "-400.00"


def test_la_periode_est_exacte_aux_bornes_et_jamais_decalee_d_un_mois(
    livre,
    plan,
):
    for jour, produits in (("2026-01-31", "1000.00"), ("2026-02-09", "1000.00"), ("2026-02-10", "3000.00")):
        assert resultats(livre, plan, "2026-01-01", jour)["etat"]["total_produits"] == produits
    # une écriture au tout dernier jour du mois entre dans ce mois, pas dans le suivant
    ecrire(livre, plan, "E10", "2026-01-31", [L("1010", "10.00"), L("4900", credit="10.00")])
    ecrire(livre, plan, "E11", "2026-02-01", [L("1010", "7.00"), L("4900", credit="7.00")])
    assert ligne(resultats(livre, plan, "2026-01-01", "2026-01-31"), "4900")["montant"] == "10.00"
    assert ligne(resultats(livre, plan, "2026-02-01", "2026-02-28"), "4900")["montant"] == "7.00"


def test_marge_brute_non_calculable_sans_comptes_de_couts_directs_declares_puis_calculee(livre, plan):
    sans = resultats(livre, plan, "2026-01-01", "2026-01-31")["etat"]["marge_brute"]
    assert sans["statut"] == "NON_CALCULABLE" and "comptes_couts_directs" in sans["manque"] and "montant" not in sans
    avec = resultats(livre, plan, "2026-01-01", "2026-01-31", couts_directs=["5100"])["etat"]["marge_brute"]
    # 1 000,00 − 400,00 = 600,00 ; 600 / 1 000 = 60,00 %
    assert avec == {
        "statut": "CALCULEE",
        "montant": "600.00",
        "pourcentage_des_produits": "60.00",
        "comptes_couts_directs": ["5100"],
    }


def test_marge_brute_sans_produit_est_non_calculable_pas_zero(livre, plan):
    e = resultats(livre, plan, "2026-02-12", "2026-02-12", couts_directs=["5600"])["etat"]
    assert e["total_produits"] == "0.00" and e["marge_brute"]["statut"] == "NON_CALCULABLE"


def test_le_pourcentage_est_arrondi_demi_cent_vers_le_haut_et_dit_etre_le_seul_arrondi(plan):
    reg = registre_module.Registre()
    ecrire(reg, plan, "V", "2026-03-05", [L("1010", "3.00"), L("4100", credit="3.00")])
    ecrire(reg, plan, "C", "2026-03-06", [L("5100", "1.00"), L("1010", credit="1.00")])
    # marge brute 2,00 sur 3,00 = 66,666…  % -> 66,67 (ROUND_HALF_UP)
    marge = resultats(reg, plan, "2026-03-01", "2026-03-31", couts_directs=["5100"])["etat"]["marge_brute"]
    assert marge["pourcentage_des_produits"] == "66.67"


def test_un_compte_absent_du_plan_courant_fait_refuser_le_rapport_au_lieu_d_etre_classe_au_hasard(livre, plan):
    etendu, _ = plan_comptable.appliquer_extension(
        plan, {"comptes_ajoutes": [{"numero": "5450", "nom": "Location", "type": "charges"}]}
    )
    ecrire(livre, etendu, "EX", "2026-02-20", [L("5450", "10.00"), L("1010", credit="10.00")])
    m, refus = rapports_financiers.extraire_mouvements(etat(livre), plan, None, rapports_financiers._jour("2026-02-28"))
    assert m is None and refus["code"] == "REJ-RAPPORT-COMPTE-HORS-PLAN" and "5450" in refus["detail"]


def test_une_chaine_alteree_fait_refuser_le_rapport(livre, plan):
    maillons = livre.lire()
    maillons[1] = {**maillons[1], "empreinte_contenu": "0" * 64}
    m, refus = rapports_financiers.extraire_mouvements(
        grand_livre.etat_grand_livre(maillons), plan, None, rapports_financiers._jour("2026-02-28")
    )
    assert m is None and refus["code"] == "REJ-RAPPORT-CHAINE-INVALIDE"


def test_periode_close_est_dite_sans_changer_les_chiffres(livre, plan):
    grand_livre.clore_periode(livre, periode="2026-01", humain=HUMAIN, horodatage=H)
    e = resultats(livre, plan, "2026-01-01", "2026-01-31")["etat"]
    assert e["completude"]["periode_close"] is True and e["total_produits"] == "1000.00"
    assert resultats(livre, plan, "2026-02-01", "2026-02-28")["etat"]["completude"]["periode_close"] is False


def test_les_dates_sont_validees_et_la_periode_est_bornee():
    assert rapports_financiers.periode_en_dates("2026-01-01", "2026-01-31")[1] is None
    for debut, fin in (
        ("2026-02-01", "2026-01-01"),
        ("2026-01-01", "2027-03-01"),
        ("2026-13-01", "2026-01-01"),
        ("2026-01-1", "2026-01-31"),
        (None, "2026-01-31"),
        ("２０２６-01-01", "2026-01-31"),
    ):
        periode, refus = rapports_financiers.periode_en_dates(debut, fin)
        assert periode is None and refus["code"] in ("REJ-RAPPORT-DATE-INVALIDE", "REJ-RAPPORT-PERIODE-INVALIDE")


# ============================================================================================================ bilan
def test_bilan_de_fin_fevrier_chiffres_a_la_main_et_equilibre(livre, plan):
    b = bilan(livre, plan, "2026-02-28")["etat"]
    # 1010 : 5 000 + 1 149,75 − 800 − 700 − 25 = 4 624,75 ; 1100 : 2 299,50 ; 1400 : 20,00 ; 1410 : 39,90 -> actif 6
    # 984,15
    # passif : 2100 459,90 + 2300 150,00 + 2310 299,25 = 909,15 ; capitaux 5 000,00
    # résultat cumulé : produits 3 000 − charges (400 + 800 + 700 + 25) = 1 075,00 ; 909,15 + 5 000 + 1 075 = 6 984,15
    assert b["total_actif"] == "6984.15" and b["total_passif"] == "909.15" and b["total_capitaux_propres"] == "5000.00"
    assert b["resultat_cumule_non_clos"] == "1075.00" and b["total_passif_et_capitaux"] == "6984.15"
    assert b["equilibre"] is True and b["ecart_equilibre"] == "0.00" and b["comptes_a_solde_anormal"] == 0
    assert b["statut"] == "BROUILLON" and "CPA" in b["mention_brouillon"]
    montants = {(x["section"], x["compte"]): x["montant"] for x in b["lignes"]}
    assert montants[("actif", "1010")] == "4624.75" and montants[("passif", "2300")] == "150.00"


def test_bilan_a_une_date_anterieure_ne_voit_pas_l_avenir(livre, plan):
    b = bilan(livre, plan, "2026-01-31")["etat"]
    # actif : 1010 = 6 149,75 ; 1400 20,00 ; 1410 39,90 ; 1100 = 0 -> 6 209,65 ; passif 459,90 + 50 + 99,75 = 609,65
    # ; résultat 600
    assert b["total_actif"] == "6209.65" and b["total_passif"] == "609.65" and b["resultat_cumule_non_clos"] == "600.00"
    assert b["equilibre"] is True


def test_le_bilan_compte_le_brouillon_a_part_et_ne_l_additionne_pas(livre, plan):
    b = bilan(livre, plan, "2026-02-28")["etat"]
    assert b["completude"]["brouillons_non_comptabilises"] == 1 and b["completude"]["ecritures_definitives"] == 8


def test_un_solde_du_mauvais_cote_est_montre_negatif_et_signale(plan):
    reg = registre_module.Registre()
    ecrire(reg, plan, "S", "2026-03-01", [L("1010", credit="40.00"), L("5990", "40.00")])
    b = bilan(reg, plan, "2026-03-31")["etat"]
    assert (
        b["comptes_a_solde_anormal"] == 1
        and b["lignes"][0]["montant"] == "-40.00"
        and b["lignes"][0]["solde_anormal"] is True
    )
    assert b["equilibre"] is True and b["total_actif"] == "-40.00" and b["resultat_cumule_non_clos"] == "-40.00"


def test_un_bilan_qui_ne_s_equilibre_pas_le_dit_au_lieu_de_l_absorber(livre, plan):
    m = mouvements(livre, plan, None, "2026-02-28")
    for compte in m["comptes"]:
        if compte["compte"] == "4100":
            compte["credit"] = "3000.01"  # entrée retouchée : le bilan ne doit pas se réajuster
    entrees = {
        "au": "2026-02-28",
        "comptes": m["comptes"],
        "ecritures_definitives": 8,
        "brouillons": 1,
        "plan_comptable_version": m["plan_comptable_version"],
    }
    b = rapports_financiers.calculer_bilan(entrees, {"au": "2026-02-28"})
    assert b["etat"]["equilibre"] is False and b["etat"]["ecart_equilibre"] == "-0.01"
    assert any("NE S'ÉQUILIBRE PAS" in a for a in b["recu"]["avertissements"])


# ===================================================================================================== budget déclaré
def lignes_budget():
    return [
        {"compte": "4100", "mois": "2026-01", "montant": "1500.00"},
        {"compte": "4100", "mois": "2026-02", "montant": "1800.00"},
        {"compte": "5100", "mois": "2026-01", "montant": "400.00"},
        {"compte": "5600", "mois": "2026-01", "montant": "800.00"},
        {"compte": "5600", "mois": "2026-02", "montant": "800.00"},
        {"compte": "5300", "mois": "2026-02", "montant": "600.00"},
    ]


def budget_contre_reel(reg, plan, mois, lignes=None, version=2):
    reel, refus = rapports_financiers.mouvements_par_mois(etat(reg), plan, mois)
    assert refus is None, refus
    lignes = [x for x in (lignes if lignes is not None else lignes_budget()) if x["mois"] in mois]
    fiches = [
        {"compte": c, "nom": plan["comptes"][c]["nom"], "type": plan["comptes"][c]["type"]}
        for c in sorted({x["compte"] for x in lignes})
    ]
    m = mouvements(reg, plan, None, "2026-02-28")
    entrees = {
        "mois": mois,
        "budget": {"budget_id": "bud-essai", "version": version, "lignes": lignes},
        "comptes_budget": fiches,
        "reel": reel,
        "ecritures_definitives": m["ecritures_definitives"],
        "brouillons": m["brouillons"],
    }
    return rapports_financiers.calculer_budget_contre_reel(entrees, {"mois_debut": mois[0], "mois_fin": mois[-1]})


def test_budget_contre_reel_chiffres_a_la_main(livre, plan):
    r = budget_contre_reel(livre, plan, ["2026-01", "2026-02"])["etat"]
    par = {x["compte"]: x for x in r["lignes"]}
    # 4100 : budget 3 300 / réel 3 000 -> −300,00 (−9,09 %) DÉFAVORABLE (moins de produits que prévu)
    assert (par["4100"]["budget"], par["4100"]["reel"], par["4100"]["ecart"]) == ("3300.00", "3000.00", "-300.00")
    assert par["4100"]["ecart_pct_du_budget"] == "-9.09" and par["4100"]["sens"] == "DEFAVORABLE"
    # 5100 : budget 400 / réel 400 -> nul ; 5600 : budget 1 600 / réel 800 -> −800 FAVORABLE (moins de charges)
    assert par["5100"]["sens"] == "NUL" and par["5100"]["ecart"] == "0.00"
    assert (par["5600"]["budget"], par["5600"]["reel"], par["5600"]["ecart"], par["5600"]["sens"]) == (
        "1600.00",
        "800.00",
        "-800.00",
        "FAVORABLE",
    )
    # 5300 : budget (février seulement) 600 / réel 700 -> +100 DÉFAVORABLE (plus de charges)
    assert (par["5300"]["ecart"], par["5300"]["sens"]) == ("100.00", "DEFAVORABLE")
    t = r["totaux"]
    assert t["produits"] == {"budget": "3300.00", "reel": "3000.00"} and t["charges"] == {
        "budget": "2600.00",
        "reel": "1900.00",
    }
    assert (t["resultat_budgete"], t["resultat_reel_des_comptes_budgetes"], t["ecart_resultat"]) == (
        "700.00",
        "1100.00",
        "400.00",
    )


def test_un_compte_avec_du_reel_sans_ligne_de_budget_est_montre_a_part_jamais_absorbe(livre, plan):
    r = budget_contre_reel(livre, plan, ["2026-01", "2026-02"])["etat"]
    assert r["non_budgetes"] == [
        {"compte": "5990", "nom": plan["comptes"]["5990"]["nom"], "type": "charges", "reel": "25.00"}
    ]
    assert "5990" not in {x["compte"] for x in r["lignes"]}


def test_un_mois_sans_aucune_ligne_de_budget_est_nomme_et_non_compare_a_zero(livre, plan):
    seulement_janvier = [x for x in lignes_budget() if x["mois"] == "2026-01"]
    r = budget_contre_reel(livre, plan, ["2026-01", "2026-02"], lignes=seulement_janvier)
    e = r["etat"]
    assert e["mois_compares"] == ["2026-01"] and e["mois_sans_budget"] == ["2026-02"]
    par = {x["compte"]: x for x in e["lignes"]}
    assert par["4100"]["reel"] == "1000.00" and par["4100"]["budget"] == "1500.00"  # le réel de février n'y est pas
    assert e["non_budgetes"] == [] and any("2026-02" in a for a in r["recu"]["avertissements"])


def test_aucun_mois_budgete_est_non_calculable_et_dit_quoi_declarer(livre, plan):
    r = budget_contre_reel(livre, plan, ["2026-01"], lignes=[x for x in lignes_budget() if x["mois"] == "2026-02"])[
        "etat"
    ]
    assert r["statut"] == "NON_CALCULABLE" and "2026-01" in r["manque"] and "m5_etablir_budget" in r["manque"]
    assert r["lignes"] == [] and "totaux" not in r


def test_un_budget_a_zero_donne_un_ecart_mais_aucun_pourcentage(livre, plan):
    r = budget_contre_reel(livre, plan, ["2026-02"], lignes=[{"compte": "5300", "mois": "2026-02", "montant": "0.00"}])[
        "etat"
    ]
    assert r["lignes"][0]["ecart"] == "700.00" and r["lignes"][0]["ecart_pct_du_budget"] is None


def test_un_compte_budgete_sans_aucun_mouvement_a_un_reel_de_zero_connu(livre, plan):
    r = budget_contre_reel(
        livre, plan, ["2026-01"], lignes=[{"compte": "5400", "mois": "2026-01", "montant": "100.00"}]
    )["etat"]
    assert (r["lignes"][0]["reel"], r["lignes"][0]["ecart"], r["lignes"][0]["sens"]) == ("0.00", "-100.00", "FAVORABLE")


# ==================================================================================================== budget déclaré
def test_declaration_du_budget_chaque_refus_est_nomme(plan):
    ok = lignes_budget()
    corps, refus = budgets.construire_budget(
        ok, "Budget 2026", plan, humain=HUMAIN, version=1, motif=None, remplace=None
    )
    assert (
        refus is None
        and corps["mois_debut"] == "2026-01"
        and corps["mois_fin"] == "2026-02"
        and len(corps["lignes"]) == 6
    )
    assert corps["budget_id"].startswith("bud-") and corps["declare_par"] == HUMAIN

    def code(lignes, libelle="Budget"):
        _, r = budgets.construire_budget(lignes, libelle, plan, humain=HUMAIN, version=1, motif=None, remplace=None)
        assert r is not None
        assert r["code"] in verdicts_rapports.CODES_RAPPORTS
        return r["code"]

    base = {"compte": "4100", "mois": "2026-01", "montant": "10.00"}
    assert code([]) == "REJ-BUDGET-ENTREE-INVALIDE" and code("x") == "REJ-BUDGET-ENTREE-INVALIDE"
    assert code([{**base, "extra": 1}]) == "REJ-BUDGET-ENTREE-INVALIDE"
    assert code([{**base, "compte": "9999"}]) == "REJ-BUDGET-COMPTE-INVALIDE"
    assert code([{**base, "compte": "1010"}]) == "REJ-BUDGET-COMPTE-INVALIDE"  # un compte de bilan ne se budgète pas
    assert code([{**base, "compte": "2300"}]) == "REJ-BUDGET-COMPTE-INVALIDE"
    assert code([{**base, "mois": "2026-13"}]) == "REJ-BUDGET-MOIS-INVALIDE"
    assert code([{**base, "mois": "2026-1"}]) == "REJ-BUDGET-MOIS-INVALIDE"
    for montant in ("-1.00", "10.001", "1e3", "", "0x10", " 5", "12,50", 10, None, "99999999999999.00"):
        assert code([{**base, "montant": montant}]) == "REJ-BUDGET-MONTANT-INVALIDE", montant
    assert code([base, base]) == "REJ-BUDGET-LIGNE-DOUBLE"
    assert code([base], libelle="") == "REJ-BUDGET-ENTREE-INVALIDE"
    assert code([base], libelle="a\nb") == "REJ-BUDGET-ENTREE-INVALIDE"
    assert code([base, {**base, "mois": "2030-01"}]) == "REJ-BUDGET-MOIS-INVALIDE"  # plus de 36 mois d'étendue
    desactive, _ = plan_comptable.appliquer_extension(plan, {"comptes_desactives": ["5990"]})
    _, r = budgets.construire_budget(
        [{**base, "compte": "5990"}], "B", desactive, humain=HUMAIN, version=1, motif=None, remplace=None
    )
    assert r["code"] == "REJ-BUDGET-COMPTE-INVALIDE" and "désactivé" in r["detail"]


def test_un_budget_n_arrondit_jamais_un_montant_et_le_zero_est_permis(plan):
    corps, refus = budgets.construire_budget(
        [
            {"compte": "4100", "mois": "2026-01", "montant": "0"},
            {"compte": "5100", "mois": "2026-01", "montant": "7.5"},
        ],
        "B",
        plan,
        humain=HUMAIN,
        version=1,
        motif=None,
        remplace=None,
    )
    assert refus is None and [x["montant"] for x in corps["lignes"]] == ["0.00", "7.50"]


def test_versions_du_budget_motif_obligatoire_idempotence_et_passe_lisible(plan):
    reg = registre_module.Registre()
    etat0 = budgets.etat_budgets(reg.lire())
    assert budgets.budget_actif(etat0) is None
    v1, _ = budgets.construire_budget(
        lignes_budget(), "Budget 2026", plan, humain=HUMAIN, version=1, motif=None, remplace=None
    )
    r1, refus = budgets.ajouter_budget(reg, etat0, v1, H)
    assert refus is None and r1["statut"] == "ecrit"
    etat1 = budgets.etat_budgets(reg.lire())
    assert budgets.budget_actif(etat1)["version"] == 1
    # le même contenu : rien n'est écrit
    r2, _ = budgets.ajouter_budget(reg, etat1, v1, H)
    assert r2["statut"] == "deja" and reg.taille() == 1
    # une autre version exige un motif
    plus = [*lignes_budget(), {"compte": "5990", "mois": "2026-02", "montant": "30.00"}]
    _, refus = budgets.construire_budget(
        plus, "Budget 2026 révisé", plan, humain=HUMAIN, version=2, motif=None, remplace=v1["budget_id"]
    )
    assert refus["code"] == "REJ-BUDGET-MOTIF-REQUIS"
    v2, refus = budgets.construire_budget(
        plus,
        "Budget 2026 révisé",
        plan,
        humain=HUMAIN,
        version=2,
        motif="Ajout des frais divers",
        remplace=v1["budget_id"],
    )
    assert refus is None and v2["remplace"] == v1["budget_id"]
    budgets.ajouter_budget(reg, etat1, v2, H)
    etat2 = budgets.etat_budgets(reg.lire())
    assert [v["version"] for v in etat2["versions"]] == [1, 2] and budgets.budget_actif(etat2)["lignes"] == v2["lignes"]
    assert etat2["versions"][0]["lignes"] == v1["lignes"]  # le passé reste lisible


def test_un_budget_retouche_a_la_main_est_detecte_par_toute_lecture(plan):
    reg = registre_module.Registre()
    v1, _ = budgets.construire_budget(lignes_budget(), "B", plan, humain=HUMAIN, version=1, motif=None, remplace=None)
    budgets.ajouter_budget(reg, budgets.etat_budgets([]), v1, H)
    maillons = reg.lire()
    maillons[0] = {
        **maillons[0],
        "lignes": [{**maillons[0]["lignes"][0], "montant": "99999.00"}, *maillons[0]["lignes"][1:]],
    }
    etat_altere = budgets.etat_budgets(maillons)
    assert etat_altere["anomalies"] and budgets.refus_anomalies(etat_altere)["code"] == "REJ-RAPPORT-CHAINE-INVALIDE"
    assert budgets.budget_actif(etat_altere) is None
    for altere in ({"version": 3}, {"remplace": "bud-autre"}, {"budget_id": "bud-xx"}):
        assert budgets.etat_budgets([{**reg.lire()[0], **altere}])["anomalies"]
    assert budgets.etat_budgets([{"type_entree": "autre"}])["anomalies"]
    assert budgets.etat_budgets([{"type_entree": "budget_declare"}])["anomalies"]


def test_mois_entre_est_inclusif_et_refuse_l_inverse():
    assert budgets.mois_entre("2026-11", "2027-02") == ["2026-11", "2026-12", "2027-01", "2027-02"]
    assert budgets.mois_entre("2026-03", "2026-03") == ["2026-03"]
    assert budgets.mois_entre("2026-03", "2026-02") is None and budgets.mois_entre("2026-00", "2026-02") is None


# ================================================================================================ rentabilité par axe
def chantier(devis, marge="1000.00", prix="5000.00", cout="4000.00", definitif=True, **dims):
    return {
        "devis_id": devis,
        "service": None,
        "ville": None,
        "prix_definitif": definitif,
        "prix_facture": prix,
        "cout_reel": cout,
        "marge_reelle": marge,
        **dims,
    }


def rentabilite(axe, chantiers):
    return rapports_financiers.calculer_rentabilite_par_axe(
        {"axe": axe, "debut": None, "fin": None, "chantiers": chantiers}, {"axe": axe, "debut": None, "fin": None}
    )["etat"]


def test_rentabilite_par_ville_regroupe_et_calcule_a_la_main():
    cs = [
        chantier("d1", ville="Lévis", prix="5000.00", cout="4000.00", marge="1000.00"),
        chantier("d2", ville="Lévis", prix="3000.00", cout="2700.00", marge="300.00"),
        chantier("d3", ville="Québec", prix="2000.00", cout="2200.00", marge="-200.00"),
    ]
    r = rentabilite("ville", cs)
    assert r["statut"] == "CALCULEE"
    par = {g["ville"]: g for g in r["groupes"]}
    # Lévis : ventes 8 000, coût 6 700, marge 1 300 -> 16,25 % ; Québec : 2 000, 2 200, −200 -> −10,00 %
    assert par["Lévis"] == {
        "ville": "Lévis",
        "chantiers": 2,
        "ventes": "8000.00",
        "cout_reel": "6700.00",
        "marge_reelle": "1300.00",
        "marge_pct_des_ventes": "16.25",
    }
    assert par["Québec"]["marge_reelle"] == "-200.00" and par["Québec"]["marge_pct_des_ventes"] == "-10.00"
    assert r["total"] == {
        "chantiers": 3,
        "ventes": "10000.00",
        "cout_reel": "8900.00",
        "marge_reelle": "1100.00",
        "marge_pct_des_ventes": "11.00",
    }


def test_un_cout_partiel_ou_un_prix_provisoire_est_exclu_et_compte_jamais_regroupe():
    cs = [
        chantier("d1", ville="Lévis"),
        chantier("d2", ville="Lévis", marge=None, cout=None),
        chantier("d3", ville="Lévis", definitif=False),
    ]
    r = rentabilite("ville", cs)
    assert r["groupes"][0]["chantiers"] == 1
    assert (r["exclus_cout_partiel"], r["exclus_prix_provisoire"], r["sans_dimension"]) == (1, 1, 0)


def test_dimension_absente_de_tous_les_chantiers_est_non_calculable_et_dit_le_manque_jamais_zero():
    for axe in ("service", "ville"):
        r = rentabilite(axe, [chantier("d1"), chantier("d2")])
        assert r["statut"] == "NON_CALCULABLE" and r["groupes"] == [] and "total" not in r
        assert axe in r["manque"] and "m4.travaux_termines" in r["manque"] and r["sans_dimension"] == 2


def test_dimension_absente_de_certains_chantiers_les_compte_a_part():
    r = rentabilite("service", [chantier("d1", service="toiture"), chantier("d2")])
    assert r["statut"] == "CALCULEE" and r["sans_dimension"] == 1 and r["groupes"][0]["service"] == "toiture"


def test_aucun_chantier_ou_aucun_cout_complet_est_non_calculable_avec_la_bonne_raison():
    assert "aucune rentabilité" in rentabilite("ville", [])["manque"]
    r = rentabilite("ville", [chantier("d1", ville="X", marge=None, cout=None)])
    assert r["statut"] == "NON_CALCULABLE" and "coût complet" in r["manque"]


def test_la_valeur_de_l_axe_est_regroupee_telle_quelle_sans_casse_devinee():
    r = rentabilite("ville", [chantier("d1", ville="Lévis"), chantier("d2", ville="levis")])
    assert len(r["groupes"]) == 2  # deux écritures, deux groupes : M5 ne normalise pas une ville


# ================================================================================================ reçu et rejeu
def test_le_recu_se_rejoue_a_l_identique_apres_un_aller_retour_json(livre, plan):
    for rapport in (
        resultats(livre, plan, "2026-01-01", "2026-02-28", couts_directs=["5100"]),
        bilan(livre, plan, "2026-02-28"),
        budget_contre_reel(livre, plan, ["2026-01", "2026-02"]),
    ):
        recu = json.loads(json.dumps(rapport["recu"], ensure_ascii=False))
        assert recu_calcul.verifier(recu) == (True, "")
        assert rapports_financiers.rejouer(recu) == (True, "")
        assert recu["mention"].startswith("À valider auprès d'un comptable (CPA)")


def test_retoucher_un_montant_des_entrees_ou_du_resultat_est_refuse(livre, plan):
    recu = resultats(livre, plan, "2026-01-01", "2026-01-31")["recu"]
    retouche = copy.deepcopy(recu)
    produit = next(c for c in retouche["entrees"]["comptes"] if c["compte"] == "4100")
    produit["credit"] = "1.00"
    assert rapports_financiers.rejouer(retouche)[0] is False
    retouche = copy.deepcopy(recu)
    retouche["resultat"]["resultat_avant_impots"] = "601.00"
    ok, raison = rapports_financiers.rejouer(retouche)
    assert ok is False and "retouché" in raison
    # entrées retouchées ET empreintes refaites à la main : le rejeu ne redonne pas les chiffres du reçu
    refait = copy.deepcopy(recu)
    next(c for c in refait["entrees"]["comptes"] if c["compte"] == "4100")["credit"] = "1500.00"
    refait["empreinte_entrees"] = recu_calcul.construire(
        moteur=recu["moteur"],
        version_moteur=recu["version_moteur"],
        methode=recu["methode"],
        precision=recu["precision"],
        parametres=recu["parametres"],
        entrees=refait["entrees"],
        resultat=recu["resultat"],
        avertissements=recu["avertissements"],
    )["empreinte_entrees"]
    refait["empreinte"] = recu_calcul.construire(
        moteur=recu["moteur"],
        version_moteur=recu["version_moteur"],
        methode=recu["methode"],
        precision=recu["precision"],
        parametres=recu["parametres"],
        entrees=refait["entrees"],
        resultat=recu["resultat"],
        avertissements=recu["avertissements"],
    )["empreinte"]
    ok, raison = rapports_financiers.rejouer(refait)
    assert recu_calcul.verifier(refait) == (True, "") and ok is False and "rejeu" in raison


def test_un_recu_compact_se_verifie_mais_ne_se_rejoue_pas_hors_ligne(livre, plan):
    compact = recu_calcul.compacter(bilan(livre, plan, "2026-02-28")["recu"])
    assert recu_calcul.verifier(compact) == (True, "")
    ok, raison = rapports_financiers.rejouer(compact)
    assert ok is False and "compact" in raison


def test_un_moteur_inconnu_ou_un_non_recu_n_est_jamais_rejoue(livre, plan):
    recu = copy.deepcopy(bilan(livre, plan, "2026-02-28")["recu"])
    recu["moteur"] = "autre"
    assert rapports_financiers.rejouer(recu)[0] is False
    assert rapports_financiers.rejouer("pas un reçu")[0] is False
    assert rapports_financiers.rejouer(None)[0] is False


def test_un_rapport_ne_contient_aucun_flottant_et_aucun_decimal_brut(livre, plan):
    for rapport in (resultats(livre, plan, "2026-01-01", "2026-02-28"), bilan(livre, plan, "2026-02-28")):
        texte = json.dumps(rapport, ensure_ascii=False, default=lambda o: pytest.fail(f"type non JSON {type(o)}"))
        assert "e+" not in texte.lower()
        recu_calcul._controler_json(rapport["recu"])  # lève si un flottant ou un Decimal s'y glisse


def test_le_meme_grand_livre_donne_le_meme_recu_et_un_autre_une_autre_empreinte(livre, plan):
    a = resultats(livre, plan, "2026-01-01", "2026-02-28")["recu"]["empreinte"]
    assert resultats(livre, plan, "2026-01-01", "2026-02-28")["recu"]["empreinte"] == a
    ecrire(livre, plan, "E12", "2026-02-20", [L("5990", "1.00"), L("1010", credit="1.00")])
    assert resultats(livre, plan, "2026-01-01", "2026-02-28")["recu"]["empreinte"] != a


# ================================================================================================ rapport de direction
def test_le_rapport_de_direction_distingue_faits_hypotheses_et_donnees_manquantes(livre, plan):
    r = resultats(livre, plan, "2026-02-01", "2026-02-28")
    s = rapports_financiers.section(
        "resultats",
        "Résultats",
        "PARTIEL",
        faits=[{"libelle": "Produits", "valeur_cad": r["etat"]["total_produits"]}],
        hypotheses=["h"],
        manquantes=[{"code": "COUTS_DIRECTS", "a_declarer": "x"}],
        recu=r["recu"],
    )
    n = rapports_financiers.section(
        "budget", "Budget", "NON_CALCULABLE", manquantes=[{"code": "BUDGET", "a_declarer": "y"}]
    )
    rapport = rapports_financiers.composer_rapport_mensuel("2026-02", [s, n], {"periode": "2026-02"})
    assert (
        rapport["etat"]["statut"] == "BROUILLON"
        and rapport["etat"]["sections"][0]["recu_empreinte"] == r["recu"]["empreinte"]
    )
    assert rapport["etat"]["sections"][1]["recu_empreinte"] is None and rapport["etat"]["sections"][1]["faits"] == []
    assert (
        rapport["recu"]["resultat"]["sections_non_calculables"] == 1
        and rapport["recu"]["resultat"]["donnees_manquantes"] == 2
    )
    # le reçu composite se VÉRIFIE (ses empreintes) ; chaque section se rejoue par son propre reçu
    assert recu_calcul.verifier(rapport["recu"]) == (True, "")
    assert rapports_financiers.rejouer(rapport["recu"])[0] is False


def test_les_sources_citees_dans_les_entrees_se_retrouvent_dans_chaque_rapport_et_dans_le_recu(livre, plan):
    source = [{"registre": "grand_livre", "taille": 12, "tete": "ab" * 32}]
    m = mouvements(livre, plan, "2026-01-01", "2026-01-31")
    entrees = {
        "debut": "2026-01-01",
        "fin": "2026-01-31",
        "comptes": m["comptes"],
        "couts_directs": None,
        "ecritures_definitives": m["ecritures_definitives"],
        "brouillons": m["brouillons"],
        "periode_close": m["periode_close"],
        "plan_comptable_version": m["plan_comptable_version"],
        "sources": source,
    }
    avec = rapports_financiers.calculer_etat_des_resultats(entrees, {"debut": "2026-01-01", "fin": "2026-01-31"})
    sans = rapports_financiers.calculer_etat_des_resultats(
        {k: v for k, v in entrees.items() if k != "sources"}, {"debut": "2026-01-01", "fin": "2026-01-31"}
    )
    assert (
        avec["etat"]["sources"] == source
        and avec["recu"]["entrees"]["sources"] == source
        and sans["etat"]["sources"] == []
    )
    assert avec["recu"]["empreinte"] != sans["recu"]["empreinte"]  # citer une autre source change l'empreinte
    assert rapports_financiers.rejouer(avec["recu"]) == (True, "")
