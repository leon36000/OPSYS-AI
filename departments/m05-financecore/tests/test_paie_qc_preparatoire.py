from decimal import ROUND_DOWN, Inexact, localcontext

import pytest
from m5_financecore.cotisations_rqap_ae_2026 import (
    HASH_PARAMETRES,
    calculer_cotisations_rqap_ae_preparatoires,
)
from m5_financecore.cotisations_rrq_regulieres import calculer_cotisation_rrq_preparatoire
from m5_financecore.paie_qc_preparatoire import calculer_paie_qc_preparatoire


def _preuve(nom):
    return {"id": nom, "sha256": "a" * 64, "fictif": True}


def entree_cotisations(**modifications):
    entree = {
        "annee": 2026,
        "date_paie": "2026-01-15",
        "juridiction": "QC",
        "frequence": "bihebdomadaire",
        "periode_annuelle": 1,
        "paiement_regulier_fixe": True,
        "gratif_ou_retroactif": False,
        "transfert_province": False,
        "taux_ae_reduit": False,
        "exemption_speciale": False,
        "assujettissement_qc": True,
        "salaire_en_argent_confirme": True,
        "assiette_rqap_periode": "1000.00",
        "rqap_salarie_cumul_avant": "0.00",
        "rqap_employeur_cumul_avant": "0.00",
        "assiette_ae_periode": "1000.00",
        "ae_salarie_cumul_avant": "0.00",
        "ae_employeur_cumul_avant": "0.00",
        "preuve_assiette_rqap": _preuve("rqap-assiette"),
        "preuve_cumul_rqap_salarie": _preuve("rqap-ee-ytd"),
        "preuve_cumul_rqap_employeur": _preuve("rqap-er-ytd"),
        "preuve_assiette_ae": _preuve("ae-assiette"),
        "preuve_cumul_ae_salarie": _preuve("ae-ee-ytd"),
        "preuve_cumul_ae_employeur": _preuve("ae-er-ytd"),
    }
    entree.update(modifications)
    return entree


def entree_rrq():
    return {
        "annee": 2026,
        "date_paie": "2026-01-15",
        "juridiction": "QC",
        "frequence": "bihebdomadaire",
        "periode_annuelle": 1,
        "emploi_continu": True,
        "paiement_regulier_fixe": True,
        "gratif_ou_retroactif": False,
        "transfert_rpc_vers_rrq": False,
        "exemption_speciale": False,
        "assujettissement_qc": True,
        "pm": 12,
        "preuve_pm": _preuve("pm"),
        "salaire_rrq_periode": "4000.00",
        "salaire_rrq_cumul_avant": "0.00",
        "rrq_palier1_cumul_avant": "0.00",
        "rrq_palier2_cumul_avant": "0.00",
        "preuve_assiette": _preuve("rrq-assiette"),
        "preuve_cumuls": _preuve("rrq-cumuls"),
        "preuve_calendrier": _preuve("rrq-calendrier"),
    }


def entree_impot():
    return {
        "annee": 2026,
        "date_paie": "2026-01-15",
        "juridiction": "QC",
        "frequence": "bihebdomadaire",
        "periode_annuelle": 1,
        "paiement_regulier_fixe": True,
        "gratif_ou_retroactif": False,
        "remuneration_variable": False,
        "exonere": False,
        "transfert_province": False,
        "resident": True,
        "G": "4000.00",
        "F": "200.00",
        "D": "4000.00",
        "CSA": "0.00",  # la façade doit remplacer cette valeur par le CSA calculé
        "J_annuel": "0.00",
        "J3": "0.00",
        "J_determined_after_period_1": False,
        "J1_annuel": "0.00",
        "J2": "0.00",
        "J1_determined_after_period_1": False,
        "K1_annuel": "0.00",
        "K2": "0.00",
        "K1_determined_after_period_1": False,
        "E1": "21830.00",
        "E2": "0.00",
        "Q": "100.00",
        "Q1": "150.00",
        "fonds_travailleurs_total_annuel_programme": "5000.00",
        "L": "0.00",
    }


def test_reproduit_vecteurs_formules_et_limites_distinctes_des_composantes():
    rapport, refus = calculer_cotisations_rqap_ae_preparatoires(**entree_cotisations())
    assert refus is None
    assert rapport["postes"] == {
        "rqap_salarie": "4.30",
        "rqap_employeur": "6.02",
        "ae_salarie": "13.00",
        "ae_employeur": "18.20",
    }
    assert rapport["hash_parametres"] == HASH_PARAMETRES
    assert rapport["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE"
    assert rapport["revenu_net"] is None
    assert rapport["statut_ccq"] == "UNKNOWN"


def test_rqap_applique_le_plancher_salarie_et_arrondi_employeur_distinct():
    rapport, refus = calculer_cotisations_rqap_ae_preparatoires(
        **entree_cotisations(assiette_rqap_periode="0.01", assiette_ae_periode="0.01")
    )
    assert refus is None
    assert rapport["postes"]["rqap_salarie"] == "0.01"
    assert rapport["postes"]["rqap_employeur"] == "0.00"
    assert rapport["postes"]["ae_salarie"] == "0.00"
    assert rapport["postes"]["ae_employeur"] == "0.00"


def test_ae_frontieres_arrondies_sur_prime_employeur_et_salarie():
    rapport, refus = calculer_cotisations_rqap_ae_preparatoires(
        **entree_cotisations(assiette_rqap_periode="1.00", assiette_ae_periode="1.00")
    )
    assert refus is None
    assert rapport["postes"]["ae_salarie"] == "0.01"
    assert rapport["postes"]["ae_employeur"] == "0.02"
    assert rapport["postes"]["ae_employeur"] != "0.01"  # 1,4 × le montant salarié déjà arrondi serait faux ici


@pytest.mark.parametrize(
    ("assiette", "salarie", "employeur"),
    [("0.38", "0.00", "0.01"), ("0.39", "0.01", "0.01"), ("0.27", "0.00", "0.00"), ("0.28", "0.00", "0.01")],
)
def test_ae_arrondit_au_cent_de_part_et_dautre_du_demi_cent(assiette, salarie, employeur):
    rapport, refus = calculer_cotisations_rqap_ae_preparatoires(
        **entree_cotisations(assiette_rqap_periode=assiette, assiette_ae_periode=assiette)
    )
    assert refus is None
    assert rapport["postes"]["ae_salarie"] == salarie
    assert rapport["postes"]["ae_employeur"] == employeur


def test_plafonds_sont_appliques_aux_cumuls_salarie_et_employeur_separement():
    rapport, refus = calculer_cotisations_rqap_ae_preparatoires(
        **entree_cotisations(
            date_paie="2026-09-15",
            periode_annuelle=20,
            rqap_salarie_cumul_avant="442.89",
            rqap_employeur_cumul_avant="620.05",
            ae_salarie_cumul_avant="895.69",
            ae_employeur_cumul_avant="1253.97",
        )
    )
    assert refus is None
    assert rapport["postes"] == {
        "rqap_salarie": "0.01",
        "rqap_employeur": "0.01",
        "ae_salarie": "0.01",
        "ae_employeur": "0.01",
    }
    _, refus = calculer_cotisations_rqap_ae_preparatoires(
        **entree_cotisations(rqap_salarie_cumul_avant="442.91")
    )
    assert refus["code"] == "REJ-PAIE-ASSIETTE-INVALIDE"


@pytest.mark.parametrize(
    "champ",
    [
        "rqap_salarie_cumul_avant",
        "rqap_employeur_cumul_avant",
        "ae_salarie_cumul_avant",
        "ae_employeur_cumul_avant",
    ],
)
def test_periode_1_refuse_tout_cumul_de_cotisation_anterieur_non_nul(champ):
    _, refus = calculer_cotisations_rqap_ae_preparatoires(
        **entree_cotisations(**{champ: "0.01"})
    )
    assert refus["code"] == "REJ-PAIE-ASSIETTE-INVALIDE"


def test_employeur_peut_atteindre_son_plafond_un_cent_avant_le_salarie():
    rapport, refus = calculer_cotisations_rqap_ae_preparatoires(
        **entree_cotisations(
            date_paie="2026-12-31",
            periode_annuelle=26,
            assiette_rqap_periode="10.00",
            rqap_salarie_cumul_avant="442.89",
            rqap_employeur_cumul_avant="620.06",
        )
    )
    assert refus is None
    assert rapport["postes"]["rqap_salarie"] == "0.01"
    assert rapport["postes"]["rqap_employeur"] == "0.00"


def test_refuse_maximum_salarie_rqap_si_cumul_employeur_ne_latteint_pas():
    _, refus = calculer_cotisations_rqap_ae_preparatoires(
        **entree_cotisations(
            date_paie="2026-01-29",
            periode_annuelle=2,
            assiette_rqap_periode="10.00",
            rqap_salarie_cumul_avant="442.90",
            rqap_employeur_cumul_avant="620.05",
        )
    )
    assert refus["code"] == "REJ-PAIE-ASSIETTE-INVALIDE"


@pytest.mark.parametrize(
    "modification",
    [
        {"assiette_rqap_periode": True},
        {"assiette_ae_periode": 1000.0},
        {"date_paie": "2025-12-31"},
        {"juridiction": "ON"},
        {"periode_annuelle": True},
        {"taux_ae_reduit": True},
        {"transfert_province": True},
        {"preuve_assiette_rqap": None},
        {"preuve_assiette_rqap": {"id": "bad id", "sha256": "a" * 64, "fictif": True}},
        {"source_externe": "inconnue"},
    ],
)
def test_refuse_entrees_non_canoniques_hors_perimetre_et_champs_inconnus(modification):
    _, refus = calculer_cotisations_rqap_ae_preparatoires(**entree_cotisations(**modification))
    assert refus is not None


@pytest.mark.parametrize("valeur", ["NaN", "Infinity", "1e999", "-1.00"])
def test_refuse_nan_inf_exposant_et_montant_negatif(valeur):
    _, refus = calculer_cotisations_rqap_ae_preparatoires(
        **entree_cotisations(assiette_ae_periode=valeur)
    )
    assert refus["code"] == "REJ-PAIE-ASSIETTE-INVALIDE"


def test_refuse_assiette_manquante():
    demande = entree_cotisations()
    demande.pop("assiette_ae_periode")
    _, refus = calculer_cotisations_rqap_ae_preparatoires(**demande)
    assert refus["code"] == "REJ-PAIE-ASSIETTE-INVALIDE"


def test_calculs_resistent_au_contexte_decimal_ambiant_et_ne_le_modifient_pas():
    demande = entree_cotisations()
    reference, _ = calculer_cotisations_rqap_ae_preparatoires(**demande)
    with localcontext() as contexte:
        contexte.prec = 2
        contexte.rounding = ROUND_DOWN
        contexte.Emax = 2
        contexte.Emin = -2
        contexte.clamp = 1
        contexte.traps[Inexact] = True
        avant = (
            contexte.prec,
            contexte.rounding,
            contexte.Emax,
            contexte.Emin,
            contexte.clamp,
            contexte.traps[Inexact],
        )
        actuel, refus = calculer_cotisations_rqap_ae_preparatoires(**demande)
        apres = (
            contexte.prec,
            contexte.rounding,
            contexte.Emax,
            contexte.Emin,
            contexte.clamp,
            contexte.traps[Inexact],
        )
    assert refus is None
    assert actuel == reference
    assert apres == avant


def test_facade_appelle_rrq_puis_r42_avec_le_csa_calcule_et_garde_postes_separes():
    rrq_input = entree_rrq()
    rrq_attendu, refus = calculer_cotisation_rrq_preparatoire(**rrq_input)
    assert refus is None
    impot_input = entree_impot()
    report = calculer_paie_qc_preparatoire(
        entree_rrq=rrq_input,
        entree_impot_qc=impot_input,
        entree_rqap_ae=entree_cotisations(),
    )
    assert report["statut"] == "INCOMPLET"
    assert report["composantes"] == "CALCULEES_PREPARATOIRES"
    assert report["postes"]["rrq"]["CSA"] == rrq_attendu["CSA"] == "38.65"
    assert report["postes"]["impot_qc"]["assiettes_fournies"]["CSA"] == "38.65"
    assert report["postes"]["rqap_ae"]["postes"]["rqap_salarie"] == "4.30"
    assert "total_retenues" not in report and "net" not in report["postes"]
    assert report["revenu_net"] is None
    assert report["statut_ccq"] == "UNKNOWN"
    assert report["actions_financieres_bloquees"] is True
    assert impot_input["CSA"] == "0.00"  # l'entrée du demandeur est laissée intacte


def test_facade_refuse_contexte_discordant_sans_calculer_un_paquet():
    cotisations = entree_cotisations(date_paie="2026-01-29")
    report = calculer_paie_qc_preparatoire(
        entree_rrq=entree_rrq(), entree_impot_qc=entree_impot(), entree_rqap_ae=cotisations
    )
    assert report["statut"] == "INCOMPLET"
    assert set(report["refus"]) == {"contexte"}
    assert report["postes"] == {}
    assert report["revenu_net"] is None


def test_facade_conserve_refus_composant_et_ne_presente_pas_de_total_partiel():
    cotisations = entree_cotisations(taux_ae_reduit=True)
    report = calculer_paie_qc_preparatoire(
        entree_rrq=entree_rrq(), entree_impot_qc=entree_impot(), entree_rqap_ae=cotisations
    )
    assert report["statut"] == "INCOMPLET"
    assert report["refus"]["rqap_ae"]["code"] == "REJ-PAIE-ASSIETTE-INVALIDE"
    assert "total_retenues" not in report
    assert report["cout_employeur_global"] is None
