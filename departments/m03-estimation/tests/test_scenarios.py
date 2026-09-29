"""PLAN T4.11 (M3.11, M3.12), `scenarios.py` : P50 et P80 du coût, facteurs dominants, trois scénarios de prix.

Module pur, éprouvé sans base ni outil. Ce que ces tests prouvent :

- P50 et P80 sont lus sur les MÊMES tirages que l'intervalle (égalité exacte, jamais approchée) ; `P50 <= P80` ;
  mêmes entrées, mêmes montants, bit à bit ; PERT si le barème fournit un mode, uniforme sinon, dit poste par poste ;
- les facteurs dominants sortent d'un calcul exact (variance de chaque poste, indépendance des postes), vérifié sur un
  barème fictif dont la réponse est connue d'avance ;
- un scénario de prix = coût x (1 + taux), avec un taux FOURNI par l'appelant ou la configuration : sans taux, aucun
  prix et un verdict qui dit où le déclarer ; un taux fourni de travers ne devient jamais un prix ;
- chaque scénario est confronté au minimum rentable par le mécanisme de motifs de T4.7 (`revue_devis`) : sous le
  minimum, alerte rouge et le motif que la revue N4 montrera ; minimum non déclaré : « non évaluable », jamais « pas
  d'alerte » ;
- tous les montants sont des `Decimal` arrondis au cent (`ROUND_HALF_UP`), comme le reste de M3.

Les données sont fictives (`fictif: true`) : aucun coût, aucun taux, aucun minimum réels.
"""

from __future__ import annotations

import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from m3_estimation import devis_durable, monte_carlo, revue_devis, scenarios, verdicts  # noqa: E402

FICTIF = True
SERVICE = "ravalement"
DEVIS_ID = "M3-DEVIS-fictif-0001"
CENT = Decimal("0.01")
ROUGE = revue_devis.PRIX_SOUS_MINIMUM_RENTABLE


def _bareme(**poste):
    valeurs = {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}
    valeurs.update(poste)
    return {"version": "fictif-2026.1", "unite": "pi2", "postes": {SERVICE: valeurs}}


BAREME_A_TROIS_POSTES = {
    "version": "fictif-2026.1",
    "unite": "pi",
    "postes": {
        "gouttieres": {"cout_unitaire_min": 10.0, "cout_unitaire_max": 12.0},
        "revetement": {"cout_unitaire_min": 20.0, "cout_unitaire_max": 60.0},
        "soffite_fascia": {"cout_unitaire_min": 15.0, "cout_unitaire_max": 25.0},
    },
}
SERVICES_A_TROIS_POSTES = ("gouttieres", "revetement", "soffite_fascia")


def _arrondi(valeur):
    return Decimal(str(valeur)).quantize(CENT, rounding=ROUND_HALF_UP)


def _distribution(bareme=None, graine=42, quantite=1200):
    distribution, verdict = scenarios.distribution_du_cout(
        bareme or _bareme(), SERVICE, quantite, graine, services=(SERVICE,))
    assert verdict is None, verdict
    return distribution


def _scenarios(distribution=None, taux_appel=None, taux_configures=None, seuils=None):
    section, verdict = scenarios.scenarios_de_prix(
        distribution or _distribution(), DEVIS_ID, taux_appel, taux_configures, seuils)
    assert verdict is None, verdict
    return section


def _par_nom(section):
    return {s["scenario"]: s for s in section["scenarios"]}


def _flottants(objet, chemin="racine"):
    """Les chemins où un `float` se cache dans une sortie : il ne doit y en avoir aucun (montants en `Decimal`)."""
    if isinstance(objet, float):
        return [chemin]
    if isinstance(objet, dict):
        return [c for cle, v in objet.items() for c in _flottants(v, f"{chemin}.{cle}")]
    if isinstance(objet, (list, tuple)):
        return [c for i, v in enumerate(objet) for c in _flottants(v, f"{chemin}[{i}]")]
    return []


# ===================================================================================== P50 et P80 du coût
def test_p50_et_p80_sont_des_decimaux_arrondis_au_cent():
    distribution = _distribution()
    for cle in ("p50", "p80"):
        assert isinstance(distribution[cle], Decimal)
        assert distribution[cle] == distribution[cle].quantize(CENT)


@pytest.mark.parametrize("graine", range(1, 31))
def test_p50_ne_depasse_jamais_p80(graine):
    distribution = _distribution(graine=graine)
    assert distribution["p50"] <= distribution["p80"]


def test_p80_est_la_borne_haute_de_l_intervalle_a_soixante_pour_cent_sur_les_memes_tirages():
    """Les mêmes graine et tirages que l'intervalle : P80 égale, au cent près de l'arrondi, la borne haute de
    l'intervalle de niveau 0,6 rendue par `simuler_intervalle`, et P50 son rang central."""
    distribution = _distribution(graine=20260929)
    p80, _ = monte_carlo.simuler_intervalle(_bareme(), SERVICE, 1200, 20260929, 0.6, services=(SERVICE,))
    p50, _ = monte_carlo.simuler_intervalle(_bareme(), SERVICE, 1200, 20260929, 1e-9, services=(SERVICE,))
    assert distribution["p80"] == _arrondi(p80["borne_haute"])
    assert distribution["p50"] == _arrondi(p50["borne_haute"])


def test_p50_et_p80_tombent_dans_l_intervalle_de_l_estimation():
    distribution = _distribution(graine=7)
    intervalle, _ = monte_carlo.simuler_intervalle(_bareme(), SERVICE, 1200, 7, 0.9, services=(SERVICE,))
    assert _arrondi(intervalle["borne_basse"]) <= distribution["p50"] <= distribution["p80"]
    assert distribution["p80"] <= _arrondi(intervalle["borne_haute"])


def test_meme_graine_memes_montants_bit_a_bit():
    premier = _distribution(graine=20260929)
    _distribution(graine=5)  # un appel entrelacé ne contamine rien
    assert _distribution(graine=20260929) == premier


def test_une_autre_graine_donne_d_autres_montants():
    assert _distribution(graine=1) != _distribution(graine=2)


def test_la_distribution_annonce_ses_tirages_et_sa_graine():
    distribution = _distribution(graine=1234)
    assert distribution["tirages"] == monte_carlo.NOMBRE_TIRAGES
    assert distribution["graine"] == 1234


def test_les_cles_de_la_distribution_sont_fermees():
    distribution = _distribution()
    assert set(distribution) == set(scenarios.CHAMPS_DISTRIBUTION_COUT)
    assert set(distribution["postes"][0]) == set(scenarios.CHAMPS_LOI_DU_POSTE)


def test_sans_mode_le_tirage_est_uniforme_et_la_sortie_le_dit():
    (poste,) = _distribution()["postes"]
    assert poste["poste"] == SERVICE
    assert poste["loi"] == "uniforme"
    assert poste["mode"] is None
    assert "cout_unitaire_mode" in poste["raison"]  # dit pourquoi : aucun mode fourni par le barème


def test_avec_un_mode_le_tirage_est_pert_et_la_sortie_le_dit():
    (poste,) = _distribution(_bareme(cout_unitaire_mode=9.0))["postes"]
    assert poste["loi"] == "PERT"
    assert poste["mode"] == Decimal("9.00")
    assert "PERT" in poste["raison"]


def test_pert_et_uniforme_donnent_des_montants_differents_sur_le_meme_barème():
    uniforme = _distribution()
    pert = _distribution(_bareme(cout_unitaire_mode=9.0))
    assert (pert["p50"], pert["p80"]) != (uniforme["p50"], uniforme["p80"])
    assert pert["p50"] < uniforme["p50"] and pert["p80"] < uniforme["p80"]  # un mode bas tire la loi vers le bas


def test_l_intervalle_de_l_estimation_suit_la_meme_loi_quand_un_mode_existe():
    """Pas d'incohérence entre l'intervalle et P50/P80 : avec un mode, les deux viennent du tirage PERT."""
    bareme = _bareme(cout_unitaire_mode=9.0)
    distribution = _distribution(bareme, graine=11)
    intervalle, _ = monte_carlo.simuler_intervalle(bareme, SERVICE, 1200, 11, 0.9, services=(SERVICE,))
    assert _arrondi(intervalle["borne_basse"]) <= distribution["p50"] <= distribution["p80"]
    assert distribution["p80"] <= _arrondi(intervalle["borne_haute"])


@pytest.mark.parametrize(
    "bareme",
    [None, {"version": "v", "unite": "u"}, _bareme(cout_unitaire_min=20.0), _bareme(cout_unitaire_mode=99.0)],
    ids=["sans_bareme", "bareme_incomplet", "bornes_inversees", "mode_hors_bornes"],
)
def test_un_bareme_inutilisable_est_un_verdict_jamais_un_montant(bareme):
    distribution, verdict = scenarios.distribution_du_cout(bareme, SERVICE, 1200, 42, services=(SERVICE,))
    assert distribution is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_un_poste_absent_du_bareme_est_un_verdict():
    distribution, verdict = scenarios.distribution_du_cout(_bareme(), "gouttieres", 1200, 42, services=("gouttieres",))
    assert distribution is None
    assert "gouttieres" in verdict["detail"]


# ====================================================================================== facteurs dominants
def _facteurs(quantites, bareme=None, services=SERVICES_A_TROIS_POSTES):
    facteurs, verdict = scenarios.facteurs_dominants(bareme or BAREME_A_TROIS_POSTES, quantites, services=services)
    assert verdict is None, verdict
    return facteurs


QUANTITES_CONNUES = {"gouttieres": 100, "revetement": 50, "soffite_fascia": 10}


def test_le_poste_qui_fait_le_plus_varier_le_cout_est_premier_sur_un_bareme_dont_la_reponse_est_connue():
    """Amplitudes (quantité x étendue) : gouttières 200, revêtement 2000, soffite 100. Variances uniformes (amplitude²
    / 12) : 40000/12, 4000000/12, 10000/12 sur un total de 4050000/12 : parts 0,0099, 0,9877 et 0,0025."""
    facteurs = _facteurs(QUANTITES_CONNUES)
    assert [f["poste"] for f in facteurs] == ["revetement", "gouttieres", "soffite_fascia"]
    assert [f["rang"] for f in facteurs] == [1, 2, 3]
    assert [f["amplitude"] for f in facteurs] == [Decimal("2000.00"), Decimal("200.00"), Decimal("100.00")]
    assert [f["part_variance"] for f in facteurs] == [Decimal("0.9877"), Decimal("0.0099"), Decimal("0.0025")]


def test_la_quantite_change_le_classement():
    """Le même barème, d'autres quantités : les gouttières (200 pi) passent devant le revêtement (2 pi)."""
    facteurs = _facteurs({"gouttieres": 1000, "revetement": 2, "soffite_fascia": 1})
    assert facteurs[0]["poste"] == "gouttieres"
    assert facteurs[0]["amplitude"] == Decimal("2000.00")


def test_les_parts_de_variance_somment_a_un_a_l_arrondi_pres():
    facteurs = _facteurs(QUANTITES_CONNUES)
    assert abs(sum(f["part_variance"] for f in facteurs) - Decimal("1")) <= Decimal("0.0003")


def test_un_seul_poste_porte_toute_la_variance():
    (facteur,) = _facteurs({"revetement": 50})
    assert facteur == {"rang": 1, "poste": "revetement", "amplitude": Decimal("2000.00"),
                       "part_variance": Decimal("1.0000")}


def test_un_mode_central_resserre_la_loi_donc_le_poste_pert_passe_derriere_l_uniforme_de_meme_amplitude():
    """Deux postes de même étendue et de même quantité : la loi PERT centrée (variance 1/28 de l'étendue²) est plus
    resserrée que l'uniforme (1/12) : le poste uniforme domine, avec 7/(7+3) = 70 % de la variance."""
    bareme = {
        "version": "fictif", "unite": "u",
        "postes": {
            "a_pert": {"cout_unitaire_min": 10.0, "cout_unitaire_max": 20.0, "cout_unitaire_mode": 15.0},
            "b_uniforme": {"cout_unitaire_min": 30.0, "cout_unitaire_max": 40.0},
        },
    }
    facteurs = _facteurs({"a_pert": 10, "b_uniforme": 10}, bareme, services=("a_pert", "b_uniforme"))
    assert [f["poste"] for f in facteurs] == ["b_uniforme", "a_pert"]
    assert facteurs[0]["part_variance"] == Decimal("0.7000")
    assert facteurs[1]["part_variance"] == Decimal("0.3000")


def test_un_mode_decale_change_la_variance_du_poste():
    """Bêta PERT : variance = étendue² x a x b / 252, avec a et b = 1 + 4 x (distance au mode) / étendue. Mode à 25 %
    de l'étendue : a = 2, b = 4, donc 8/252 ; mode central : 3 x 3 / 252 = 9/252. Le mode central varie plus."""
    def _part(mode):
        bareme = {
            "version": "fictif", "unite": "u",
            "postes": {
                "p": {"cout_unitaire_min": 0.0, "cout_unitaire_max": 4.0, "cout_unitaire_mode": mode},
                "q": {"cout_unitaire_min": 0.0, "cout_unitaire_max": 4.0},
            },
        }
        return {f["poste"]: f["part_variance"] for f in
                _facteurs({"p": 1, "q": 1}, bareme, services=("p", "q"))}["p"]
    # p contre un poste uniforme de même étendue (16/12) : 8/252 contre 1/12, puis 9/252 contre 1/12
    assert _part(1.0) == (Decimal(8) / 252 / (Decimal(8) / 252 + Decimal(1) / 12)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    assert _part(2.0) == (Decimal(9) / 252 / (Decimal(9) / 252 + Decimal(1) / 12)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    assert _part(1.0) < _part(2.0)


def test_a_egalite_le_nom_du_poste_departage_et_les_rangs_restent_distincts():
    bareme = {
        "version": "fictif", "unite": "u",
        "postes": {"zeta": {"cout_unitaire_min": 1.0, "cout_unitaire_max": 3.0},
                   "alpha": {"cout_unitaire_min": 1.0, "cout_unitaire_max": 3.0}},
    }
    facteurs = _facteurs({"zeta": 5, "alpha": 5}, bareme, services=("zeta", "alpha"))
    assert [f["poste"] for f in facteurs] == ["alpha", "zeta"]
    assert [f["rang"] for f in facteurs] == [1, 2]
    assert [f["part_variance"] for f in facteurs] == [Decimal("0.5000"), Decimal("0.5000")]


def test_l_ordre_des_quantites_fournies_ne_change_rien():
    a = _facteurs({"gouttieres": 100, "revetement": 50, "soffite_fascia": 10})
    b = _facteurs({"soffite_fascia": 10, "revetement": 50, "gouttieres": 100})
    assert a == b


def test_des_couts_fixes_n_ont_aucun_facteur_dominant_et_le_disent():
    """Aucune variation : la variance totale est nulle. Pas de division par zéro, pas de part inventée."""
    bareme = {"version": "fictif", "unite": "u",
              "postes": {"a": {"cout_unitaire_min": 5.0, "cout_unitaire_max": 5.0},
                         "b": {"cout_unitaire_min": 7.0, "cout_unitaire_max": 7.0}}}
    facteurs = _facteurs({"b": 3, "a": 4}, bareme, services=("a", "b"))
    assert [f["part_variance"] for f in facteurs] == [None, None]
    assert [f["amplitude"] for f in facteurs] == [Decimal("0.00"), Decimal("0.00")]
    assert [f["poste"] for f in facteurs] == ["a", "b"]


def test_les_cles_d_un_facteur_dominant_sont_fermees():
    for facteur in _facteurs(QUANTITES_CONNUES):
        assert set(facteur) == set(scenarios.CHAMPS_FACTEUR_DOMINANT)


@pytest.mark.parametrize(
    "quantites",
    [None, {}, [("revetement", 1)], {"revetement": 0}, {"revetement": -3}, {"revetement": True},
     {"revetement": "50"}, {"revetement": float("nan")}, {"inconnu": 5}, {"revetement": 50, "inconnu": 5}],
    ids=["none", "vide", "liste", "zero", "negative", "booleenne", "texte", "nan", "poste_absent", "un_poste_absent"],
)
def test_des_quantites_inutilisables_sont_un_verdict(quantites):
    facteurs, verdict = scenarios.facteurs_dominants(
        BAREME_A_TROIS_POSTES, quantites, services=SERVICES_A_TROIS_POSTES)
    assert facteurs is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_un_bareme_qui_refuse_un_poste_refuse_les_facteurs():
    bareme = {"version": "v", "unite": "u", "postes": {"a": {"cout_unitaire_min": 9.0, "cout_unitaire_max": 1.0}}}
    facteurs, verdict = scenarios.facteurs_dominants(bareme, {"a": 1}, services=("a",))
    assert facteurs is None
    assert "bornes incohérentes" in verdict["detail"]


# ====================================================================================== scénarios : les taux
def test_sans_aucun_taux_aucun_prix_et_un_verdict_qui_dit_ou_declarer():
    section = _scenarios()
    assert [s["scenario"] for s in section["scenarios"]] == ["prudent", "normal", "agressif"]
    for scenario in section["scenarios"]:
        assert scenario["prix"] is None
        assert scenario["taux_marge"] is None
        assert scenario["source_taux"] is None
        assert scenario["alerte_rouge"] is None
        assert scenario["motifs"] == []
        assert scenario["verdict"]["code"] == "REJ-SCENARIOS-TAUX-ABSENT"
        assert f"taux_marge_scenarios.{scenario['scenario']}" in scenario["verdict"]["detail"]
        assert f"configuration.scenarios_prix.taux_marge.{scenario['scenario']}" in scenario["verdict"]["detail"]
    assert section["alerte_rouge"] is None


def test_le_verdict_d_un_taux_absent_appartient_au_catalogue_ferme_de_m3():
    for code in ("REJ-SCENARIOS-TAUX-ABSENT", "REJ-SCENARIOS-TAUX-INVALIDE"):
        assert code in verdicts.CODES_M3_LIST
        assert verdicts.construire_verdict(code, "x")["code"] == code


TAUX = {"prudent": "0.40", "normal": "0.30", "agressif": "0.15"}


def test_un_scenario_est_le_cout_de_base_fois_un_plus_le_taux_arrondi_au_cent():
    distribution = _distribution()
    section = _scenarios(distribution, taux_appel=TAUX)
    scenarios_par_nom = _par_nom(section)
    bases = {"prudent": distribution["p80"], "normal": distribution["p50"], "agressif": distribution["p50"]}
    for nom, taux in TAUX.items():
        entree = scenarios_par_nom[nom]
        attendu = (bases[nom] * (1 + Decimal(taux))).quantize(CENT, rounding=ROUND_HALF_UP)
        assert entree["cout"] == bases[nom]
        assert entree["taux_marge"] == Decimal(taux)
        assert entree["prix"] == attendu
        assert entree["verdict"] is None
        assert entree["source_taux"] == "appel"


def test_la_base_de_cout_de_chaque_scenario_est_annoncee():
    entrees = _par_nom(_scenarios(taux_appel=TAUX))
    assert {nom: e["base_cout"] for nom, e in entrees.items()} == {
        "prudent": "P80", "normal": "P50", "agressif": "P50"}


def test_le_prix_reutilise_la_formule_de_prix_du_paquet():
    """Aucune seconde formule de prix : le scénario rend ce que `devis_durable.prix_depuis_cout` rend."""
    distribution = _distribution()
    entree = _par_nom(_scenarios(distribution, taux_appel=TAUX))["normal"]
    assert entree["prix"] == devis_durable.prix_depuis_cout(distribution["p50"], Decimal("0.30"))


def test_l_arrondi_est_au_cent_superieur_a_la_demie_pas_a_l_arrondi_bancaire():
    """100,10 x 1,05 = 105,105 : ROUND_HALF_UP donne 105,11 (l'arrondi bancaire donnerait 105,10)."""
    distribution = {"p50": Decimal("100.10"), "p80": Decimal("100.10")}
    entree = _par_nom(_scenarios(distribution, taux_appel={"normal": "0.05"}))["normal"]
    assert entree["prix"] == Decimal("105.11")


def test_un_taux_de_zero_vend_au_cout_et_c_est_permis():
    entree = _par_nom(_scenarios(taux_appel={"agressif": "0"}))["agressif"]
    assert entree["prix"] == entree["cout"]
    assert entree["verdict"] is None


def test_les_taux_de_la_configuration_valent_ceux_de_l_appel_quand_l_appel_se_tait():
    """Le YAML donne des nombres (0.35) : lus tels qu'écrits, pas par leur codage binaire."""
    section = _scenarios(taux_configures={"prudent": 0.35, "normal": "0.25", "agressif": 0.1})
    entrees = _par_nom(section)
    assert entrees["prudent"]["taux_marge"] == Decimal("0.35")
    assert entrees["normal"]["taux_marge"] == Decimal("0.25")
    assert entrees["agressif"]["taux_marge"] == Decimal("0.1")
    assert {e["source_taux"] for e in entrees.values()} == {"configuration"}


def test_l_appel_l_emporte_sur_la_configuration_scenario_par_scenario():
    section = _scenarios(taux_appel={"normal": "0.50"},
                         taux_configures={"prudent": "0.35", "normal": "0.25", "agressif": "0.10"})
    entrees = _par_nom(section)
    assert (entrees["prudent"]["taux_marge"], entrees["prudent"]["source_taux"]) == (Decimal("0.35"), "configuration")
    assert (entrees["normal"]["taux_marge"], entrees["normal"]["source_taux"]) == (Decimal("0.50"), "appel")
    assert (entrees["agressif"]["taux_marge"], entrees["agressif"]["source_taux"]) == (Decimal("0.10"), "configuration")


def test_un_taux_null_vaut_un_taux_absent():
    section = _scenarios(taux_appel={"normal": None}, taux_configures={"normal": None})
    assert _par_nom(section)["normal"]["verdict"]["code"] == "REJ-SCENARIOS-TAUX-ABSENT"


def test_un_taux_absent_n_empeche_pas_les_autres_scenarios():
    entrees = _par_nom(_scenarios(taux_appel={"normal": "0.30"}))
    assert entrees["normal"]["prix"] is not None
    assert entrees["prudent"]["prix"] is None and entrees["prudent"]["verdict"]["code"] == "REJ-SCENARIOS-TAUX-ABSENT"
    assert entrees["agressif"]["prix"] is None


@pytest.mark.parametrize(
    "taux",
    ["abc", "", " ", "0,30", "-1", "-0.05", "NaN", "Infinity", 0.3, 1, True, ["0.3"], {"taux": "0.3"}],
    ids=["texte", "vide", "espace", "virgule", "moins_un", "negatif", "nan", "infini", "flottant_json", "entier",
         "booleen", "liste", "objet"],
)
def test_un_taux_d_appel_fourni_de_travers_ne_donne_jamais_de_prix(taux):
    entree = _par_nom(_scenarios(taux_appel={"normal": taux}))["normal"]
    assert entree["prix"] is None
    assert entree["taux_marge"] is None
    assert entree["verdict"]["code"] == "REJ-SCENARIOS-TAUX-INVALIDE"
    assert "normal" in entree["verdict"]["detail"] and "appel" in entree["verdict"]["detail"]


@pytest.mark.parametrize("taux", ["abc", -0.05, "-1", True, [0.3], float("nan")],
                         ids=["texte", "negatif", "moins_un", "booleen", "liste", "nan"])
def test_un_taux_configure_de_travers_ne_donne_jamais_de_prix_et_nomme_la_configuration(taux):
    entree = _par_nom(_scenarios(taux_configures={"agressif": taux}))["agressif"]
    assert entree["prix"] is None
    assert entree["verdict"]["code"] == "REJ-SCENARIOS-TAUX-INVALIDE"
    assert "configuration" in entree["verdict"]["detail"]


def test_un_taux_appel_invalide_ne_retombe_pas_sur_la_configuration():
    """Une donnée fournie de travers est signalée, jamais remplacée en silence par une autre source."""
    entree = _par_nom(_scenarios(taux_appel={"normal": "abc"}, taux_configures={"normal": "0.25"}))["normal"]
    assert entree["prix"] is None
    assert entree["verdict"]["code"] == "REJ-SCENARIOS-TAUX-INVALIDE"


@pytest.mark.parametrize("appel", ["0.3", ["normal"], 0.3, {"normal": "0.3", "moyen": "0.2"}, {"Normal": "0.3"}])
def test_une_demande_mal_formee_est_refusee_en_bloc(appel):
    section, verdict = scenarios.scenarios_de_prix(_distribution(), DEVIS_ID, appel, None, None)
    assert section is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


@pytest.mark.parametrize(
    "configuration", ["0.3", ["normal"], 0.3, {"normal": "0.3", "moyen": "0.2"}, {"Normal": "0.3"}, "illisible"],
    ids=["texte", "liste", "nombre", "scenario_inconnu", "casse", "manifeste_illisible"],
)
def test_une_configuration_mal_formee_ne_donne_aucun_taux_et_ne_bloque_pas_l_estimation(configuration):
    """La configuration est celle de Nathan, l'estimation n'en dépend pas : une faute de forme (pas un objet, un
    scénario que personne ne connaît) est dite scénario par scénario, sans prix, sans rien refuser en bloc."""
    section, verdict = scenarios.scenarios_de_prix(_distribution(), DEVIS_ID, None, configuration, None)
    assert verdict is None
    for scenario in section["scenarios"]:
        assert scenario["prix"] is None
        assert scenario["verdict"]["code"] == "REJ-SCENARIOS-TAUX-INVALIDE"
        assert "configuration" in scenario["verdict"]["detail"]


def test_une_configuration_mal_formee_laisse_passer_les_taux_de_l_appel():
    entrees = _par_nom(_scenarios(taux_appel={"normal": "0.30"}, taux_configures="0.3"))
    assert entrees["normal"]["prix"] is not None and entrees["normal"]["source_taux"] == "appel"
    assert entrees["prudent"]["verdict"]["code"] == "REJ-SCENARIOS-TAUX-INVALIDE"
    assert entrees["agressif"]["prix"] is None


@pytest.mark.parametrize("devis_id", ["", "  ", None, 12])
def test_un_devis_id_inutilisable_refuse_la_revue_de_chaque_prix(devis_id):
    """Le `devis_id` sert la revue de T4.7 : elle le refuse, et le refus remonte tel quel (jamais un prix sans elle)."""
    section, verdict = scenarios.scenarios_de_prix(_distribution(), devis_id, TAUX, None, None)
    assert section is None
    assert verdict["code"] == "REJ-REVUE-DEVIS-INVALIDE"


# ============================================================================ scénarios : le minimum rentable
def _prix(distribution=None, taux=None):
    entrees = _par_nom(_scenarios(distribution, taux_appel=taux or TAUX))
    return {nom: e["prix"] for nom, e in entrees.items()}


def test_un_scenario_sous_le_minimum_rentable_leve_l_alerte_rouge_et_le_motif_de_revue():
    distribution = _distribution()
    prix = _prix(distribution)
    assert prix["agressif"] < prix["normal"] < prix["prudent"]
    minimum = prix["normal"]  # le prudent et le normal sont au-dessus (ou au minimum) ; l'agressif est dessous
    section = _scenarios(distribution, taux_appel=TAUX, seuils={"minimum_rentable_cad": str(minimum)})
    entrees = _par_nom(section)
    assert entrees["agressif"]["alerte_rouge"] is True
    (motif,) = entrees["agressif"]["motifs"]
    assert motif["code"] == ROUGE
    assert motif["gravite"] == revue_devis.GRAVITE_ROUGE
    assert motif["donnee"] == {"nom": "prix_total", "valeur": format(prix["agressif"], "f"), "source": "devis"}
    assert motif["seuil"]["nom"] == "minimum_rentable_cad"
    assert motif["seuil"]["source"] == "configuration"
    assert section["alerte_rouge"] is True
    assert section["non_evaluables"] == []


def test_un_prix_exactement_au_minimum_rentable_ne_leve_rien():
    """Comparaison stricte, comme `plancher.confronter_au_plancher` et la revue de T4.7."""
    distribution = _distribution()
    prix = _prix(distribution)
    entrees = _par_nom(_scenarios(distribution, taux_appel=TAUX, seuils={"minimum_rentable_cad": str(prix["normal"])}))
    assert entrees["normal"]["alerte_rouge"] is False
    assert entrees["normal"]["motifs"] == []
    assert entrees["prudent"]["alerte_rouge"] is False


def test_un_scenario_au_dessus_du_minimum_est_evalue_et_sans_alerte():
    distribution = _distribution()
    section = _scenarios(distribution, taux_appel=TAUX, seuils={"minimum_rentable_cad": 1})
    assert [s["alerte_rouge"] for s in section["scenarios"]] == [False, False, False]
    assert section["alerte_rouge"] is False


def test_tous_les_scenarios_sous_le_minimum_sont_rouges_chacun_avec_son_motif():
    section = _scenarios(taux_appel=TAUX, seuils={"minimum_rentable_cad": 10**9})
    assert [s["alerte_rouge"] for s in section["scenarios"]] == [True, True, True]
    assert all(len(s["motifs"]) == 1 for s in section["scenarios"])
    assert len({s["motifs"][0]["donnee"]["valeur"] for s in section["scenarios"]}) == 3


def test_le_motif_est_exactement_celui_que_la_revue_n4_de_t4_7_montrera_pour_ce_prix():
    """Le mécanisme est réutilisé, pas recopié : le motif d'un scénario égale celui que `revue_devis.evaluer_revue`
    rend pour un devis à ce prix et à ce taux."""
    distribution = _distribution()
    seuils = {"minimum_rentable_cad": 10**9}
    entree = _par_nom(_scenarios(distribution, taux_appel=TAUX, seuils=seuils))["agressif"]
    revue, verdict = revue_devis.evaluer_revue(
        {"devis_id": DEVIS_ID, "prix_total": entree["prix"], "taux_marge": entree["taux_marge"]}, None, seuils)
    assert verdict is None
    assert entree["motifs"] == [m for m in revue["motifs"] if m["code"] == ROUGE]


def test_le_seul_critere_juge_par_scenario_est_le_minimum_rentable():
    """Le montant maximal et la marge minimale se jugent sur le devis réel, à l'envoi (T4.7) : pas ici."""
    seuils = {"minimum_rentable_cad": 10**9, "montant_maximal_cad": 1, "marge_minimale": 0.99}
    for scenario in _scenarios(taux_appel=TAUX, seuils=seuils)["scenarios"]:
        assert [m["code"] for m in scenario["motifs"]] == [ROUGE]


@pytest.mark.parametrize(
    "seuils",
    [None, {}, {"minimum_rentable_cad": None}, {"marge_minimale": 0.2}],
    ids=["aucun_seuil", "seuils_vides", "minimum_vide", "un_autre_seuil_seulement"],
)
def test_un_minimum_non_declare_est_non_evaluable_jamais_pas_d_alerte(seuils):
    section = _scenarios(taux_appel=TAUX, seuils=seuils)
    assert [s["alerte_rouge"] for s in section["scenarios"]] == [None, None, None]
    assert all(s["motifs"] == [] and s["prix"] is not None for s in section["scenarios"])
    assert section["alerte_rouge"] is None
    (manque,) = section["non_evaluables"]
    assert manque["code"] == ROUGE
    assert manque["manque"] == ["seuil à configurer : minimum_rentable_cad"]
    assert manque["a_faire"] == ["renseigner minimum_rentable_cad dans department.yaml, configuration, revue_devis"]


@pytest.mark.parametrize("seuils", [{"minimum_rentable_cad": 0}, {"minimum_rentable_cad": -5},
                                    {"minimum_rentable_cad": "abc"}, {"minimum_rentable_cad": True}, "illisible"],
                         ids=["zero", "negatif", "texte", "booleen", "configuration_illisible"])
def test_un_minimum_invalide_est_non_evaluable_et_dit_pourquoi(seuils):
    section = _scenarios(taux_appel=TAUX, seuils=seuils)
    assert section["alerte_rouge"] is None
    (manque,) = section["non_evaluables"]
    assert manque["code"] == ROUGE
    assert "seuil invalide" in manque["manque"][0]


def test_le_manque_n_est_dit_qu_une_fois_pour_les_trois_scenarios():
    assert len(_scenarios(taux_appel=TAUX)["non_evaluables"]) == 1


def test_sans_prix_il_n_y_a_rien_a_confronter_donc_rien_a_dire_du_minimum():
    section = _scenarios(seuils=None)
    assert section["non_evaluables"] == []
    assert section["alerte_rouge"] is None


def test_l_alerte_de_la_section_est_vraie_des_qu_un_scenario_est_rouge_meme_si_un_autre_manque_de_taux():
    section = _scenarios(taux_appel={"agressif": "0.01"}, seuils={"minimum_rentable_cad": 10**9})
    assert _par_nom(section)["agressif"]["alerte_rouge"] is True
    assert _par_nom(section)["prudent"]["alerte_rouge"] is None
    assert section["alerte_rouge"] is True


# ===================================================================================== forme de la sortie
def test_les_cles_de_la_section_et_de_chaque_scenario_sont_fermees():
    section = _scenarios(taux_appel=TAUX, seuils={"minimum_rentable_cad": 10**9})
    assert set(section) == set(scenarios.CHAMPS_SCENARIOS_PRIX)
    for scenario in section["scenarios"]:
        assert set(scenario) == set(scenarios.CHAMPS_SCENARIO)
    sans_taux = _scenarios()
    for scenario in sans_taux["scenarios"]:
        assert set(scenario) == set(scenarios.CHAMPS_SCENARIO)


def test_aucun_montant_n_est_un_flottant_dans_aucune_sortie():
    resultat, verdict = scenarios.evaluer(
        _bareme(cout_unitaire_mode=9.0), SERVICE, 1200, 42, DEVIS_ID,
        taux_appel=TAUX, seuils_revue={"minimum_rentable_cad": 10**9}, services=(SERVICE,))
    assert verdict is None
    assert _flottants(resultat) == []


def test_les_montants_sont_au_cent_partout():
    resultat, _ = scenarios.evaluer(
        _bareme(), SERVICE, 1200, 42, DEVIS_ID, taux_appel=TAUX, services=(SERVICE,))
    for scenario in resultat["scenarios_prix"]["scenarios"]:
        for cle in ("cout", "prix"):
            assert scenario[cle] == scenario[cle].quantize(CENT)
    for facteur in resultat["facteurs_dominants"]:
        assert facteur["amplitude"] == facteur["amplitude"].quantize(CENT)


def test_evaluer_rend_exactement_les_trois_cles_soeurs_d_estimation_v1():
    resultat, verdict = scenarios.evaluer(_bareme(), SERVICE, 1200, 42, DEVIS_ID, services=(SERVICE,))
    assert verdict is None
    assert set(resultat) == set(scenarios.CHAMPS_SOEURS_ESTIMATION)


def test_evaluer_fait_du_poste_demande_l_unique_facteur_de_l_estimation():
    resultat, _ = scenarios.evaluer(_bareme(), SERVICE, 1200, 42, DEVIS_ID, services=(SERVICE,))
    (facteur,) = resultat["facteurs_dominants"]
    assert facteur["poste"] == SERVICE
    assert facteur["amplitude"] == Decimal("7200.00")  # 1200 x (14 - 8)
    assert facteur["part_variance"] == Decimal("1.0000")
    assert [p["poste"] for p in resultat["distribution_cout"]["postes"]] == [SERVICE]


def test_evaluer_est_deterministe_bit_a_bit():
    def _lancer():
        return scenarios.evaluer(
            _bareme(cout_unitaire_mode=9.0), SERVICE, 1200, 42, DEVIS_ID, taux_appel=TAUX,
            taux_configures={"prudent": "0.5"}, seuils_revue={"minimum_rentable_cad": 15000}, services=(SERVICE,))
    premier = _lancer()
    scenarios.evaluer(_bareme(), SERVICE, 1200, 7, DEVIS_ID, services=(SERVICE,))
    assert _lancer() == premier


@pytest.mark.parametrize("graine", range(1, 21))
def test_le_cout_de_base_du_scenario_prudent_est_p80_et_celui_des_autres_p50(graine):
    resultat, _ = scenarios.evaluer(_bareme(), SERVICE, 1200, graine, DEVIS_ID, taux_appel=TAUX, services=(SERVICE,))
    distribution = resultat["distribution_cout"]
    entrees = _par_nom(resultat["scenarios_prix"])
    assert entrees["prudent"]["cout"] == distribution["p80"]
    assert entrees["normal"]["cout"] == entrees["agressif"]["cout"] == distribution["p50"]


@pytest.mark.parametrize(
    ("bareme", "quantite", "graine"),
    [(None, 1200, 42), (_bareme(), 0, 42), (_bareme(), 1200, 4.5), (_bareme(cout_unitaire_mode="x"), 1200, 42)],
    ids=["sans_bareme", "quantite_nulle", "graine_flottante", "mode_illisible"],
)
def test_evaluer_refuse_ce_que_le_monte_carlo_refuse(bareme, quantite, graine):
    resultat, verdict = scenarios.evaluer(bareme, SERVICE, quantite, graine, DEVIS_ID, services=(SERVICE,))
    assert resultat is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_un_refus_de_taux_mal_forme_remonte_par_evaluer():
    resultat, verdict = scenarios.evaluer(
        _bareme(), SERVICE, 1200, 42, DEVIS_ID, taux_appel="0.3", services=(SERVICE,))
    assert resultat is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
