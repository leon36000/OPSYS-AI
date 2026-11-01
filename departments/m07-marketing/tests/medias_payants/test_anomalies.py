"""Anomalies de dépense : sept règles transparentes, identifiants déterministes, jamais une action exécutée.

Plan de référence : 20 $ par jour (plafond quotidien, tolérance 20 % => 24 $), 200 $ au total, dix jours à compter du
10 novembre
2026 (jusqu'au 19 inclus). Les valeurs attendues sont calculées à la main.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from decimal import Decimal

import pytest
from m7_marketing.medias_payants import anomalies as a
from m7_marketing.medias_payants import regles as r

BUDGET = {"montant_total_cents": 20000, "plafond_quotidien_cents": 2000, "duree_jours": 10, "date_debut": "2026-11-10"}
D0 = date(2026, 11, 10)
D9 = date(2026, 11, 19)


def plan(*supplementaires):
    return {"budget": BUDGET, "regles": [*r.regles_obligatoires(BUDGET), *supplementaires]}


def jour(i, cout, conv=None):
    return r.Jour(D0 + timedelta(days=i), cout, None if conv is None else Decimal(str(conv)))


def normale(conv=2):
    return [jour(i, 2000, conv) for i in range(10)]


def detecter(serie, p=None, debut=D0, fin=D9, ref="meta-111", canal="meta", fictif=False):
    return a.detecter(canal=canal, campagne_ref=ref, serie=serie, debut=debut, fin=fin, plan=p, fictif=fictif)


def codes(resultat):
    return [x["regle"] for x in resultat["anomalies"]]


def par_regle(resultat, code):
    (x,) = [x for x in resultat["anomalies"] if x["regle"] == code]
    return x


# ======================================================================================================================
def test_une_serie_normale_ne_produit_aucune_anomalie_ni_regle_non_evaluable():
    cpa = {"type": "cpa_max", "regle_id": "cpa-max", "seuil_cents": 5000, "conversions_min": 5}
    res = detecter(normale(), plan(cpa))
    assert res["anomalies"] == [] and res["non_evaluables"] == []
    assert res["jours_lus"] == 10 and res["jours_manquants"] == []
    assert all(c["declenchee"] is False for c in res["constats"])
    assert res["periode"] == {"debut": "2026-11-10", "fin": "2026-11-19"}


def test_dep01_attention_puis_critique_a_la_frontiere_du_double_du_seuil():
    # seuil quotidien avec tolérance : 24,00 $ ; « critique » seulement au-delà de 48,00 $
    for cout, severite in ((2401, "attention"), (4800, "attention"), (4801, "critique")):
        s = normale()
        s[3] = jour(3, cout, 2)
        x = par_regle(detecter(s, plan()), "DEP-01")
        assert x["severite"] == severite, cout
        assert x["valeur"] == format(Decimal(cout) / 100, "f") and x["seuil"] == "24"
        assert x["jour_debut"] == x["jour_fin"] == "2026-11-13" and x["unite"] == "CAD"


def test_dep01_pile_au_seuil_avec_tolerance_ne_declenche_pas():
    s = normale()
    s[3] = jour(3, 2400, 2)
    assert "DEP-01" not in codes(detecter(s, plan()))


def test_dep07_est_critique_des_que_le_total_lu_depasse_le_budget():
    s = normale()
    s[9] = jour(9, 2001, 2)  # 9 x 20 $ + 20,01 $ = 200,01 $
    x = par_regle(detecter(s, plan()), "DEP-07")
    assert x["severite"] == "critique" and x["valeur"] == "200.01" and x["seuil"] == "200"
    assert "DEP-01" not in codes(detecter(s, plan()))  # 20,01 $ reste sous 24 $


def test_dep07_pile_au_budget_total_ne_declenche_pas():
    assert "DEP-07" not in codes(detecter(normale(), plan()))


def test_dep04_depense_hors_periode_du_plan_et_zero_hors_periode_ignore():
    s = [jour(-2, 0, 0), jour(-1, 500, 0), *normale(), jour(10, 700, 0)]
    res = detecter(s, plan(), debut=D0 - timedelta(days=2), fin=D0 + timedelta(days=10))
    x = par_regle(res, "DEP-04")
    assert x["severite"] == "attention" and x["unite"] == "CAD" and x["valeur"] == "12"
    assert x["jour_debut"] == "2026-11-09" and x["jour_fin"] == "2026-11-20"
    assert "5 $" not in x["raison"] and "2026-11-10 au 2026-11-19" in x["raison"]
    # un jour à zéro dollar hors période n'est pas de la dépense
    res = detecter([jour(-1, 0, 0), *normale()], plan(), debut=D0 - timedelta(days=1), fin=D9)
    assert "DEP-04" not in codes(res)


def test_dep05_trous_sont_une_info_et_la_depense_de_ces_jours_est_inconnue():
    s = [jour(i, 2000, 2) for i in (0, 1, 2, 3, 4, 7, 8, 9)]  # manquent les jours 5 et 6
    x = par_regle(detecter(s, plan()), "DEP-05")
    assert x["severite"] == "info" and x["valeur"] == "2" and x["unite"] == "jours" and x["seuil"] is None
    assert x["jour_debut"] == "2026-11-15" and x["jour_fin"] == "2026-11-16"
    assert "INCONNUE" in x["raison"]


def test_dep06_cpa_au_dessus_du_maximum_avec_assez_de_conversions():
    cpa = {"type": "cpa_max", "regle_id": "cpa-max", "seuil_cents": 1000, "conversions_min": 5}
    # 200 $ pour 20 conversions = 10,00 $ : pile au maximum, pas au-dessus
    assert "DEP-06" not in codes(detecter(normale(), plan(cpa)))
    # 200 $ pour 19,9 conversions... : 10 jours x 1,99 conversions = 19,9 => 10,05 $ : au-dessus
    s = [jour(i, 2000, "1.99") for i in range(10)]
    x = par_regle(detecter(s, plan(cpa)), "DEP-06")
    assert x["severite"] == "attention" and x["valeur"] == "10.05" and x["seuil"] == "10"


def test_dep06_echantillon_trop_mince_est_non_evaluable_pas_normal():
    cpa = {"type": "cpa_max", "regle_id": "cpa-max", "seuil_cents": 1, "conversions_min": 50}
    res = detecter(normale(), plan(cpa))
    assert "DEP-06" not in codes(res)
    assert [n["regle"] for n in res["non_evaluables"]] == ["DEP-06"]
    assert "échantillon trop mince" in res["non_evaluables"][0]["raison"]


def test_dep02_depense_sans_aucune_conversion():
    sans = {
        "type": "depense_sans_conversion",
        "regle_id": "depense-sans-conversion",
        "seuil_cents": 6000,
        "fenetre_jours": 3,
    }
    s = [*normale()[:7], jour(7, 2000, 0), jour(8, 2000, 0), jour(9, 2000, 0)]
    x = par_regle(detecter(s, plan(sans)), "DEP-02")
    assert (
        x["valeur"] == "60" and x["seuil"] == "60" and x["jour_debut"] == "2026-11-17" and x["jour_fin"] == "2026-11-19"
    )
    s[9] = jour(9, 2000, "0.1")
    assert "DEP-02" not in codes(detecter(s, plan(sans)))


def test_dep03_saut_defini_dans_le_plan_ou_par_defaut():
    # par défaut : 300 % et 25 $ ; sept jours à 10 $ puis 35 $
    s = [jour(i, 1000, 1) for i in range(7)] + [jour(7, 3500, 1)]
    res = a.detecter(
        canal="meta", campagne_ref=None, serie=s, debut=D0, fin=D0 + timedelta(days=7), plan=None, fictif=False
    )
    x = par_regle(res, "DEP-03")
    assert x["valeur"] == "35" and x["seuil"] == "30" and x["jour_debut"] == "2026-11-17"
    s[7] = jour(7, 3499, 1)
    res = a.detecter(
        canal="meta", campagne_ref=None, serie=s, debut=D0, fin=D0 + timedelta(days=7), plan=None, fictif=False
    )
    assert "DEP-03" not in codes(res)


def test_le_plan_peut_definir_sa_propre_regle_de_saut_et_elle_remplace_celle_par_defaut():
    saut = {"type": "saut_depense", "regle_id": "saut-depense", "ratio_pct": 150, "minimum_cents": 0}
    s = [jour(i, 1000, 1) for i in range(7)] + [jour(7, 1501, 1)]
    res = detecter(s, plan(saut), fin=D0 + timedelta(days=7))
    assert par_regle(res, "DEP-03")["valeur"] == "15.01"
    assert len([c for c in res["constats"] if c["type"] == "saut_depense"]) == 1


def test_sans_plan_seuls_dep03_et_les_trous_sont_juges_et_le_reste_est_dit_non_evaluable():
    s = [jour(i, 99999, 0) for i in (0, 1, 2, 3, 4, 5, 6, 8)]  # 999,99 $ par jour : sans plan, aucun plafond connu
    res = a.detecter(
        canal="google_ads", campagne_ref=None, serie=s, debut=D0, fin=D0 + timedelta(days=8), plan=None, fictif=False
    )
    assert sorted(codes(res)) == ["DEP-05"]  # ni DEP-01, ni DEP-04, ni DEP-07 sans plan
    raisons = {n["regle_id"]: n["raison"] for n in res["non_evaluables"]}
    assert "plafonds" in raisons and "aucun plan" in raisons["plafonds"]
    assert [c["type"] for c in res["constats"]] == ["saut_depense"]


def test_les_identifiants_sont_deterministes_et_distincts_par_canal_campagne_regle_et_jours():
    s = normale()
    s[3] = jour(3, 3000, 2)
    res = detecter(s, plan())
    x = par_regle(res, "DEP-01")
    corps = "meta\x1fmeta-111\x1fDEP-01\x1f2026-11-13\x1f2026-11-13"
    assert x["anomalie_id"] == hashlib.sha256(corps.encode()).hexdigest()[:32] and len(x["anomalie_id"]) == 32
    assert a.identifiant("meta", "meta-111", "DEP-01", "2026-11-13", "2026-11-13") == x["anomalie_id"]
    variantes = {
        a.identifiant("meta", "meta-111", "DEP-01", "2026-11-13", "2026-11-13"),
        a.identifiant("google_ads", "meta-111", "DEP-01", "2026-11-13", "2026-11-13"),
        a.identifiant("meta", "meta-222", "DEP-01", "2026-11-13", "2026-11-13"),
        a.identifiant("meta", None, "DEP-01", "2026-11-13", "2026-11-13"),
        a.identifiant("meta", "meta-111", "DEP-02", "2026-11-13", "2026-11-13"),
        a.identifiant("meta", "meta-111", "DEP-01", "2026-11-14", "2026-11-14"),
        a.identifiant("meta", "meta-111", "DEP-01", "2026-11-13", "2026-11-14"),
    }
    assert len(variantes) == 7


def test_rejouer_la_meme_detection_donne_exactement_le_meme_resultat():
    s = normale()
    s[2] = jour(2, 5000, 0)
    s[8] = jour(8, 100, 2)
    assert detecter(s, plan()) == detecter(list(reversed(s)), plan())  # l'ordre d'entrée ne compte pas
    assert detecter(s, plan()) == detecter(s, plan())


def test_aucune_anomalie_ne_s_execute_et_la_seule_action_preparee_est_la_pause():
    s = [jour(0, 99999, 0), jour(1, 99999, 0), jour(4, 5, 0)]
    res = detecter(s, plan(), debut=D0 - timedelta(days=1))
    assert res["anomalies"]
    for x in res["anomalies"]:
        assert x["executee"] is False and x["action_preparee"] == "proposer_pause"
        assert x["severite"] in a.SEVERITES and x["fictif"] is False
    assert all(c["executee"] is False for c in res["constats"])


@pytest.mark.parametrize("fictif", [True, False])
def test_le_drapeau_fictif_est_porte_par_chaque_anomalie(fictif):
    s = normale()
    s[3] = jour(3, 5000, 2)
    assert all(x["fictif"] is fictif for x in detecter(s, plan(), fictif=fictif)["anomalies"])


def test_les_anomalies_sont_triees_par_regle_puis_par_jour():
    s = [jour(i, 2000, 2) for i in (0, 1, 2, 4, 5, 6, 7, 8, 9)]  # trou le jour 3 (DEP-05)
    s[0] = jour(0, 5000, 2)  # DEP-01 le jour 0
    res = detecter(s, plan())
    assert codes(res) == sorted(codes(res)) and codes(res)[0] == "DEP-01"
