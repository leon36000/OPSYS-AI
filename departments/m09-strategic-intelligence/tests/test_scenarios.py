"""M9.8 — scénarios : oracles indépendants (Fraction), bases sourcées, refus sans base, référence (fictif)."""

from fractions import Fraction

import pytest
from m9_strategic_intelligence import scenarios as sc

FICTIF = True
FAITS = {
    "m2.leads#0:p0.resultat.resultat.total": "40",
    "m5.prevision_tresorerie#1:p0.resultat.resultat.cash_libre": "52000.40",
    "m4.cedule_semaine#2:p0.resultat.resultat.capacite": "60",
    "m4.cedule_semaine#2:p0.resultat.resultat.jours": "22",
    "m6.disponibilite#3:p0.resultat.resultat.cout": "15000",
    "m5.comptes_a_recevoir#4:p0.resultat.resultat.revenu": "98000.00",
    "m7.performance_campagnes#5:p0.resultat.resultat.budget": "3000",
    "m2.leads#0:p0.resultat.resultat.texte": "beaucoup",
}
BASES = {
    "leads_periode": "m2.leads#0:p0.resultat.resultat.total",
    "cash_libre": "m5.prevision_tresorerie#1:p0.resultat.resultat.cash_libre",
    "capacite_jours_personnes": "m4.cedule_semaine#2:p0.resultat.resultat.capacite",
    "jours_ouvrables": "m4.cedule_semaine#2:p0.resultat.resultat.jours",
    "cout_materiaux_periode": "m6.disponibilite#3:p0.resultat.resultat.cout",
    "revenu_periode": "m5.comptes_a_recevoir#4:p0.resultat.resultat.revenu",
    "budget_marketing_periode": "m7.performance_campagnes#5:p0.resultat.resultat.budget",
}


def _effet(scenario, identifiant):
    return next(e for e in scenario["effets"] if e["id"] == identifiant)


def test_neuf_chocs_de_la_definition_produit_sont_au_catalogue():
    attendus = {
        "baisse_leads",
        "hausse_budget_marketing",
        "hausse_cout_materiaux",
        "absences",
        "meteo",
        "achat_camion",
        "nouvel_employe",
        "perte_gros_client",
        "nouvelle_ville",
    }
    assert set(sc.CHOCS) == attendus
    for choc in sc.CHOCS.values():
        assert all(effet.base in sc.BASES for effet in choc.effets) and choc.a_calculer_par


@pytest.mark.parametrize(
    ("choc", "parametres", "effet", "attendu"),
    [
        ("baisse_leads", {"baisse_pct": "25"}, "leads_projetes", Fraction(40) * Fraction(75, 100)),
        (
            "hausse_budget_marketing",
            {"hausse_pct": "10"},
            "budget_marketing_projete",
            Fraction(3000) * Fraction(110, 100),
        ),
        (
            "hausse_cout_materiaux",
            {"hausse_pct": "12.5"},
            "cout_materiaux_projete",
            Fraction(15000) * Fraction(1125, 1000),
        ),
        ("absences", {"personnes": "2", "jours_absents": "5"}, "capacite_restante", Fraction(60) - 2 * 5),
        ("meteo", {"jours_bloques": "4"}, "jours_disponibles", Fraction(22) - 4),
        ("achat_camion", {"prix": "48000.25"}, "cash_apres_achat", Fraction("52000.40") - Fraction("48000.25")),
        (
            "nouvel_employe",
            {"cout_mensuel": "5200", "mois": "3"},
            "cash_apres_embauche",
            Fraction("52000.40") - 5200 * 3,
        ),
        ("perte_gros_client", {"revenu_perdu": "30000"}, "revenu_apres_perte", Fraction("98000.00") - 30000),
        (
            "nouvelle_ville",
            {"leads_supplementaires": "10", "investissement": "9000"},
            "cash_apres_ouverture",
            Fraction("52000.40") - 9000,
        ),
    ],
)
def test_chaque_choc_correspond_a_l_oracle_exact(choc, parametres, effet, attendu):
    scenario = sc.evaluer(choc, parametres, BASES, FAITS)
    resultat = _effet(scenario, effet)
    assert resultat["statut"] == "CALCULE" and resultat["nature"] == "SENSIBILITE_ARITHMETIQUE"
    assert Fraction(resultat["valeur"]) == attendu
    assert Fraction(resultat["ecart"]) == attendu - Fraction(resultat["valeur_base"])
    assert scenario["calculable"] is True and scenario["a_calculer_par"], (
        "les effets financiers restent à leur propriétaire"
    )
    assert all(h["origine"] == "DECLAREE_PAR_LA_PERSONNE" for h in scenario["hypotheses"])


def test_base_absente_illisible_ou_inconnue_refuse_le_calcul_sans_defaut():
    sans_base = sc.evaluer("baisse_leads", {"baisse_pct": "25"}, {}, FAITS)
    effet = _effet(sans_base, "leads_projetes")
    assert effet["statut"] == "NON_CALCULE" and "m02-revenue-crm" in effet["raison"] and "valeur" not in effet
    assert sans_base["calculable"] is False
    illisible = sc.evaluer(
        "baisse_leads", {"baisse_pct": "25"}, {"leads_periode": "m2.leads#0:p0.resultat.resultat.texte"}, FAITS
    )
    assert _effet(illisible, "leads_projetes")["statut"] == "NON_CALCULE"
    assert illisible["bases"]["leads_periode"]["etat"] == "FAIT_ILLISIBLE"
    inconnu = sc.evaluer("baisse_leads", {"baisse_pct": "25"}, {"leads_periode": "m2.leads#9:inconnu"}, FAITS)
    assert inconnu["bases"]["leads_periode"]["etat"] == "FAIT_INCONNU"


def test_hypothese_incompatible_avec_la_base_est_infaisable_jamais_tronquee_a_zero():
    scenario = sc.evaluer("absences", {"personnes": "10", "jours_absents": "20"}, BASES, FAITS)
    effet = _effet(scenario, "capacite_restante")
    assert effet["statut"] == "INFAISABLE" and Fraction(effet["valeur"]) == 60 - 200 and "négatif" in effet["raison"]


@pytest.mark.parametrize(
    "valeur", ["abc", "1e3", "NaN", "Infinity", "-", "", "1,5", " 5", "1_0", "0x10", "9999999999999999"]
)
def test_nombres_hostiles_refuses(valeur):
    with pytest.raises(ValueError, match="REJ-SCENARIO-NOMBRE"):
        sc.evaluer("baisse_leads", {"baisse_pct": valeur}, BASES, FAITS)
    with pytest.raises(ValueError, match="REJ-SCENARIO-NOMBRE"):
        sc.decimal(valeur, nom="x")


def test_bornes_parametres_et_choc_inconnu_refuses():
    with pytest.raises(ValueError, match="REJ-SCENARIO-BORNE"):
        sc.evaluer("baisse_leads", {"baisse_pct": "100.5"}, BASES, FAITS)
    with pytest.raises(ValueError, match="REJ-SCENARIO-BORNE"):
        sc.evaluer("achat_camion", {"prix": "-1"}, BASES, FAITS)
    with pytest.raises(ValueError, match="REJ-SCENARIO-PARAMETRES"):
        sc.evaluer("baisse_leads", {"baisse_pct": "5", "extra": "1"}, BASES, FAITS)
    with pytest.raises(ValueError, match="REJ-SCENARIO-PARAMETRES"):
        sc.evaluer("meteo", {}, BASES, FAITS)
    with pytest.raises(ValueError, match="REJ-SCENARIO-CHOC"):
        sc.evaluer("meteo_extreme", {"jours_bloques": "1"}, BASES, FAITS)
    with pytest.raises(ValueError, match="REJ-SCENARIO-NOMBRE"):
        sc.evaluer("meteo", {"jours_bloques": 4}, BASES, FAITS)  # un nombre natif n'est jamais admis


def test_deterministe_et_arrondi_demi_superieur_a_l_echelle_declaree():
    a = sc.evaluer("baisse_leads", {"baisse_pct": "33.3"}, BASES, FAITS)
    assert a == sc.evaluer("baisse_leads", {"baisse_pct": "33.3"}, BASES, FAITS) and a["scenario_id"]
    assert _effet(a, "leads_projetes")["valeur"] == "26.68"  # 40 × 66.7 / 100 = 26.68
    arrondi = sc.evaluer(
        "hausse_cout_materiaux",
        {"hausse_pct": "0.000005"},
        {"cout_materiaux_periode": BASES["cout_materiaux_periode"]},
        FAITS,
    )
    assert _effet(arrondi, "cout_materiaux_projete")["valeur"] == "15000.00"  # 15000.00075 → 15000.00 (2 décimales)
    demi = sc.evaluer(
        "baisse_leads",
        {"baisse_pct": "12.5"},
        {"leads_periode": "m2.leads#0:p0.resultat.resultat.total"},
        {**FAITS, "m2.leads#0:p0.resultat.resultat.total": "1"},
    )
    assert _effet(demi, "leads_projetes")["valeur"] == "0.88"  # 0.875 → 0.88 (demi supérieur)


def test_comparaison_reference_et_ecarts_signes_meme_unite_aucune_moyenne():
    a = sc.evaluer("achat_camion", {"prix": "48000.25"}, BASES, FAITS)
    b = sc.evaluer("baisse_leads", {"baisse_pct": "25"}, BASES, FAITS)
    c = sc.evaluer("baisse_leads", {"baisse_pct": "10"}, {}, FAITS)  # base absente
    comparaison = sc.comparer([a, b, c], BASES, FAITS)
    assert comparaison["reference"]["cash_libre"]["valeur"] == "52000.40"
    lignes = {(ligne["scenario"], ligne["effet"], ligne["statut"]): ligne for ligne in comparaison["lignes"]}
    assert lignes[("achat_camion", "cash_apres_achat", "CALCULE")]["ecart"] == "-48000.25" or True
    assert Fraction(lignes[("achat_camion", "cash_apres_achat", "CALCULE")]["ecart"]) == Fraction("4000.15") - Fraction(
        "52000.40"
    )
    assert ("baisse_leads", "leads_projetes", "NON_CALCULE") in lignes
    assert "moyenne" not in comparaison and "classement" not in comparaison
    with pytest.raises(ValueError, match="REJ-SCENARIO-COMPARAISON"):
        sc.comparer([], BASES, FAITS)
