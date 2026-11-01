"""Moteur de calcul M5, tranche 1 (`docs/moteur-calcul.md`) : valeurs de référence, propriétés, refus et reçus.

Les valeurs de référence sont recalculées INDÉPENDAMMENT du code testé : en `fractions.Fraction` (arithmétique
exacte), par bissection rationnelle quand la réponse est irrationnelle (TRI, taux canadien composé semestriellement),
ou ce sont des cas publiés connus (versement hypothécaire canadien de 581,60 $ ; prêt de 250 000 $ à 6 % sur 30 ans :
1 498,88 $). Les propriétés tournent sur des cas générés à graine (`random.Random`, graines fixes : aucun test n'est
aléatoire d'une exécution à l'autre). Données fictives.
"""

from __future__ import annotations

import json
import random
import statistics
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

import pytest
from m5_financecore import maths_financieres as mf
from m5_financecore import monte_carlo_tresorerie as mc
from m5_financecore import moteur_calcul, recu_calcul, verdicts_calcul
from m5_financecore.analyse import MENTION_COMPTABLE

FICTIF = True
D = Decimal


# ------------------------------------------------------------------------------------- références indépendantes
def _van_fraction(taux: Fraction, flux: list[Fraction]) -> Fraction:
    return sum((c / (1 + taux) ** t for t, c in enumerate(flux)), Fraction(0))


def _tri_fraction(flux: list[Fraction], bas=Fraction(-9999, 10000), haut=Fraction(100), iterations=140) -> Fraction:
    """Bissection rationnelle exacte (aucun Decimal, aucun Newton) : une référence indépendante du moteur."""
    v_bas = _van_fraction(bas, flux)
    assert v_bas * _van_fraction(haut, flux) < 0
    for _ in range(iterations):
        milieu = (bas + haut) / 2
        v = _van_fraction(milieu, flux)
        if (v > 0) == (v_bas > 0):
            bas, v_bas = milieu, v
        else:
            haut = milieu
    return (bas + haut) / 2


def _au_cent_fraction(x: Fraction) -> Decimal:
    return (D(x.numerator) / D(x.denominator)).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def _versement_fraction(principal: Fraction, i: Fraction, n: int) -> Fraction:
    return principal * i / (1 - (1 + i) ** -n)


def _taux_canadien_bornes(j: Fraction, m: int) -> tuple[Fraction, Fraction]:
    """i tel que (1 + i)^(m/2) = 1 + j/2 (m pair), encadré par bissection rationnelle à 2^-120 près."""
    cible, puissance = 1 + j / 2, m // 2
    bas, haut = Fraction(0), j
    for _ in range(120):
        milieu = (bas + haut) / 2
        if (1 + milieu) ** puissance < cible:
            bas = milieu
        else:
            haut = milieu
    return bas, haut


def _ok(couple):
    sortie, verdict = couple
    assert verdict is None, verdict
    return sortie["recu"] if "tableau" not in sortie else sortie


def _code(couple):
    sortie, verdict = couple
    assert sortie is None, sortie
    return verdict["code"]


# ------------------------------------------------------------------------------------------ VAN, VA, VF, TRI
def test_van_va_vf_valent_la_formule_exacte_au_cent():
    flux = [D("-50000.00"), D("12000.00"), D("15000.00"), D("18000.00"), D("21000.00")]
    reference = _van_fraction(Fraction(8, 100), [Fraction(c) for c in flux])
    assert mf.au_cent(mf.van(D("0.08"), flux)) == _au_cent_fraction(reference)
    assert mf.au_cent(mf.valeur_actuelle(D("1000"), D("0.05"), 3)) == _au_cent_fraction(Fraction(1000) / Fraction(
        105, 100) ** 3) == D("863.84")
    assert mf.au_cent(mf.valeur_future(D("1000"), D("0.05"), 3)) == D("1157.63")


@pytest.mark.parametrize(("flux", "attendu"), [
    (["-100", "110"], D("0.1")),
    (["-100", "0", "121"], D("0.1")),
    (["-1000", "1331"], None),  # (1+r)^1 = 1.331 : 33,1 %
    (["-1000", "0", "0", "1331"], D("0.1")),
    (["100", "-100"], D("0")),
])
def test_tri_des_flux_a_solution_exacte(flux, attendu):
    resultat = mf.tri([D(x) for x in flux])
    assert resultat["statut"] == "UNIQUE"
    exact = attendu if attendu is not None else D("0.331")
    assert abs(resultat["tri"] - exact) <= D("1e-29")
    assert str(resultat["tri"]) != "-0E-30"


def test_tri_d_une_rente_et_de_flux_irreguliers_contre_la_bissection_rationnelle():
    for flux in (["-1000"] + ["100"] * 20, ["-100", "50", "60"], ["-250000", "30000", "45000", "0", "90000", "180000"]):
        decimaux = [D(x) for x in flux]
        resultat = mf.tri(decimaux)
        reference = _tri_fraction([Fraction(x) for x in flux])
        assert resultat["statut"] == "UNIQUE"
        assert abs(Fraction(resultat["tri"]) - reference) < Fraction(1, 10**28), flux
    assert format(mf.tri([D("-1000")] + [D("100")] * 20)["tri"] * 100, ".4f") == "7.7547"


def test_identite_van_du_tri_nulle_sur_des_flux_generes_a_graine():
    """Propriété : pour 300 suites conventionnelles générées (un seul changement de signe), le TRI est UNIQUE et
    |VAN(TRI)| ≤ tolérance déclarée ; sur 40 d'entre elles, il égale la bissection rationnelle à 1e-26 près."""
    generateur = random.Random(20261031)
    for numero in range(300):
        n = generateur.randint(1, 40)
        investissement = D(generateur.randint(1, 10**8)) / 100
        flux = [-investissement] + [D(generateur.randint(0, 10**7)) / 100 for _ in range(n)]
        if all(c == 0 for c in flux[1:]):
            flux[-1] = D("1.00")
        resultat = mf.tri(flux)
        if resultat["statut"] == "HORS_BORNES":
            continue
        assert resultat["statut"] == "UNIQUE", (numero, flux)
        echelle = max(D(1), sum(abs(c) for c in flux))
        assert abs(mf.van(resultat["tri"], flux)) <= mf.TOLERANCE_VAN_RELATIVE * echelle
        if numero < 40:
            reference = _tri_fraction([Fraction(c) for c in flux])
            assert abs(Fraction(resultat["tri"]) - reference) < Fraction(1, 10**26), numero


def test_tri_multiple_indefini_ou_non_garanti_n_invente_jamais_un_nombre():
    multiple = mf.tri([D("-100"), D("230"), D("-132")])  # (1+r)² − 2,3(1+r) + 1,32 = 0 : 10 % et 20 %
    assert multiple["statut"] == "MULTIPLE" and multiple["tri"] is None
    assert [Fraction(r) for r in multiple["racines"]] == [Fraction(1, 10), Fraction(2, 10)]
    assert _van_fraction(Fraction(1, 10), [Fraction(-100), Fraction(230), Fraction(-132)]) == 0
    assert mf.tri([D("-100"), D("100"), D("-100")])["statut"] == "INDEFINI"
    assert mf.tri([D("-100"), D("150"), D("-10"), D("20")])["statut"] == "NON_GARANTI"
    assert mf.tri([D("-100"), D("150"), D("-10"), D("20")])["tri"] is None
    assert mf.tri([D("-100"), D("-50")])["statut"] == "AUCUN_CHANGEMENT_DE_SIGNE"
    assert mf.tri([D("-1"), D("1000000")])["statut"] == "HORS_BORNES"


def test_tri_modifie_et_delais_de_recuperation():
    assert mf.tri_modifie([D("-100"), D("121")], D("0.05"), D("0.09")) == D("0.21")
    trim = mf.tri_modifie([D("-1000"), D("500"), D("600")], D("0.1"), D("0.1"))
    assert abs((1 + Fraction(trim)) ** 2 - Fraction(115, 100)) < Fraction(1, 10**40)
    assert mf.tri_modifie([D("100"), D("50")], D("0.1"), D("0.1")) is None
    assert mf.delai_recuperation([D("-1000"), D("400"), D("400"), D("400")])["periodes"] == D("2.5000")
    assert mf.delai_recuperation([D("-1000"), D("400"), D("400"), D("400")], D("0.1"))["statut"] == "NON_RECUPERE"
    actualise = mf.delai_recuperation([D("-1000"), D("450"), D("450"), D("450")], D("0.1"))
    cumul_2 = Fraction(-1000) + Fraction(450) / Fraction(11, 10) + Fraction(450) / Fraction(11, 10) ** 2
    attendu = 2 + (-cumul_2) / (Fraction(450) / Fraction(11, 10) ** 3)
    assert abs(Fraction(actualise["periodes"]) - attendu) <= Fraction(1, 2 * 10**4)  # rendu à 1e-4 près
    assert mf.delai_recuperation([D("-1000"), D("100")])["statut"] == "NON_RECUPERE"
    assert mf.delai_recuperation([D("100"), D("100")])["statut"] == "SANS_INVESTISSEMENT"
    retour = mf.delai_recuperation([D("-100"), D("150"), D("-200"), D("10")])
    assert retour["statut"] == "RECUPERE" and retour["redevient_negatif"] is True


# ------------------------------------------------------------------------------------------- amortissement
def test_versement_hypothecaire_canadien_compose_semestriellement_reference_publiee_et_fraction():
    """100 000 $, 5 % composé semestriellement, 25 ans, mensuel : 581,60 $ (cas publié) ; et la formule fermée en
    Fraction, i encadré par bissection rationnelle, donne le même cent aux deux bornes."""
    for principal, j, annees, frequence in ((100000, "0.05", 25, "mensuelle"), (350000, "0.0479", 25, "mensuelle"),
                                            (250000, "0.065", 30, "aux_deux_semaines"),
                                            (80000, "0.0325", 15, "hebdomadaire")):
        m = mf.FREQUENCES[frequence]
        bas, haut = _taux_canadien_bornes(Fraction(j), m)
        attendu_bas = _au_cent_fraction(_versement_fraction(Fraction(principal), bas, annees * m))
        attendu_haut = _au_cent_fraction(_versement_fraction(Fraction(principal), haut, annees * m))
        assert attendu_bas == attendu_haut
        i = mf.taux_periodique(D(j), frequence, "canadienne_semestrielle")
        assert bas <= Fraction(i) <= haut + Fraction(1, 10**45)
        assert mf.versement_constant(D(principal), i, annees * m) == attendu_bas
    i = mf.taux_periodique(D("0.05"), "mensuelle", "canadienne_semestrielle")
    assert mf.versement_constant(D(100000), i, 300) == D("581.60")


def test_versement_nominal_mensuel_reference_publiee_et_fraction_exacte():
    i = mf.taux_periodique(D("0.06"), "mensuelle", "nominal_compose_a_la_frequence")
    assert i == D("0.005")
    assert mf.versement_constant(D(250000), i, 360) == D("1498.88")
    assert _au_cent_fraction(_versement_fraction(Fraction(250000), Fraction(5, 1000), 360)) == D("1498.88")
    effectif = mf.taux_periodique(D("0.12682503013196972066120"), "mensuelle", "effectif_annuel")
    assert abs(effectif - D("0.01")) < D("1e-20")


def _verifier_tableau(principal: Decimal, i: Decimal, n: int) -> dict:
    tableau = mf.amortir(principal, i, n)
    lignes = tableau["lignes"]
    assert sum(ligne["capital"] for ligne in lignes) == principal
    solde = principal
    for ligne in lignes:
        assert ligne["interet"] == mf.au_cent(solde * i)
        assert ligne["versement"] == ligne["interet"] + ligne["capital"]
        solde -= ligne["capital"]
        assert ligne["solde"] == solde and solde >= 0
        assert ligne["capital"] > 0
    assert solde == 0
    assert all(ligne["versement"] == tableau["versement"] for ligne in lignes[:-1])
    assert tableau["total_interets"] == tableau["total_versements"] - principal
    return tableau


def test_tableaux_d_amortissement_generes_a_graine_soldent_au_cent():
    """Propriété : 150 prêts générés (3 fréquences, 3 conventions, taux 0 compris), Σ capital = principal au cent,
    chaque ligne cohérente, seule la dernière échéance diffère du versement constant."""
    generateur = random.Random(5150)
    for _ in range(150):
        frequence = generateur.choice(sorted(mf.FREQUENCES))
        convention = generateur.choice(sorted(mf.CONVENTIONS_TAUX))
        taux = D(generateur.choice([0, generateur.randint(1, 1500)])) / 10000
        principal = D(generateur.randint(10000, 10**8)) / 100
        n = generateur.randint(1, 10) * mf.FREQUENCES[frequence]
        i = mf.taux_periodique(taux, frequence, convention)
        tableau = _verifier_tableau(principal, i, n)
        assert abs(tableau["ajustement_dernier_versement"]) <= D("0.01") * n + D("0.01") or (
            tableau["nombre_versements"] < n)


def test_taux_nul_et_derniere_echeance_ajustee():
    tableau = _verifier_tableau(D("1000.00"), D(0), 3)
    assert [ligne["versement"] for ligne in tableau["lignes"]] == [D("333.33"), D("333.33"), D("333.34")]
    assert tableau["ajustement_dernier_versement"] == D("0.01")


# ---------------------------------------------------------------------------------- crédit-bail, point mort
def test_credit_bail_contre_achat_a_taux_nul_et_relation_debut_fin_de_periode():
    base = {"objet": "vehicule", "taux_actualisation_annuel": "0", "mois": 36, "prix_achat": "45000",
            "frais_achat": "500", "valeur_residuelle": "15000", "paiement_mensuel": "900", "depot_initial": "2000",
            "paiements_en_debut_de_periode": True, "option_achat_finale": "12000"}
    recu = _ok(moteur_calcul.comparer_credit_bail_achat(base))
    assert recu["resultat"]["va_cout_achat"] == "30500.00"  # 45 000 + 500 − 15 000
    assert recu["resultat"]["va_cout_credit_bail"] == "31400.00"  # 2 000 + 36 × 900 + (12 000 − 15 000)
    assert recu["resultat"]["option_au_cout_actualise_le_plus_bas"] == "achat"
    assert recu["resultat"]["ecart_credit_bail_moins_achat"] == "900.00"
    debut = _ok(moteur_calcul.comparer_credit_bail_achat({**base, "taux_actualisation_annuel": "0.08"}))
    fin = _ok(moteur_calcul.comparer_credit_bail_achat({**base, "taux_actualisation_annuel": "0.08",
                                                       "paiements_en_debut_de_periode": False}))
    i = D(debut["resultat"]["taux_mensuel"])
    assert abs(D(debut["resultat"]["va_paiements_credit_bail"])
               - D(fin["resultat"]["va_paiements_credit_bail"]) * (1 + i)) <= D("0.02")
    assert D(debut["resultat"]["va_paiements_credit_bail"]) > D(fin["resultat"]["va_paiements_credit_bail"])


def test_point_mort_exact():
    recu = _ok(moteur_calcul.calculer_point_mort({"frais_fixes": "120000", "prix_unitaire": "4500",
                                                  "cout_variable_unitaire": "2900", "quantite_prevue": "100"}))
    assert recu["resultat"]["quantite_exacte"] == "75.0000" and recu["resultat"]["quantite_entiere"] == "75"
    assert recu["resultat"]["chiffre_affaires_point_mort"] == "337500.00"
    assert recu["resultat"]["marge_de_securite_pourcentage"] == "25.0000"
    fractionnaire = _ok(moteur_calcul.calculer_point_mort({"frais_fixes": "1000", "prix_unitaire": "7",
                                                          "cout_variable_unitaire": "4"}))
    assert fractionnaire["resultat"]["quantite_entiere"] == "334"  # 1000/3 = 333,33...


def test_van_au_cent_arrondit_le_demi_cent_vers_le_haut():
    recu = _ok(moteur_calcul.calculer_rentabilite({"objet": "equipement", "flux": ["-1.00", "2.01"],
                                                   "taux_actualisation": "1"}))
    assert recu["resultat"]["van"] == "0.01"  # −1 + 2,01/2 = 0,005 → 0,01 (ROUND_HALF_UP déclaré)


# ---------------------------------------------------------------------------------------------- sensibilité
def _sensibilite(**remplacements):
    entrees = {
        "objet": "equipement",
        "base": {"investissement_initial": "50000", "flux_annuel": "12000", "croissance_annuelle": "0",
                 "duree_annees": 6, "taux_actualisation": "0.08", "valeur_residuelle": "5000"},
        "variations": {"flux_annuel": {"bas": "9000", "haut": "15000"},
                       "taux_actualisation": {"bas": "0.05", "haut": "0.12"},
                       "duree_annees": {"bas": 4, "haut": 8}},
        "scenarios": [{"nom": "pessimiste", "hypotheses": {"flux_annuel": "8000", "valeur_residuelle": "0"}}],
    }
    entrees.update(remplacements)
    return moteur_calcul.analyser_sensibilite(entrees)


def test_tornade_triee_et_chaque_barre_egale_la_van_recalculee_en_fraction():
    recu = _ok(_sensibilite())
    tornade = recu["resultat"]["tornade"]
    amplitudes = [D(b["amplitude"]) for b in tornade]
    assert amplitudes == sorted(amplitudes, reverse=True)
    for barre in tornade:
        for cote in ("basse", "haute"):
            h = {"investissement_initial": 50000, "flux_annuel": 12000, "duree_annees": 6,
                 "taux_actualisation": Fraction(8, 100), "valeur_residuelle": 5000}
            valeur = barre[f"valeur_{cote}"]
            h[barre["hypothese"]] = valeur if isinstance(valeur, int) else Fraction(valeur)
            flux = [Fraction(-h["investissement_initial"])] + [Fraction(h["flux_annuel"])] * h["duree_annees"]
            flux[-1] += h["valeur_residuelle"]
            assert D(barre[f"van_{cote}"]) == _au_cent_fraction(_van_fraction(h["taux_actualisation"], flux))
        assert D(barre["amplitude"]) == abs(D(barre["van_haute"]) - D(barre["van_basse"]))
    assert recu["resultat"]["scenarios"][0]["nom"] == "pessimiste"


# ------------------------------------------------------------------------------------------- refus typés
@pytest.mark.parametrize(("entrees", "code"), [
    ({"flux": [], "taux_actualisation": "0.1"}, "REJ-CALC-FLUX-VIDES"),
    ({"flux": ["-100"], "taux_actualisation": "0.1"}, "REJ-CALC-FLUX-VIDES"),
    ({"flux": ["0", "0"], "taux_actualisation": "0.1"}, "REJ-CALC-FLUX-INVALIDES"),
    ({"flux": ["-100"] * 601, "taux_actualisation": "0.1"}, "REJ-CALC-BORNE-DEPASSEE"),
    ({"flux": ["-100", "10.005"], "taux_actualisation": "0.1"}, "REJ-CALC-MONTANT-INVALIDE"),
    ({"flux": ["-100", 110], "taux_actualisation": "0.1"}, "REJ-CALC-MONTANT-INVALIDE"),
    ({"flux": ["-100", "1e3"], "taux_actualisation": "0.1"}, "REJ-CALC-MONTANT-INVALIDE"),
    ({"flux": ["-100", "110"], "taux_actualisation": "-0.01"}, "REJ-CALC-TAUX-HORS-BORNES"),
    ({"flux": ["-100", "110"], "taux_actualisation": "1.5"}, "REJ-CALC-TAUX-HORS-BORNES"),
    ({"flux": ["-100", "110"], "taux_actualisation": 0.1}, "REJ-CALC-TAUX-HORS-BORNES"),
    ({"flux": ["-100", "110"], "taux_actualisation": "NaN"}, "REJ-CALC-TAUX-HORS-BORNES"),
    ({"flux": ["-100", "110"], "taux_actualisation": "0.1", "taux_financement": "0.05"},
     "REJ-CALC-TAUX-HORS-BORNES"),
    ({"objet": "actions", "flux": ["-100", "110"], "taux_actualisation": "0.1"}, "REJ-CALC-OBJET-HORS-PERIMETRE"),
    ({"objet": "crypto", "flux": ["-100", "110"], "taux_actualisation": "0.1"}, "REJ-CALC-OBJET-HORS-PERIMETRE"),
    ({"objet": ["equipement"], "flux": ["-100", "110"], "taux_actualisation": "0.1"},
     "REJ-CALC-OBJET-HORS-PERIMETRE"),
])
def test_refus_typés_de_la_rentabilite(entrees, code):
    assert _code(moteur_calcul.calculer_rentabilite({"objet": "equipement", **entrees})) == code


_PRET = {"objet": "pret_entreprise", "montant_emprunte": "100000", "taux_annuel": "0.05", "frequence": "mensuelle",
         "convention": "canadienne_semestrielle", "amortissement_annees": 25}


@pytest.mark.parametrize(("remplacement", "code"), [
    ({"frequence": "trimestrielle"}, "REJ-CALC-FREQUENCE-INCONNUE"),
    ({"frequence": "Mensuelle"}, "REJ-CALC-FREQUENCE-INCONNUE"),
    ({"frequence": ["mensuelle"]}, "REJ-CALC-FREQUENCE-INCONNUE"),
    ({"convention": {"nom": "canadienne_semestrielle"}}, "REJ-CALC-CONVENTION-INCONNUE"),
    ({"convention": "americaine"}, "REJ-CALC-CONVENTION-INCONNUE"),
    ({"taux_annuel": "1.01"}, "REJ-CALC-TAUX-HORS-BORNES"),
    ({"montant_emprunte": "0"}, "REJ-CALC-MONTANT-INVALIDE"),
    ({"montant_emprunte": "-5000"}, "REJ-CALC-MONTANT-INVALIDE"),
    ({"amortissement_annees": 0}, "REJ-CALC-DUREE-INVALIDE"),
    ({"amortissement_annees": 41}, "REJ-CALC-DUREE-INVALIDE"),
    ({"amortissement_annees": True}, "REJ-CALC-DUREE-INVALIDE"),
    ({"objet": "portefeuille"}, "REJ-CALC-OBJET-HORS-PERIMETRE"),
    ({"montant_emprunte": "0.01", "taux_annuel": "1", "amortissement_annees": 40, "frequence": "hebdomadaire",
      "convention": "nominal_compose_a_la_frequence"}, "REJ-CALC-AMORTISSEMENT-IMPOSSIBLE"),
])
def test_refus_typés_de_l_amortissement(remplacement, code):
    assert _code(moteur_calcul.calculer_amortissement({**_PRET, **remplacement})) == code


def test_refus_typés_point_mort_credit_bail_et_sensibilite():
    assert _code(moteur_calcul.calculer_point_mort({"frais_fixes": "1000", "prix_unitaire": "10",
                                                    "cout_variable_unitaire": "10"})) == "REJ-CALC-MARGE-NON-POSITIVE"
    assert _code(moteur_calcul.comparer_credit_bail_achat({
        "objet": "vehicule", "taux_actualisation_annuel": "0.05", "mois": 121, "prix_achat": "1", "frais_achat": "0",
        "valeur_residuelle": "0", "paiement_mensuel": "1", "depot_initial": "0",
        "paiements_en_debut_de_periode": True})) == "REJ-CALC-DUREE-INVALIDE"
    assert _code(moteur_calcul.comparer_credit_bail_achat({
        "objet": "vehicule", "taux_actualisation_annuel": "0.05", "mois": 12, "prix_achat": "1", "frais_achat": "0",
        "valeur_residuelle": "0", "paiement_mensuel": "1", "depot_initial": "0",
        "paiements_en_debut_de_periode": "oui"})) == "REJ-CALC-FLUX-INVALIDES"
    assert _code(_sensibilite(variations={"inflation": {"bas": "0", "haut": "1"}})) == "REJ-CALC-HYPOTHESE-INVALIDE"
    assert _code(_sensibilite(variations={"flux_annuel": {"bas": "13000", "haut": "15000"}})) == (
        "REJ-CALC-HYPOTHESE-INVALIDE")  # bas > base
    assert _code(_sensibilite(variations={"taux_actualisation": {"bas": "0.05", "haut": "2"}})) == (
        "REJ-CALC-TAUX-HORS-BORNES")
    double = [{"nom": "a", "hypotheses": {"flux_annuel": "1"}}] * 2
    assert _code(_sensibilite(scenarios=double)) == "REJ-CALC-SCENARIO-INVALIDE"
    neuf = [{"nom": f"s{k}", "hypotheses": {"flux_annuel": "1"}} for k in range(9)]
    assert _code(_sensibilite(scenarios=neuf)) == "REJ-CALC-BORNE-DEPASSEE"
    assert _code(_sensibilite(variations={}, scenarios=[])) == "REJ-CALC-HYPOTHESE-INVALIDE"
    assert _code(_sensibilite(objet="fnb")) == "REJ-CALC-OBJET-HORS-PERIMETRE"


def test_un_code_hors_catalogue_leve():
    with pytest.raises(verdicts_calcul.CodeCalculInconnu):
        verdicts_calcul.construire_verdict("REJ-CALC-INVENTE")
    assert len(set(verdicts_calcul.CODES_CALCUL)) == len(verdicts_calcul.CODES_CALCUL)


# -------------------------------------------------------------------------------------------------- reçus
def _tous_les_recus():
    return [
        _ok(moteur_calcul.calculer_rentabilite({"objet": "equipement", "flux": ["-1000", "300", "400", "500"],
                                                "taux_actualisation": "0.08", "taux_financement": "0.06",
                                                "taux_reinvestissement": "0.05"})),
        _ok(moteur_calcul.calculer_amortissement(_PRET))["recu"],
        _ok(moteur_calcul.comparer_credit_bail_achat({
            "objet": "vehicule", "taux_actualisation_annuel": "0.07", "mois": 48, "prix_achat": "60000",
            "frais_achat": "500", "valeur_residuelle": "20000", "paiement_mensuel": "1100", "depot_initial": "3000",
            "paiements_en_debut_de_periode": True})),
        _ok(moteur_calcul.calculer_point_mort({"frais_fixes": "120000", "prix_unitaire": "4500",
                                               "cout_variable_unitaire": "2900"})),
        _ok(_sensibilite()),
        _ok(moteur_calcul.simuler_tresorerie(*_monte_carlo())),
    ]


def test_chaque_recu_porte_sa_structure_sa_mention_et_se_rejoue_a_l_identique_apres_json():
    for recu in _tous_les_recus():
        assert recu["mention"] == MENTION_COMPTABLE
        assert {"moteur", "version_moteur", "methode", "precision", "parametres", "entrees", "empreinte_entrees",
                "resultat", "avertissements", "empreinte"} <= set(recu)
        assert len(recu["empreinte"]) == 64 and recu_calcul.verifier(recu) == (True, "")
        voyage = json.loads(json.dumps(recu, ensure_ascii=False))
        rejeu, verdict = moteur_calcul.rejouer(voyage)
        assert verdict is None and rejeu["identique"] is True, recu["moteur"]
        assert recu_calcul.verifier(recu_calcul.compacter(voyage)) == (True, "")


def test_un_recu_retouche_ou_d_un_moteur_inconnu_est_refuse():
    recu = _tous_les_recus()[0]
    retouche = json.loads(json.dumps(recu))
    retouche["resultat"]["van"] = "999999.99"
    assert _code(moteur_calcul.rejouer(retouche)) == "REJ-CALC-RECU-INVALIDE"
    entrees_retouchees = json.loads(json.dumps(recu))
    entrees_retouchees["entrees"]["taux_actualisation"] = "0.01"
    assert _code(moteur_calcul.rejouer(entrees_retouchees)) == "REJ-CALC-RECU-INVALIDE"
    assert _code(moteur_calcul.rejouer(recu_calcul.compacter(recu))) == "REJ-CALC-RECU-INVALIDE"
    inconnu = recu_calcul.construire(moteur="rentabilite_investissement", version_moteur="0.9.0", methode="m",
                                     precision={}, parametres={}, entrees=recu["entrees"], resultat={},
                                     avertissements=[])
    assert _code(moteur_calcul.rejouer(inconnu)) == "REJ-CALC-MOTEUR-INCONNU"
    with pytest.raises(TypeError):
        recu_calcul.construire(moteur="x", version_moteur="1", methode="m", precision={}, parametres={},
                               entrees={"a": 0.1}, resultat={}, avertissements=[])


def test_deux_ecritures_d_une_meme_entree_donnent_le_meme_recu():
    a = _ok(moteur_calcul.calculer_rentabilite({"objet": "equipement", "flux": ["-1000", "300.0", "800"],
                                                "taux_actualisation": "0.0800"}))
    b = _ok(moteur_calcul.calculer_rentabilite({"objet": "equipement", "flux": ["-1000.00", "300", "800.00"],
                                                "taux_actualisation": "0.08"}))
    assert a["empreinte"] == b["empreinte"] and a["entrees"] == b["entrees"]


def test_tri_non_unique_rend_des_avertissements_et_aucun_nombre_dans_le_recu():
    recu = _ok(moteur_calcul.calculer_rentabilite({"objet": "projet_interne", "flux": ["-100", "230", "-132"],
                                                   "taux_actualisation": "0.15"}))
    assert recu["resultat"]["tri"]["statut"] == "MULTIPLE" and recu["resultat"]["tri"]["valeur"] is None
    assert any("plusieurs racines" in a for a in recu["avertissements"])
    assert moteur_calcul.AVERTISSEMENT_NC_31_103 in recu["avertissements"]


# --------------------------------------------------------------------------------------------- Monte-Carlo
def _flux_mc():
    flux = []
    for k in range(1, 9):
        flux.append({"id": f"client:F-{k}", "sens": "ENTREE", "nature": "facture_client", "semaine": k,
                     "montant": "4000.00"})
        flux.append({"id": f"fournisseur:A-{k}", "sens": "SORTIE", "nature": "facture_fournisseur", "semaine": k,
                     "montant": "3000.00"})
    flux.append({"id": "obligation:paies", "sens": "SORTIE", "nature": "paies", "semaine": 2, "montant": "6500.00"})
    return flux


_DISTRIBUTIONS = {
    "facture_client": {"montant": {"loi": "normale_tronquee", "moyenne": "1", "ecart_type": "0.15", "min": "0.5",
                                   "max": "1.3"}, "retard": {"probabilite": "0.25", "semaines": 2}},
    "facture_fournisseur": {"montant": {"loi": "triangulaire", "min": "0.95", "mode": "1", "max": "1.25"}},
}


def _monte_carlo(graine=7, tirages=300, semaines=8, distributions=None, flux=None, seuil="1000.00"):
    entrees = {"solde_initial": "2500.00", "flux": _flux_mc() if flux is None else flux, "seuil": seuil,
               "prevision_id": "f" * 64}
    return entrees, {"graine": graine, "tirages": tirages, "semaines": semaines,
                     "distributions": _DISTRIBUTIONS if distributions is None else distributions}


def _colonne(recu, nom):
    index = recu["resultat"]["colonnes"].index(nom)
    return [ligne[index] for ligne in recu["resultat"]["semaines"]]


def test_inverse_normale_et_repartition_egalent_la_bibliotheque_standard():
    """AS241 en Decimal contre `statistics.NormalDist` (le même algorithme en flottants), sur 400 p générés."""
    generateur = random.Random(241)
    loi = statistics.NormalDist()
    for p in [D("1e-12"), D("0.0001"), D("0.025"), D("0.5"), D("0.975"), D("0.999999")] + [
            D(generateur.randint(1, 10**9 - 1)) / 10**9 for _ in range(400)]:
        # Au-dessus de 1/2, la référence flottante perd 1 − p : la symétrie Φ⁻¹(p) = −Φ⁻¹(1 − p) la garde exacte.
        reference = loi.inv_cdf(float(p)) if p <= D("0.5") else -loi.inv_cdf(float(1 - p))
        assert abs(float(mc.inverse_normale(p)) - reference) < 1e-12, p
    for z in [D("-6"), D("-1.96"), D("0"), D("0.5"), D("3.1")]:
        assert abs(float(mc.repartition_normale(z)) - loi.cdf(float(z))) < 1e-15, z


def test_monte_carlo_rejouable_bit_pour_bit_et_sensible_a_la_graine():
    premier = _ok(moteur_calcul.simuler_tresorerie(*_monte_carlo()))
    second = _ok(moteur_calcul.simuler_tresorerie(*_monte_carlo()))
    autre = _ok(moteur_calcul.simuler_tresorerie(*_monte_carlo(graine=8)))
    assert premier == second and premier["empreinte"] != autre["empreinte"]
    assert premier["parametres"]["graine"] == 7 and premier["parametres"]["tirages"] == 300
    # Épinglé : la même graine sur les mêmes entrées rend exactement ces chiffres, sur toute machine (Decimal, MT).
    p50 = _colonne(premier, "p50")
    assert _colonne(premier, "solde_base") == ["3500.00", "-2000.00", "-1000.00", "0.00", "1000.00", "2000.00",
                                               "3000.00", "4000.00"]
    assert p50 == ["2978.19", "-3684.49", "-3207.26", "-2465.08", "-1310.10", "-857.79", "-529.32", "721.42"]
    assert premier["resultat"]["plus_bas_du_chemin"] == {"p5": "-10238.05", "p50": "-6105.09", "p95": "-2326.31"}
    # L'empreinte couvre aussi la méthode et la version : changer l'une sans changer de version casse ce test.
    assert premier["empreinte"] == "18223706180dc5bde2db7055280e67613cdc97705638073fd4a61fa2ea888002"
    assert premier["resultat"]["probabilite_au_moins_une_semaine_negative"] == "1.0000"


def test_monte_carlo_sans_perturbation_rend_la_prevision_et_retard_certain_la_decale():
    neutre = _ok(moteur_calcul.simuler_tresorerie(*_monte_carlo(distributions={
        "taxes": {"montant": {"loi": "triangulaire", "min": "0.9", "mode": "1", "max": "1.1"}}})))
    for nom in ("p5", "p50", "p95", "moyenne"):
        assert _colonne(neutre, nom) == _colonne(neutre, "solde_base")
    assert any("sans flux correspondant" in a for a in neutre["avertissements"])
    decale = _ok(moteur_calcul.simuler_tresorerie(*_monte_carlo(distributions={
        "facture_client": {"retard": {"probabilite": "1", "semaines": 1}}}, tirages=5)))
    attendu, solde = [], D("2500.00")
    for k in range(1, 9):
        solde += (D("4000") if k >= 2 else 0) - D("3000") - (D("6500") if k == 2 else 0)
        attendu.append(format(solde, ".2f"))
    assert _colonne(decale, "p50") == attendu == _colonne(decale, "p5") == _colonne(decale, "p95")
    assert decale["resultat"]["encaissements_reportes_hors_horizon"] == 5


def test_monte_carlo_moyennes_des_lois_et_percentiles_au_rang_le_plus_proche():
    """Propriétés statistiques (graine fixe, donc déterministes) : la moyenne des facteurs triangulaires vaut
    (a + b + c)/3, celle d'une normale tronquée symétrique vaut μ ; P5 ≤ P50 ≤ P95 chaque semaine."""
    flux = [{"id": "fournisseur:X", "sens": "SORTIE", "nature": "facture_fournisseur", "semaine": 1,
             "montant": "1000.00"}]
    tri = _ok(moteur_calcul.simuler_tresorerie(*_monte_carlo(
        flux=flux, semaines=1, tirages=4000, seuil=None,
        distributions={"facture_fournisseur": {"montant": {"loi": "triangulaire", "min": "0.9", "mode": "1",
                                                           "max": "1.4"}}})))
    moyenne_sortie = D("2500.00") - D(_colonne(tri, "moyenne")[0])
    assert abs(moyenne_sortie - D("1100.00")) < D("6")  # 1000 × (0,9 + 1 + 1,4)/3
    normale = _ok(moteur_calcul.simuler_tresorerie(*_monte_carlo(
        flux=flux, semaines=1, tirages=4000, seuil=None,
        distributions={"facture_fournisseur": {"montant": {"loi": "normale_tronquee", "moyenne": "1",
                                                           "ecart_type": "0.2", "min": "0.6", "max": "1.4"}}})))
    assert abs(D("2500.00") - D(_colonne(normale, "moyenne")[0]) - D("1000.00")) < D("6")
    complet = _ok(moteur_calcul.simuler_tresorerie(*_monte_carlo(tirages=500)))
    for p5, p50, p95 in zip(_colonne(complet, "p5"), _colonne(complet, "p50"), _colonne(complet, "p95"),
                            strict=True):
        assert D(p5) <= D(p50) <= D(p95)
    rangs = sorted(D(k) for k in range(1, 21))
    assert mc._rang(rangs, D("0.05")) == 1 and mc._rang(rangs, D("0.5")) == 10 and mc._rang(rangs, D("0.95")) == 19
    sept = [D(k) for k in range(1, 8)]  # p·N non entier : ⌈0,35⌉ = 1, ⌈3,5⌉ = 4, ⌈6,65⌉ = 7
    assert [mc._rang(sept, p) for _, p in mc._PERCENTILES] == [D(1), D(4), D(7)]
    trente = [D(k) for k in range(1, 31)]  # ⌈1,5⌉ = 2, ⌈15⌉ = 15, ⌈28,5⌉ = 29
    assert [mc._rang(trente, p) for _, p in mc._PERCENTILES] == [D(2), D(15), D(29)]


def test_monte_carlo_probabilites_comptees():
    sur = _ok(moteur_calcul.simuler_tresorerie(*_monte_carlo(tirages=50)))
    negatifs = _colonne(sur, "tirages_negatifs")
    probabilites = _colonne(sur, "probabilite_negatif")
    for compte, probabilite in zip(negatifs, probabilites, strict=True):
        assert D(probabilite) == (D(compte) / 50).quantize(D("0.0001"))
    assert sur["resultat"]["tirages_avec_semaine_negative"] >= max(negatifs)


@pytest.mark.parametrize(("parametres", "code"), [
    ({"tirages": 0}, "REJ-CALC-BORNE-DEPASSEE"),
    ({"tirages": 10001}, "REJ-CALC-BORNE-DEPASSEE"),
    ({"semaines": 27}, "REJ-CALC-DUREE-INVALIDE"),
    ({"graine": -1}, "REJ-CALC-GRAINE-INVALIDE"),
    ({"graine": 2**63}, "REJ-CALC-GRAINE-INVALIDE"),
    ({"graine": "42"}, "REJ-CALC-GRAINE-INVALIDE"),
    ({"graine": True}, "REJ-CALC-GRAINE-INVALIDE"),
    ({"distributions": {}}, "REJ-CALC-DISTRIBUTION-INVALIDE"),
    ({"distributions": {"ventes_futures": {"retard": {"probabilite": "0.1", "semaines": 1}}}},
     "REJ-CALC-DISTRIBUTION-INVALIDE"),
    ({"distributions": {"paies": {"retard": {"probabilite": "0.1", "semaines": 1}}}}, "REJ-CALC-DISTRIBUTION-INVALIDE"),
    ({"distributions": {"paies": {"montant": {"loi": "uniforme", "min": "0", "max": "1"}}}},
     "REJ-CALC-DISTRIBUTION-INVALIDE"),
    ({"distributions": {"paies": {"montant": {"loi": "triangulaire", "min": "1", "mode": "0.9", "max": "1.2"}}}},
     "REJ-CALC-DISTRIBUTION-INVALIDE"),
    ({"distributions": {"paies": {"montant": {"loi": "normale_tronquee", "moyenne": "1", "ecart_type": "0",
                                              "min": "0.5", "max": "1.5"}}}}, "REJ-CALC-DISTRIBUTION-INVALIDE"),
    ({"distributions": {"paies": {"montant": {"loi": "normale_tronquee", "moyenne": "1", "ecart_type": "0.01",
                                              "min": "2", "max": "3"}}}}, "REJ-CALC-DISTRIBUTION-INVALIDE"),
    ({"distributions": {"facture_client": {"retard": {"probabilite": "1.5", "semaines": 1}}}},
     "REJ-CALC-DISTRIBUTION-INVALIDE"),
    ({"tirages": 10000, "distributions": {"facture_client": {"retard": {"probabilite": "0.5", "semaines": 1}},
                                          "facture_fournisseur": {"retard": None, "montant": {
                                              "loi": "triangulaire", "min": "1", "mode": "1", "max": "2"}}}},
     "REJ-CALC-BORNE-DEPASSEE"),
])
def test_refus_typés_du_monte_carlo(parametres, code):
    entrees, base = _monte_carlo()
    flux = _flux_mc() * 1
    if parametres.get("tirages") == 10000:
        flux = [{**f, "id": f"{f['id']}:{k}"} for k in range(3) for f in _flux_mc()]
        entrees = {**entrees, "flux": flux}
    assert _code(moteur_calcul.simuler_tresorerie(entrees, {**base, **parametres})) == code


def test_monte_carlo_refuse_des_flux_incoherents():
    entrees, parametres = _monte_carlo()
    mauvais_sens = [{**_flux_mc()[0], "sens": "SORTIE"}]
    assert _code(moteur_calcul.simuler_tresorerie({**entrees, "flux": mauvais_sens}, parametres)) == (
        "REJ-CALC-FLUX-INVALIDES")
    hors_horizon = [{**_flux_mc()[0], "semaine": 9}]
    assert _code(moteur_calcul.simuler_tresorerie({**entrees, "flux": hors_horizon}, parametres)) == (
        "REJ-CALC-FLUX-INVALIDES")
    double = [_flux_mc()[0], _flux_mc()[0]]
    assert _code(moteur_calcul.simuler_tresorerie({**entrees, "flux": double}, parametres)) == (
        "REJ-CALC-FLUX-INVALIDES")
    trop = [{**_flux_mc()[0], "id": f"c{k}"} for k in range(401)]
    assert _code(moteur_calcul.simuler_tresorerie({**entrees, "flux": trop}, parametres)) == (
        "REJ-CALC-BORNE-DEPASSEE")
