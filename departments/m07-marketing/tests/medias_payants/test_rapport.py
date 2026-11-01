"""Rapport de performance honnête : couverture, intervalles de Wilson, suffisance, aucune comparaison classée,
aucune cause.

Les valeurs attendues sont calculées à la main ; l'intervalle de Wilson de 5 sur 20 est un résultat classique
([0,111862 ; 0,468701]), celui de 1 sur 5 aussi ([0,0362 ; 0,6245]).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from m7_marketing.medias_payants import rapport as rp
from m7_marketing.mesure import statistiques as st

D0 = date(2026, 10, 1)


def j(i, cout, impr=None, clics=None, conv=None):
    return rp.JourPerf(D0 + timedelta(days=i), cout, impr, clics, None if conv is None else Decimal(str(conv)))


def construire(campagnes, jours=1, **kw):
    return rp.construire(canal="meta", campagnes=campagnes, debut=D0, fin=D0 + timedelta(days=jours - 1), **kw)


def une(campagnes, jours=1, ref="meta-1"):
    return next(c for c in construire(campagnes, jours)["campagnes"] if c["campagne_ref"] == ref)


# ======================================================================================================================
def test_taux_de_clic_5_sur_20_avec_son_intervalle_de_wilson():
    c = une({"meta-1": [j(0, 1000, 20, 5, 1)]})
    assert c["taux_de_clic"] == {"valeur": "0.25", "intervalle": {"bas": "0.111862", "haut": "0.468701"}, "n": 20}
    bas, haut = st.wilson(5, 20)
    assert c["taux_de_clic"]["intervalle"] == {"bas": st.texte(bas), "haut": st.texte(haut)}


def test_taux_de_conversion_1_sur_5_et_cout_par_conversion_avec_intervalle():
    c = une({"meta-1": [j(0, 1000, 20, 5, 1)]})
    taux = c["taux_de_conversion"]
    assert taux["valeur"] == "0.2" and taux["n"] == 5
    assert Decimal(taux["intervalle"]["bas"]) == pytest.approx(Decimal("0.0362"), abs=Decimal("0.0001"))
    assert Decimal(taux["intervalle"]["haut"]) == pytest.approx(Decimal("0.6245"), abs=Decimal("0.0001"))
    cpa = c["cout_par_conversion_cad"]
    assert cpa["valeur"] == "10.00" and cpa["n"] == 1
    # 10 $ / (5 clics x borne haute 0,624464) = 3,20 $ ; 10 $ / (5 clics x borne basse 0,036228) = 55,20 $
    assert Decimal(cpa["intervalle"]["bas"]) == pytest.approx(Decimal("3.20"), abs=Decimal("0.02"))
    assert Decimal(cpa["intervalle"]["haut"]) == pytest.approx(Decimal("55.2"), abs=Decimal("0.3"))
    p_bas, p_haut = Decimal(taux["intervalle"]["bas"]), Decimal(taux["intervalle"]["haut"])
    assert cpa["intervalle"]["bas"] == format((Decimal(10) / (Decimal(5) * p_haut)).quantize(Decimal("0.01")), "f")
    assert cpa["intervalle"]["haut"] == format((Decimal(10) / (Decimal(5) * p_bas)).quantize(Decimal("0.01")), "f")


def test_la_borne_haute_du_cout_par_conversion_est_non_bornee_quand_la_borne_basse_du_taux_est_zero():
    # 1 conversion sur 1 000 000 de clics : la borne basse de Wilson (environ 1,8e-7) s'arrondit à 0 à six décimales
    c = une({"meta-1": [j(0, 100_000, 10_000_000, 1_000_000, 1)]})
    assert c["taux_de_conversion"]["intervalle"]["bas"] == "0"
    cpa = c["cout_par_conversion_cad"]
    assert cpa["intervalle"]["haut"] is None
    # borne haute de Wilson 0,000006 => 1000 $ / (1 000 000 x 0,000006) = 166,67 $
    assert c["taux_de_conversion"]["intervalle"]["haut"] == "0.000006"
    assert cpa["intervalle"]["bas"] == "166.67"


def test_totaux_exacts_couverture_et_cout_par_clic():
    s = [j(0, 1234, 100, 10, 1), j(1, 766, 300, 40, 2), j(2, 1000, 50, 5, "0.5")]
    c = une({"meta-1": s}, jours=3)
    assert c["totaux"] == {"cout_cad": "30.00", "impressions": 450, "clics": 55, "conversions": "3.5"}
    assert c["couverture"] == {"jours_attendus": 3, "jours_lus": 3, "jours_manquants": []}
    assert c["cout_par_clic_cad"] == "0.55"  # 3000 cents / 55 clics = 54,545 cents => 0,55 $ (au cent)
    assert c["periode"] == {"debut": "2026-10-01", "fin": "2026-10-03"}


def test_un_jour_manquant_est_un_trou_et_les_totaux_sont_ceux_des_jours_lus():
    c = une({"meta-1": [j(0, 1000, 100, 10, 1), j(2, 1000, 100, 10, 1)]}, jours=3)
    assert c["couverture"]["jours_manquants"] == ["2026-10-02"] and c["couverture"]["jours_lus"] == 2
    assert c["totaux"]["cout_cad"] == "20.00" and c["totaux"]["clics"] == 20
    assert any("1 jour(s) sans donnée" in n for n in c["notes"])


def test_metrique_non_declaree_donne_total_inconnu_et_jamais_zero():
    c = une({"meta-1": [j(0, 1000, 100, 10, 1), j(1, 1000, None, 10, 1)]}, jours=2)
    assert c["totaux"]["impressions"] is None and c["totaux"]["clics"] == 20
    assert c["taux_de_clic"] == {"valeur": None, "intervalle": None, "n": None}
    assert any("impressions non déclarées" in n for n in c["notes"])
    c = une({"meta-1": [j(0, 1000, 100, 10, None)]})
    assert c["totaux"]["conversions"] is None and c["cout_par_conversion_cad"]["valeur"] is None
    assert c["taux_de_conversion"]["valeur"] is None


def test_les_montants_ont_toujours_deux_decimales():
    c = une({"meta-1": [j(0, 1000, 100, 10, 2)]})
    assert c["totaux"]["cout_cad"] == "10.00" and c["cout_par_clic_cad"] == "1.00"
    assert c["cout_par_conversion_cad"]["valeur"] == "5.00"


def test_zero_conversion_certain_ne_donne_pas_de_cout_par_conversion():
    c = une({"meta-1": [j(0, 1000, 100, 10, 0)]})
    assert c["totaux"]["conversions"] == "0" and c["taux_de_conversion"]["valeur"] == "0"
    assert c["cout_par_conversion_cad"] == {"valeur": None, "intervalle": None, "n": None}


@pytest.mark.parametrize(
    "clics, conv, suffisant",
    [
        (99, 5, False),
        (100, 5, True),
        (100, 4, False),
        (500, 5, True),
        (0, 0, False),
    ],
)
def test_suffisance_aux_deux_cotes_des_seuils(clics, conv, suffisant):
    c = une({"meta-1": [j(0, 5000, max(clics, 1) * 10, clics, conv)]})
    assert c["suffisant"] is suffisant
    texte = " ".join(c["notes"])
    assert ("échantillon insuffisant" in texte) is (not suffisant)
    assert rp.MIN_CLICS == 100 and rp.MIN_CONVERSIONS == 5


def test_conversions_fractionnaires_pas_d_intervalle_de_conversion_ni_de_cout_et_une_note():
    c = une({"meta-1": [j(0, 5000, 1000, 200, "2.5")]})
    assert c["taux_de_conversion"]["valeur"] == "0.0125" and c["taux_de_conversion"]["intervalle"] is None
    assert c["cout_par_conversion_cad"]["valeur"] == "20.00"  # 50 $ / 2,5
    assert c["cout_par_conversion_cad"]["intervalle"] is None and c["cout_par_conversion_cad"]["n"] is None
    assert any("fractionnaires" in n for n in c["notes"])


def test_les_jours_hors_periode_sont_ignores():
    c = une({"meta-1": [j(-1, 99999, 1, 1, 1), j(0, 1000, 100, 10, 1), j(5, 99999, 1, 1, 1)]}, jours=2)
    assert c["totaux"]["cout_cad"] == "10.00" and c["couverture"]["jours_lus"] == 1


# ======================================================================================================================
def _camp(cout_cad, clics, conv):
    return [j(0, cout_cad * 100, clics * 10, clics, conv)]


def test_campagnes_aux_intervalles_chevauchants_sont_indistinguables_les_autres_separees_sans_classement():
    rapport = construire(
        {
            "meta-a": _camp(1000, 1000, 100),  # CPA 10 $ : intervalle environ [8,3 ; 12,1]
            "meta-b": _camp(2000, 1000, 50),  # CPA 40 $ : environ [30,6 ; 52,5]
            "meta-c": _camp(1000, 1000, 90),  # CPA 11,11 $ : environ [9,2 ; 13,5] : chevauche A
        }
    )
    assert rapport["comparaison"]["niveaux_indistinguables"] == [["meta-a", "meta-c"], ["meta-b"]]
    assert rapport["comparaison"]["classement"] is None
    assert all(c["suffisant"] for c in rapport["campagnes"])


def test_une_campagne_insuffisante_n_entre_dans_aucun_niveau():
    rapport = construire({"meta-a": _camp(1000, 1000, 100), "meta-b": _camp(10, 50, 2)})
    assert rapport["comparaison"]["niveaux_indistinguables"] == [["meta-a"]]


def test_deux_campagnes_identiques_sont_dans_le_meme_niveau():
    rapport = construire({"meta-a": _camp(1000, 1000, 100), "meta-b": _camp(1000, 1000, 100)})
    assert rapport["comparaison"]["niveaux_indistinguables"] == [["meta-a", "meta-b"]]


def test_ensemble_additionne_les_campagnes_jour_par_jour():
    s1, s2 = [j(0, 1000, 100, 10, 1), j(1, 500, 50, 5, 0)], [j(0, 2000, 200, 20, 2)]
    e = construire({"meta-a": s1, "meta-b": s2}, jours=2)["ensemble"]
    assert e["campagne_ref"] == "ensemble"
    assert e["totaux"] == {"cout_cad": "35.00", "impressions": 350, "clics": 35, "conversions": "3"}
    assert e["couverture"]["jours_lus"] == 2


def test_causalite_jamais_affirmee_et_champs_de_cadrage():
    rapport = construire({"meta-a": _camp(1000, 1000, 100)}, fictifs_presents=True)
    assert rapport["causalite"] == "non_etablie" and rapport["fictifs_presents"] is True
    assert "aucun effet causal" in rapport["avertissement"] and rapport["avertissement"] == rp.CAUSALITE
    assert rapport["niveau_confiance"] == "0.95" and rapport["type"] == "RAPPORT_PERFORMANCE_PUBLICITAIRE"
    assert rapport["seuils"]["clics_min"] == 100 and rapport["seuils"]["conversions_min"] == 5
    assert "classement" in rapport["comparaison"]


def test_niveau_de_confiance_change_l_intervalle():
    a = une({"meta-1": [j(0, 1000, 20, 5, 1)]})
    rapport = rp.construire(
        canal="meta", campagnes={"meta-1": [j(0, 1000, 20, 5, 1)]}, debut=D0, fin=D0, niveau=Decimal("0.80")
    )
    b = rapport["campagnes"][0]
    assert rapport["niveau_confiance"] == "0.8"
    assert Decimal(b["taux_de_clic"]["intervalle"]["bas"]) > Decimal(a["taux_de_clic"]["intervalle"]["bas"])
    assert Decimal(b["taux_de_clic"]["intervalle"]["haut"]) < Decimal(a["taux_de_clic"]["intervalle"]["haut"])


@pytest.mark.parametrize("debut, fin", [(date(2026, 10, 5), date(2026, 10, 1)), (date(2025, 1, 1), date(2026, 10, 1))])
def test_periode_inversee_ou_trop_longue_refusee(debut, fin):
    with pytest.raises(ValueError):
        rp.construire(canal="meta", campagnes={}, debut=debut, fin=fin)


def test_periode_de_367_jours_acceptee_368_refusee():
    debut = date(2026, 1, 1)
    rp.construire(canal="meta", campagnes={}, debut=debut, fin=debut + timedelta(days=366))
    with pytest.raises(ValueError):
        rp.construire(canal="meta", campagnes={}, debut=debut, fin=debut + timedelta(days=367))


def test_sans_aucune_campagne_le_rapport_est_vide_sans_inventer_un_zero():
    rapport = rp.construire(canal="meta", campagnes={}, debut=D0, fin=D0 + timedelta(days=1))
    assert rapport["campagnes"] == [] and rapport["comparaison"]["niveaux_indistinguables"] == []
    e = rapport["ensemble"]
    assert e["couverture"]["jours_lus"] == 0 and e["couverture"]["jours_manquants"] == ["2026-10-01", "2026-10-02"]
    # aucun jour lu : les totaux sont INCONNUS, jamais zéro
    assert e["totaux"] == {"cout_cad": None, "impressions": None, "clics": None, "conversions": None}
    assert e["taux_de_clic"]["valeur"] is None and e["suffisant"] is False
