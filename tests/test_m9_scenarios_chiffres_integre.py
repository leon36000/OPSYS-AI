"""M9-C2 par les VRAIS moteurs : le Monte-Carlo de M5, la projection de capacité de M4 et l'intervalle de M2, appelés
par le
port privé de M9 sur de vraies données fictives. M9 recopie les chiffres et les reçus des propriétaires, fait rejouer
leurs
reçus par eux, et dit « non chiffré, manque X » quand un moteur est absent ou refuse (jamais zéro, jamais un chiffre
de M9).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from m9_strategic_intelligence import scenarios_chiffres

from opsys import contexte


def _charger(nom: str):
    if nom in sys.modules:
        return sys.modules[nom]
    spec = importlib.util.spec_from_file_location(nom, Path(__file__).with_name(f"{nom}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


W = _charger("m9_radar_monde")
B = W.B
FICTIF = True
JOUR, HORO = W.JOUR[1], W.T[1]
RETARD = {
    "choc": "retard_paiement_carnet",
    "parametres": {"part_carnet_pct": "30", "retard_semaines": 2},
    "jour": JOUR,
    "horodatage": HORO,
    "options": {"graine": 42, "tirages": 500},
}
ABSENCES = {
    "choc": "absences_equipe",
    "parametres": {"absences": [{"equipe_id": "eq-a", "personnes": 2, "jours": 5}]},
    "jour": JOUR,
    "horodatage": HORO,
    "options": {"debut_semaine": "2026-11-02"},
}


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = W.Monde(tmp_path, monkeypatch)
    m.cedule()
    m.mouvements()
    m.factures()
    m.historique_de_leads([3, 4, 2, 5, 3, 4, 3, 2, 4, 5, 3, 4, 3], W.T[1])
    yield m
    m.fermer()


def _sans(*retires: str):
    """Le dispatcher de M9 quand certains propriétaires NE SONT PAS installés : le port répond « indisponible »."""
    from opsys import stockage
    from opsys.capacites import Capacites
    from opsys.departements import charger_departements

    installes = {k: v for k, v in charger_departements().items() if k not in retires}
    return Capacites(installes, stockage.transaction, filtre={W.M9, *(set(installes) - {W.M9})}, memoire=False)


def _chiffrer(m, appel: dict, identite=W.ADMIN, cap=None) -> dict:
    cible = cap or m.cap
    if identite is None:
        return cible.appeler("m9_chiffrer_scenario", appel)
    with contexte.appele_par_appareil(identite):
        return cible.appeler("m9_chiffrer_scenario", appel)


def _scenario(m, appel: dict, cap=None) -> dict:
    reponse = _chiffrer(m, appel, cap=cap)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _direct(departement: str, outil: str, arguments: dict) -> dict:
    """Ce que le propriétaire répond, appelé directement par le port (même contexte que M9) : la vérité à recopier."""
    reponse = B.lire_par_le_port(departement, outil, arguments)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


# =================================================================================================== finance : M5
def test_retard_de_paiement_d_une_part_du_carnet_est_chiffre_par_le_monte_carlo_de_m5_avec_son_recu(monde):
    scenario = _scenario(monde, RETARD)
    impact = scenario["impacts"][0]
    assert impact["statut"] == "CHIFFRE" and impact["proprietaire"] == W.M5 and scenario["m9_calcule"] is False
    arguments = impact["source"]["arguments"]
    assert arguments["distributions"] == {"facture_client": {"retard": {"probabilite": "0.3", "semaines": 2}}}
    propre = _direct(W.M5, "m5_simuler_tresorerie_monte_carlo", arguments)["recu"]
    valeurs = impact["valeurs"]
    # chaque chiffre de M9 est celui du propriétaire, mot pour mot
    assert valeurs["plus_bas_du_chemin"] == propre["resultat"]["plus_bas_du_chemin"]
    assert (
        valeurs["probabilite_au_moins_une_semaine_negative"]
        == propre["resultat"]["probabilite_au_moins_une_semaine_negative"]
    )
    assert valeurs["solde_initial"] == propre["entrees"]["solde_initial"] == "20000.00"
    assert valeurs["flux_perturbes"] == propre["resultat"]["flux_perturbes"] == 2
    assert impact["recu"]["empreinte"] == propre["empreinte"] and "entrees" not in impact["recu"]
    assert impact["recu"]["resultat"] == propre["resultat"]
    # le reçu est REJOUÉ par M5 (pas par M9) : identique
    assert impact["verification"]["outil"] == "m5_verifier_recu_calcul" and impact["verification"]["identique"] is True
    rejeu = _direct(W.M5, "m5_verifier_recu_calcul", {"recu": propre})
    assert rejeu["identique"] is True and rejeu["empreinte_recalculee"] == impact["recu"]["empreinte"]


def test_une_autre_hypothese_ou_une_autre_graine_change_le_chiffre_et_le_recu_du_proprietaire(monde):
    base = _scenario(monde, RETARD)["impacts"][0]
    autre_part = _scenario(monde, {**RETARD, "parametres": {"part_carnet_pct": "100", "retard_semaines": 4}})[
        "impacts"
    ][0]
    autre_graine = _scenario(monde, {**RETARD, "options": {"graine": 43, "tirages": 500}})["impacts"][0]
    assert autre_part["recu"]["empreinte"] != base["recu"]["empreinte"]
    assert autre_part["valeurs"]["plus_bas_du_chemin"] != base["valeurs"]["plus_bas_du_chemin"]
    assert autre_graine["recu"]["empreinte"] != base["recu"]["empreinte"]
    assert _scenario(monde, RETARD)["scenario_id"] == _scenario(monde, RETARD)["scenario_id"], "déterministe"


def test_hausse_du_cout_des_materiaux_et_baisse_des_encaissements_sont_chiffrees_par_m5(monde):
    hausse = _scenario(
        monde,
        {
            **RETARD,
            "choc": "hausse_cout_materiaux",
            "parametres": {"hausse_min_pct": "5", "hausse_probable_pct": "12", "hausse_max_pct": "25"},
        },
    )["impacts"][0]
    assert hausse["statut"] == "CHIFFRE"
    assert hausse["source"]["arguments"]["distributions"]["facture_fournisseur"]["montant"] == {
        "loi": "triangulaire",
        "min": "1.05",
        "mode": "1.12",
        "max": "1.25",
    }
    baisse = _scenario(
        monde,
        {
            **RETARD,
            "choc": "baisse_encaissements",
            "parametres": {"baisse_min_pct": "10", "baisse_probable_pct": "20", "baisse_max_pct": "40"},
        },
    )["impacts"][0]
    assert baisse["statut"] == "CHIFFRE" and baisse["verification"]["identique"] is True
    propre = _direct(W.M5, "m5_simuler_tresorerie_monte_carlo", baisse["source"]["arguments"])["recu"]
    assert baisse["valeurs"]["plus_bas_du_chemin"] == propre["resultat"]["plus_bas_du_chemin"]


def test_achat_d_un_equipement_est_compare_par_m5_achat_contre_credit_bail(monde):
    appel = {
        "choc": "achat_equipement_comparaison",
        "jour": JOUR,
        "horodatage": HORO,
        "parametres": {
            "prix_achat": "40000",
            "frais_achat": "500",
            "valeur_residuelle": "8000",
            "paiement_mensuel": "900",
            "depot_initial": "1000",
            "mois": 48,
            "taux_actualisation_annuel": "0.08",
            "paiements_en_debut_de_periode": True,
        },
    }
    impact = _scenario(monde, appel)["impacts"][0]
    propre = _direct(W.M5, "m5_comparer_credit_bail_achat", impact["source"]["arguments"])["recu"]
    assert impact["statut"] == "CHIFFRE" and impact["valeurs"]["va_cout_achat"] == propre["resultat"]["va_cout_achat"]
    assert impact["valeurs"]["va_cout_credit_bail"] == propre["resultat"]["va_cout_credit_bail"]
    assert impact["valeurs"]["option_au_cout_actualise_le_plus_bas"] in {"achat", "credit_bail", "egalite"}
    assert impact["verification"]["identique"] is True


# ================================================================================================== capacité : M4
def test_deux_employes_absents_toute_la_semaine_sont_chiffres_par_m4_avec_un_recu_que_m4_rejoue(monde):
    scenario = _scenario(monde, ABSENCES)
    impact = scenario["impacts"][0]
    assert impact["statut"] == "CHIFFRE" and impact["proprietaire"] == W.M4 and scenario["dimension"] == "capacite"
    propre = _direct(W.M4, "m4_projeter_capacite_hypotheses", impact["source"]["arguments"])
    assert impact["valeurs"]["equipes"] == propre["equipes"], "les lignes d'équipe sont celles de M4, recopiées"
    a = {e["equipe_id"]: e for e in impact["valeurs"]["equipes"]}
    # 2 personnes × 5 jours × 480 min / effectif planifié 2 = 2 400 min = les 40 h de la semaine type d'eq-a
    assert a["eq-a"]["perte_absences_heures"] == "40.00" and a["eq-a"]["heures_disponibles_projetees"] == "0.00"
    assert a["eq-a"]["capacite_epuisee"] is True and a["eq-a"]["statut"] == "SURCHARGE"
    assert a["eq-b"]["heures_disponibles_projetees"] == "40.00" and a["eq-b"]["statut"] == "SUFFISANTE"
    assert impact["valeurs"]["equipes_en_surcharge"] == ["eq-a"]
    assert impact["recu"]["empreinte"] == propre["recu"]["empreinte"]
    assert impact["verification"] == {
        "outil": "m4_verifier_recu_projection_capacite",
        "mode": "rejeu",
        "identique": True,
        "empreinte": impact["recu"]["empreinte"],
    }
    assert impact["source"]["arguments"]["horodatage_reference"] == HORO, "l'instant de lecture est tracé au reçu"
    moins = _scenario(
        monde, {**ABSENCES, "parametres": {"absences": [{"equipe_id": "eq-a", "personnes": 1, "jours": 2}]}}
    )
    ligne = {e["equipe_id"]: e for e in moins["impacts"][0]["valeurs"]["equipes"]}["eq-a"]
    assert ligne["perte_absences_heures"] == "8.00" and ligne["heures_disponibles_projetees"] == "32.00"
    assert moins["impacts"][0]["recu"]["empreinte"] != impact["recu"]["empreinte"]


def test_mauvaise_meteo_et_hausse_de_la_demande_sont_chiffrees_par_m4(monde):
    meteo = _scenario(
        monde,
        {**ABSENCES, "choc": "meteo_jours_bloques", "parametres": {"jours_bloques": ["2026-11-03", "2026-11-04"]}},
    )["impacts"][0]
    lignes = {e["equipe_id"]: e for e in meteo["valeurs"]["equipes"]}
    assert all(
        e["perte_jours_bloques_heures"] == "16.00" and e["heures_disponibles_projetees"] == "24.00"
        for e in lignes.values()
    ), "deux jours de 8 h retirés à chaque équipe par M4"
    demande = _scenario(
        monde, {**ABSENCES, "choc": "hausse_demande_charge", "parametres": {"hausse_demande_pct": "1000"}}
    )["impacts"][0]
    eq_a = {e["equipe_id"]: e for e in demande["valeurs"]["equipes"]}["eq-a"]
    assert eq_a["heures_planifiees_base"] == "3.50" and eq_a["heures_planifiees_projetees"] == "38.50"
    assert eq_a["statut"] == "SUFFISANTE" and eq_a["utilisation_pct"] == "96.3"


def test_m4_sans_effectif_declare_les_absences_sont_non_chiffrees_et_m4_nomme_le_manque(monde):
    monde.profil_etendu()  # retire rien : on redéclare ensuite sans effectif
    import yaml

    from opsys import cli

    fichier = monde.tmp / "equipes-sans-effectif.yaml"
    profil = {
        "liste": [
            {
                "id": e,
                "membres": [mb],
                "competences": ["gouttieres"],
                "depot": {"id": d, **W.A.DEPOTS[d]},
                "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}],
                "semaine_type": {
                    "fuseau": "America/Montreal",
                    "lundi": [{"debut": "07:00", "fin": "15:00"}],
                    "mardi": [],
                    "mercredi": [],
                    "jeudi": [],
                    "vendredi": [],
                    "samedi": [],
                    "dimanche": [],
                },
            }
            for (e, d), mb in zip(W.A.EQUIPES, ("marc.fictif", "lea.fictif"), strict=True)
        ],
        "services": {s: {"duree_min": W.A.DUREES[s], "competences": W.A.COMPETENCES[s]} for s in W.A.DUREES},
        "cedule": dict(W.A.PARAMETRES_CEDULE),
        "fenetre_par_defaut": dict(W.A.FENETRE_CLIENT),
        "feries": {"annees": [2026], "jours": []},
        "duree_jour_personne_minutes": 480,
    }
    fichier.write_text(yaml.safe_dump(profil, allow_unicode=True), encoding="utf-8")
    assert cli.main(["equipes", "declarer", "--depuis", str(fichier), "--par", "nathan"]) == 0
    impact = _scenario(monde, ABSENCES)["impacts"][0]
    assert impact["statut"] == "NON_CHIFFRE" and impact["valeurs"] is None and impact["recu"] is None
    assert "effectif_planifie_non_declare:eq-a" in impact["manque"] and "M4" in impact["manque"]


# ================================================================================================== pipeline : M2
def test_un_niveau_de_leads_est_compare_a_l_intervalle_de_m2_sans_calcul_de_m9(monde):
    options = {
        "serie": "leads_ingeres",
        "methode": "moyenne_mobile",
        "horizon": 1,
        "niveau": 80,
        "fenetre": 3,
        "graine": 5,
    }
    positions = {}
    for niveau in ("1.5", "4", "9"):
        s = _scenario(
            monde,
            {
                "choc": "leads_niveau_hypothetique",
                "parametres": {"leads_par_semaine": niveau},
                "jour": JOUR,
                "horodatage": HORO,
                "options": options,
            },
        )
        impact = s["impacts"][0]
        assert impact["statut"] == "CHIFFRE" and impact["proprietaire"] == W.M2
        positions[niveau] = impact["valeurs"]["par_periode"][0]["position_du_niveau_declare"]
        assert impact["valeurs"]["par_periode"][0]["intervalle"] == {"niveau": 80, "bas": "2.33", "haut": "5.33"}
        assert (
            impact["verification"]["identique"] is True
            and impact["verification"]["outil"] == "m2_rejouer_recu_commercial"
        )
    assert positions == {"1.5": "SOUS_L_INTERVALLE", "4": "DANS_L_INTERVALLE", "9": "AU_DESSUS_DE_L_INTERVALLE"}


def test_historique_insuffisant_chez_m2_est_non_chiffre_avec_le_code_du_proprietaire(tmp_path, monkeypatch):
    m = W.Monde(tmp_path, monkeypatch)
    try:
        m.historique_de_leads([1, 2, 1], W.T[1])
        options = {"serie": "leads_ingeres", "methode": "moyenne_mobile", "horizon": 1, "niveau": 80, "fenetre": 3}
        s = _scenario(
            m,
            {
                "choc": "leads_niveau_hypothetique",
                "parametres": {"leads_par_semaine": "2"},
                "jour": JOUR,
                "horodatage": HORO,
                "options": options,
            },
        )
        impact = s["impacts"][0]
        assert (
            impact["statut"] == "NON_CHIFFRE" and impact["raison"].startswith("REJ-PREV") and impact["valeurs"] is None
        )
        assert "M2" in impact["manque"] and s["chiffre"] is False
    finally:
        m.fermer()


# ===================================================================== moteur absent, refusé, en erreur : jamais zéro
def test_moteur_absent_le_proprietaire_n_est_pas_installe_non_chiffre_manque_m5(monde):
    sans_m5 = _sans(W.M5)  # le dispatcher de M9 n'a pas M5 : le port répond « producteur indisponible »
    scenario = _scenario(monde, RETARD, cap=sans_m5)
    impact = scenario["impacts"][0]
    assert impact["statut"] == "NON_CHIFFRE" and impact["raison"] == "producteur_indisponible"
    assert "M5" in impact["manque"] and impact["valeurs"] is None and impact["recu"] is None
    assert scenario["chiffre"] is False and scenario["non_chiffre"][0]["impact"] == "tresorerie"
    texte = json.dumps(scenario, ensure_ascii=False)
    assert "probabilite_au_moins_une_semaine_negative" not in texte and "plus_bas_du_chemin" not in texte


def test_moteur_en_erreur_la_prevision_de_m5_n_est_pas_calculable_donc_non_chiffre(monde):
    configuration = {k: v for k, v in monde.config_m5.items() if k != "prevision"}
    B.declarer_m5(monde.tmp, monde.mp, configuration)  # M5 sans horizon ni seuil : sa prévision refuse
    scenario = _scenario(monde, RETARD)
    impact = scenario["impacts"][0]
    assert impact["statut"] == "NON_CHIFFRE" and impact["raison"].startswith("REJ-") and "M5" in impact["manque"]
    assert impact["valeurs"] is None and impact["recu"] is None and impact["verification"] is None
    assert "plus_bas_du_chemin" not in json.dumps(scenario)


def test_un_moteur_non_installe_pour_la_capacite_ou_le_pipeline_est_aussi_non_chiffre(monde):
    sans_m4 = _sans(W.M4)
    assert _scenario(monde, ABSENCES, cap=sans_m4)["impacts"][0]["statut"] == "NON_CHIFFRE"
    options = {"serie": "leads_ingeres", "methode": "moyenne_mobile", "horizon": 1, "niveau": 80, "fenetre": 3}
    sans_m2 = _sans(W.M2)
    s = _scenario(
        monde,
        {
            "choc": "leads_niveau_hypothetique",
            "parametres": {"leads_par_semaine": "2"},
            "jour": JOUR,
            "horodatage": HORO,
            "options": options,
        },
        cap=sans_m2,
    )
    assert s["impacts"][0]["statut"] == "NON_CHIFFRE" and "M2" in s["impacts"][0]["manque"]


# ============================================================================== accès, aucune écriture, aucune action
@pytest.mark.parametrize(
    "identite",
    [
        None,
        contexte.IdentiteAppelante("vendeur.fictif", "seller", source="console"),
        contexte.IdentiteAppelante("employe.fictif", "employee", source="console"),
        contexte.IdentiteAppelante("ancien.admin", "admin", source="console"),
        contexte.IdentiteAppelante("admin.fictif", "admin", source="appareil"),
    ],
)
def test_agent_employe_vendeur_admin_revoque_et_appareil_sont_refuses_avant_tout_calcul(monde, identite):
    reponse = _chiffrer(monde, RETARD, identite)
    assert reponse["ok"] is False or reponse["resultat"].get("accepte") is False, reponse
    assert "plus_bas_du_chemin" not in json.dumps(reponse)


def test_un_scenario_chiffre_n_ecrit_rien_ne_propose_rien_et_ne_touche_aucune_capture(monde):
    monde.capturer("m5.prevision_tresorerie", {"aujourd_hui": JOUR}, "2026-10-30T21:00:01Z")
    avant = B.etat_base()
    captures = len(B.captures_stockees())
    for appel in (RETARD, ABSENCES):
        scenario = _scenario(monde, appel)
        assert scenario["decision"] is None and scenario["action_externe"] is False
        assert not {"action", "actions", "proposition", "approbation"} & set(scenario)
    apres = B.etat_base()
    modifiees = {nom for nom in avant if avant[nom] != apres[nom]}
    assert modifiees <= {"journal", "mutations_appliquees"}, modifiees
    assert len(B.captures_stockees()) == captures


def test_lister_les_chocs_chiffrables_dit_le_proprietaire_et_les_options_exigees(monde):
    with contexte.appele_par_appareil(W.ADMIN):
        reponse = monde.cap.appeler("m9_lister_scenarios_chiffres", {})
    chocs = {c["choc"]: c for c in reponse["resultat"]["chocs"]}
    assert chocs["retard_paiement_carnet"]["proprietaire"] == W.M5 and chocs["retard_paiement_carnet"]["options"] == [
        "graine",
        "tirages",
    ]
    assert (
        chocs["absences_equipe"]["proprietaire"] == W.M4 and chocs["leads_niveau_hypothetique"]["proprietaire"] == W.M2
    )


# ======================================================================== M9 ne calcule rien : garde sur le source
def _fonctions():
    arbre = ast.parse(Path(scenarios_chiffres.__file__).read_text(encoding="utf-8"))
    return [n for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef)]


def test_seules_les_conversions_de_forme_font_de_l_arithmetique_et_seuls_les_controles_touchent_aux_decimaux():
    """Multiplier, diviser ou élever à une puissance n'est admis que dans ``_facteur`` et ``_fraction`` (pourcentage ->
    facteur ou fraction exigé par le moteur). Un ``Decimal`` n'est manipulé que pour VALIDER une hypothèse, la convertir
    de forme ou COMPARER deux nombres (``_position``, ``_negatif``) : jamais pour produire un impact."""
    arithmetique = [
        (f.name, n.lineno)
        for f in _fonctions()
        for n in ast.walk(f)
        if isinstance(n, ast.BinOp)
        and isinstance(n.op, (ast.Mult, ast.Div, ast.FloorDiv, ast.Pow))
        and f.name not in {"_facteur", "_fraction"}
    ]
    assert arithmetique == [], arithmetique
    avec_decimal = {f.name for f in _fonctions() if "Decimal" in {n.id for n in ast.walk(f) if isinstance(n, ast.Name)}}
    assert avec_decimal == {"_decimal", "_p", "valider", "_facteur", "_fraction", "_negatif", "_position"}, avec_decimal
    sources = Path(scenarios_chiffres.__file__).read_text(encoding="utf-8")
    assert "quantize" not in sources and "sum(" not in sources and "round(" not in sources
