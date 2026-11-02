"""M9.12 (M9-C1) — les règles du radar sur des lectures déjà captées : seuils DÉCLARÉS, raison/mesure/seuil/source,
critique par multiple déclaré, règle non évaluée dite (jamais « aucun risque »), dimension de chaque risque (fictif)."""

import copy
import importlib.util
import sys
from pathlib import Path

import pytest
from m9_strategic_intelligence import risques as rk


def _charger_aide():
    if "aide_radar" in sys.modules:
        return sys.modules["aide_radar"]
    spec = importlib.util.spec_from_file_location("aide_radar", Path(__file__).with_name("aide_radar.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["aide_radar"] = module
    spec.loader.exec_module(module)
    return module


A = _charger_aide()
FICTIF = True
S = A.SEUILS
LECTURE_DE = {
    "plaintes_afflux": "m1.plaintes_structurees",
    "plaintes_sensibles_ouvertes": "m1.plaintes_structurees",
    "capacite_surcharge_cedule": "m4.capacite_equipe",
    "depense_marketing_plafond": "m7.depenses_marketing",
    "leads_sous_plancher": "m2.prevision_pipeline",
    "estimation_ecart_main_doeuvre": "m3.ecarts",
    "materiaux_variance_critique": "m3.ecarts",
    "materiaux_disponible_negatif": "m6.disponibilite",
    "chantier_retard_prolonge": "m4.retards_incidents",
    "cash_libre_deficit": "m8.vue_executive",
    "cash_libre_non_calculable": "m8.vue_executive",
    "cash_libre_sous_plancher": "m8.vue_executive",
    "filet_sla_violation": "m2.sla_filet",
}


def _chaine(lecture, page, **plus):
    chaine: list = []
    A.capturer(chaine, lecture, page)
    return chaine, plus


def _un(lecture, page, seuils=S, **plus):
    chaine: list = []
    A.capturer(chaine, lecture, page)
    return A.radar(chaine, seuils=seuils, **plus)


def _seule(res, regle):
    trouves = [r for r in res["risques"] if r["regle"] == regle]
    assert len(trouves) == 1, (regle, res["risques"])
    return trouves[0]


# ---------------------------------------------------------------------------------------------------- plaintes (M1)
def test_plaintes_au_seuil_declare_donnent_un_risque_eleve_avec_raison_mesure_seuil_et_source():
    res = _un("m1.plaintes_structurees", A.page_plaintes(3))
    r = _seule(res, "plaintes_afflux")
    assert (r["domaine"], r["gravite"], r["statut"], r["sujet"]) == ("plaintes", "ELEVE", "ACTIF", "plaintes_periode")
    assert r["mesure"] == {"valeur": "3", "unite": "plaintes", "periode_jours": 7}
    assert r["seuil"] == {
        "reglage": "m9.plaintes_seuil_nombre",
        "valeur": "3",
        "unite": "plaintes",
        "critique_si_au_moins": "4.5",
    }
    assert "plainte" in r["raison"] and r["origine_etablie"] is False
    assert r["source"]["lecture_id"] == "m1.plaintes_structurees" and r["source"]["capture"] == 0
    assert r["preuves"][0] == "m1.plaintes_structurees#0:p0.resultat.resultat.comptes.declarees"
    assert "plaintes_afflux" in res["regles_evaluees"]


def test_plaintes_sous_le_seuil_aucun_risque_mais_la_regle_est_evaluee():
    res = _un("m1.plaintes_structurees", A.page_plaintes(2))
    assert not [r for r in res["risques"] if r["regle"] == "plaintes_afflux"]
    assert "plaintes_afflux" in res["regles_evaluees"]


def test_plaintes_au_multiple_declare_du_seuil_sont_critiques_et_sans_multiple_elles_ne_le_sont_pas():
    page = A.page_plaintes(5)
    assert _seule(_un("m1.plaintes_structurees", page), "plaintes_afflux")["gravite"] == "CRITIQUE"
    sans = {k: v for k, v in S.items() if k != "multiple_seuil_critique"}
    res = _un("m1.plaintes_structurees", page, seuils=sans)
    assert _seule(res, "plaintes_afflux")["gravite"] == "ELEVE"
    assert res["escalade"]["multiple_declare"] is None
    assert "m9.multiple_seuil_critique" in res["reglages_a_declarer"]
    assert "aucun dépassement n'est dit critique" in res["escalade"]["dit"]


def test_plainte_sensible_ouverte_est_une_reputation_sans_seuil():
    res = _un("m1.plaintes_structurees", A.page_plaintes(1, categories=("avocat",)), seuils={})
    r = _seule(res, "plaintes_sensibles_ouvertes")
    assert (r["domaine"], r["gravite"], r["seuil"]) == ("reputation", "ELEVE", None)
    close = _un("m1.plaintes_structurees", A.page_plaintes(1, categories=("avocat",), statut="clos"), seuils={})
    assert not [x for x in close["risques"] if x["regle"] == "plaintes_sensibles_ouvertes"]
    banale = _un("m1.plaintes_structurees", A.page_plaintes(1, categories=("degat",)), seuils={})
    assert not [x for x in banale["risques"] if x["regle"] == "plaintes_sensibles_ouvertes"]


def test_plaintes_non_branchee_n_est_pas_zero_plainte():
    res = _un("m1.plaintes_structurees", A.page_plaintes_non_branchee())
    assert not [r for r in res["risques"] if r["domaine"] in ("plaintes", "reputation")]
    assert A.non_evaluee(res, "plaintes_afflux")[0]["raison"] == "PARTIELLE"
    assert "plaintes_afflux" not in res["regles_evaluees"]


# ----------------------------------------------------------------------------------------------- capacité (M4)
def test_surcharge_par_equipe_au_seuil_en_pourcentage_sans_division():
    res = _un("m4.capacite_equipe", A.page_capacite([("eq-a", 600, 540), ("eq-b", 600, 300)]))
    r = _seule(res, "capacite_surcharge_cedule")
    assert (r["domaine"], r["gravite"], r["sujet"]) == ("capacite", "ELEVE", "equipe:eq-a")
    assert r["mesure"]["heures_planifiees"] == "9.00" and r["mesure"]["heures_disponibles"] == "10.00"
    assert r["seuil"]["reglage"] == "m9.capacite_utilisation_seuil_pct" and r["seuil"]["valeur"] == "90"
    assert r["seuil"]["critique_si_au_moins"] == "135"


def test_surcharge_un_cran_sous_le_seuil_ne_declenche_pas_et_a_135_pour_cent_c_est_critique():
    assert not _un("m4.capacite_equipe", A.page_capacite([("eq-a", 600, 539)]))["risques"]
    res = _un("m4.capacite_equipe", A.page_capacite([("eq-a", 600, 810)]))
    assert _seule(res, "capacite_surcharge_cedule")["gravite"] == "CRITIQUE"
    res2 = _un("m4.capacite_equipe", A.page_capacite([("eq-a", 600, 809)]))
    assert _seule(res2, "capacite_surcharge_cedule")["gravite"] == "ELEVE"


def test_equipe_planifiee_sans_heure_declaree_est_en_surcharge_mais_rien_planifie_n_en_est_pas_une():
    res = _un("m4.capacite_equipe", A.page_capacite([("eq-a", 0, 60), ("eq-b", 0, 0)]))
    assert [r["sujet"] for r in res["risques"] if r["regle"] == "capacite_surcharge_cedule"] == ["equipe:eq-a"]


def test_capacite_non_calculable_est_un_risque_inconnu_pas_une_capacite_libre():
    res = _un("m4.capacite_equipe", A.page_capacite_non_calculable())
    assert not res["risques"] and A.non_evaluee(res, "capacite_surcharge_cedule")[0]["raison"] == "PARTIELLE"


# ----------------------------------------------------------------------------------------- dépense marketing (M7)
def test_depense_marketing_au_dessus_du_plafond_declare_seulement():
    res = _un("m7.depenses_marketing", A.page_depenses("1400.00", "300.00"))
    r = _seule(res, "depense_marketing_plafond")
    assert (r["domaine"], r["gravite"]) == ("marketing", "ELEVE")
    assert r["mesure"]["valeur"] == "1700.00" and r["mesure"]["unite"] == "CAD"
    assert r["mesure"]["periode"] == {"debut": A.m7.DEBUT, "fin": A.m7.FIN}
    assert r["seuil"]["valeur"] == "1500" and r["seuil"]["critique_si_au_moins"] == "2250"
    egal = _un("m7.depenses_marketing", A.page_depenses("1200.00", "300.00"))
    assert not egal["risques"], "pile au plafond n'est pas un dépassement"
    assert (
        _seule(_un("m7.depenses_marketing", A.page_depenses("2000.00", "300.00")), "depense_marketing_plafond")[
            "gravite"
        ]
        == "CRITIQUE"
    )


def test_depense_marketing_non_branchee_ou_partielle_n_est_jamais_une_depense_nulle():
    chaine: list = []
    A.capturer(chaine, "m7.depenses_marketing", A.ok(A.m7.charge_partielle("1800.00")))
    res = A.radar(chaine, seuils=S)
    assert not res["risques"] and A.non_evaluee(res, "depense_marketing_plafond")[0]["raison"] == "PARTIELLE"


# ------------------------------------------------------------------------------------------------ leads (M2)
def test_leads_la_borne_haute_de_l_intervalle_de_m2_sous_le_plancher_declare():
    res = _un("m2.prevision_pipeline", A.page_prevision(haut="4.00"))
    risques = [r for r in res["risques"] if r["regle"] == "leads_sous_plancher"]
    assert {r["sujet"] for r in risques} == {"periode:1", "periode:2"}
    r = risques[0]
    assert (r["domaine"], r["gravite"]) == ("ventes", "MOYEN")
    assert r["mesure"]["borne_haute"] == "4" and r["seuil"]["valeur"] == "5"
    egal = _un("m2.prevision_pipeline", A.page_prevision(haut="5.00", centre="4.00"))
    assert not egal["risques"], "borne haute égale au plancher : pas de baisse signalée"


def test_leads_une_prevision_refusee_par_m2_est_un_risque_inconnu():
    page = A.ok({"accepte": False, "verdict": {"code": "REJ-PREV-HISTORIQUE-INSUFFISANT", "detail": "x"}})
    chaine: list = []
    A.capturer(chaine, "m2.prevision_pipeline", page)
    res = A.radar(chaine, seuils=S)
    assert not res["risques"] and A.non_evaluee(res, "leads_sous_plancher")[0]["raison"] == "REFUSEE"


# -------------------------------------------------------------------------------- estimation et matériaux (M3, M6)
def test_estimation_ecart_relatif_de_m3_au_seuil_declare():
    res = _un(
        "m3.ecarts",
        A.page_ecarts(
            A.ligne_ecart("w1", ecart="0.25"), A.ligne_ecart("w2", ecart="0.24"), A.ligne_ecart("w3", ecart="-0.40")
        ),
    )
    r = _seule(res, "estimation_ecart_main_doeuvre")
    assert (r["domaine"], r["sujet"], r["gravite"]) == ("estimation", "wct:w1", "ELEVE")
    assert r["mesure"] == {"ecart_relatif": "0.25", "unite": "fraction"}
    assert r["seuil"]["reglage"] == "m9.estimation_ecart_relatif_max"
    critique = _un("m3.ecarts", A.page_ecarts(A.ligne_ecart("w1", ecart="0.38")))
    assert _seule(critique, "estimation_ecart_main_doeuvre")["gravite"] == "CRITIQUE"


def test_estimation_sans_ecart_calculable_ne_signale_rien():
    ligne = A.ligne_ecart("w1")
    ligne["main_doeuvre"]["ecart_relatif"] = None
    ligne["main_doeuvre"]["verdict"] = {"code": "REJ-ECART-DEVIS-ID-ABSENT"}
    assert not _un("m3.ecarts", A.page_ecarts(ligne))["risques"]


def test_variance_critique_de_m6_via_m3_est_un_risque_de_materiaux_sans_seuil_de_m9():
    res = _un(
        "m3.ecarts",
        A.page_ecarts(
            A.ligne_ecart("w1", signal=True), A.ligne_ecart("w2", signal=False), A.ligne_ecart("w3", signal=None)
        ),
        seuils={},
    )
    r = _seule(res, "materiaux_variance_critique")
    assert (r["domaine"], r["sujet"], r["seuil"]) == ("materiaux", "wct:w1", None)
    assert r["mesure"] == {"seuil_pourcentage_m6": 10}


def test_stock_disponible_negatif_chez_m6():
    res = _un(
        "m6.disponibilite",
        A.page_disponibilite([A.article("a", "-3"), A.article("b", "0"), A.article("c", "5")]),
        seuils={},
    )
    r = _seule(res, "materiaux_disponible_negatif")
    assert (r["domaine"], r["sujet"], r["mesure"]) == ("materiaux", "materiau:a", {"disponible": "-3"})


# ---------------------------------------------------------------------------------------- retard de chantier (M4)
def test_retard_prolonge_au_nombre_de_jours_declare():
    res = _un(
        "m4.retards_incidents",
        A.page_retards(reports=[("I1", "client", "2026-10-23T12:00:00Z"), ("I2", "client", "2026-10-24T12:00:00Z")]),
    )
    r = _seule(res, "chantier_retard_prolonge")
    assert (r["domaine"], r["sujet"], r["gravite"]) == ("chantiers", "retard:I1", "ELEVE")
    assert r["mesure"] == {"valeur": "5", "unite": "jours"} and r["seuil"]["valeur"] == "5"
    # le report de 4 jours n'est qu'un report ordinaire (règle historique), pas un retard prolongé
    assert ("capacite_report_en_cours", "report:I2") in A.par_regle(res)
    critique = _un("m4.retards_incidents", A.page_retards(reports=[("I1", "meteo", "2026-10-20T12:00:00Z")]))
    assert _seule(critique, "chantier_retard_prolonge")["gravite"] == "CRITIQUE"


def test_retard_tres_au_dessus_du_seuil_reste_eleve_tant_que_le_multiple_critique_n_est_pas_declare():
    sans = {k: v for k, v in S.items() if k != "multiple_seuil_critique"}
    page = A.page_retards(reports=[("I1", "meteo", "2026-10-01T12:00:00Z")])
    res = _un("m4.retards_incidents", page, seuils=sans)
    r = _seule(res, "chantier_retard_prolonge")
    assert r["gravite"] == "ELEVE" and r["seuil"]["critique_si_au_moins"] is None
    assert not [x for x in res["risques"] if x["gravite"] == "CRITIQUE"]


def test_une_regle_sla_dite_non_evaluee_par_m2_ne_compte_jamais_de_violation_meme_si_un_nombre_y_figure():
    ligne = {"regle": "photos_non_recues", "etat": "non_evaluee", "manque": "délai à déclarer", "violations": 2}
    assert rk._signal_sla(ligne, rk.Contexte({}, None, None)) is None
    evaluee = dict(ligne, etat="evaluee")
    assert rk._signal_sla(evaluee, rk.Contexte({}, None, None)).mesure["valeur"] == "2"


# ----------------------------------------------------------------------------------------------- cash libre (M5/M8)
def test_cash_libre_negatif_est_critique_sans_aucun_reglage():
    res = _un("m8.vue_executive", A.page_cash_libre("-120.00"), seuils={})
    r = _seule(res, "cash_libre_deficit")
    assert (r["domaine"], r["gravite"], r["seuil"]) == ("cash", "CRITIQUE", None)
    assert r["mesure"] == {"valeur": "-120.00", "unite": "CAD"}
    assert not [x for x in res["risques"] if x["regle"] == "cash_libre_sous_plancher"]


def test_cash_libre_sous_le_plancher_declare_mais_positif_est_eleve():
    res = _un("m8.vue_executive", A.page_cash_libre("4999.99"))
    r = _seule(res, "cash_libre_sous_plancher")
    assert (r["gravite"], r["seuil"]["valeur"]) == ("ELEVE", "5000")
    assert not _un("m8.vue_executive", A.page_cash_libre("5000.00"))["risques"]


def test_cash_libre_exactement_nul_n_est_pas_un_deficit_mais_reste_sous_le_plancher_declare():
    res = _un("m8.vue_executive", A.page_cash_libre("0.00"))
    assert not [r for r in res["risques"] if r["regle"] == "cash_libre_deficit"]
    assert _seule(res, "cash_libre_sous_plancher")["gravite"] == "ELEVE"


def test_cash_libre_non_calculable_ou_sans_constat_est_inconnu_pas_nul():
    for page in (A.page_cash_libre(None, statut="NON_CALCULABLE"), A.page_cash_libre(None, statut="manque")):
        res = _un("m8.vue_executive", page)
        r = _seule(res, "cash_libre_non_calculable")
        assert (r["gravite"], r["domaine"]) == ("INCONNU", "cash")


# --------------------------------------------------------------------------------------------- SLA du filet (M2)
def test_sla_du_filet_compte_les_violations_par_regle_et_dit_les_regles_non_evaluees_par_m2():
    page = A.page_sla(
        violations={"lead_chaud_non_contacte": 2, "tache_en_retard": 1}, non_evaluees=("photos_non_recues",)
    )
    res = _un("m2.sla_filet", page, seuils={})
    chaud = A.par_regle(res)[("filet_sla_violation", "sla:lead_chaud_non_contacte")]
    assert (chaud["domaine"], chaud["gravite"], chaud["mesure"]) == (
        "ventes",
        "ELEVE",
        {"valeur": "2", "unite": "violations"},
    )
    assert A.par_regle(res)[("filet_sla_violation", "sla:tache_en_retard")]["gravite"] == "MOYEN"
    amont = [n for n in res["regles_non_evaluees"] if n["regle"] == "filet_sla_violation:photos_non_recues"]
    assert amont and amont[0]["raison"] == "NON_EVALUEE_PAR_LE_PROPRIETAIRE"
    assert not [r for r in res["risques"] if "photos" in r["sujet"]]


def test_sla_sans_violation_est_evalue_sans_risque():
    res = _un("m2.sla_filet", A.page_sla(), seuils={})
    assert not res["risques"] and "filet_sla_violation" in res["regles_evaluees"]


# ------------------------------------------------------------------------------------------------ données périmées
def test_donnees_perimees_au_dela_de_l_age_declare_seulement():
    chaine: list = []
    A.capturer(chaine, "m6.disponibilite", A.page_disponibilite(), recu="2026-10-10T12:00:00Z")
    A.capturer(chaine, "m8.vue_executive", A.page_cash_libre(), recu="2026-10-20T12:00:00Z")
    res = A.radar(chaine, seuils=S)
    r = _seule(res, "donnees_perimees")
    assert (r["domaine"], r["sujet"], r["gravite"]) == ("donnees", "lecture:m6.disponibilite", "MOYEN")
    assert r["mesure"] == {"valeur": "18", "unite": "jours"} and r["seuil"]["valeur"] == "14"
    juste = A.radar(chaine, seuils=S, connaissance="2026-10-24T12:00:00Z")
    assert not [x for x in juste["risques"] if x["regle"] == "donnees_perimees"], "14 jours pile : encore à jour"


# --------------------------------------------------------------------------------- seuils non déclarés ou refusés
@pytest.mark.parametrize("regle", [r for r in rk.REGLES if r.seuils and r.id != "donnees_perimees"], ids=lambda r: r.id)
def test_sans_seuil_declare_la_regle_n_est_pas_evaluee_et_dit_quoi_declarer(regle):
    pages = {
        "plaintes_afflux": A.page_plaintes(9),
        "capacite_surcharge_cedule": A.page_capacite([("eq-a", 600, 900)]),
        "depense_marketing_plafond": A.page_depenses("9000.00", "9000.00"),
        "leads_sous_plancher": A.page_prevision(haut="1.00", centre="0.50", bas="0.10"),
        "estimation_ecart_main_doeuvre": A.page_ecarts(A.ligne_ecart(ecart="0.90")),
        "chantier_retard_prolonge": A.page_retards(reports=[("I1", "client", "2026-01-01T12:00:00Z")]),
        "cash_libre_sous_plancher": A.page_cash_libre("10.00"),
    }
    res = _un(regle_lecture(regle), pages[regle.id], seuils={})
    entree = A.non_evaluee(res, regle.id)
    assert len(entree) == 1 and entree[0]["raison"] == "SEUIL_NON_DECLARE"
    assert entree[0]["a_declarer"] == [rk.REGLAGES[n].cle for n in regle.seuils]
    for cle in entree[0]["a_declarer"]:
        assert (
            res["reglages_a_declarer"][cle]["ou"] == "Réglages de direction"
            and res["reglages_a_declarer"][cle]["libelle"]
        )
    assert not [r for r in res["risques"] if r["regle"] == regle.id], (
        "jamais un risque sans seuil, jamais « aucun risque »"
    )
    assert regle.id not in res["regles_evaluees"]


def regle_lecture(regle):
    return regle.lecture_id


def test_une_lecture_absente_dit_aussi_quoi_declarer():
    res = A.radar([], seuils={})
    entree = A.non_evaluee(res, "plaintes_afflux")[0]
    assert entree["raison"] == "ABSENTE" and entree["a_declarer"] == ["m9.plaintes_seuil_nombre"]
    sans_seuil = A.non_evaluee(res, "filet_sla_violation")[0]
    assert sans_seuil["raison"] == "ABSENTE" and "a_declarer" not in sans_seuil


def test_un_seuil_refuse_par_sa_declaration_est_traite_comme_non_declare_avec_le_code():
    res = _un(
        "m1.plaintes_structurees",
        A.page_plaintes(9),
        seuils={},
        seuils_refuses={"plaintes_seuil_nombre": "REJ-REGLAGE-HORS-BORNES"},
    )
    assert A.non_evaluee(res, "plaintes_afflux")[0]["a_declarer"] == ["m9.plaintes_seuil_nombre"]
    assert res["reglages_a_declarer"]["m9.plaintes_seuil_nombre"]["refus"] == "REJ-REGLAGE-HORS-BORNES"


def test_donnees_perimees_sans_seuil_est_non_evaluee():
    res = A.radar([], seuils={})
    entree = A.non_evaluee(res, "donnees_perimees")[0]
    assert entree["raison"] == "SEUIL_NON_DECLARE" and entree["a_declarer"] == ["m9.donnees_perimees_jours"]


@pytest.mark.parametrize(
    "seuils",
    [
        {"inconnu": 1},
        {"plaintes_seuil_nombre": 0},
        {"plaintes_seuil_nombre": 2.5},
        {"plaintes_seuil_nombre": True},
        {"multiple_seuil_critique": "0.5"},
    ],
)
def test_un_seuil_inconnu_ou_invalide_passe_au_radar_est_refuse(seuils):
    with pytest.raises(ValueError, match="REJ-RISQUE-SEUIL"):
        A.radar([], seuils=seuils)


# ------------------------------------------------------------------------------------------ dimension et cohérence
def test_chaque_risque_reste_dans_le_domaine_de_sa_regle_et_cite_sa_propre_lecture():
    chaine: list = []
    A.capturer(chaine, "m1.plaintes_structurees", A.page_plaintes(9, categories=("avocat",)), 0)
    A.capturer(chaine, "m4.capacite_equipe", A.page_capacite([("eq-a", 600, 900)]), 1)
    A.capturer(chaine, "m8.vue_executive", A.page_cash_libre("-5.00"), 2)
    A.capturer(chaine, "m7.depenses_marketing", A.page_depenses("2000.00", "900.00"), 3)
    res = A.radar(chaine, seuils=S)
    assert res["risques"]
    for r in res["risques"]:
        assert r["domaine"] == rk.DOMAINES[r["regle"]], r
        assert r["source"]["lecture_id"] == LECTURE_DE.get(r["regle"], r["source"]["lecture_id"]), r
    domaines = {r["regle"]: r["domaine"] for r in res["risques"]}
    assert domaines["capacite_surcharge_cedule"] == "capacite" and domaines["cash_libre_deficit"] == "cash"
    assert domaines["plaintes_afflux"] == "plaintes" and domaines["depense_marketing_plafond"] == "marketing"


def test_le_tri_met_les_critiques_avant_les_eleves_et_le_delta_nomme_la_gravite():
    chaine: list = []
    A.capturer(chaine, "m1.plaintes_structurees", A.page_plaintes(3), 0, recu="2026-10-26T12:00:00Z")
    A.capturer(chaine, "m1.plaintes_structurees", A.page_plaintes(6), 1, recu="2026-10-28T11:00:00Z")
    A.capturer(chaine, "m8.vue_executive", A.page_cash_libre("-1.00"), 2, recu="2026-10-28T12:00:01Z")
    res = A.radar(chaine, seuils=S)
    assert [r["gravite"] for r in res["risques"][:2]] == ["CRITIQUE", "CRITIQUE"]
    delta = rk.delta(chaine, connaissance=A.CONNAISSANCE, jours=1, seuils=S)
    assert {(a["regle"], a["gravite"]) for a in delta["apparus"]} >= {("cash_libre_deficit", "CRITIQUE")}
    assert delta["gravite_changee"] == [
        {
            "regle": "plaintes_afflux",
            "sujet": "plaintes_periode",
            "domaine": "plaintes",
            "gravite": "CRITIQUE",
            "gravite_precedente": "ELEVE",
        }
    ]


def test_le_radar_est_deterministe_et_ses_seuils_declares_sont_rendus():
    chaine: list = []
    A.capturer(chaine, "m1.plaintes_structurees", A.page_plaintes(3))
    un, deux = A.radar(chaine, seuils=S), A.radar(copy.deepcopy(chaine), seuils=dict(S))
    assert un == deux and un["radar_id"] == deux["radar_id"]
    assert un["seuils_declares"]["m9.plaintes_seuil_nombre"] == "3"
    autre = A.radar(chaine, seuils={**S, "plaintes_seuil_nombre": 4})
    assert autre["radar_id"] != un["radar_id"] and not autre["risques"]


def test_la_peremption_par_defaut_est_l_age_declare_par_la_direction_l_argument_l_emporte():
    chaine: list = []
    A.capturer(chaine, "m1.plaintes_structurees", A.page_plaintes(3), 0, recu="2026-10-10T12:00:00Z")
    declare = A.radar(chaine, seuils=S)  # 18 jours d'âge, âge déclaré : 14
    r = _seule(declare, "plaintes_afflux")
    assert r["statut"] == "A_RECONFIRMER" and r["source"]["age_jours"] == 18
    assert (declare["perime_apres_jours"], declare["perime_origine"]) == (14, "reglage")
    assert r["donnees_manquantes"], "une source périmée est à reconfirmer, jamais affirmée"
    argument = A.radar(chaine, seuils=S, perime_apres_jours=30)
    assert _seule(argument, "plaintes_afflux")["statut"] == "ACTIF"
    assert (argument["perime_apres_jours"], argument["perime_origine"]) == (30, "argument")
    sans = A.radar(chaine, seuils={k: v for k, v in S.items() if k != "donnees_perimees_jours"})
    assert _seule(sans, "plaintes_afflux")["statut"] == "ACTIF" and sans["perime_origine"] is None
