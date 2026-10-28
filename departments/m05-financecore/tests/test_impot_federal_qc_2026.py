from copy import deepcopy
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


def _demandes_ytd(salaire="1000.00", *, periode=22, date_paie="2026-10-23", plafonne=False):
    demandes = _demandes(salaire)
    for entree in demandes.values():
        entree.update(periode_annuelle=periode, date_paie=date_paie)
    demandes["entree_rrq"].update(
        salaire_rrq_cumul_avant="105000.00" if plafonne else "21000.00",
        rrq_palier1_cumul_avant="4479.30" if plafonne else "1144.92",
        rrq_palier2_cumul_avant="416.00" if plafonne else "0.00",
    )
    demandes["entree_rqap_ae"].update(
        rqap_salarie_cumul_avant="442.90" if plafonne else "90.30",
        rqap_employeur_cumul_avant="620.06" if plafonne else "126.42",
        ae_salarie_cumul_avant="895.70" if plafonne else "273.00",
        ae_employeur_cumul_avant="1253.98" if plafonne else "382.20",
    )
    return demandes


def test_ytd_octobre_retenue_non_nulle_et_sources_datees_sans_paie_finale():
    # Oracle conditionnel T4127 ch.4, fractions exactes : T=27.784792.
    demandes = _demandes_ytd()
    original = deepcopy(demandes)
    rapport, refus = _calculer(demandes)
    assert refus is None
    assert rapport["retenue_impot_federal"] == "27.78"
    assert rapport["contexte"]["periode_annuelle"] == 22
    assert rapport["methode_credits"] == "CUMULS_PLUS_PERIODES_RESTANTES"
    assert rapport["parametres"]["edition"] == "T4127-123-2026-07"
    assert rapport["facteurs_exacts"]["PR"] == "5"
    assert rapport["revenu_net"] is None
    assert rapport["das_complete"] is None
    assert rapport["actions_financieres_bloquees"] is True
    assert rapport["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE"
    assert demandes == original


def test_ytd_apres_plafonds_les_credits_rrq_ae_ne_disparaissent_pas():
    # C=EI=0 n'annule pas les droits cumulés. Oracle indépendant : 652.925488...
    rapport, refus = _calculer(_demandes_ytd("5000.00", plafonne=True))
    assert refus is None
    assert rapport["postes_composants"]["rrq"] == {"cotisation_palier1": "0.00", "cotisation_palier2": "0.00"}
    assert rapport["postes_composants"]["rqap_ae"]["ae_salarie"] == "0.00"
    assert Decimal(rapport["facteurs_exacts"]["K2Q"]) == Decimal("714.966")
    assert rapport["retenue_impot_federal"] == "652.93"


def test_ytd_atteinte_du_plafond_dans_la_periode_utilise_le_cumul_valide():
    demandes = _demandes_ytd("3500.00")
    demandes["entree_rrq"].update(salaire_rrq_cumul_avant="73500.00", rrq_palier1_cumul_avant="4452.42")
    demandes["entree_rqap_ae"].update(
        rqap_salarie_cumul_avant="316.05", rqap_employeur_cumul_avant="442.47",
        ae_salarie_cumul_avant="895.70", ae_employeur_cumul_avant="1253.98",
    )
    rapport, refus = _calculer(demandes)
    assert refus is None
    assert rapport["postes_composants"]["rrq"] == {"cotisation_palier1": "26.88", "cotisation_palier2": "96.00"}
    # T4127 Option1/YTD, facteurs exacts : T=4447043/12480.
    assert rapport["retenue_impot_federal"] == "356.33"


@pytest.mark.parametrize("entree,champ", [
    ("entree_rrq", "rrq_palier1_cumul_avant"),
    ("entree_rrq", "preuve_cumuls"),
    ("entree_rqap_ae", "ae_salarie_cumul_avant"),
    ("entree_rqap_ae", "preuve_cumul_rqap_salarie"),
])
def test_ytd_refuse_cumul_ou_preuve_manquante_sans_defaut(entree, champ):
    demandes = _demandes_ytd()
    del demandes[entree][champ]
    rapport, refus = _calculer(demandes)
    assert rapport is None
    assert refus["code"] == "REJ-PAIE-SOURCE-NON-QUALIFIEE"


@pytest.mark.parametrize("periode", [True, 0, 27])
def test_ytd_refuse_periode_non_entiere_ou_hors_26(periode):
    rapport, refus = _calculer(_demandes_ytd(periode=periode))
    assert rapport is None
    assert refus["code"] == "REJ-PAIE-ASSIETTE-INVALIDE"


def test_ytd_deuxieme_periode_garde_le_bareme_janvier_et_pr_inclusif():
    demandes = _demandes_ytd(periode=2, date_paie="2026-01-16")
    demandes["entree_rrq"].update(salaire_rrq_cumul_avant="1000.00", rrq_palier1_cumul_avant="54.52")
    demandes["entree_rqap_ae"].update(
        rqap_salarie_cumul_avant="4.30", rqap_employeur_cumul_avant="6.02",
        ae_salarie_cumul_avant="13.00", ae_employeur_cumul_avant="18.20",
    )
    rapport, refus = _calculer(demandes)
    assert refus is None
    assert rapport["parametres"]["edition"] == "T4127-122-2026-01"
    assert rapport["facteurs_exacts"]["PR"] == "25"
    assert rapport["retenue_impot_federal"] == "27.78"


def test_ytd_decimal_ambiant_hostile_ne_modifie_ni_retenue_ni_contexte():
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
        rapport, refus = _calculer(_demandes_ytd("5000.00", plafonne=True))
        assert refus is None
        assert rapport["retenue_impot_federal"] == "652.93"
        assert getcontext().prec == 2
        assert getcontext().rounding == ROUND_DOWN
        assert all(getcontext().traps.values())
    finally:
        setcontext(original)
