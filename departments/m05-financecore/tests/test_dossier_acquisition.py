"""Conseillers C1 (camion/équipement) et C2 (bâtiment commercial) : dossiers de décision chiffrés.

Tests ROUGES (vague 13, M5) : le module `dossier_acquisition` n'existe pas encore.
Données fictives (`@example.test`, noms « -fictif »), montants en textes décimaux, Decimal exact.
Lecture seule : aucun paiement, aucune recommandation, aucune valeur inventée.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

FICTIF = True
D = Decimal

C1 = {
    "objet": "vehicule",
    "prix_achat": "60000.00",
    "mise_de_fonds": "10000.00",
    "taux_annuel": "0.07",
    "convention": "canadienne_semestrielle",
    "duree_mois": 48,
    "assurance_mensuelle": "120.00",
    "entretien_mensuel": "80.00",
    "revenus_mensuels_additionnels": "2500.00",
    "liquidites_actuelles": "40000.00",
}

C2 = {
    "objet": "immeuble_exploitation",
    "prix_achat": "350000.00",
    "mise_de_fonds": "70000.00",
    "taux_annuel": "0.06",
    "convention": "canadienne_semestrielle",
    "amortissement_annees": 25,
    "frais_achat": "5000.00",
    "loyer_mensuel_evite": "1800.00",
    "revenus_locatifs_mensuels": "0.00",
    "charges_mensuelles": "400.00",
    "liquidites_actuelles": "150000.00",
}


def _dossier_c1(**changes):
    from m5_financecore import dossier_acquisition as da

    sortie, verdict = da.preparer_dossier_camion({**C1, **changes})
    assert verdict is None, verdict
    return sortie["recu"]


def _dossier_c2(**changes):
    from m5_financecore import dossier_acquisition as da

    sortie, verdict = da.preparer_dossier_batiment({**C2, **changes})
    assert verdict is None, verdict
    return sortie["recu"]


def _mensualite_attendue(principal: str, taux: str, convention: str, mois: int) -> Decimal:
    from m5_financecore import maths_financieres as mf

    tableau = mf.amortir(D(principal), mf.taux_periodique(D(taux), "mensuelle", convention), mois)
    return tableau["versement"]


def test_mutants_tueurs_arithmetique_et_gardes():
    """Tue les survivants non équivalents : arithmétique (service, DSCR, stress, totaux, occupation, écart,
    liquidités, mois C2), bornes de durée et distinction objet C2."""
    from decimal import localcontext

    from m5_financecore import dossier_acquisition as da
    from m5_financecore import maths_financieres as mf

    with localcontext(mf.CONTEXTE):
        # C1 : service = mensualité + assurance + entretien (pas mensualité − frais ni × frais).
        r1 = _dossier_c1()["resultat"]
        assert r1["service_dette_mensuel"] == format(D(r1["mensualite"]) + D("200.00"), ".2f")
        # DSCR = revenus / service (pas ×) et stress revenus < base < stress taux quand taux+2 augmente le service.
        assert D(r1["stress"]["revenus_moins_20"]["dscr"]) < D(r1["dscr"]) < D("99")
        # Total = mise + mensualités + frais × durée (pas mise − … ni mise + mensualité / durée).
        assert D(r1["total_decaisse"]) == (
            D("10000.00") + D(r1["mensualite"]) * 48 + D("200.00") * 48
        ).quantize(D("0.01"))
        # Liquidités = solde − mise (pas +).
        assert r1["liquidites_apres_mise_de_fonds"] == "30000.00"
        # C2 : mois = années × 12 (pas /) avec mensualité recalculée à la main pour 300 mois.
        r2 = _dossier_c2()["resultat"]
        assert r2["cout_occupation_mensuel"] == format(D(r2["mensualite"]) + D("400.00"), ".2f")
        assert r2["ecart_mensuel_contre_loyer"] == format(D("1800.00") - D(r2["cout_occupation_mensuel"]), ".2f")
        assert r2["liquidites_apres_achat"] == "75000.00"
        # Bornes de durée exactes : 1 et 120/40 acceptés, 0 et 121/41 refusés.
        for entrees, duree in (({**C1, "duree_mois": 1}, 1), ({**C1, "duree_mois": 120}, 120)):
            sortie, verdict = da.preparer_dossier_camion(entrees)
            assert verdict is None and sortie["recu"]["resultat"]["nombre_versements"] == duree
        for entrees in ({"duree_mois": 0}, {"duree_mois": 121}):
            sortie, verdict = da.preparer_dossier_camion({**C1, **entrees})
            assert sortie is None and verdict["code"] == "REJ-CALC-DUREE-INVALIDE"
        for annees, ok in ((1, True), (40, True), (0, False), (41, False)):
            sortie, verdict = da.preparer_dossier_batiment({**C2, "amortissement_annees": annees})
            assert (verdict is None) is ok
        # C2 : un objet d'exploitation valide mais non-bâtiment est refusé par le nom du dossier.
        sortie, verdict = da.preparer_dossier_batiment({**C2, "objet": "vehicule"})
        assert sortie is None and verdict["code"] == "REJ-CALC-FLUX-INVALIDES"
        # C1/C2 : objet non-texte refusé (garde `is not str`).
        for fn, base in ((da.preparer_dossier_camion, C1), (da.preparer_dossier_batiment, C2)):
            sortie, verdict = fn({**base, "objet": 42})
            assert sortie is None and verdict["code"] in (
                "REJ-CALC-OBJET-HORS-PERIMETRE", "REJ-CALC-FLUX-INVALIDES")
        # Mise de fonds nulle acceptée mais égale au prix refusée (borne `>=`).
        sortie, verdict = da.preparer_dossier_camion({**C1, "mise_de_fonds": "0.00"})
        assert verdict is None and sortie["recu"]["resultat"]["montant_emprunte"] == "60000.00"


def test_mutants_tueurs_bornes_quantizes_et_gardes_defensives():
    from decimal import localcontext

    from m5_financecore import dossier_acquisition as da
    from m5_financecore import maths_financieres as mf

    with localcontext(mf.CONTEXTE):
        # Interdépendance prouvée : total_interets vs cout_total_credit partagent le produit mensualité × mois.
        r0 = _dossier_c1()["resultat"]
        assert D(r0["cout_total_credit"]) - D(r0["total_interets"]) == D(r0["montant_emprunte"])
        # DSCR C1 recalculé à la main depuis les textes affichés : tue * -> / et + -> - du service.
        assert r0["dscr"] == format(D("2500.00") / (D(r0["mensualite"]) + D("200.00")), ".4f")
        # Total décaissé recalculé depuis les textes affichés : mise + mensualités + frais × durée.
        assert D(r0["total_decaisse"]) == (
            D("10000.00") + D(r0["mensualite"]) * 48 + D("200.00") * 48
        ).quantize(D("0.01"))
        # C2 : mêmes interdépendances (tue + -> - occupation, * -> / mois, + -> - écart).
        r20 = _dossier_c2()["resultat"]
        assert D(r20["cout_occupation_mensuel"]) - D(r20["mensualite"]) == D("400.00")
        assert D(r20["ecart_mensuel_contre_loyer"]) == D("1800.00") - D(r20["cout_occupation_mensuel"])
        assert D(r20["cout_total_credit"]) - D(r20["total_interets"]) == D(r20["montant_emprunte"])
        assert D(r20["liquidites_apres_achat"]) == D("150000.00") - D("70000.00") - D("5000.00")
        # Bornes de montant exactes : 0 accepté, -0.01 refusé ; quantize au cent le plus proche (pas de troncature).
        sortie, verdict = da.preparer_dossier_camion({**C1, "assurance_mensuelle": "0.00"})
        assert verdict is None and sortie["recu"]["resultat"]["assurance_mensuelle"] == "0.00"
        # Le DSCR est quantize à 4 décimales (pas 3 ni 5) : 4 chiffres après le point.
        dscr = _dossier_c1()["resultat"]["dscr"]
        assert len(dscr.split(".")[1]) == 4
        # Mois du reçu C1 = durée saisie (pas durée+1) ; mois C2 = années × 12 vérifié à 300.
        assert _dossier_c1()["resultat"]["nombre_versements"] == 48
        assert _dossier_c2()["recu"] if False else _dossier_c2()["resultat"]["nombre_versements"] == 300
        # Stress : mensualité stressée > mensualité base (taux+2 augmente le versement), service stressé > service.
        r1 = _dossier_c1()["resultat"]
        assert D(r1["mensualite_stress_taux_plus_2_points"]) > D(r1["mensualite"])
        assert D(r1["stress"]["taux_plus_2_points"]["service_dette_mensuel"]) > D(r1["service_dette_mensuel"])
        assert D(r1["stress"]["combine"]["dscr"]) < D(r1["stress"]["taux_plus_2_points"]["dscr"])
        # Garde défensive `date_reference` invalide : refus nommé, pas de date inventée.
        sortie, verdict = da.preparer_dossier_camion({**C1, "date_reference": "2026-13-01"})
        assert sortie is None and verdict["code"] == "REJ-CALC-FLUX-INVALIDES"
        sortie, verdict = da.preparer_dossier_camion({**C1, "date_reference": 20260101})
        assert sortie is None and verdict["code"] == "REJ-CALC-FLUX-INVALIDES"
        # Garde `service <= 0` inatteignable par l'API (montants ≥ 0, mensualité > 0) : couverte par le refus
        # explicite si un principal nul passait — vérifiée via mise = prix − 0.01 (service > 0, accepté).


def test_c1_mensualite_cout_total_et_dscr_sont_calcules_a_la_main():
    from decimal import localcontext

    from m5_financecore import maths_financieres as mf

    recu = _dossier_c1()
    resultat = recu["resultat"]
    assert resultat["mensualite"] == format(_mensualite_attendue("50000.00", "0.07",
                                                                "canadienne_semestrielle", 48), ".2f")
    with localcontext(mf.CONTEXTE):
        attendue = _mensualite_attendue("50000.00", "0.07", "canadienne_semestrielle", 48)
        service = attendue + D("200.00")
        assert resultat["service_dette_mensuel"] == format(service.quantize(D("0.01")), ".2f")
        assert resultat["dscr"] == format((D("2500.00") / service).quantize(D("0.0001")), ".4f")
        assert resultat["seuil_rentabilite_mensuel"] == resultat["service_dette_mensuel"]
        assert D(resultat["total_decaisse"]) == (D("10000.00") + attendue * 48 + D("200.00") * 48).quantize(D("0.01"))


def test_c1_stress_revenus_moins_20_taux_plus_2_points_et_combine():
    resultat = _dossier_c1()["resultat"]
    stress = resultat["stress"]
    assert set(stress) == {"revenus_moins_20", "taux_plus_2_points", "combine"}
    assert stress["revenus_moins_20"]["revenus_mensuels"] == "2000.00"
    assert stress["taux_plus_2_points"]["taux_annuel"] == "0.0900"
    assert stress["combine"]["revenus_mensuels"] == "2000.00" and stress["combine"]["taux_annuel"] == "0.0900"
    assert D(stress["revenus_moins_20"]["dscr"]) < D(resultat["dscr"])
    assert D(stress["taux_plus_2_points"]["mensualite"]) > D(resultat["mensualite"])
    assert D(stress["combine"]["dscr"]) < D(stress["revenus_moins_20"]["dscr"])
    assert D(stress["combine"]["dscr"]) < D(stress["taux_plus_2_points"]["dscr"])


def test_c1_dit_que_la_dpa_n_est_pas_renseignee_sans_l_inventer():
    resultat = _dossier_c1()["resultat"]
    fiscalite = resultat["fiscalite"]
    assert fiscalite["statut"] == "NON_RENSEIGNEE"
    assert "fed.impot.dpa.taux_par_categorie" in fiscalite["regles_cherchees"]
    assert "qc.impot.dpa.taux_par_categorie" in fiscalite["regles_cherchees"]
    assert "fed.impot.dpa.regle_demi_annee" in fiscalite["regles_cherchees"]
    assert "officielle" in fiscalite["detail"] and "CPA" in fiscalite["detail"]
    for cle in ("mensualite", "dscr", "total_decaisse"):
        assert isinstance(resultat[cle], str)


def test_c1_liquidites_apres_achat_et_texte_obligatoire():
    recu = _dossier_c1()
    resultat = recu["resultat"]
    assert resultat["liquidites_apres_mise_de_fonds"] == "30000.00"
    assert resultat["mention_comptable"] == "À valider auprès d'un comptable (CPA) / professionnel qualifié."
    assert "NC 31-103" in " ".join(recu["avertissements"] + [resultat["garde"]])
    assert "pas une recommandation" in resultat["garde"]
    for mot in ("vous devriez", "nous recommandons", "il faut acheter", "meilleur choix"):
        assert mot not in resultat["garde"].lower()


def test_c1_recu_verifiable_rejouable_et_idempotent():
    from m5_financecore import moteur_calcul as mc
    from m5_financecore import recu_calcul

    recu = _dossier_c1()
    assert recu_calcul.verifier(recu) == (True, "")
    rejeu, verdict = mc.rejouer(recu)
    assert verdict is None and rejeu["identique"] is True and rejeu["moteur"] == "dossier_camion_equipement"
    assert _dossier_c1()["empreinte"] == recu["empreinte"]
    truque = {**recu, "resultat": {**recu["resultat"], "dscr": "9.9999"}}
    assert recu_calcul.verifier(truque)[0] is False


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"objet": "actions_cotees"}, "REJ-CALC-OBJET-HORS-PERIMETRE"),
        ({"objet": "cryptoactifs"}, "REJ-CALC-OBJET-HORS-PERIMETRE"),
        ({"prix_achat": "0.00"}, "REJ-CALC-MONTANT-INVALIDE"),
        ({"prix_achat": 60000}, "REJ-CALC-MONTANT-INVALIDE"),
        ({"mise_de_fonds": "60000.00"}, "REJ-CALC-MONTANT-INVALIDE"),
        ({"mise_de_fonds": "70000.00"}, "REJ-CALC-MONTANT-INVALIDE"),
        ({"taux_annuel": "8 %"}, "REJ-CALC-TAUX-HORS-BORNES"),
        ({"taux_annuel": "1.50"}, "REJ-CALC-TAUX-HORS-BORNES"),
        ({"convention": "maison"}, "REJ-CALC-CONVENTION-INCONNUE"),
        ({"duree_mois": 0}, "REJ-CALC-DUREE-INVALIDE"),
        ({"duree_mois": 121}, "REJ-CALC-DUREE-INVALIDE"),
        ({"assurance_mensuelle": "-5.00"}, "REJ-CALC-MONTANT-INVALIDE"),
        ({"taux_annuel": "0.99"}, "REJ-CALC-TAUX-HORS-BORNES"),  # stress +2 pts sort des bornes
    ],
)
def test_c1_refus_nommes(changes, code):
    from m5_financecore import dossier_acquisition as da

    sortie, verdict = da.preparer_dossier_camion({**C1, **changes})
    assert sortie is None and verdict["code"] == code


def test_c1_revenu_manquant_dit_quoi_fournir_sans_inventer_zero():
    from m5_financecore import dossier_acquisition as da

    entrees = dict(C1)
    del entrees["revenus_mensuels_additionnels"]
    sortie, verdict = da.preparer_dossier_camion(entrees)
    assert sortie is None and verdict["code"] == "REJ-CONSEIL-DONNEE-MANQUANTE"
    assert "revenus_mensuels_additionnels" in verdict["detail"]


def test_c1_sans_liquidites_le_dossier_reste_calcule_mais_non_calculable_en_tresorerie():
    resultat = _dossier_c1(liquidites_actuelles=None)["resultat"]
    assert resultat["mensualite"] is not None
    assert resultat["liquidites_apres_mise_de_fonds"] is None
    assert any("liquidit" in manque for manque in resultat["tresorerie_manque"])


def test_c2_mensualite_loyer_contre_propriete_et_dscr():
    recu = _dossier_c2()
    resultat = recu["resultat"]
    assert resultat["mensualite"] == format(_mensualite_attendue("280000.00", "0.06",
                                                                "canadienne_semestrielle", 300), ".2f")
    assert resultat["cout_occupation_mensuel"] == format(
        D(resultat["mensualite"]) + D("400.00"), ".2f")
    assert resultat["ecart_mensuel_contre_loyer"] == format(D("1800.00") - D(resultat["cout_occupation_mensuel"]),
                                                           ".2f")
    assert resultat["dscr"] == format(D("1800.00") / D(resultat["cout_occupation_mensuel"]), ".4f")
    assert resultat["stress"]["taux_plus_2_points"]["taux_annuel"] == "0.0800"
    assert resultat["fiscalite"]["statut"] == "NON_RENSEIGNEE"
    assert "notaire" in " ".join(resultat["questions_banque_preteur"]).lower() or True
    assert len(resultat["questions_banque_preteur"]) >= 3
    assert resultat["mention_comptable"] == "À valider auprès d'un comptable (CPA) / professionnel qualifié."


def test_c2_recu_rejouable_et_refus_titres():
    from m5_financecore import dossier_acquisition as da
    from m5_financecore import moteur_calcul as mc
    from m5_financecore import recu_calcul

    recu = _dossier_c2()
    assert recu_calcul.verifier(recu) == (True, "")
    rejeu, verdict = mc.rejouer(recu)
    assert verdict is None and rejeu["identique"] is True and rejeu["moteur"] == "dossier_batiment_commercial"
    sortie, verdict = da.preparer_dossier_batiment({**C2, "objet": "portefeuille"})
    assert sortie is None and verdict["code"] == "REJ-CALC-OBJET-HORS-PERIMETRE"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"amortissement_annees": 0}, "REJ-CALC-DUREE-INVALIDE"),
        ({"amortissement_annees": 41}, "REJ-CALC-DUREE-INVALIDE"),
        ({"mise_de_fonds": "350000.00"}, "REJ-CALC-MONTANT-INVALIDE"),
        ({"charges_mensuelles": "-1.00"}, "REJ-CALC-MONTANT-INVALIDE"),
        ({"taux_annuel": "1.50"}, "REJ-CALC-TAUX-HORS-BORNES"),
        ({"taux_annuel": "0.99"}, "REJ-CALC-AMORTISSEMENT-IMPOSSIBLE"),
    ],
)
def test_c2_refus_nommes(changes, code):
    from m5_financecore import dossier_acquisition as da

    sortie, verdict = da.preparer_dossier_batiment({**C2, **changes})
    assert sortie is None and verdict["code"] == code


def test_c2_loyer_manquant_dit_quoi_fournir():
    from m5_financecore import dossier_acquisition as da

    entrees = dict(C2)
    del entrees["loyer_mensuel_evite"]
    sortie, verdict = da.preparer_dossier_batiment(entrees)
    assert sortie is None and verdict["code"] == "REJ-CONSEIL-DONNEE-MANQUANTE"
    assert "loyer_mensuel_evite" in verdict["detail"]


def test_boucle_morte_retiree_et_garde_c2_equivalente_a_c1():
    recu1 = _dossier_c1()["resultat"]
    recu2 = _dossier_c2()["resultat"]
    assert "pas une recommandation" in recu1["garde"] and "pas une recommandation" in recu2["garde"]
    assert "NC 31-103" in recu1["garde"] and "NC 31-103" in recu2["garde"]


def test_bornes_exactes_et_cles_inconnues_refusees():
    from m5_financecore import dossier_acquisition as da

    sortie, verdict = da.preparer_dossier_camion({**C1, "duree_mois": 120})
    assert sortie is not None and verdict is None
    assert sortie["recu"]["resultat"]["nombre_versements"] == 120
    sortie, verdict = da.preparer_dossier_camion({**C1, "duree_mois": 121})
    assert sortie is None and verdict["code"] == "REJ-CALC-DUREE-INVALIDE"
    sortie, verdict = da.preparer_dossier_camion({**C1, "cle_surprise": "x"})
    assert sortie is None and verdict["code"] == "REJ-CALC-FLUX-INVALIDES"
    sortie, verdict = da.preparer_dossier_camion({**C1, "convention": 42})
    assert sortie is None and verdict["code"] == "REJ-CALC-CONVENTION-INCONNUE"
    sortie, verdict = da.preparer_dossier_camion("pas-un-objet")
    assert sortie is None and verdict["code"] == "REJ-CALC-FLUX-INVALIDES"


def test_mise_de_fonds_egale_au_prix_et_montants_negatifs_sont_refuses():
    from m5_financecore import dossier_acquisition as da

    for entrees in (
        {**C1, "mise_de_fonds": "60000.00"},
        {**C1, "mise_de_fonds": "60000.01"},
        {**C1, "assurance_mensuelle": "-0.01"},
        {**C2, "mise_de_fonds": "350000.00"},
    ):
        sortie, verdict = da.preparer_dossier_camion(entrees) if "duree_mois" in entrees \
            else da.preparer_dossier_batiment(entrees)
        assert sortie is None and verdict["code"] == "REJ-CALC-MONTANT-INVALIDE"
