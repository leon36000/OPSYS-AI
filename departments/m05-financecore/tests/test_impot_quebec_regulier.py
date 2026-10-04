from decimal import ROUND_DOWN, Decimal, getcontext, setcontext

import m5_financecore.impot_quebec_regulier as moteur_impot_qc
import pytest
from m5_financecore.impot_quebec_regulier import calculer_retenue_preparatoire


def entree(**modifications):
    valeur = {
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
        "CSA": "38.65",
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
    valeur.update(modifications)
    return valeur


def test_reproduit_les_cinq_checkpoints_officiels_dun_seul_scenario():
    checkpoints = [
        (18, "38.65", "100.00", "150.00", "444.51", "96345.08", "11557.37"),
        (19, "71.24", "100.00", "150.00", "438.32", "95497.74", "11396.37"),
        (21, "160.00", "100.00", "150.00", "421.46", "93189.98", "10957.90"),
        (22, "40.00", "0.00", "0.00", "481.76", "96309.98", "12525.70"),
        (26, "0.00", "0.00", "0.00", "489.36", "97349.98", "12723.30"),
    ]
    for periode, csa, q, q1, attendu, imposable, impot_annuel in checkpoints:
        resultat, refus = calculer_retenue_preparatoire(**entree(periode_annuelle=periode, CSA=csa, Q=q, Q1=q1))
        assert refus is None
        assert resultat["retenue_qc_preparatoire"] == attendu
        assert resultat["revenu_imposable_annuel"] == imposable
        assert resultat["impot_annuel_intermediaire"] == impot_annuel
        assert resultat["mode"] == "PREPARATOIRE"
        assert resultat["source"]["statut"] == "NON_QUALIFIEE_POUR_PAIE"
        assert resultat["date_paie"] == "2026-01-15"
        assert resultat["net"] is None
        assert resultat["actions_bloquees"] is True


def test_frontieres_des_quatre_tranches_incluent_le_seuil_dans_la_tranche_basse():
    for revenu, taux, constante in [
        ("54345.00", "0.14", "0.00"),
        ("54345.01", "0.19", "2717.00"),
        ("108680.00", "0.19", "2717.00"),
        ("108680.01", "0.24", "8151.00"),
        ("132245.00", "0.24", "8151.00"),
        ("132245.01", "0.2575", "10465.00"),
    ]:
        annuel_base = Decimal("208000.00")
        resultat, refus = calculer_retenue_preparatoire(
            **entree(
                G="8000.00",
                F="0.00",
                D="0.00",
                CSA="0.00",
                J_annuel=str(annuel_base - Decimal(revenu)),
                E1="0.00",
                Q="0.00",
                Q1="0.00",
                fonds_travailleurs_total_annuel_programme="0.00",
            )
        )
        assert refus is None
        assert resultat["revenu_imposable_annuel"] == revenu
        assert resultat["tranche"]["taux"] == taux
        assert resultat["tranche"]["constante"] == constante


def test_pr_se_termine_a_un_a_la_derniere_periode():
    resultat, refus = calculer_retenue_preparatoire(
        **entree(
            periode_annuelle=26,
            CSA="0.00",
            J_determined_after_period_1=True,
            J3="100.00",
            J1_determined_after_period_1=True,
            J2="50.00",
            K1_determined_after_period_1=True,
            K2="20.00",
        )
    )
    assert refus is None
    assert resultat["periodes_restantes"] == 1
    assert resultat["J_applique"] == "2600.00"
    assert resultat["J1_applique"] == "1300.00"
    assert resultat["K1_applique"] == "520.00"


def test_marqueur_post_periode_1_refuse_a_la_premiere_periode():
    resultat, refus = calculer_retenue_preparatoire(**entree(J_determined_after_period_1=True, J3="10.00"))
    assert resultat is None
    assert refus["code"] == "REJ-PAIE-ASSIETTE-INVALIDE"


def test_credit_k1_annuel_debut_annee_est_applique_sans_reannualisation():
    resultat, refus = calculer_retenue_preparatoire(**entree(K1_annuel="26.00"))
    assert refus is None
    assert resultat["retenue_qc_preparatoire"] == "443.51"
    assert resultat["K1_applique"] == "26.00"


def test_recalcule_j_j1_et_k1_selon_periodes_restantes_incluant_periode_courante():
    resultat, refus = calculer_retenue_preparatoire(
        **entree(
            periode_annuelle=10,
            CSA="0.00",
            J_determined_after_period_1=True,
            J3="100.00",
            J1_determined_after_period_1=True,
            J2="50.00",
            K1_determined_after_period_1=True,
            K2="20.00",
        )
    )
    assert refus is None
    assert resultat["periodes_restantes"] == 17
    assert resultat["J_applique"] == "152.94"
    assert resultat["J1_applique"] == "76.47"
    assert resultat["K1_applique"] == "30.59"


def test_les_montants_annuels_negatifs_dimpot_sont_plafonnes_a_zero():
    resultat, refus = calculer_retenue_preparatoire(
        **entree(
            G="0.00",
            F="0.00",
            D="0.00",
            CSA="0.00",
            E1="0.00",
            Q="0.00",
            Q1="0.00",
            fonds_travailleurs_total_annuel_programme="0.00",
        )
    )
    assert refus is None
    assert resultat["revenu_imposable_annuel"] == "0.00"
    assert resultat["impot_annuel_intermediaire"] == "0.00"
    assert resultat["retenue_qc_preparatoire"] == "0.00"


def test_e1_e2_sont_arrondis_a_leuro_dollar_plus_proche_egalite_vers_le_haut():
    resultat, refus = calculer_retenue_preparatoire(**entree(E1="0.25", E2="0.25"))
    assert refus is None
    assert resultat["intermediaires"]["E_arrondi"] == "1"


def test_coefficients_canoniques_pilotent_effectivement_la_retenue(monkeypatch):
    entree_calcul = entree(E1="26.00", Q="1.00", Q1="0.00")
    avec_coefficients, refus = calculer_retenue_preparatoire(**entree_calcul)
    assert refus is None

    monkeypatch.setattr(moteur_impot_qc, "_E_CREDIT", Decimal("0"))
    monkeypatch.setattr(moteur_impot_qc, "_Q_CREDIT", Decimal("0"))
    sans_coefficients, refus = calculer_retenue_preparatoire(**entree_calcul)
    assert refus is None
    assert Decimal(sans_coefficients["retenue_qc_preparatoire"]) - Decimal(
        avec_coefficients["retenue_qc_preparatoire"]
    ) == Decimal("0.29")


@pytest.mark.parametrize(
    "modifications",
    [
        {"frequence": "mensuelle"},
        {"annee": 2025},
        {"periode_annuelle": 27},
        {"periode_annuelle": True},
        {"resident": False},
        {"transfert_province": True},
        {"paiement_regulier_fixe": False},
        {"gratif_ou_retroactif": True},
        {"remuneration_variable": True},
        {"exonere": True},
        {"G": "NaN"},
        {"G": "Infinity"},
        {"G": "-1.00"},
        {"G": "1.001"},
        {"G": 4000.0},
        {"CSA": None},
        {"fonds_travailleurs_total_annuel_programme": "5000.01"},
        {"Q": "6000.00", "fonds_travailleurs_total_annuel_programme": "5000.00"},
        {"G": "0" * 1000},
    ],
)
def test_refuse_entrees_malformees_ou_hors_couverture(modifications):
    resultat, refus = calculer_retenue_preparatoire(**entree(**modifications))
    assert resultat is None
    assert refus is not None
    assert refus["code"].startswith("REJ-PAIE-")


def test_calcul_ne_depend_pas_du_contexte_decimal_ambiant_extreme_et_le_preserve():
    original = getcontext().copy()
    contexte = original.copy()
    contexte.prec = 2
    contexte.rounding = ROUND_DOWN
    contexte.Emin = -2
    contexte.Emax = 2
    contexte.clamp = 1
    for signal in contexte.traps:
        contexte.traps[signal] = True
    try:
        setcontext(contexte)
        resultat, refus = calculer_retenue_preparatoire(**entree())
        assert getcontext().prec == 2
        assert getcontext().rounding == ROUND_DOWN
        assert getcontext().Emin == -2
        assert getcontext().Emax == 2
        assert getcontext().clamp == 1
        assert all(getcontext().traps.values())
    finally:
        setcontext(original)
    assert refus is None
    assert resultat["retenue_qc_preparatoire"] == "444.51"


def test_date_malformee_et_champ_ajoute_sont_refuses():
    resultat, refus = calculer_retenue_preparatoire(**entree(date_paie="2026-1-1"))
    assert resultat is None and refus["code"] == "REJ-PAIE-DATE-INVALIDE"
    resultat, refus = calculer_retenue_preparatoire(**entree(client="donnée interdite"))
    assert resultat is None and refus["code"] == "REJ-PAIE-ASSIETTE-INVALIDE"
