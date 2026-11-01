"""Moteur de calcul, vague 3 : remboursement anticipé d'un prêt et échelonnement de placements à terme fixe de la
trésorerie. Contre-vérifiés par une implémentation INDÉPENDANTE (Fraction, cents entiers). Données fictives."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext

import pytest
from m5_financecore import moteur_calcul as mc
from m5_financecore import recu_calcul

FICTIF = True
D = Decimal


def _cents(valeur: Decimal) -> int:
    """Arrondi half-up au cent d'un montant en dollars, en entier de cents."""
    return int((valeur * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _reference_pret(principal: str, taux_annuel: str, annees: int, extra: str = "0", forfaits=None):
    """Prêt mensuel, convention canadienne semestrielle, en cents entiers (implémentation indépendante de mf)."""
    forfaits = forfaits or {}
    with localcontext() as ctx:
        ctx.prec = 80
        i = (1 + D(taux_annuel) / 2) ** (D(1) / 6) - 1
        n = annees * 12
        versement = _cents(D(principal) * i / (1 - (1 + i) ** -n))
        solde = _cents(D(principal))
        interets = paye = nombre = 0
        for periode in range(1, n + 1):
            interet = _cents(D(solde) / 100 * i)
            paiement = versement + _cents(D(extra)) + _cents(D(forfaits.get(periode, "0")))
            if periode == n or paiement >= solde + interet:
                paiement = solde + interet
            solde -= paiement - interet
            interets, paye, nombre = interets + interet, paye + paiement, periode
            if solde == 0:
                break
    return versement, nombre, interets, paye


ENTREES = {
    "objet": "pret_entreprise",
    "montant_emprunte": "100000.00",
    "taux_annuel": "0.05",
    "frequence": "mensuelle",
    "convention": "canadienne_semestrielle",
    "amortissement_annees": 25,
    "strategies": [
        {"nom": "plus-100", "versement_additionnel": "100.00"},
        {
            "nom": "forfait-an-3",
            "remboursements_forfaitaires": [{"periode": 36, "montant": "20000.00"}],
            "frais": "300.00",
        },
    ],
}


def _sortie(entrees):
    sortie, verdict = mc.calculer_remboursement_anticipe(entrees)
    assert verdict is None, verdict
    return sortie["recu"]


def test_remboursement_anticipe_concorde_avec_une_implementation_independante():
    recu = _sortie(ENTREES)
    resultat = recu["resultat"]
    versement, nombre, interets, paye = _reference_pret("100000.00", "0.05", 25)
    assert resultat["versement_normal"] == "581.60" and Decimal(resultat["versement_normal"]) * 100 == versement
    assert (
        resultat["base"]["nombre_versements"],
        D(resultat["base"]["total_interets"]) * 100,
        D(resultat["base"]["total_paye"]) * 100,
    ) == (nombre, interets, paye)
    plus = resultat["strategies"][0]
    _, n2, i2, p2 = _reference_pret("100000.00", "0.05", 25, extra="100.00")
    assert (plus["nombre_versements"], D(plus["total_interets"]) * 100, D(plus["total_paye"]) * 100) == (n2, i2, p2)
    assert D(plus["economie_interets"]) * 100 == interets - i2 and plus["versements_economises"] == nombre - n2
    forfait = resultat["strategies"][1]
    _, n3, i3, p3 = _reference_pret("100000.00", "0.05", 25, forfaits={36: "20000.00"})
    assert (forfait["nombre_versements"], D(forfait["total_interets"]) * 100) == (n3, i3)
    assert D(forfait["total_paye"]) * 100 == p3 + 30000 and forfait["frais"] == "300.00"
    assert D(forfait["economie_nette_des_frais"]) == D(forfait["economie_interets"]) - D("300.00")


def test_remboursement_anticipe_soldes_nuls_recu_verifiable_et_rejouable():
    recu = _sortie(ENTREES)
    assert all(s["solde_final"] == "0.00" for s in recu["resultat"]["strategies"])
    assert recu_calcul.verifier(recu) == (True, "")
    rejeu, verdict = mc.rejouer(recu)
    assert verdict is None and rejeu["identique"] is True and rejeu["moteur"] == "remboursement_anticipe_pret"
    assert any("pénalités" in a for a in recu["avertissements"]) and any(
        "NC 31-103" in a for a in recu["avertissements"]
    )
    truque = {**recu, "resultat": {**recu["resultat"], "versement_normal": "1.00"}}
    assert recu_calcul.verifier(truque)[0] is False


@pytest.mark.parametrize(
    ("modif", "code"),
    [
        ({"objet": "actions"}, "REJ-CALC-OBJET-HORS-PERIMETRE"),
        ({"objet": "portefeuille_fnb"}, "REJ-CALC-OBJET-HORS-PERIMETRE"),
        ({"strategies": []}, "REJ-CALC-SCENARIO-INVALIDE"),
        ({"strategies": [{"nom": "x"}]}, "REJ-CALC-SCENARIO-INVALIDE"),  # ni extra ni forfait : c'est « base »
        ({"strategies": [{"nom": "base", "versement_additionnel": "10"}]}, "REJ-CALC-SCENARIO-INVALIDE"),
        (
            {"strategies": [{"nom": "a", "versement_additionnel": "10"}, {"nom": "a", "versement_additionnel": "20"}]},
            "REJ-CALC-SCENARIO-INVALIDE",
        ),
        ({"strategies": [{"nom": "Majuscule", "versement_additionnel": "10"}]}, "REJ-CALC-SCENARIO-INVALIDE"),
        (
            {"strategies": [{"nom": "a", "remboursements_forfaitaires": [{"periode": 301, "montant": "1.00"}]}]},
            "REJ-CALC-DUREE-INVALIDE",
        ),
        (
            {"strategies": [{"nom": "a", "remboursements_forfaitaires": [{"periode": 0, "montant": "1.00"}]}]},
            "REJ-CALC-DUREE-INVALIDE",
        ),
        ({"strategies": [{"nom": "a", "versement_additionnel": -5}]}, "REJ-CALC-MONTANT-INVALIDE"),
        ({"strategies": [{"nom": "a", "versement_additionnel": "10", "inconnu": 1}]}, "REJ-CALC-SCENARIO-INVALIDE"),
        (
            {"strategies": [{"nom": f"s{i}", "versement_additionnel": "10"} for i in range(5)]},
            "REJ-CALC-SCENARIO-INVALIDE",
        ),
        ({"taux_annuel": "1.5"}, "REJ-CALC-TAUX-HORS-BORNES"),
        ({"frequence": "quotidienne"}, "REJ-CALC-FREQUENCE-INCONNUE"),
        ({"amortissement_annees": 41}, "REJ-CALC-DUREE-INVALIDE"),
        ({"montant_emprunte": 100000}, "REJ-CALC-MONTANT-INVALIDE"),
    ],
)
def test_remboursement_anticipe_refus_nommes(modif, code):
    sortie, verdict = mc.calculer_remboursement_anticipe({**ENTREES, **modif})
    assert sortie is None and verdict["code"] == code


ECHELONS = {
    "montant_total": "30000.00",
    "echelons": [
        {"nom": "six-mois", "montant": "10000.00", "terme_mois": 6, "taux_annuel": "0.04", "interets": "simple"},
        {
            "nom": "dix-huit-mois",
            "montant": "10000.00",
            "terme_mois": 18,
            "taux_annuel": "0.05",
            "interets": "compose_annuellement",
        },
        {
            "nom": "deux-ans",
            "montant": "10000.00",
            "terme_mois": 24,
            "taux_annuel": "0.06",
            "interets": "compose_annuellement",
        },
    ],
    "besoins": [
        {"mois": 6, "montant": "9000.00"},
        {"mois": 18, "montant": "11000.00"},
        {"mois": 24, "montant": "10000.00"},
    ],
}


def test_echelonnement_calcule_a_la_main_les_valeurs_a_l_echeance():
    sortie, verdict = mc.calculer_echelonnement_termes(ECHELONS)
    assert verdict is None
    r = sortie["recu"]["resultat"]
    valeurs = {e["nom"]: e["valeur_a_l_echeance"] for e in r["echelons"]}
    assert valeurs == {"six-mois": "10200.00", "dix-huit-mois": "10762.50", "deux-ans": "11236.00"}
    assert r["interets_totaux"] == "2198.50" and r["valeur_totale_aux_echeances"] == "32198.50"
    assert r["taux_moyen_pondere"] == "0.050000000000" and r["terme_moyen_pondere_mois"] == "16.00"
    c = r["couverture_des_besoins"]
    assert [(x["mois"], x["valeur_echue_cumulee"], x["ecart"], x["couvert"]) for x in c] == [
        (6, "10200.00", "1200.00", True),
        (18, "20962.50", "962.50", True),
        (24, "32198.50", "2198.50", True),
    ]


def test_echelonnement_signale_un_besoin_non_couvert():
    donnees = {**ECHELONS, "besoins": [{"mois": 3, "montant": "100.00"}]}
    sortie, _ = mc.calculer_echelonnement_termes(donnees)
    assert sortie["recu"]["resultat"]["couverture_des_besoins"][0]["couvert"] is False


def test_echelonnement_recu_rejouable_sans_taux_invente_et_avec_avertissements():
    sortie, _ = mc.calculer_echelonnement_termes(ECHELONS)
    recu = sortie["recu"]
    assert recu_calcul.verifier(recu) == (True, "")
    assert mc.rejouer(recu)[0]["identique"] is True
    texte = " ".join(recu["avertissements"])
    assert "n'en fournit aucun" in texte and "NC 31-103" in texte and "rachat" in texte


@pytest.mark.parametrize(
    ("modif", "code"),
    [
        ({"montant_total": "29999.99"}, "REJ-CALC-FLUX-INVALIDES"),
        ({"echelons": []}, "REJ-CALC-SCENARIO-INVALIDE"),
        (
            {"echelons": [{**ECHELONS["echelons"][0], "interets": "maison"}, *ECHELONS["echelons"][1:]]},
            "REJ-CALC-CONVENTION-INCONNUE",
        ),
        (
            {"echelons": [{**ECHELONS["echelons"][0], "terme_mois": 121}, *ECHELONS["echelons"][1:]]},
            "REJ-CALC-DUREE-INVALIDE",
        ),
        (
            {"echelons": [{**ECHELONS["echelons"][0], "taux_annuel": "4 %"}, *ECHELONS["echelons"][1:]]},
            "REJ-CALC-TAUX-HORS-BORNES",
        ),
        (
            {"echelons": [{**ECHELONS["echelons"][0], "nom": "A B"}, *ECHELONS["echelons"][1:]]},
            "REJ-CALC-SCENARIO-INVALIDE",
        ),
        ({"echelons": [ECHELONS["echelons"][0]] * 2, "montant_total": "20000.00"}, "REJ-CALC-SCENARIO-INVALIDE"),
        ({"besoins": [{"mois": 0, "montant": "1.00"}]}, "REJ-CALC-DUREE-INVALIDE"),
        ({"besoins": [{"mois": 5, "montant": "1.00"}] * 13}, "REJ-CALC-BORNE-DEPASSEE"),
        ({"produit": "FNB"}, "REJ-CALC-FLUX-INVALIDES"),
    ],
)
def test_echelonnement_refus_nommes(modif, code):
    sortie, verdict = mc.calculer_echelonnement_termes({**ECHELONS, **modif})
    assert sortie is None and verdict["code"] == code
