from decimal import ROUND_DOWN, Decimal, getcontext, setcontext

import pytest
from m5_financecore.cotisations_rqap_ae_2026 import calculer_cotisations_rqap_ae_preparatoires
from m5_financecore.cotisations_rrq_regulieres import calculer_cotisation_rrq_preparatoire
from m5_financecore.impot_federal_qc_2026 import calculer_retenue_federale_qc_preparatoire
from m5_financecore.paie_qc_preparatoire import calculer_paie_qc_preparatoire


def _preuve(nom):
    return {"id": nom, "sha256": "a" * 64, "fictif": True}


def _demandes(salaire="1002.00"):
    contexte = {
        "annee": 2026,
        "date_paie": "2026-01-15",
        "juridiction": "QC",
        "frequence": "bihebdomadaire",
        "periode_annuelle": 1,
    }
    rrq = {
        **contexte,
        "emploi_continu": True,
        "paiement_regulier_fixe": True,
        "gratif_ou_retroactif": False,
        "transfert_rpc_vers_rrq": False,
        "exemption_speciale": False,
        "assujettissement_qc": True,
        "pm": 12,
        "preuve_pm": _preuve("rrq-pm12"),
        "salaire_rrq_periode": salaire,
        "salaire_rrq_cumul_avant": "0.00",
        "rrq_palier1_cumul_avant": "0.00",
        "rrq_palier2_cumul_avant": "0.00",
        "preuve_assiette": _preuve("rrq-assiette"),
        "preuve_cumuls": _preuve("rrq-cumuls"),
        "preuve_calendrier": _preuve("rrq-calendrier"),
    }
    rqap_ae = {
        **contexte,
        "paiement_regulier_fixe": True,
        "gratif_ou_retroactif": False,
        "transfert_province": False,
        "taux_ae_reduit": False,
        "exemption_speciale": False,
        "assujettissement_qc": True,
        "salaire_en_argent_confirme": True,
        "assiette_rqap_periode": salaire,
        "rqap_salarie_cumul_avant": "0.00",
        "rqap_employeur_cumul_avant": "0.00",
        "assiette_ae_periode": salaire,
        "ae_salarie_cumul_avant": "0.00",
        "ae_employeur_cumul_avant": "0.00",
        "preuve_assiette_rqap": _preuve("rqap-assiette"),
        "preuve_cumul_rqap_salarie": _preuve("rqap-salarie-ytd"),
        "preuve_cumul_rqap_employeur": _preuve("rqap-employeur-ytd"),
        "preuve_assiette_ae": _preuve("ae-assiette"),
        "preuve_cumul_ae_salarie": _preuve("ae-salarie-ytd"),
        "preuve_cumul_ae_employeur": _preuve("ae-employeur-ytd"),
    }
    impot_qc = {
        **contexte,
        "paiement_regulier_fixe": True,
        "gratif_ou_retroactif": False,
        "remuneration_variable": False,
        "exonere": False,
        "transfert_province": False,
        "resident": True,
        "G": salaire,
        "F": "0.00",
        "D": salaire,
        "CSA": "0.00",
        "J_annuel": "0.00",
        "J3": "0.00",
        "J_determined_after_period_1": False,
        "J1_annuel": "0.00",
        "J2": "0.00",
        "J1_determined_after_period_1": False,
        "K1_annuel": "0.00",
        "K2": "0.00",
        "K1_determined_after_period_1": False,
        "E1": "0.00",
        "E2": "0.00",
        "Q": "0.00",
        "Q1": "0.00",
        "fonds_travailleurs_total_annuel_programme": "0.00",
        "L": "0.00",
    }
    federal = {
        **contexte,
        "periode_annuelle": 1,
        "pm": 12,
        "emploi_annuel_continu": True,
        "resident": True,
        "revenu_brut_emploi": salaire,
        "TC": "16452.00",
        "F": "0.00",
        "F2": "0.00",
        "HD": "0.00",
        "F1": "0.00",
        "U1": "0.00",
        "K3": "0.00",
        "LCF": "0.00",
        "L": "0.00",
        "preuves": {
            "td1": _preuve("td1-federal"),
            "emploi_annuel_continu": _preuve("emploi-annuel"),
            "assiettes_egales": _preuve("assiettes-egales"),
            "residence": _preuve("residence-declaree"),
            "zeros_hors_scope": _preuve("zeros-hors-scope"),
        },
    }
    return {"entree_rrq": rrq, "entree_impot_qc": impot_qc, "entree_rqap_ae": rqap_ae, "demande_federale": federal}


def _calculer(demandes):
    return calculer_retenue_federale_qc_preparatoire(**demandes)


def test_parcours_public_rrq_rqap_ae_facade_jusqu_a_retenue_federale_p1():
    demandes = _demandes("1002.00")
    rrq, refus_rrq = calculer_cotisation_rrq_preparatoire(**demandes["entree_rrq"])
    rqap_ae, refus_rqap_ae = calculer_cotisations_rqap_ae_preparatoires(**demandes["entree_rqap_ae"])
    facade = calculer_paie_qc_preparatoire(
        entree_rrq=demandes["entree_rrq"],
        entree_impot_qc=demandes["entree_impot_qc"],
        entree_rqap_ae=demandes["entree_rqap_ae"],
    )
    assert refus_rrq is None
    assert refus_rqap_ae is None
    assert rrq["cotisation_palier1"] == "54.65"
    assert rqap_ae["postes"]["ae_salarie"] == "13.03"
    assert facade["statut"] == "INCOMPLET"
    assert facade["refus"] == {}
    assert set(facade["postes"]) == {"rrq", "impot_qc", "rqap_ae"}

    rapport, refus = _calculer(demandes)

    assert refus is None
    assert rapport["retenue_impot_federal"] == "28.00"
    assert rapport["facteurs_exacts"]["F5Q"] == "8.6746031746031746031746031746031746031746031746032"
    assert rapport["facteurs_exacts"]["K2Q"] == "230.46294844444444444444444444444444444444444444444"
    assert rapport["authenticite_preuves"] == "NON_VERIFIEE"
    assert rapport["statut"] == "PREPARATOIRE"
    assert rapport["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE"
    assert rapport["revenu_net"] is None
    assert rapport["das_complete"] is None
    assert rapport["cout_employeur_global"] is None
    assert rapport["statut_ccq"] == "UNKNOWN"
    assert rapport["actions_financieres_bloquees"] is True


def test_f5q_est_garde_en_precision_complete_jusqua_A():
    rapport, refus = _calculer(_demandes("1000.00"))
    assert refus is None
    assert rapport["facteurs_exacts"]["F5Q"] == "8.6539682539682539682539682539682539682539682539683"
    assert rapport["retenue_impot_federal"] == "27.78"


def test_k2q_utilise_IE_brut_plutot_que_prime_qpip_arrondie():
    rapport, refus = _calculer(_demandes("742.54"))
    assert refus is None
    assert rapport["postes_composants"]["rqap_ae"]["rqap_salarie"] == "3.19"
    assert rapport["retenue_impot_federal"] == "0.10"
    assert rapport["entrees"]["assiette_IE"] == "742.54"


def test_les_seuils_federaux_et_plafonds_k2q_sont_appliques():
    sous_seuil, refus_sous = _calculer(_demandes("2272.26"))
    au_dessus, refus_au_dessus = _calculer(_demandes("2272.27"))
    assert refus_sous is None
    assert refus_au_dessus is None
    assert sous_seuil["facteurs_exacts"]["A"] == "58522.979047619047619047619047619047619047619047619"
    assert sous_seuil["facteurs_exacts"]["R"] == "0.1400"
    assert sous_seuil["facteurs_exacts"]["K"] == "0.00"
    assert au_dessus["facteurs_exacts"]["A"] == "58523.239047619047619047619047619047619047619047619"
    assert au_dessus["facteurs_exacts"]["R"] == "0.2050"
    assert au_dessus["facteurs_exacts"]["K"] == "3804.00"

    plafonds, refus_plafonds = _calculer(_demandes("10000.00"))
    assert refus_plafonds is None
    assert Decimal(plafonds["facteurs_exacts"]["K2Q"]) == Decimal("714.966")


@pytest.mark.parametrize("changement", [
    {"date_paie": "2026-07-01"},
    {"periode_annuelle": 2},
    {"emploi_annuel_continu": False},
    {"resident": False},
    {"TC": None},
    {"TC": "NaN"},
    {"K3": "1.00"},
    {"LCF": "0.01"},
])
def test_refuse_date_periode_attestation_et_postes_hors_perimetre(changement):
    demandes = _demandes()
    demandes["demande_federale"].update(changement)
    rapport, refus = _calculer(demandes)
    assert rapport is None
    assert refus is not None


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("assiette_ae_periode", "1001.00"),
        ("assiette_rqap_periode", "1001.00"),
    ],
)
def test_refuse_assiettes_incoherentes_avant_la_facade(champ, valeur):
    demandes = _demandes()
    demandes["entree_rqap_ae"][champ] = valeur
    rapport, refus = _calculer(demandes)
    assert rapport is None
    assert refus["code"] == "REJ-PAIE-ASSIETTE-INVALIDE"


def test_refuse_un_refus_de_composante_et_ne_mutile_pas_les_demandes():
    demandes = _demandes()
    demandes["entree_rrq"]["salaire_rrq_cumul_avant"] = "0.01"
    original = {nom: dict(valeur) for nom, valeur in demandes.items() if nom != "demande_federale"}
    rapport, refus = _calculer(demandes)
    assert rapport is None
    assert refus["code"] == "REJ-PAIE-SOURCE-NON-QUALIFIEE"
    for nom, valeur in original.items():
        assert demandes[nom] == valeur


def test_contexte_decimal_ambiant_ne_change_pas_le_resultat_ni_le_contexte_appelant():
    original = getcontext().copy()
    contexte = original.copy()
    try:
        contexte.prec = 2
        contexte.rounding = ROUND_DOWN
        contexte.Emin = -2
        contexte.Emax = 2
        contexte.clamp = 1
        for signal in contexte.traps:
            contexte.traps[signal] = True
        setcontext(contexte)
        rapport, refus = _calculer(_demandes("1002.00"))
        assert refus is None
        assert rapport["retenue_impot_federal"] == "28.00"
        assert getcontext().prec == 2
        assert getcontext().rounding == ROUND_DOWN
        assert getcontext().Emin == -2
        assert getcontext().Emax == 2
        assert getcontext().clamp == 1
        assert all(getcontext().traps.values())
    finally:
        setcontext(original)
