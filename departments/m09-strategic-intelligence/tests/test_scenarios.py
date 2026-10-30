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
    "m5.comptes_a_recevoir#4:p0.resultat.resultat.attendus": "41000.50",
}
BASES = {
    "leads_periode": "m2.leads#0:p0.resultat.resultat.total",
    "cash_libre": "m5.prevision_tresorerie#1:p0.resultat.resultat.cash_libre",
    "capacite_jours_personnes": "m4.cedule_semaine#2:p0.resultat.resultat.capacite",
    "jours_ouvrables": "m4.cedule_semaine#2:p0.resultat.resultat.jours",
    "cout_materiaux_periode": "m6.disponibilite#3:p0.resultat.resultat.cout",
    "revenu_periode": "m5.comptes_a_recevoir#4:p0.resultat.resultat.revenu",
    "budget_marketing_periode": "m7.performance_campagnes#5:p0.resultat.resultat.budget",
    "encaissements_attendus_periode": "m5.comptes_a_recevoir#4:p0.resultat.resultat.attendus",
}
NEUF_DE_LA_DEFINITION = {
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
DIX_NOUVEAUX = {
    "achat_equipement",
    "achat_batisse",
    "gain_gros_client",
    "retard_paiement_client",
    "saison_morte_faible",
    "nouveau_service",
    "concurrent_agressif",
    "cashflow_serre",
    "rupture_inventaire",
    "trop_de_demandes",
}
# Paramètres valides de chaque nouveau choc (hypothèses déclarées, fictives).
PARAMETRES_NOUVEAUX = {
    "achat_equipement": {"prix": "12000.10"},
    "achat_batisse": {"prix": "450000", "mise_de_fonds_pct": "12.5"},
    "gain_gros_client": {"revenu_ajoute": "25000.55"},
    "retard_paiement_client": {"montant_retarde": "15000", "jours_retard": "45"},
    "saison_morte_faible": {"baisse_revenu_pct": "30"},
    "nouveau_service": {"investissement": "20000"},
    "concurrent_agressif": {"perte_leads_pct": "15"},
    "cashflow_serre": {"horizon_semaines": "8", "seuil_minimal": "10000"},
    "rupture_inventaire": {"jours_rupture": "10"},
    "trop_de_demandes": {"hausse_pct": "250"},
}


def _effet(scenario, identifiant):
    return next(e for e in scenario["effets"] if e["id"] == identifiant)


def test_dix_neuf_chocs_au_catalogue_dont_les_neuf_de_la_definition_produit():
    assert set(sc.CHOCS) >= NEUF_DE_LA_DEFINITION
    assert set(sc.CHOCS) == NEUF_DE_LA_DEFINITION | DIX_NOUVEAUX and len(sc.CHOCS) == 19
    for choc in sc.CHOCS.values():
        assert all(effet.base in sc.BASES for effet in choc.effets) and choc.a_calculer_par
        assert all(effet.operation in sc.OPERATIONS for effet in choc.effets)
        for parametre in choc.parametres:
            assert parametre.unite and parametre.minimum <= parametre.maximum, "chaque paramètre est borné et unité"
        for confie in choc.a_calculer_par:
            assert confie["proprietaire"].startswith("m") and isinstance(confie["entrees"], list)


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
    assert lignes[("achat_camion", "cash_apres_achat", "CALCULE")]["ecart"] == "-48000.25"
    assert Fraction(lignes[("achat_camion", "cash_apres_achat", "CALCULE")]["ecart"]) == Fraction("4000.15") - Fraction(
        "52000.40"
    )
    assert ("baisse_leads", "leads_projetes", "NON_CALCULE") in lignes
    assert "moyenne" not in comparaison and "classement" not in comparaison
    with pytest.raises(ValueError, match="REJ-SCENARIO-COMPARAISON"):
        sc.comparer([], BASES, FAITS)


# --- Dix chocs ajoutés (M9.8) ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("choc", "effet", "attendu"),
    [
        ("achat_equipement", "cash_apres_achat_equipement", Fraction("52000.40") - Fraction("12000.10")),
        ("achat_batisse", "cash_apres_mise_de_fonds", Fraction("52000.40") - 450000 * Fraction(125, 1000)),
        ("gain_gros_client", "revenu_apres_gain", Fraction("98000.00") + Fraction("25000.55")),
        ("retard_paiement_client", "encaissements_apres_retard", Fraction("41000.50") - 15000),
        ("saison_morte_faible", "revenu_projete", Fraction("98000.00") * Fraction(70, 100)),
        ("nouveau_service", "cash_apres_lancement", Fraction("52000.40") - 20000),
        ("concurrent_agressif", "leads_projetes", Fraction(40) * Fraction(85, 100)),
        ("trop_de_demandes", "leads_projetes", Fraction(40) * Fraction(350, 100)),
    ],
)
def test_nouveaux_chocs_arithmetiques_calculent_exactement_l_oracle(choc, effet, attendu):
    scenario = sc.evaluer(choc, PARAMETRES_NOUVEAUX[choc], BASES, FAITS)
    resultat = _effet(scenario, effet)
    assert resultat["statut"] == "CALCULE" and resultat["nature"] == "SENSIBILITE_ARITHMETIQUE"
    assert Fraction(resultat["valeur"]) == attendu
    assert Fraction(resultat["ecart"]) == attendu - Fraction(resultat["valeur_base"])
    assert scenario["calculable"] is True and scenario["a_calculer_par"]
    assert [b["base"] for b in sc.bases_requises(choc)] == [resultat["base"]]


@pytest.mark.parametrize("choc", sorted(DIX_NOUVEAUX))
def test_chaque_nouveau_choc_refuse_sans_base_en_nommant_ce_qui_manque_et_qui_le_possede(choc):
    scenario = sc.evaluer(choc, PARAMETRES_NOUVEAUX[choc], {}, FAITS)
    assert scenario["calculable"] is False
    assert all("valeur" not in effet for effet in scenario["effets"]), "aucune valeur sans base citée"
    for effet in scenario["effets"]:
        base = sc.BASES[effet["base"]]
        assert effet["statut"] == "NON_CALCULE" and base.proprietaire in effet["raison"]
        assert scenario["bases"][effet["base"]]["etat"] == "BASE_ABSENTE"


@pytest.mark.parametrize("choc", ["cashflow_serre", "rupture_inventaire"])
def test_chocs_sans_sensibilite_honnete_restent_a_calculer_par_le_proprietaire(choc):
    scenario = sc.evaluer(choc, PARAMETRES_NOUVEAUX[choc], BASES, FAITS)
    assert scenario["effets"] == [] and scenario["calculable"] is False
    assert scenario["nature"] == "A_CALCULER_PAR_LE_PROPRIETAIRE" and sc.bases_requises(choc) == []
    entrees = {e for confie in scenario["a_calculer_par"] for e in confie["entrees"]}
    assert entrees == set(PARAMETRES_NOUVEAUX[choc]), "les entrées exactes à fournir sont les hypothèses déclarées"
    assert {c["proprietaire"] for c in scenario["a_calculer_par"]} <= {"m05-financecore", "m06-material-control",
                                                                       "m04-field-ops"}  # fmt: skip
    comparaison = sc.comparer([scenario], BASES, FAITS)
    assert comparaison["lignes"] == [], "rien n'est présenté comme calculé"


def test_retard_superieur_aux_encaissements_attendus_est_infaisable_sans_troncature():
    scenario = sc.evaluer("retard_paiement_client", {"montant_retarde": "50000", "jours_retard": "30"}, BASES, FAITS)
    effet = _effet(scenario, "encaissements_apres_retard")
    assert effet["statut"] == "INFAISABLE" and Fraction(effet["valeur"]) == Fraction("41000.50") - 50000


def test_nouveaux_chocs_ne_calculent_ni_marge_ni_tresorerie_ni_capacite_ni_roi():
    interdits = ("marge", "tresorerie", "capacite", "roi", "rentabilite")
    for choc in DIX_NOUVEAUX:
        effets = sc.CHOCS[choc].effets
        assert not any(mot in effet.id for effet in effets for mot in interdits), choc
        assert all(effet.base != "capacite_jours_personnes" for effet in effets), choc


@pytest.mark.parametrize(
    ("choc", "parametres", "code"),
    [
        ("achat_batisse", {"prix": "450000", "mise_de_fonds_pct": "100.01"}, "REJ-SCENARIO-BORNE"),
        ("trop_de_demandes", {"hausse_pct": "1000.5"}, "REJ-SCENARIO-BORNE"),
        ("cashflow_serre", {"horizon_semaines": "0", "seuil_minimal": "10"}, "REJ-SCENARIO-BORNE"),
        ("cashflow_serre", {"horizon_semaines": "53", "seuil_minimal": "10"}, "REJ-SCENARIO-BORNE"),
        ("retard_paiement_client", {"montant_retarde": "10"}, "REJ-SCENARIO-PARAMETRES"),
        ("rupture_inventaire", {"jours_rupture": "1e3"}, "REJ-SCENARIO-NOMBRE"),
        ("gain_gros_client", {"revenu_ajoute": "-1"}, "REJ-SCENARIO-BORNE"),
    ],
)
def test_nouveaux_chocs_bornes_et_parametres_refuses(choc, parametres, code):
    with pytest.raises(ValueError, match=code):
        sc.evaluer(choc, parametres, BASES, FAITS)
    with pytest.raises(ValueError, match=code):
        sc.valider_parametres(choc, parametres)


def test_fonctions_du_catalogue_valident_un_parametre_isole_et_refusent_l_inconnu():
    assert sc.valider_parametre("trop_de_demandes", "hausse_pct", "999") == sc.decimal("999", nom="x")
    with pytest.raises(ValueError, match="REJ-SCENARIO-PARAMETRES"):
        sc.valider_parametre("meteo", "jours_inventes", "1")
    with pytest.raises(ValueError, match="REJ-SCENARIO-CHOC"):
        sc.valider_parametre("inconnu", "x", "1")
    with pytest.raises(ValueError, match="REJ-SCENARIO-CHOC"):
        sc.bases_requises(["liste"])
