"""Conception statistique de tests marketing : chaque moteur est comparé à un calcul INDÉPENDANT (stdlib flottante,
valeurs
publiées, calcul à la main), puis les reçus, le préenregistrement et la langue de sortie sont éprouvés."""

from __future__ import annotations

import copy
import math
import statistics
from datetime import UTC, date, datetime, timedelta

import pytest
from m7_marketing import journal_chaine
from m7_marketing.mesure import experiences as x

from opsys import recu_calcul_pont

NORMALE = statistics.NormalDist()
V = x.VERSION


def _produire(moteur, entrees, parametres):
    recu, verdict = x.produire(moteur, V, entrees, parametres)
    assert verdict is None, verdict
    return recu


def _refus(moteur, entrees, parametres, code):
    recu, verdict = x.produire(moteur, V, entrees, parametres)
    assert recu is None and verdict["code"] == code, verdict
    return verdict


def _n_oracle(p1, p2, alpha, puissance):
    za, zb = NORMALE.inv_cdf(1 - alpha / 2), NORMALE.inv_cdf(puissance)
    pb = (p1 + p2) / 2
    return (za * math.sqrt(2 * pb * (1 - pb)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / (p1 - p2) ** 2


TAILLE = {"alpha": "0.05", "puissance": "0.8"}


# ------------------------------------------------------------------------------------------- SplitMix64
def test_splitmix64_vecteurs_connus_de_la_graine_zero():
    g = x.SplitMix64(0)
    assert [g.suivant() for _ in range(3)] == [0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4, 0x06C45D188009454F]


def test_splitmix64_deterministe_et_graine_validee():
    a, b = x.SplitMix64(12345), x.SplitMix64(12345)
    assert [a.suivant() for _ in range(5)] == [b.suivant() for _ in range(5)]
    assert x.SplitMix64(1).suivant() != x.SplitMix64(2).suivant()
    for mauvaise in (-1, 2**64, 1.5, True, "1"):
        with pytest.raises(ValueError):
            x.SplitMix64(mauvaise)
    assert x.SplitMix64(2**64 - 1).suivant() >= 0


# ------------------------------------------------------------------------------------- taille d'échantillon
def test_exemple_classique_10_pour_cent_contre_12_pour_cent():
    recu = _produire(
        "taille_echantillon_deux_proportions", {"p1": "0.10", "effet": {"mode": "absolu", "valeur": "0.02"}}, TAILLE
    )
    r = recu["resultat"]
    assert r["n_par_groupe"] == 3841 and r["n_total"] == 7682 and r["p2"] == "0.12" and r["p_moyen"] == "0.11"
    assert r["z_alpha"] == "1.959964" and r["z_puissance"] == "0.841621"
    assert abs(float(r["n_exact"]) - _n_oracle(0.10, 0.12, 0.05, 0.8)) < 1e-3


@pytest.mark.parametrize(
    "p1,mode,valeur,p2,alpha,puiss",
    [
        ("0.20", "absolu", "0.05", 0.25, "0.05", "0.8"),
        ("0.05", "relatif", "0.20", 0.06, "0.05", "0.9"),
        ("0.30", "absolu", "-0.04", 0.26, "0.01", "0.8"),
        ("0.50", "relatif", "0.10", 0.55, "0.10", "0.95"),
        ("0.02", "relatif", "0.5", 0.03, "0.05", "0.8"),
    ],
)
def test_taille_contre_la_formule_independante_et_arrondi_superieur(p1, mode, valeur, p2, alpha, puiss):
    recu = _produire(
        "taille_echantillon_deux_proportions",
        {"p1": p1, "effet": {"mode": mode, "valeur": valeur}},
        {"alpha": alpha, "puissance": puiss},
    )
    attendu = _n_oracle(float(p1), p2, float(alpha), float(puiss))
    r = recu["resultat"]
    assert abs(float(r["n_exact"]) - attendu) < max(1e-3, attendu * 1e-5)
    assert r["n_par_groupe"] == math.ceil(float(r["n_exact"])) == math.ceil(attendu)
    assert r["n_par_groupe"] >= attendu  # jamais arrondi vers le bas


def test_effet_negatif_et_positif_de_meme_taille_demandent_le_meme_n():
    a = _produire(
        "taille_echantillon_deux_proportions", {"p1": "0.10", "effet": {"mode": "absolu", "valeur": "0.02"}}, TAILLE
    )
    b = _produire(
        "taille_echantillon_deux_proportions", {"p1": "0.12", "effet": {"mode": "absolu", "valeur": "-0.02"}}, TAILLE
    )
    assert a["resultat"]["n_par_groupe"] == b["resultat"]["n_par_groupe"]


@pytest.mark.parametrize(
    "p1,effet,params,code",
    [
        ("0", {"mode": "absolu", "valeur": "0.02"}, TAILLE, "REJ-MESURE-TAUX-INVALIDE"),
        ("1", {"mode": "absolu", "valeur": "0.02"}, TAILLE, "REJ-MESURE-TAUX-INVALIDE"),
        (0.1, {"mode": "absolu", "valeur": "0.02"}, TAILLE, "REJ-MESURE-TAUX-INVALIDE"),
        ("1.5", {"mode": "absolu", "valeur": "0.02"}, TAILLE, "REJ-MESURE-TAUX-INVALIDE"),
        ("0.10", {"mode": "absolu", "valeur": "0"}, TAILLE, "REJ-MESURE-EFFET-INVALIDE"),
        ("0.10", {"mode": "absolu", "valeur": "0.95"}, TAILLE, "REJ-MESURE-EFFET-INVALIDE"),
        ("0.10", {"mode": "relatif", "valeur": "10"}, TAILLE, "REJ-MESURE-EFFET-INVALIDE"),
        ("0.10", {"mode": "pourcent", "valeur": "0.02"}, TAILLE, "REJ-MESURE-EFFET-INVALIDE"),
        ("0.10", {"mode": "absolu", "valeur": 0.02}, TAILLE, "REJ-MESURE-EFFET-INVALIDE"),
        (
            "0.10",
            {"mode": "absolu", "valeur": "0.0000001"},
            TAILLE,
            "REJ-MESURE-EFFET-INVALIDE",
        ),  # irréaliste ou illisible
        ("0.10", {"mode": "absolu", "valeur": "0.02"}, {"alpha": "0", "puissance": "0.8"}, "REJ-MESURE-ALPHA-INVALIDE"),
        (
            "0.10",
            {"mode": "absolu", "valeur": "0.02"},
            {"alpha": "0.5", "puissance": "0.8"},
            "REJ-MESURE-ALPHA-INVALIDE",
        ),
        (
            "0.10",
            {"mode": "absolu", "valeur": "0.02"},
            {"alpha": 0.05, "puissance": "0.8"},
            "REJ-MESURE-ALPHA-INVALIDE",
        ),
        (
            "0.10",
            {"mode": "absolu", "valeur": "0.02"},
            {"alpha": "0.05", "puissance": "0.3"},
            "REJ-MESURE-PUISSANCE-INVALIDE",
        ),
        (
            "0.10",
            {"mode": "absolu", "valeur": "0.02"},
            {"alpha": "0.05", "puissance": "1"},
            "REJ-MESURE-PUISSANCE-INVALIDE",
        ),
        ("0.10", {"mode": "absolu", "valeur": "0.02"}, {"alpha": "0.05"}, "REJ-MESURE-ARGUMENT-INVALIDE"),
        ("0.10", {"mode": "absolu", "valeur": "0.02"}, {**TAILLE, "extra": "x"}, "REJ-MESURE-ARGUMENT-INVALIDE"),
        ("0.10", {"mode": "absolu"}, TAILLE, "REJ-MESURE-ARGUMENT-INVALIDE"),
    ],
)
def test_taille_entrees_invalides_refusees_avec_code(p1, effet, params, code):
    _refus("taille_echantillon_deux_proportions", {"p1": p1, "effet": effet}, params, code)


def test_taille_irrealiste_au_dela_de_dix_millions_par_groupe_est_refusee():
    v = _refus(
        "taille_echantillon_deux_proportions",
        {"p1": "0.5", "effet": {"mode": "absolu", "valeur": "0.0001"}},
        TAILLE,
        "REJ-MESURE-EFFET-INVALIDE",
    )
    assert "irréaliste" in v["detail"]
    ok = _produire(
        "taille_echantillon_deux_proportions", {"p1": "0.5", "effet": {"mode": "absolu", "valeur": "0.001"}}, TAILLE
    )
    assert ok["resultat"]["n_par_groupe"] > 1_000_000


def test_entrees_inconnues_ou_mal_formees():
    _refus("taille_echantillon_deux_proportions", {"p1": "0.1"}, TAILLE, "REJ-MESURE-ARGUMENT-INVALIDE")
    _refus("taille_echantillon_deux_proportions", "texte", TAILLE, "REJ-MESURE-ARGUMENT-INVALIDE")
    _refus(
        "taille_echantillon_deux_proportions",
        {"p1": "0.1", "effet": {"mode": "absolu", "valeur": "0.02"}, "x": 1},
        TAILLE,
        "REJ-MESURE-ARGUMENT-INVALIDE",
    )
    recu, verdict = x.produire("inconnu", V, {}, {})
    assert recu is None and verdict["code"] == "REJ-MESURE-MOTEUR-INCONNU"
    recu, verdict = x.produire("taille_echantillon_deux_proportions", "9.9.9", {}, {})
    assert verdict["code"] == "REJ-MESURE-MOTEUR-INCONNU"


# ------------------------------------------------------------------------------------------------- puissance
def _puissance(n, p1, p2, alpha="0.05"):
    return float(
        _produire("puissance_deux_proportions", {"n_par_groupe": n, "p1": p1, "p2": p2}, {"alpha": alpha})["resultat"][
            "puissance"
        ]
    )


def test_puissance_contre_la_formule_independante():
    for n, p1, p2 in [(500, "0.10", "0.14"), (3841, "0.10", "0.12"), (50, "0.5", "0.6"), (10000, "0.02", "0.025")]:
        a, b = float(p1), float(p2)
        pb = (a + b) / 2
        z = (abs(a - b) * math.sqrt(n) - NORMALE.inv_cdf(0.975) * math.sqrt(2 * pb * (1 - pb))) / math.sqrt(
            a * (1 - a) + b * (1 - b)
        )
        assert abs(_puissance(n, p1, p2) - NORMALE.cdf(z)) < 1e-5


@pytest.mark.parametrize("p1,effet,puiss", [("0.10", "0.02", "0.8"), ("0.20", "0.05", "0.9"), ("0.05", "0.015", "0.8")])
def test_n_calcule_atteint_la_puissance_visee_et_n_moins_un_ne_l_atteint_pas(p1, effet, puiss):
    recu = _produire(
        "taille_echantillon_deux_proportions",
        {"p1": p1, "effet": {"mode": "absolu", "valeur": effet}},
        {"alpha": "0.05", "puissance": puiss},
    )
    n, p2 = recu["resultat"]["n_par_groupe"], recu["resultat"]["p2"]
    assert _puissance(n, p1, p2) >= float(puiss) - 1e-6
    assert _puissance(n - 1, p1, p2) < float(puiss)
    assert _puissance(n // 4, p1, p2) < float(puiss) - 0.2


def test_puissance_refus():
    _refus(
        "puissance_deux_proportions",
        {"n_par_groupe": 1, "p1": "0.1", "p2": "0.2"},
        {"alpha": "0.05"},
        "REJ-MESURE-ARGUMENT-INVALIDE",
    )
    _refus(
        "puissance_deux_proportions",
        {"n_par_groupe": 100.0, "p1": "0.1", "p2": "0.2"},
        {"alpha": "0.05"},
        "REJ-MESURE-ARGUMENT-INVALIDE",
    )
    _refus(
        "puissance_deux_proportions",
        {"n_par_groupe": 100, "p1": "0.1", "p2": "0.1"},
        {"alpha": "0.05"},
        "REJ-MESURE-EFFET-INVALIDE",
    )
    _refus(
        "puissance_deux_proportions",
        {"n_par_groupe": 100, "p1": "0.1", "p2": "1"},
        {"alpha": "0.05"},
        "REJ-MESURE-TAUX-INVALIDE",
    )


# --------------------------------------------------------------------------------------------- marche-arrêt
HISTORIQUE = ["10", "12", "14", "16", "18", "20", "22", "24"]
ARRET = {"alpha": "0.05", "puissance": "0.8", "graine": 42, "plafond_semaines": 26}


def _marche_arret(historique=HISTORIQUE, delta="0.5", debut="2026-12-07", params=None):
    return _produire(
        "duree_test_marche_arret",
        {"historique_hebdo": historique, "effet_relatif": delta, "debut": debut},
        params or ARRET,
    )


def test_marche_arret_calcul_a_la_main():
    # moyenne 17 ; variance d'échantillon (49+25+9+1+1+9+25+49)/7 = 24 ; n = 2·(z_a+z_b)²·24 / (0.5·17)²
    r = _marche_arret()["resultat"]
    assert r["moyenne_hebdo"] == "17" and r["ecart_type_hebdo"] == "4.898979"
    n = 2 * (NORMALE.inv_cdf(0.975) + NORMALE.inv_cdf(0.8)) ** 2 * 24 / (0.5 * 17) ** 2
    assert r["n_formule"] == math.ceil(n) == 6 and r["semaines_par_bras"] == 6 and r["duree_totale_semaines"] == 12
    assert r["faisabilite"] == "realisable" and len(r["calendrier"]) == 12


def test_marche_arret_minimum_deux_paires_meme_si_la_formule_dit_moins():
    r = _marche_arret(delta="5")["resultat"]
    assert r["n_formule"] < 2 and r["semaines_par_bras"] == 2 and r["duree_totale_semaines"] == 4


def test_marche_arret_irrealisable_est_declare_sans_calendrier():
    r = _marche_arret(delta="0.05")["resultat"]
    assert r["faisabilite"] == "irrealisable" and r["calendrier"] == [] and r["duree_totale_semaines"] > 26
    assert "plafond de faisabilité 26" in r["raison"]
    court = _marche_arret(params={**ARRET, "plafond_semaines": 8})["resultat"]
    assert court["faisabilite"] == "irrealisable" and court["duree_totale_semaines"] == 12


def test_calendrier_equilibre_contigu_et_deterministe():
    r = _marche_arret()["resultat"]
    cal = r["calendrier"]
    for i in range(0, 12, 2):  # chaque paire de semaines consécutives : une marche, un arrêt
        assert {cal[i]["bras"], cal[i + 1]["bras"]} == {"marche", "arret"}
    assert sum(1 for c in cal if c["bras"] == "marche") == 6
    debut = date(2026, 12, 7)
    for i, c in enumerate(cal):
        lundi = debut + timedelta(days=7 * i)
        assert (
            c["semaine"] == i + 1
            and c["debut"] == lundi.isoformat()
            and c["fin"] == (lundi + timedelta(days=6)).isoformat()
        )
        assert date.fromisoformat(c["debut"]).weekday() == 0
    assert _marche_arret()["resultat"]["calendrier"] == cal
    # l'ordre vient de la graine : le bit de chaque paire est celui de SplitMix64
    g = x.SplitMix64(42)
    attendu = []
    for _ in range(6):
        attendu += ["marche", "arret"] if g.suivant() & 1 == 0 else ["arret", "marche"]
    assert [c["bras"] for c in cal] == attendu
    autres = {
        tuple(c["bras"] for c in _marche_arret(params={**ARRET, "graine": s})["resultat"]["calendrier"])
        for s in range(8)
    }
    assert len(autres) > 1


@pytest.mark.parametrize(
    "modif,code",
    [
        ({"historique": HISTORIQUE[:7]}, "REJ-MESURE-HISTORIQUE-INSUFFISANT"),
        ({"historique": ["5"] * 10}, "REJ-MESURE-SERIE-DEGENEREE"),
        ({"historique": ["0"] * 10}, "REJ-MESURE-SERIE-DEGENEREE"),
        ({"historique": [10, 11, 12, 13, 14, 15, 16, 17]}, "REJ-MESURE-ARGUMENT-INVALIDE"),
        ({"historique": ["-1", "2", "3", "4", "5", "6", "7", "8"]}, "REJ-MESURE-ARGUMENT-INVALIDE"),
        ({"delta": "0"}, "REJ-MESURE-EFFET-INVALIDE"),
        ({"delta": "6"}, "REJ-MESURE-EFFET-INVALIDE"),
        ({"debut": "2026-12-08"}, "REJ-MESURE-PERIODE-INVALIDE"),
        ({"debut": "2026-13-01"}, "REJ-MESURE-PERIODE-INVALIDE"),
        ({"params": {**ARRET, "graine": -1}}, "REJ-MESURE-GRAINE-INVALIDE"),
        ({"params": {**ARRET, "graine": "42"}}, "REJ-MESURE-GRAINE-INVALIDE"),
        ({"params": {**ARRET, "plafond_semaines": 27}}, "REJ-MESURE-ARGUMENT-INVALIDE"),
        ({"params": {**ARRET, "plafond_semaines": 1}}, "REJ-MESURE-ARGUMENT-INVALIDE"),
        ({"params": {k: v for k, v in ARRET.items() if k != "graine"}}, "REJ-MESURE-ARGUMENT-INVALIDE"),
    ],
)
def test_marche_arret_refus(modif, code):
    entrees = {
        "historique_hebdo": modif.get("historique", HISTORIQUE),
        "effet_relatif": modif.get("delta", "0.5"),
        "debut": modif.get("debut", "2026-12-07"),
    }
    _refus("duree_test_marche_arret", entrees, modif.get("params", ARRET), code)


# -------------------------------------------------------------------------------------------- géographique
def _regions(n):
    return [{"id": f"r{i:02d}", "mesure_base": str(100 + 10 * i)} for i in range(n)]


GEO = {"alpha": "0.05", "puissance": "0.8", "graine": 7}


def _geo(n, ecarts=None, delta="0.1", params=None):
    entrees = {"regions": _regions(n), "effet_relatif": delta}
    if ecarts is not None:
        entrees["ecarts_relatifs_apparies"] = ecarts
    return _produire("plan_test_geographique", entrees, params or GEO)["resultat"]


@pytest.mark.parametrize("n,paires", [(2, 1), (3, 1), (10, 5), (11, 5)])
def test_moins_de_six_paires_est_insuffisant_avec_ce_qu_il_manque(n, paires):
    r = _geo(n)
    assert r["statut"] == "INSUFFISANT" and r["paires_disponibles"] == paires and r["paires_minimales"] == 6
    assert r["regions_a_ajouter"] == 12 - n and r["paires"] == [] and r["puissance_approx"] is None
    assert "au moins 6" in r["raison"]


def test_douze_regions_donnent_six_paires_affectees_par_la_graine():
    r = _geo(12)
    assert r["statut"] == "PLAN" and r["paires_disponibles"] == 6 and r["regions_exclues"] == []
    # appariement par mesure de base voisine : (r11,r10), (r09,r08), … ; une région test, une témoin par paire
    assert [{p["test"], p["temoin"]} for p in r["paires"]] == [
        {"r11", "r10"},
        {"r09", "r08"},
        {"r07", "r06"},
        {"r05", "r04"},
        {"r03", "r02"},
        {"r01", "r00"},
    ]
    g = x.SplitMix64(7)
    for p, haut in zip(r["paires"], ["r11", "r09", "r07", "r05", "r03", "r01"], strict=True):
        assert (p["test"] == haut) == (g.suivant() & 1 == 0)
    ids = [p["test"] for p in r["paires"]] + [p["temoin"] for p in r["paires"]]
    assert len(set(ids)) == 12
    assert _geo(12) == r
    assert _geo(12, params={**GEO, "graine": 8}) != r


def test_region_impaire_exclue_est_la_plus_petite():
    r = _geo(13)
    assert r["paires_disponibles"] == 6 and r["regions_exclues"] == ["r00"]


def test_puissance_geo_sur_les_ecarts_fournis():
    ecarts = ["0.05", "0.08", "-0.03", "0.02", "0.06", "0.04"]
    r = _geo(14, ecarts, "0.1")
    valeurs = [float(v) for v in ecarts]
    sigma = statistics.stdev(valeurs)
    za, zb = NORMALE.inv_cdf(0.975), NORMALE.inv_cdf(0.8)
    assert abs(float(r["ecart_type_apparie"]) - sigma) < 1e-6
    assert abs(float(r["puissance_approx"]) - NORMALE.cdf(0.1 * math.sqrt(7) / sigma - za)) < 1e-5
    assert r["paires_requises"] == math.ceil((za + zb) ** 2 * sigma**2 / 0.01)
    assert r["suffisant"] == (r["paires_requises"] <= 7)
    sans = _geo(14)
    assert sans["puissance_approx"] is None and "inconnue" in sans["lecture_puissance"]
    faible = _geo(12, ecarts, "0.01")  # effet minuscule : le plan dit qu'il n'est pas suffisant
    assert faible["suffisant"] is False and float(faible["puissance_approx"]) < 0.8


@pytest.mark.parametrize(
    "regions,code",
    [
        ([], "REJ-MESURE-REGIONS-INVALIDES"),
        ([{"id": "a", "mesure_base": "1"}], "REJ-MESURE-REGIONS-INVALIDES"),
        ([{"id": "a", "mesure_base": "1"}, {"id": "a", "mesure_base": "2"}], "REJ-MESURE-REGIONS-INVALIDES"),
        ([{"id": "A", "mesure_base": "1"}, {"id": "b", "mesure_base": "2"}], "REJ-MESURE-REGIONS-INVALIDES"),
        ([{"id": "a", "mesure_base": "0"}, {"id": "b", "mesure_base": "2"}], "REJ-MESURE-REGIONS-INVALIDES"),
        ([{"id": "a", "mesure_base": 5}, {"id": "b", "mesure_base": "2"}], "REJ-MESURE-REGIONS-INVALIDES"),
        ([{"id": "a"}, {"id": "b", "mesure_base": "2"}], "REJ-MESURE-REGIONS-INVALIDES"),
        ([{"id": f"r{i}", "mesure_base": "1"} for i in range(101)], "REJ-MESURE-REGIONS-INVALIDES"),
    ],
)
def test_geo_regions_invalides(regions, code):
    _refus("plan_test_geographique", {"regions": regions, "effet_relatif": "0.1"}, GEO, code)


def test_geo_ecarts_constants_ou_trop_courts():
    _refus(
        "plan_test_geographique",
        {"regions": _regions(12), "effet_relatif": "0.1", "ecarts_relatifs_apparies": ["0.05"] * 5},
        GEO,
        "REJ-MESURE-SERIE-DEGENEREE",
    )
    _refus(
        "plan_test_geographique",
        {"regions": _regions(12), "effet_relatif": "0.1", "ecarts_relatifs_apparies": ["0.05", "0.1"]},
        GEO,
        "REJ-MESURE-HISTORIQUE-INSUFFISANT",
    )
    _refus("plan_test_geographique", {"regions": _regions(12), "effet_relatif": "0"}, GEO, "REJ-MESURE-EFFET-INVALIDE")


# ---------------------------------------------------------------------------------------------------- analyse
def _newcombe_oracle(k1, n1, k2, n2, z=1.959964):
    def w(k, n):
        p = k / n
        c = (p + z * z / (2 * n)) / (1 + z * z / n)
        d = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        return p, c - d, c + d

    p1, l1, u1 = w(k1, n1)
    p2, l2, u2 = w(k2, n2)
    d = p1 - p2
    return d, d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)


def _analyse(test, temoin, niveau="0.95"):
    return _produire("analyse_resultat_test", {"test": test, "temoin": temoin}, {"niveau": niveau})["resultat"]


def test_analyse_difference_et_intervalle_de_newcombe():
    r = _analyse({"k": 120, "n": 1000}, {"k": 90, "n": 1000})
    d, bas, haut = _newcombe_oracle(120, 1000, 90, 1000)
    assert abs(float(r["difference"]) - d) < 1e-6 and abs(float(r["borne_basse"]) - bas) < 1e-5
    assert abs(float(r["borne_haute"]) - haut) < 1e-5
    assert r["taux_test"] == "0.12" and r["taux_temoin"] == "0.09"
    assert (
        r["conclusion"] == "difference_observee_test_superieur" and r["lecture"] == "différence observée dans ce test"
    )


def test_analyse_compatible_avec_aucune_difference_quand_zero_est_dans_l_intervalle():
    r = _analyse({"k": 52, "n": 500}, {"k": 45, "n": 500})
    assert float(r["borne_basse"]) < 0 < float(r["borne_haute"])
    assert r["conclusion"] == "aucune_difference_detectee" and r["lecture"] == "compatible avec aucune différence"


def test_analyse_difference_negative_et_niveau_99_plus_large():
    n = _analyse({"k": 60, "n": 1000}, {"k": 100, "n": 1000})
    assert n["conclusion"] == "difference_observee_test_inferieur" and float(n["difference"]) < 0
    a95 = _analyse({"k": 120, "n": 1000}, {"k": 90, "n": 1000})
    a99 = _analyse({"k": 120, "n": 1000}, {"k": 90, "n": 1000}, "0.99")
    assert float(a99["borne_haute"]) - float(a99["borne_basse"]) > float(a95["borne_haute"]) - float(a95["borne_basse"])


@pytest.mark.parametrize(
    "test,temoin,niveau",
    [
        ({"k": -1, "n": 10}, {"k": 1, "n": 10}, "0.95"),
        ({"k": 11, "n": 10}, {"k": 1, "n": 10}, "0.95"),
        ({"k": 1, "n": 0}, {"k": 1, "n": 10}, "0.95"),
        ({"k": 1.0, "n": 10}, {"k": 1, "n": 10}, "0.95"),
        ({"k": True, "n": 10}, {"k": 1, "n": 10}, "0.95"),
        ({"k": "1", "n": 10}, {"k": 1, "n": 10}, "0.95"),
        ({"k": 1, "n": 10}, {"k": 1}, "0.95"),
        ({"k": 1, "n": 10}, {"k": 1, "n": 10}, "0.97"),
        ({"k": 1, "n": 10}, {"k": 1, "n": 10}, 0.95),
    ],
)
def test_analyse_entrees_impossibles(test, temoin, niveau):
    recu, verdict = x.produire("analyse_resultat_test", V, {"test": test, "temoin": temoin}, {"niveau": niveau})
    assert recu is None and verdict["code"] in ("REJ-MESURE-ECHANTILLON-INVALIDE", "REJ-MESURE-ARGUMENT-INVALIDE")


# ----------------------------------------------------------------------------------------------------- reçus
def _tous_les_recus():
    return [
        _produire(
            "taille_echantillon_deux_proportions", {"p1": "0.10", "effet": {"mode": "absolu", "valeur": "0.02"}}, TAILLE
        ),
        _produire("puissance_deux_proportions", {"n_par_groupe": 500, "p1": "0.1", "p2": "0.14"}, {"alpha": "0.05"}),
        _marche_arret(),
        _produire("plan_test_geographique", {"regions": _regions(12), "effet_relatif": "0.1"}, GEO),
        _produire("analyse_resultat_test", {"test": {"k": 5, "n": 50}, "temoin": {"k": 3, "n": 50}}, {"niveau": "0.9"}),
    ]


def test_chaque_recu_est_verifiable_par_le_pont_du_socle_et_rejouable_identique():
    for recu in _tous_les_recus():
        assert recu["format"] == "recu-calcul.v1" and recu_calcul_pont.verifier(recu) == (True, "")
        rejeu, verdict = x.rejouer(recu)
        assert verdict is None and rejeu["identique"] is True and rejeu["empreinte_recue"] == recu["empreinte"]
        assert x.rejouer(copy.deepcopy(recu))[0]["identique"] is True


def test_les_recus_sont_du_json_sans_flottant_et_portent_les_avertissements_statistiques():
    def verifier(v):
        assert not isinstance(v, float)
        if isinstance(v, dict):
            for s in v.values():
                verifier(s)
        elif isinstance(v, list):
            for s in v:
                verifier(s)

    for recu in _tous_les_recus():
        verifier(recu)
        texte = " ".join(recu["avertissements"])
        for mot in ("Approximation normale", "indépendantes", "SUPPOSITION", "exploratoire"):
            assert mot in texte


def test_recu_retouche_compact_ou_de_moteur_inconnu_refuse():
    recu = _tous_les_recus()[0]
    retouche = copy.deepcopy(recu)
    retouche["resultat"]["n_par_groupe"] = 10
    assert x.rejouer(retouche)[1]["code"] == "REJ-MESURE-RECU-INVALIDE"
    entrees_retouchees = copy.deepcopy(recu)
    entrees_retouchees["entrees"]["p1"] = "0.2"
    assert x.rejouer(entrees_retouchees)[1]["code"] == "REJ-MESURE-RECU-INVALIDE"
    compact = recu_calcul_pont.compacter(recu)
    assert recu_calcul_pont.verifier(compact) == (True, "")
    assert x.rejouer(compact)[1]["code"] == "REJ-MESURE-RECU-INVALIDE" and "compact" in x.rejouer(compact)[1]["detail"]
    etranger = recu_calcul_pont.construire(
        moteur="inconnu",
        version_moteur="1",
        methode="m",
        precision={},
        parametres={},
        entrees={},
        resultat={},
        avertissements=[],
    )
    assert x.rejouer(etranger)[1]["code"] == "REJ-MESURE-RECU-INVALIDE"
    assert x.rejouer("pas un reçu")[1]["code"] == "REJ-MESURE-RECU-INVALIDE"
    # un reçu bien formé dont le résultat a changé de moteur est détecté par le rejeu (empreintes différentes)
    faux = recu_calcul_pont.construire(
        moteur=recu["moteur"],
        version_moteur=recu["version_moteur"],
        methode=recu["methode"],
        precision=recu["precision"],
        parametres=recu["parametres"],
        entrees=recu["entrees"],
        resultat={**recu["resultat"], "n_par_groupe": 5},
        avertissements=recu["avertissements"],
    )
    assert recu_calcul_pont.verifier(faux) == (True, "")
    assert x.rejouer(faux)[0]["identique"] is False


def test_les_entrees_du_recu_sont_normalisees():
    a = _produire(
        "taille_echantillon_deux_proportions",
        {"p1": "0.100", "effet": {"mode": "absolu", "valeur": "0.020"}},
        {"alpha": "0.050", "puissance": "0.80"},
    )
    b = _produire(
        "taille_echantillon_deux_proportions", {"p1": "0.1", "effet": {"mode": "absolu", "valeur": "0.02"}}, TAILLE
    )
    assert a["empreinte"] == b["empreinte"] and a["entrees"] == b["entrees"]


# --------------------------------------------------------------------------------------------- préenregistrement
MAINTENANT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
HYP = "L'arrêt de la publicité payante réduit les demandes de soumission de plus de 20 %."


def _plan(journal, plan_id="plan-a", recu=None, debut="2026-12-07", fin="2027-02-28", maintenant=MAINTENANT, **modif):
    recu = recu or _marche_arret(debut="2026-12-07")
    args = {"hypothese": HYP, "metrique_primaire": "soumissions_signees", **modif}
    return x.enregistrer_plan(
        journal, plan_id, recu, args["hypothese"], args["metrique_primaire"], debut, fin, "agent", maintenant
    )


DONNEES = {"test": {"k": 120, "n": 1000}, "temoin": {"k": 90, "n": 1000}}
PERIODE = {"debut": "2026-12-07", "fin": "2027-02-28"}


def test_effet_lu_seulement_avec_un_plan_enregistre_avant_le_debut_et_la_bonne_periode():
    journal: list = []
    ack = _plan(journal)
    assert ack["accepte"] and ack["tardif"] is False and ack["deja_enregistre"] is False
    r = x.analyser_resultat(journal, DONNEES, "0.95", "plan-a", PERIODE)
    assert r["accepte"] and r["statut"] == "preenregistre" and r["raisons"] == []
    assert "design préenregistré" in r["lecture"] and "associée au groupe test" in r["lecture"]
    assert r["plan"]["empreinte_recu"] == _marche_arret()["empreinte"]


def test_sans_plan_le_resultat_est_exploratoire_aucune_causalite():
    r = x.analyser_resultat([], DONNEES)
    assert r["statut"] == "exploratoire" and r["raisons"] == ["aucun design préenregistré : aucune causalité"]
    assert "aucun design préenregistré : aucune causalité" in r["lecture"] and r["plan"] is None


def test_plan_enregistre_le_jour_du_debut_ou_apres_est_tardif_donc_exploratoire():
    journal: list = []
    jour = datetime(2026, 12, 7, 0, 0, tzinfo=UTC)
    ack = _plan(journal, maintenant=jour)
    assert ack["tardif"] is True and "ne comptera pas" in ack["avertissement"]
    r = x.analyser_resultat(journal, DONNEES, "0.95", "plan-a", PERIODE)
    assert r["statut"] == "exploratoire" and any("après le début" in m for m in r["raisons"])
    veille = datetime(2026, 12, 6, 23, 59, tzinfo=UTC)
    autre: list = []
    assert _plan(autre, maintenant=veille)["tardif"] is False
    assert x.analyser_resultat(autre, DONNEES, "0.95", "plan-a", PERIODE)["statut"] == "preenregistre"


@pytest.mark.parametrize(
    "periode",
    [
        None,
        {"debut": "2026-12-14", "fin": "2027-02-28"},
        {"debut": "2026-12-07", "fin": "2027-03-07"},
        {"debut": "2026-12-07"},
        "x",
    ],
)
def test_periode_des_donnees_differente_du_plan_est_exploratoire(periode):
    journal: list = []
    _plan(journal)
    r = x.analyser_resultat(journal, DONNEES, "0.95", "plan-a", periode)
    assert r["statut"] == "exploratoire" and "la période des données n'est pas celle du plan" in r["raisons"]


def test_plan_inconnu_est_un_refus_pas_un_exploratoire_silencieux():
    r = x.analyser_resultat([], DONNEES, "0.95", "plan-fantome", PERIODE)
    assert r["accepte"] is False and r["refus"][0]["code"] == "REJ-MESURE-PLAN-INCONNU"
    r2 = x.analyser_resultat([], DONNEES, "0.95", 123, PERIODE)
    assert r2["refus"][0]["code"] == "REJ-MESURE-PLAN-INCONNU"


def test_idempotence_et_plan_existant_different():
    journal: list = []
    _plan(journal)
    n = len(journal)
    ack = _plan(journal, maintenant=MAINTENANT + timedelta(days=1))
    assert ack["deja_enregistre"] is True and ack["enregistre_le"] == "2026-11-01T12:00:00Z" and len(journal) == n
    autre = _plan(journal, hypothese="Une autre hypothèse, plus ambitieuse que la première annoncée.")
    assert autre["accepte"] is False and autre["refus"][0]["code"] == "REJ-MESURE-PLAN-EXISTANT"
    autre_recu = _plan(journal, recu=_marche_arret(delta="0.6"))
    assert autre_recu["refus"][0]["code"] == "REJ-MESURE-PLAN-EXISTANT" and len(journal) == n


def test_un_plan_irrealisable_ou_insuffisant_n_est_pas_preenregistrable():
    journal: list = []
    r = _plan(journal, recu=_marche_arret(delta="0.05"))
    assert r["refus"][0]["code"] == "REJ-MESURE-PLAN-INVALIDE" and "irréalisable" in r["refus"][0]["detail"]
    insuffisant = _produire("plan_test_geographique", {"regions": _regions(6), "effet_relatif": "0.1"}, GEO)
    assert _plan(journal, recu=insuffisant)["refus"][0]["code"] == "REJ-MESURE-PLAN-INVALIDE"
    assert journal == []


def test_plan_refuse_recu_retouche_moteur_d_analyse_et_champs_invalides():
    journal: list = []
    retouche = copy.deepcopy(_marche_arret())
    retouche["resultat"]["semaines_par_bras"] = 1
    assert _plan(journal, recu=retouche)["refus"][0]["code"] == "REJ-MESURE-RECU-INVALIDE"
    analyse = _produire(
        "analyse_resultat_test", {"test": {"k": 1, "n": 5}, "temoin": {"k": 1, "n": 5}}, {"niveau": "0.95"}
    )
    assert _plan(journal, recu=analyse)["refus"][0]["code"] == "REJ-MESURE-PLAN-INVALIDE"
    puissance = _produire(
        "puissance_deux_proportions", {"n_par_groupe": 500, "p1": "0.1", "p2": "0.14"}, {"alpha": "0.05"}
    )
    assert _plan(journal, recu=puissance)["refus"][0]["code"] == "REJ-MESURE-PLAN-INVALIDE"
    for modif, code in [
        ({"hypothese": "court"}, "REJ-MESURE-PLAN-INVALIDE"),
        ({"hypothese": "x" * 301}, "REJ-MESURE-PLAN-INVALIDE"),
        ({"hypothese": "ligne\x00 avec contrôle assez longue"}, "REJ-MESURE-PLAN-INVALIDE"),
        ({"metrique_primaire": "chiffre_d_affaires"}, "REJ-MESURE-PLAN-INVALIDE"),
    ]:
        assert _plan(journal, **modif)["refus"][0]["code"] == code
    assert _plan(journal, plan_id="a b")["refus"][0]["code"] == "REJ-MESURE-PLAN-INVALIDE"
    assert _plan(journal, debut="2027-03-01", fin="2027-02-01")["refus"][0]["code"] == "REJ-MESURE-PERIODE-INVALIDE"
    assert _plan(journal, debut="2026-12-07", fin="2028-12-07")["refus"][0]["code"] == "REJ-MESURE-PERIODE-INVALIDE"
    assert _plan(journal, debut="pas une date")["refus"][0]["code"] == "REJ-MESURE-PERIODE-INVALIDE"
    assert journal == []


def test_plan_chaine_alteree_detectee_a_l_enregistrement_et_a_l_analyse():
    journal: list = []
    _plan(journal)
    _plan(journal, plan_id="plan-b")
    falsifie = copy.deepcopy(journal)
    falsifie[0]["debut"] = "2026-01-01"
    assert _plan(falsifie, plan_id="plan-c")["refus"][0]["code"] == "REJ-MESURE-JOURNAL-ALTERE"
    assert (
        x.analyser_resultat(falsifie, DONNEES, "0.95", "plan-a", PERIODE)["refus"][0]["code"]
        == "REJ-MESURE-JOURNAL-ALTERE"
    )
    assert journal_chaine.integre(journal)


def test_echantillon_inferieur_au_plan_est_signale():
    journal: list = []
    recu = _produire(
        "taille_echantillon_deux_proportions", {"p1": "0.10", "effet": {"mode": "absolu", "valeur": "0.02"}}, TAILLE
    )
    _plan(journal, recu=recu)
    petit = x.analyser_resultat(
        journal, {"test": {"k": 12, "n": 100}, "temoin": {"k": 9, "n": 100}}, "0.95", "plan-a", PERIODE
    )
    assert petit["statut"] == "preenregistre" and petit["echantillon_conforme_au_plan"] is False
    assert "sous-dimensionné" in petit["lecture"]
    grand = x.analyser_resultat(
        journal, {"test": {"k": 480, "n": 3841}, "temoin": {"k": 400, "n": 3841}}, "0.95", "plan-a", PERIODE
    )
    assert grand["echantillon_conforme_au_plan"] is True and "sous-dimensionné" not in grand["lecture"]
    assert x.analyser_resultat(journal, DONNEES, "0.95", None)["echantillon_conforme_au_plan"] is None


def test_aucune_sortie_n_affirme_une_cause():
    journal: list = []
    _plan(journal)
    sorties = [
        x.analyser_resultat(journal, DONNEES, "0.95", "plan-a", PERIODE),
        x.analyser_resultat(journal, DONNEES),
        x.analyser_resultat(
            journal, {"test": {"k": 5, "n": 500}, "temoin": {"k": 4, "n": 500}}, "0.95", "plan-a", PERIODE
        ),
        *_tous_les_recus(),
    ]
    for sortie in sorties:
        brut = repr(sortie).lower()
        for interdit in ("causé", "cause par", "grâce à", "grace a", "à cause", "provoqué"):
            assert interdit not in brut, interdit


def test_analyse_refuse_les_entrees_et_le_niveau():
    assert (
        x.analyser_resultat([], {"test": {"k": 1, "n": 0}, "temoin": {"k": 1, "n": 5}})["refus"][0]["code"]
        == "REJ-MESURE-ECHANTILLON-INVALIDE"
    )
    assert x.analyser_resultat([], DONNEES, "0.5")["refus"][0]["code"] == "REJ-MESURE-ARGUMENT-INVALIDE"
