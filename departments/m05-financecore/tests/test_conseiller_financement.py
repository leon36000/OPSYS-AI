"""Conseiller en financement (M5.13) : comptant, prêt, location et sensibilité par le moteur déterministe, avec reçu.
Contre-vérifié à la main (valeur actuelle du comptant, versement du prêt). Données fictives, aucune recommandation."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext

import pytest
from m5_financecore import conseiller_financement as cf
from m5_financecore import moteur_calcul as mc
from m5_financecore import recu_calcul

FICTIF = True
D = Decimal

ENTREES = {
    "objet": "vehicule",
    "prix_achat": "60000.00",
    "frais_achat": "500.00",
    "horizon_mois": 48,
    "valeur_residuelle": "30000.00",
    "taux_actualisation_annuel": "0.08",
    "pret": {
        "mise_de_fonds": "10000.00",
        "taux_annuel": "0.07",
        "convention": "canadienne_semestrielle",
        "amortissement_annees": 5,
        "frais_dossier": "300.00",
    },
    "location": {
        "depot_initial": "1000.00",
        "paiement_mensuel": "1100.00",
        "paiements_en_debut_de_periode": True,
        "option_achat_finale": "28000.00",
    },
    "variations": [
        {"nom": "taux-pret-plus-2", "modifications": {"pret.taux_annuel": "0.09"}},
        {"nom": "actualisation-12", "modifications": {"taux_actualisation_annuel": "0.12"}},
    ],
}


def calculer(**changes):
    sortie, verdict = cf.comparer_financement({**ENTREES, **changes})
    assert verdict is None, verdict
    return sortie["recu"]


def par_nom(recu):
    return {s["scenario"]: s for s in recu["resultat"]["scenarios"]}


def test_le_cout_du_comptant_est_la_valeur_actuelle_calculee_a_la_main():
    recu = calculer()
    with localcontext() as ctx:
        ctx.prec = 60
        attendu = D("60500") - D("30000") / (D("1.08") ** 4)
    assert par_nom(recu)["comptant"]["cout_actualise"] == format(
        attendu.quantize(D("0.01"), rounding=ROUND_HALF_UP), "f"
    )


def test_pret_versement_total_et_taux_effectif_avec_frais_de_dossier():
    s = par_nom(calculer())["pret"]
    assert s["mensualite"] == "987.70"  # 50 000 $ à 7 % semestriel sur 5 ans, versements mensuels
    assert s["sorties_initiales"] == "10800.00" and s["versements_dans_l_horizon"] == 48
    assert s["statut_tri"] == "UNIQUE"
    # le taux effectif dépasse le taux nominal à cause des frais de dossier
    assert D(s["taux_effectif_annuel_pourcentage"]) > D("7.0")
    total = D(s["total_decaisse"])
    assert total == D("10800.00") + D("987.70") * 48 + D(s["solde_rembourse_a_l_horizon"])


def test_ordre_par_cout_actualise_est_un_fait_de_calcul_pas_une_recommandation():
    recu = calculer()
    r = recu["resultat"]
    couts = [D(s["cout_actualise"]) for s in r["scenarios"]]
    assert couts == sorted(couts) and r["cout_actualise_le_plus_bas"] == r["ordre_par_cout_actualise"][0]
    texte = " ".join(r["lectures"]) + " ".join(recu["avertissements"])
    assert "pas une recommandation" in texte and "NC 31-103" in texte
    for mot in ("vous devriez", "nous recommandons", "il faut acheter", "meilleur choix"):
        assert mot not in texte.lower()


def test_sensibilite_ne_s_execute_que_sur_les_variations_demandees():
    r = calculer()["resultat"]
    assert [v["variation"] for v in r["sensibilite"]] == ["taux-pret-plus-2", "actualisation-12"]
    assert (
        r["sensibilite"][0]["ordre_change"] is True and r["sensibilite"][0]["cout_actualise_le_plus_bas"] == "comptant"
    )
    assert any("dépend des hypothèses" in ligne for ligne in r["lectures"])
    sans = calculer(variations=[])["resultat"]
    assert sans["sensibilite"] == []


def test_recu_verifiable_rejouable_et_retouche_detectee():
    recu = calculer()
    assert recu_calcul.verifier(recu) == (True, "")
    rejeu, verdict = mc.rejouer(recu)
    assert verdict is None and rejeu["identique"] is True and rejeu["moteur"] == "comparaison_financement"
    truque = {**recu, "resultat": {**recu["resultat"], "cout_actualise_le_plus_bas": "location"}}
    assert recu_calcul.verifier(truque)[0] is False
    assert recu["resultat"]["recus_composes"]["nombre"] >= 9


@pytest.mark.parametrize(
    ("modif", "code"),
    [
        ({"objet": "actions_cotees"}, "REJ-CALC-OBJET-HORS-PERIMETRE"),
        ({"objet": "fnb"}, "REJ-CALC-OBJET-HORS-PERIMETRE"),
        ({"objet": "cryptoactifs"}, "REJ-CALC-OBJET-HORS-PERIMETRE"),
        ({"pret": None, "location": None}, "REJ-CALC-SCENARIO-INVALIDE"),
        ({"horizon_mois": 0}, "REJ-CALC-DUREE-INVALIDE"),
        ({"horizon_mois": 121}, "REJ-CALC-DUREE-INVALIDE"),
        ({"prix_achat": 60000}, "REJ-CALC-MONTANT-INVALIDE"),
        ({"prix_achat": "0.00"}, "REJ-CALC-MONTANT-INVALIDE"),
        ({"taux_actualisation_annuel": "8 %"}, "REJ-CALC-TAUX-HORS-BORNES"),
        ({"pret": {**ENTREES["pret"], "mise_de_fonds": "60000.00"}}, "REJ-CALC-MONTANT-INVALIDE"),
        ({"pret": {**ENTREES["pret"], "convention": "maison"}}, "REJ-CALC-CONVENTION-INCONNUE"),
        ({"pret": {**ENTREES["pret"], "inconnu": 1}}, "REJ-CALC-FLUX-INVALIDES"),
        ({"location": {**ENTREES["location"], "paiements_en_debut_de_periode": "oui"}}, "REJ-CALC-FLUX-INVALIDES"),
        ({"variations": [{"nom": "x", "modifications": {"loyer": "1"}}]}, "REJ-CALC-HYPOTHESE-INVALIDE"),
        ({"variations": [{"nom": "x", "modifications": {}}]}, "REJ-CALC-HYPOTHESE-INVALIDE"),
        ({"variations": [{"nom": "x", "modifications": {"prix_achat": "-1"}}]}, "REJ-CALC-MONTANT-INVALIDE"),
        (
            {"variations": [{"nom": f"v{i}", "modifications": {"prix_achat": "50000"}} for i in range(7)]},
            "REJ-CALC-BORNE-DEPASSEE",
        ),
        ({"variations": [{"nom": "x", "modifications": {"prix_achat": "50000"}}] * 2}, "REJ-CALC-SCENARIO-INVALIDE"),
        ({"variations": [{"nom": "x", "modifications": {"pret.mise_de_fonds": "70000"}}]}, "REJ-CALC-MONTANT-INVALIDE"),
    ],
)
def test_refus_nommes(modif, code):
    sortie, verdict = cf.comparer_financement({**ENTREES, **modif})
    assert sortie is None and verdict["code"] == code


def test_variation_sur_un_scenario_absent_est_refusee():
    sans_pret = {**ENTREES, "pret": None}
    sortie, verdict = cf.comparer_financement(
        {**sans_pret, "variations": [{"nom": "x", "modifications": {"pret.taux_annuel": "0.09"}}]}
    )
    assert sortie is None and verdict["code"] == "REJ-CALC-HYPOTHESE-INVALIDE"


def test_pret_echu_avant_l_horizon_ne_laisse_aucun_solde():
    s = par_nom(calculer(horizon_mois=72, valeur_residuelle="20000.00"))["pret"]
    assert s["solde_rembourse_a_l_horizon"] == "0.00" and s["versements_dans_l_horizon"] == 60


def test_location_sans_option_rend_l_actif_et_ne_compte_pas_la_valeur_residuelle():
    sans = par_nom(calculer(location={**ENTREES["location"], "option_achat_finale": None}))["location"]
    avec = par_nom(calculer())["location"]
    assert sans["option_exercee"] is False and D(sans["cout_actualise"]) > D("0")
    assert sans["total_decaisse"] == "53800.00" and avec["total_decaisse"] == "81800.00"


def test_entrees_non_objet_refusees():
    for entrees in (None, [], "texte"):
        sortie, verdict = cf.comparer_financement(entrees)
        assert sortie is None and verdict["code"] == "REJ-CALC-FLUX-INVALIDES"
