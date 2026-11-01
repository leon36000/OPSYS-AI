"""Règles de plafond et d'arrêt PRÉPARÉES : jamais exécutées, jamais un doute présenté comme « tout va bien ».

Chaque seuil est testé des DEUX côtés ; les valeurs attendues sont calculées à la main dans le test.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from m7_marketing.medias_payants import regles as r

BUDGET = {"montant_total_cents": 20000, "plafond_quotidien_cents": 2000, "duree_jours": 10, "date_debut": "2026-11-10"}
D0 = date(2026, 11, 10)


def jour(i: int, cout: int, conv=None) -> r.Jour:
    return r.Jour(D0 + timedelta(days=i), cout, None if conv is None else Decimal(str(conv)))


def serie(couts, conv=None) -> list[r.Jour]:
    return [jour(i, c, conv) for i, c in enumerate(couts)]


def regle_quotidien(seuil=2000, tol=20):
    return {"regle_id": "plafond-quotidien", "type": "plafond_quotidien", "seuil_cents": seuil, "tolerance_pct": tol}


def unique(constats):
    (c,) = constats
    return c


# ======================================================================================================================
# normaliser_regles
# ======================================================================================================================
def test_les_deux_plafonds_sont_toujours_presents_et_deduits_du_budget():
    regles, refus = r.normaliser_regles(None, BUDGET)
    assert refus == []
    assert [x["type"] for x in regles] == ["plafond_quotidien", "plafond_total"]
    quotidien, total = regles
    assert quotidien["seuil_cents"] == 2000 and quotidien["tolerance_pct"] == 20
    assert total["seuil_cents"] == 20000
    for x in regles:
        assert x["obligatoire"] is True and x["action"] == "proposer_pause" and x["executee_par_opsys"] is False
        assert x["statut"] == "PREPAREE_NON_EXECUTEE"


def test_une_liste_vide_donne_les_memes_deux_plafonds():
    assert r.normaliser_regles([], BUDGET)[0] == r.regles_obligatoires(BUDGET)


def test_les_plafonds_ne_se_declarent_pas_et_ne_se_retirent_pas():
    for type_ in ("plafond_quotidien", "plafond_total"):
        regles, refus = r.normaliser_regles([{"type": type_, "seuil_cents": 99999}], BUDGET)
        assert regles is None
        assert refus[0]["code"] == "REJ-PLAN-MEDIA-REGLE" and "déduit du budget" in refus[0]["detail"]


def test_regles_supplementaires_valides_dans_leur_forme_canonique():
    brutes = [
        {"type": "cpa_max", "seuil_cents": 5000, "conversions_min": 5},
        {"type": "depense_sans_conversion", "seuil_cents": 3000, "fenetre_jours": 3, "action": "proposer_pause"},
        {"type": "saut_depense", "ratio_pct": 300, "minimum_cents": 2500},
    ]
    regles, refus = r.normaliser_regles(brutes, BUDGET)
    assert refus == []
    assert [x["regle_id"] for x in regles] == [
        "plafond-quotidien",
        "plafond-total",
        "cpa-max",
        "depense-sans-conversion",
        "saut-depense",
    ]
    for x in regles[2:]:
        assert x["obligatoire"] is False and x["action"] == "proposer_pause" and x["executee_par_opsys"] is False
    assert regles[2]["seuil_cents"] == 5000 and regles[2]["conversions_min"] == 5


@pytest.mark.parametrize(
    "brutes",
    [
        [{"type": "pause_auto"}],  # type inconnu
        [{"type": "cpa_max", "seuil_cents": 5000, "conversions_min": 5, "extra": 1}],  # champ inconnu
        [{"type": "cpa_max", "seuil_cents": 5000}],  # champ manquant
        [{"type": "cpa_max", "seuil_cents": 5000, "conversions_min": 5, "action": "mettre_en_pause"}],
        [{"type": "cpa_max", "seuil_cents": 5000, "conversions_min": 5, "action": "supprimer_campagne"}],
        [{"type": "cpa_max", "seuil_cents": 0, "conversions_min": 5}],  # sous la borne
        [{"type": "cpa_max", "seuil_cents": 100_000_001, "conversions_min": 5}],  # au-dessus de la borne
        [{"type": "cpa_max", "seuil_cents": 5000, "conversions_min": 1001}],
        [{"type": "cpa_max", "seuil_cents": 50.0, "conversions_min": 5}],  # flottant
        [{"type": "cpa_max", "seuil_cents": True, "conversions_min": 5}],  # booléen
        [{"type": "cpa_max", "seuil_cents": "5000", "conversions_min": 5}],  # texte
        [{"type": "depense_sans_conversion", "seuil_cents": 3000, "fenetre_jours": 1}],
        [{"type": "depense_sans_conversion", "seuil_cents": 3000, "fenetre_jours": 31}],
        [{"type": "saut_depense", "ratio_pct": 149, "minimum_cents": 0}],
        [{"type": "saut_depense", "ratio_pct": 2001, "minimum_cents": 0}],
        [{"type": "saut_depense", "ratio_pct": 300, "minimum_cents": -1}],
        [
            {"type": "cpa_max", "seuil_cents": 5000, "conversions_min": 5},
            {"type": "cpa_max", "seuil_cents": 6000, "conversions_min": 5},
        ],  # doublon
        ["cpa_max"],  # pas un objet
        [None],
        "cpa_max",  # pas une liste
        {"type": "cpa_max"},
    ],
)
def test_une_regle_invalide_est_refusee_et_rien_n_est_corrige(brutes):
    regles, refus = r.normaliser_regles(brutes, BUDGET)
    assert regles is None
    assert refus and all(x["code"] == "REJ-PLAN-MEDIA-REGLE" for x in refus)


def test_plus_de_six_regles_supplementaires_sont_refusees():
    brutes = [{"type": "saut_depense", "ratio_pct": 300, "minimum_cents": 0}] * 7
    regles, refus = r.normaliser_regles(brutes, BUDGET)
    assert regles is None and refus[0]["chemin"] == "$.regles"


def test_les_bornes_incluses_sont_acceptees():
    for brutes in (
        [{"type": "cpa_max", "seuil_cents": 1, "conversions_min": 1}],
        [{"type": "cpa_max", "seuil_cents": 100_000_000, "conversions_min": 1000}],
        [{"type": "depense_sans_conversion", "seuil_cents": 1, "fenetre_jours": 2}],
        [{"type": "depense_sans_conversion", "seuil_cents": 1, "fenetre_jours": 30}],
        [{"type": "saut_depense", "ratio_pct": 150, "minimum_cents": 0}],
        [{"type": "saut_depense", "ratio_pct": 2000, "minimum_cents": 100_000_000}],
    ):
        assert r.normaliser_regles(brutes, BUDGET)[1] == []


def test_la_seule_action_possible_est_proposer_pause():
    assert r.ACTION == "proposer_pause"
    assert set(r.TYPES) == {"plafond_quotidien", "plafond_total", "cpa_max", "depense_sans_conversion", "saut_depense"}


# ======================================================================================================================
# trous
# ======================================================================================================================
def test_trous_rend_les_jours_sans_fait_bornes_incluses():
    s = [jour(0, 100), jour(2, 100), jour(4, 100)]
    assert r.trous(s, D0, D0 + timedelta(days=4)) == [D0 + timedelta(days=1), D0 + timedelta(days=3)]
    assert r.trous([], D0, D0 + timedelta(days=2)) == [D0, D0 + timedelta(days=1), D0 + timedelta(days=2)]
    assert r.trous(s, D0 + timedelta(days=2), D0 + timedelta(days=2)) == []
    assert r.trous(s, D0 + timedelta(days=5), D0 + timedelta(days=6)) == [
        D0 + timedelta(days=5),
        D0 + timedelta(days=6),
    ]


# ======================================================================================================================
# plafond quotidien : seuil 2000 + 20 % = 2400 cents
# ======================================================================================================================
def test_plafond_quotidien_pile_au_seuil_avec_tolerance_n_est_pas_depasse():
    c = unique(r.evaluer([regle_quotidien()], serie([2400, 1000]), debut=D0, fin=D0 + timedelta(days=1)))
    assert c["declenchee"] is False and c["valeur"] == "24" and c["seuil"] == "24"
    assert c["jours"] == [] and c["action_preparee"] is None


def test_plafond_quotidien_un_cent_de_plus_declenche_et_nomme_le_jour():
    c = unique(r.evaluer([regle_quotidien()], serie([1000, 2401, 1000]), debut=D0, fin=D0 + timedelta(days=2)))
    assert c["declenchee"] is True and c["valeur"] == "24.01" and c["seuil"] == "24"
    assert c["jours"] == ["2026-11-11"] and c["action_preparee"] == "proposer_pause"
    assert c["code_dep"] == "DEP-01" and c["unite"] == "CAD"


def test_plafond_quotidien_le_seuil_est_arrondi_vers_le_bas_en_cents():
    regle = regle_quotidien(seuil=1999)  # 1999 * 120 // 100 = 2398
    intervalle = dict(debut=D0, fin=D0)
    assert unique(r.evaluer([regle], serie([2398]), **intervalle))["declenchee"] is False
    assert unique(r.evaluer([regle], serie([2399]), **intervalle))["declenchee"] is True
    assert unique(r.evaluer([regle], serie([2398]), **intervalle))["seuil"] == "23.98"


def test_plafond_quotidien_sans_tolerance():
    regle = regle_quotidien(tol=0)
    assert unique(r.evaluer([regle], serie([2000]), debut=D0, fin=D0))["declenchee"] is False
    assert unique(r.evaluer([regle], serie([2001]), debut=D0, fin=D0))["declenchee"] is True


def test_plafond_quotidien_sans_aucun_jour_n_est_pas_evaluable():
    c = unique(r.evaluer([regle_quotidien()], [], debut=D0, fin=D0 + timedelta(days=2)))
    assert c["declenchee"] is None and c["valeur"] is None and c["action_preparee"] is None


def test_plafond_quotidien_jours_manquants_disent_que_la_depense_est_inconnue():
    c = unique(r.evaluer([regle_quotidien()], [jour(0, 100)], debut=D0, fin=D0 + timedelta(days=2)))
    assert c["declenchee"] is False and "2 jour(s) sans donnée" in c["raison"]


def test_plafond_quotidien_ignore_les_jours_hors_de_la_fenetre():
    s = [jour(-1, 99999), jour(0, 100), jour(5, 99999)]
    c = unique(r.evaluer([regle_quotidien()], s, debut=D0, fin=D0 + timedelta(days=1)))
    assert c["declenchee"] is False and c["valeur"] == "1"


# ======================================================================================================================
# plafond total : seuil 20000 cents
# ======================================================================================================================
REGLE_TOTAL = {"regle_id": "plafond-total", "type": "plafond_total", "seuil_cents": 20000}


def test_plafond_total_pile_au_seuil_pas_depasse_un_cent_de_plus_declenche():
    fin = D0 + timedelta(days=9)
    ok = unique(r.evaluer([REGLE_TOTAL], serie([2000] * 10), debut=D0, fin=fin))
    assert ok["declenchee"] is False and ok["valeur"] == "200" and ok["seuil"] == "200"
    depasse = unique(r.evaluer([REGLE_TOTAL], serie([2000] * 9 + [2001]), debut=D0, fin=fin))
    assert depasse["declenchee"] is True and depasse["valeur"] == "200.01" and depasse["code_dep"] == "DEP-07"
    assert depasse["action_preparee"] == "proposer_pause"


def test_plafond_total_avec_trous_et_sous_le_seuil_n_exclut_pas_un_depassement():
    s = [jour(0, 2000), jour(1, 2000), jour(3, 2000)]  # le jour 2 manque
    c = unique(r.evaluer([REGLE_TOTAL], s, debut=D0, fin=D0 + timedelta(days=3)))
    assert c["declenchee"] is None and c["valeur"] == "60" and c["jours"] == ["2026-11-12"]
    assert "minimum" in c["raison"] and c["action_preparee"] is None


def test_plafond_total_deja_depasse_malgre_des_trous_est_declenche():
    s = [jour(0, 20001)]
    c = unique(r.evaluer([REGLE_TOTAL], s, debut=D0, fin=D0 + timedelta(days=5)))
    assert c["declenchee"] is True and c["valeur"] == "200.01"


# ======================================================================================================================
# cpa_max : 50 $ ; au moins 5 conversions
# ======================================================================================================================
REGLE_CPA = {"regle_id": "cpa-max", "type": "cpa_max", "seuil_cents": 5000, "conversions_min": 5}


def test_cpa_pile_au_maximum_n_est_pas_depasse_un_cent_de_plus_declenche():
    fin = D0 + timedelta(days=4)
    # 5 jours x 10 $ = 50 $ pour 5 conversions => 10,00 $ : bien sous le maximum de 50 $
    bas = unique(r.evaluer([REGLE_CPA], serie([1000] * 5, conv=1), debut=D0, fin=fin))
    assert bas["declenchee"] is False and bas["valeur"] == "10.00"
    # 5 jours x 50 $ = 250 $ pour 5 conversions => exactement 50,00 $ : pas au-dessus
    pile = unique(r.evaluer([REGLE_CPA], serie([5000] * 5, conv=1), debut=D0, fin=fin))
    assert pile["declenchee"] is False and pile["valeur"] == "50.00" and pile["seuil"] == "50"
    # 5 x 50,01 $ = 250,05 $ pour 5 conversions => 50,01 $ : au-dessus
    haut = unique(r.evaluer([REGLE_CPA], serie([5001] * 5, conv=1), debut=D0, fin=fin))
    assert haut["declenchee"] is True and haut["valeur"] == "50.01" and haut["code_dep"] == "DEP-06"


def test_cpa_moins_de_conversions_que_le_minimum_n_est_pas_evaluable():
    c = unique(r.evaluer([REGLE_CPA], serie([9000] * 4, conv=1), debut=D0, fin=D0 + timedelta(days=3)))
    assert c["declenchee"] is None and c["valeur"] == "4" and c["unite"] == "conversions"
    assert "échantillon trop mince" in c["raison"]


def test_cpa_conversions_fractionnaires_comptent_exactement():
    fin = D0 + timedelta(days=1)
    c = unique(r.evaluer([REGLE_CPA], [jour(0, 15000, "2.5"), jour(1, 15000, "2.5")], debut=D0, fin=fin))
    assert c["declenchee"] is True and c["valeur"] == "60.00"  # 300 $ / 5 conversions


def test_cpa_conversion_inconnue_n_est_pas_un_zero_et_rend_non_evaluable():
    s = [jour(0, 5000, 3), jour(1, 5000, None), jour(2, 5000, 3)]
    c = unique(r.evaluer([REGLE_CPA], s, debut=D0, fin=D0 + timedelta(days=2)))
    assert c["declenchee"] is None and "inconnues" in c["raison"]


def test_cpa_jour_manquant_rend_non_evaluable():
    s = [jour(0, 5000, 3), jour(2, 5000, 3)]
    c = unique(r.evaluer([REGLE_CPA], s, debut=D0, fin=D0 + timedelta(days=2)))
    assert c["declenchee"] is None and c["jours"] == ["2026-11-11"]


# ======================================================================================================================
# dépense sans conversion : fenêtre 3 jours, 30 $
# ======================================================================================================================
REGLE_SANS = {
    "regle_id": "depense-sans-conversion",
    "type": "depense_sans_conversion",
    "seuil_cents": 3000,
    "fenetre_jours": 3,
}


def test_depense_sans_conversion_pile_au_seuil_declenche_un_cent_en_dessous_non():
    fin = D0 + timedelta(days=3)
    s = [jour(0, 9999, 5), jour(1, 1000, 0), jour(2, 1000, 0), jour(3, 1000, 0)]
    c = unique(r.evaluer([REGLE_SANS], s, debut=D0, fin=fin))
    assert c["declenchee"] is True and c["valeur"] == "30" and c["jours"] == ["2026-11-11", "2026-11-12", "2026-11-13"]
    assert c["code_dep"] == "DEP-02"
    s[3] = jour(3, 999, 0)
    c = unique(r.evaluer([REGLE_SANS], s, debut=D0, fin=fin))
    assert c["declenchee"] is False and c["valeur"] == "29.99"


def test_depense_sans_conversion_une_conversion_dans_la_fenetre_suffit_a_ne_pas_declencher():
    s = [jour(0, 1000, 0), jour(1, 1000, "0.5"), jour(2, 1000, 0)]
    c = unique(r.evaluer([REGLE_SANS], s, debut=D0, fin=D0 + timedelta(days=2)))
    assert c["declenchee"] is False


def test_depense_sans_conversion_conversion_inconnue_ou_fenetre_incomplete_non_evaluable():
    s = [jour(0, 1000, 0), jour(1, 1000, None), jour(2, 1000, 0)]
    assert unique(r.evaluer([REGLE_SANS], s, debut=D0, fin=D0 + timedelta(days=2)))["declenchee"] is None
    s = [jour(1, 1000, 0), jour(2, 1000, 0)]  # seulement 2 jours lus sur 3
    c = unique(r.evaluer([REGLE_SANS], s, debut=D0, fin=D0 + timedelta(days=2)))
    assert c["declenchee"] is None and "non évaluable" in c["raison"]


# ======================================================================================================================
# saut de dépense : 300 %, minimum 25 $, médiane des 7 jours précédents
# ======================================================================================================================
REGLE_SAUT = {"regle_id": "saut-depense", "type": "saut_depense", "ratio_pct": 300, "minimum_cents": 2500}


def _avec_saut(x, base=(1000,) * 7):
    return serie([*base, x]), D0 + timedelta(days=len(base))


@pytest.mark.parametrize(
    "x, attendu",
    [
        (3000, False),  # 3000 * 100 = 300000, pas strictement supérieur à 1000 * 300
        (3001, False),  # ratio dépassé mais écart de 2001 < minimum 2500
        (3499, False),  # écart 2499 < 2500
        (3500, True),  # 350000 > 300000 et écart 2500 >= 2500
        (9000, True),
    ],
)
def test_saut_aux_deux_cotes_des_seuils(x, attendu):
    s, fin = _avec_saut(x)
    c = unique(r.evaluer([REGLE_SAUT], s, debut=D0, fin=fin))
    assert c["declenchee"] is attendu
    if attendu:
        assert c["valeur"] == format(Decimal(x) / 100, "f") and c["seuil"] == "30" and c["code_dep"] == "DEP-03"
        assert c["jours"] == [fin.isoformat()]


def test_saut_sans_minimum_le_ratio_seul_decide_strictement():
    regle = {**REGLE_SAUT, "minimum_cents": 0}
    s, fin = _avec_saut(3000)  # exactement 300 % de la médiane : pas un saut
    assert unique(r.evaluer([regle], s, debut=D0, fin=fin))["declenchee"] is False
    s, fin = _avec_saut(3001)
    assert unique(r.evaluer([regle], s, debut=D0, fin=fin))["declenchee"] is True


def test_saut_utilise_la_mediane_et_pas_la_moyenne():
    # précédents : 500,500,500,1000,1000,1000,9000 => médiane 1000 (moyenne 1928)
    s, fin = _avec_saut(3500, base=(500, 500, 500, 1000, 1000, 1000, 9000))
    c = unique(r.evaluer([REGLE_SAUT], s, debut=D0, fin=fin))
    assert c["declenchee"] is True  # 3500 > 3 x 1000 ; avec la moyenne (1928 x 3 = 5784) il ne l'aurait pas été
    assert "médiane" in c["raison"] and "(1000 cents)" in c["raison"]


def test_saut_moins_de_huit_jours_n_est_pas_evaluable_et_n_invente_pas_une_mediane():
    s = serie([1000] * 7)
    c = unique(r.evaluer([REGLE_SAUT], s, debut=D0, fin=D0 + timedelta(days=6)))
    assert c["declenchee"] is None and c["valeur"] is None


def test_saut_huit_jours_calmes_rend_faux_et_pas_inconnu():
    s = serie([1000] * 8)
    c = unique(r.evaluer([REGLE_SAUT], s, debut=D0, fin=D0 + timedelta(days=7)))
    assert c["declenchee"] is False


def test_saut_un_trou_dans_les_sept_jours_precedents_empeche_le_jugement_et_le_dit():
    # jours 0,1,2,4,5,6 calmes (il manque le 3), pic au jour 7, jour 8 calme
    s = [jour(i, 1000) for i in (0, 1, 2, 4, 5, 6)] + [jour(7, 9000), jour(8, 1000)]
    c = unique(r.evaluer([REGLE_SAUT], s, debut=D0, fin=D0 + timedelta(days=8)))
    # le jour 7 n'a que 6 jours précédents dans sa fenêtre : la médiane serait incomplète, rien n'est déclenché...
    assert c["declenchee"] is False and c["jours"] == []
    # ... mais le constat ne prétend pas que tout va bien : il dit que des jours manquent
    assert "1 jour(s) sans donnée" in c["raison"] and "non jugés" in c["raison"]


# ======================================================================================================================
# invariants
# ======================================================================================================================
SCENARIOS = [
    serie([1000] * 12),
    serie([1000] * 9 + [9000, 5000, 100]),
    serie([2500, 0, 0, 30000, 100, 100, 100, 100], conv=0),
    serie([5000] * 6, conv=1),
    [jour(0, 100), jour(5, 100000)],
    [],
]


@pytest.mark.parametrize("s", SCENARIOS)
def test_aucune_regle_ne_s_execute_jamais_et_la_seule_action_est_une_proposition(s):
    toutes = [*r.regles_obligatoires(BUDGET), REGLE_CPA, REGLE_SANS, REGLE_SAUT]
    for c in r.evaluer(toutes, s, debut=D0, fin=D0 + timedelta(days=11)):
        assert c["executee"] is False
        assert c["action_preparee"] in (None, "proposer_pause")
        assert (c["action_preparee"] == "proposer_pause") is (c["declenchee"] is True)
        assert c["declenchee"] in (True, False, None)
        assert c["code_dep"] == r.CODE_DEP[c["type"]]


def test_la_fenetre_d_evaluation_exclut_les_jours_hors_periode():
    s = serie([99999] * 3)
    c = unique(r.evaluer([REGLE_TOTAL], s, debut=D0 + timedelta(days=10), fin=D0 + timedelta(days=10)))
    assert (
        c["declenchee"] is None
    )  # aucun jour dans la fenêtre : le total lu est 0 mais un trou, jamais « sous le seuil »
