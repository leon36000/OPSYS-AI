"""PLAN T4.11 : `m3_estimer_projet` expose P50, P80, facteurs dominants et scénarios de prix à l'agent.

L'extension d'un outil existant, pas un outil de plus : la chaîne d'estimation reste UN appel (économie de tokens,
DEPARTEMENTS.md règle 2), et les scénarios ne se calculent que derrière la garde des photos, dans la même chaîne. Ce
que ces tests prouvent, par les outils RÉELS (`executer_atomique`) sur une base SQLite temporaire migrée :

- le contrat d'outil : paramètre optionnel et fermé, autonomie et niveau inchangés, outil toujours fermé aux
  appareils, description sous la limite ;
- le manifeste `department.yaml` : trois taux VIDES à dessein, lus par l'outil (l'appel d'abord, la configuration
  ensuite), jamais par le module pur ; un manifeste illisible ne bloque pas l'estimation ;
- sans taux, aucun prix et un verdict qui dit quoi déclarer ; avec taux et minimum rentable configuré, l'alerte rouge ;
- une demande mal formée ne laisse rien au registre durable ; la réponse est du JSON, montants en texte décimal.

Données fictives (`fictif: true`).
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from m2_preparation_estimation import marqueur_m2

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import outils as outils_m3  # noqa: E402
from m3_estimation import scenarios  # noqa: E402

from opsys import stockage  # noqa: E402
from opsys.outils import Autonomie, Niveau, executer_atomique  # noqa: E402

FICTIF = True
MANIFESTE = Path(__file__).resolve().parents[1] / "department.yaml"
SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
BAREME = {
    "version": "2026.1",
    "unite": "pi2",
    "postes": {"ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}},
}
TAUX = {"prudent": "0.40", "normal": "0.30", "agressif": "0.15"}
SOEURS = scenarios.CHAMPS_SOEURS_ESTIMATION


def _outil():
    return next(o for o in outils_m3.outils() if o.nom == "m3_estimer_projet")


def _arguments(**surcharges):
    contrat_estimation = {
        "lead_id": "lead-outil-scenarios-001",
        "conversation_id": "conv-outil-scenarios-001",
        "type_travaux": "ravalement",
        "ville": "Quebec",
        "canal": "formulaire",
        "contact": {"nom": "Durand", "telephone": "5145550000"},
        "urgence_declaree": False,
    }
    arguments = {
        "contrat": contrat_estimation,
        "marqueur": marqueur_m2("lead-outil-scenarios-001", contrat=contrat_estimation),
        "photos": [{
            "photo_id": "p1", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7,
            "angle": "face", "reference_echelle": {"type": "porte", "dimensions_connues": True},
        }],
        "seuils": SEUILS,
        "bareme": BAREME,
        "quantite": 1200,
        "plancher_rentable": 9000,
        "graine": 42,
    }
    arguments.update(surcharges)
    return arguments


def _estimer(**surcharges):
    reponse = executer_atomique(_outil(), _arguments(**surcharges))
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-scenarios.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _manifeste_jetable(tmp_path, monkeypatch, configuration):
    """Un manifeste de test : le propriétaire a fixé ses taux et son minimum (le vrai les laisse vides, à dessein)."""
    chemin = tmp_path / "department.yaml"
    chemin.write_text(json.dumps({"configuration": configuration}), encoding="utf-8")
    monkeypatch.setattr(outils_m3, "_MANIFESTE", chemin)


# ------------------------------------------------------------------------------------------ contrat d'outil
def test_le_schema_declare_un_parametre_optionnel_de_taux_par_scenario_et_ferme():
    schema = _outil().parametres
    assert "taux_marge_scenarios" in schema["properties"]
    assert "taux_marge_scenarios" not in schema["required"]
    assert schema["additionalProperties"] is False
    declare = schema["properties"]["taux_marge_scenarios"]
    assert declare["type"] == ["object", "null"]
    assert set(declare["properties"]) == {"prudent", "normal", "agressif"}
    # texte décimal, jamais un nombre JSON
    assert all(p["type"] == ["string", "null"] for p in declare["properties"].values())
    assert declare["additionalProperties"] is False


def test_l_outil_garde_son_autonomie_son_niveau_et_reste_ferme_aux_appareils():
    outil = _outil()
    assert outil.autonomie is Autonomie.T1
    assert outil.niveau_effectif is Niveau.N3
    assert outil.roles_appareil == frozenset()  # le barème, le plancher et les taux viendraient de l'appelant


def test_aucun_outil_n_a_ete_ajoute_pour_les_scenarios():
    noms = [o.nom for o in outils_m3.outils()]
    outils_calibration = {
        "m3_evaluer_calibration_cohortes", "m3_proposer_calibration_temps",
        "m3_evaluer_candidate_calibration", "m3_activer_candidate_calibration",
        "m3_rollback_candidate_calibration",
    }
    # Lectures livrées après les scénarios : le catalogue reste exact et aucun
    # outil de mutation supplémentaire n'est admis par cette exception.
    lectures_reprise = {
        "m3_lister_devis", "m3_lire_apprentissage_chantier",
        "m3_auditer_couverture_apprentissage", "m3_lister_devis_lead_admin",
    }
    # Catalogue et création de devis CRM07 : ports console uniquement, sans scénario.
    modeles_console = {
        "m3_enregistrer_lignes_modele", "m3_lire_lignes_modele",
        "m3_lire_tarif_modele", "m3_creer_devis_prefill",
        "m3_enregistrer_modele_soumission", "m3_lire_modele_soumission",
        "m3_lister_modeles_soumission", "m3_creer_devis_depuis_modele",
        "m3_document_devis_console",
    }
    baseline_13 = {
        "m3_estimer_projet", "m3_qualifier_photos", "m3_classifier_confiance",
        "m3_simuler_intervalle", "m3_confronter_plancher", "m3_creer_devis",
        "m3_lire_devis", "m3_marquer_devis_accepte", "m3_lire_ecarts_estime_reel",
        "m3_detecter_devis_sans_reponse", "m3_generer_soumission_brouillon",
        "m3_demander_envoi_devis", "m3_verifier_politique_photos",
    }
    assert noms[0] == "m3_estimer_projet"
    assert len(noms) == len(set(noms))
    assert set(noms) - outils_calibration - lectures_reprise - modeles_console == baseline_13
    assert set(noms) & modeles_console == modeles_console
    assert all(not o.roles_appareil for o in outils_m3.outils() if o.nom in modeles_console)
    assert set(noms) & outils_calibration == outils_calibration
    assert set(noms) & lectures_reprise == lectures_reprise
    assert all(o.autonomie is Autonomie.T0 for o in outils_m3.outils() if o.nom in lectures_reprise)
    assert not any("scenario" in nom or "p50" in nom or "facteur" in nom for nom in noms)


def test_la_description_dit_l_essentiel_sous_la_limite():
    description = _outil().description
    assert len(description) <= 1024  # la limite de `Outil` : payée à chaque tour
    for mot in ("P50", "P80", "facteurs_dominants", "scenarios_prix", "taux_marge_scenarios", "cout_unitaire_mode",
                "department.yaml", "minimum rentable"):
        assert mot in description, mot


def test_le_bareme_documente_le_mode_optionnel_du_poste():
    assert "cout_unitaire_mode" in _outil().parametres["properties"]["bareme"]["description"]


# ------------------------------------------------------------------------------------------- le manifeste
def test_le_manifeste_reel_declare_trois_taux_vides_a_dessein():
    configuration = yaml.safe_load(MANIFESTE.read_text(encoding="utf-8"))["configuration"]
    assert configuration["scenarios_prix"]["taux_marge"] == {"prudent": None, "normal": None, "agressif": None}
    assert configuration["revue_devis"]["minimum_rentable_cad"] is None  # le minimum que les scénarios confrontent


def test_la_lecture_des_taux_configures_rend_le_bloc_tel_quel_ou_rien():
    assert outils_m3._taux_scenarios_configures() == {"prudent": None, "normal": None, "agressif": None}


@pytest.mark.parametrize(
    ("configuration", "attendu"),
    [
        ({"scenarios_prix": {"taux_marge": {"prudent": 0.4, "normal": "0.3"}}}, {"prudent": 0.4, "normal": "0.3"}),
        ({"revue_devis": {}}, None),
        ({"scenarios_prix": None}, None),
        ({"scenarios_prix": ["prudent"]}, None),
        ({"scenarios_prix": {"taux_marge": None}}, None),
        ({}, None),
    ],
    ids=["declares", "sans_bloc", "bloc_nul", "bloc_liste", "taux_nuls", "configuration_vide"],
)
def test_la_lecture_des_taux_configures_suit_le_manifeste(tmp_path, monkeypatch, configuration, attendu):
    _manifeste_jetable(tmp_path, monkeypatch, configuration)
    assert outils_m3._taux_scenarios_configures() == attendu


def test_un_manifeste_illisible_donne_le_marqueur_d_illisibilite_aux_deux_lectures(tmp_path, monkeypatch):
    chemin = tmp_path / "department.yaml"
    chemin.write_text("configuration: [", encoding="utf-8")  # YAML cassé
    monkeypatch.setattr(outils_m3, "_MANIFESTE", chemin)
    assert outils_m3._taux_scenarios_configures() == outils_m3._CONFIGURATION_ILLISIBLE
    assert outils_m3._seuils_revue() == outils_m3._CONFIGURATION_ILLISIBLE
    monkeypatch.setattr(outils_m3, "_MANIFESTE", tmp_path / "absent.yaml")
    assert outils_m3._taux_scenarios_configures() == outils_m3._CONFIGURATION_ILLISIBLE


@pytest.mark.parametrize(
    "configuration", [["revue_devis"], "texte", 12, "illisible", None],
    ids=["liste", "texte", "nombre", "mot_du_marqueur", "nulle"],
)
def test_une_configuration_qui_n_est_pas_un_objet_ne_donne_ni_seuils_ni_taux(tmp_path, monkeypatch, configuration):
    """Ni plantage, ni marqueur d'illisibilité : le mot « illisible » écrit dans le fichier reste une valeur du fichier,
    pas le signe que le manifeste n'a pas pu être lu."""
    _manifeste_jetable(tmp_path, monkeypatch, configuration)
    assert outils_m3._taux_scenarios_configures() is None
    assert outils_m3._seuils_revue() is None


def test_la_lecture_des_seuils_de_la_revue_est_celle_de_t4_7_apres_le_partage_de_la_lecture(tmp_path, monkeypatch):
    assert outils_m3._seuils_revue() == {
        "confiance_minimale": None, "montant_maximal_cad": None, "marge_minimale": None,
        "distance_maximale_km": None, "minimum_rentable_cad": None}
    _manifeste_jetable(tmp_path, monkeypatch, {"revue_devis": {"minimum_rentable_cad": 2500}})
    assert outils_m3._seuils_revue() == {"minimum_rentable_cad": 2500}
    _manifeste_jetable(tmp_path, monkeypatch, {"scenarios_prix": {}})
    assert outils_m3._seuils_revue() is None


# ------------------------------------------------------------------------------------------- par l'outil
def test_sans_taux_ni_configuration_l_outil_ne_chiffre_aucun_prix_et_dit_quoi_declarer(base_durable):
    resultat = _estimer()
    assert resultat["accepte"] is True
    section = resultat["scenarios_prix"]
    for scenario in section["scenarios"]:
        assert scenario["prix"] is None and scenario["taux_marge"] is None
        assert scenario["verdict"]["code"] == "REJ-SCENARIOS-TAUX-ABSENT"
        assert f"taux_marge_scenarios.{scenario['scenario']}" in scenario["verdict"]["detail"]
    assert section["alerte_rouge"] is None
    # P50 et P80 n'ont besoin d'aucun taux : ils sont là, en texte décimal
    assert Decimal(resultat["distribution_cout"]["p50"]) <= Decimal(resultat["distribution_cout"]["p80"])


def test_l_appel_l_emporte_et_le_minimum_rentable_configure_leve_l_alerte_rouge(base_durable, tmp_path, monkeypatch):
    _manifeste_jetable(tmp_path, monkeypatch, {
        "scenarios_prix": {"taux_marge": {"prudent": 0.45, "normal": "0.32", "agressif": None}},
        "revue_devis": {"minimum_rentable_cad": 10**9},
    })
    resultat = _estimer(taux_marge_scenarios={"normal": "0.30", "agressif": "0.15"})
    par_nom = {s["scenario"]: s for s in resultat["scenarios_prix"]["scenarios"]}
    assert (par_nom["prudent"]["taux_marge"], par_nom["prudent"]["source_taux"]) == ("0.45", "configuration")
    assert (par_nom["normal"]["taux_marge"], par_nom["normal"]["source_taux"]) == ("0.30", "appel")  # l'appel d'abord
    assert (par_nom["agressif"]["taux_marge"], par_nom["agressif"]["source_taux"]) == ("0.15", "appel")
    assert all(s["alerte_rouge"] is True and s["motifs"][0]["code"] == "PRIX_SOUS_MINIMUM_RENTABLE"
               for s in par_nom.values())
    assert resultat["scenarios_prix"]["alerte_rouge"] is True


def test_un_manifeste_illisible_ne_bloque_pas_l_estimation_ni_ne_donne_de_prix(base_durable, tmp_path, monkeypatch):
    chemin = tmp_path / "department.yaml"
    chemin.write_text("configuration: [", encoding="utf-8")
    monkeypatch.setattr(outils_m3, "_MANIFESTE", chemin)
    resultat = _estimer()
    assert resultat["accepte"] is True and resultat["estimation"]["prix_bloque"] is False
    assert all(s["verdict"]["code"] == "REJ-SCENARIOS-TAUX-INVALIDE" for s in resultat["scenarios_prix"]["scenarios"])
    assert resultat["scenarios_prix"]["alerte_rouge"] is None


def test_une_demande_mal_formee_ne_laisse_rien_au_registre_durable(base_durable):
    resultat = _estimer(taux_marge_scenarios={"normal": "0.3", "moyen": "0.2"})
    assert resultat["accepte"] is False
    assert resultat["etape"] == "scenarios"
    assert resultat["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"
    assert len(outils_m3.registre_production().lire()) == 0


def test_le_schema_refuse_un_taux_qui_n_est_pas_du_texte_au_premier_niveau(base_durable):
    """Un `taux_marge_scenarios` qui n'est pas un objet est refusé AU SCHÉMA, avant toute écriture."""
    reponse = executer_atomique(_outil(), _arguments(taux_marge_scenarios="0.3"))
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"
    assert len(outils_m3.registre_production().lire()) == 0


def test_un_nombre_json_comme_taux_est_un_taux_invalide_jamais_un_prix(base_durable):
    resultat = _estimer(taux_marge_scenarios={"normal": 0.3})
    normal = next(s for s in resultat["scenarios_prix"]["scenarios"] if s["scenario"] == "normal")
    assert normal["prix"] is None
    assert normal["verdict"]["code"] == "REJ-SCENARIOS-TAUX-INVALIDE"


def test_la_reponse_est_du_json_les_montants_en_texte_decimal_et_les_photos_faibles_ne_donnent_rien(base_durable):
    resultat = _estimer(taux_marge_scenarios=TAUX)
    assert json.loads(json.dumps(resultat, ensure_ascii=False)) == resultat
    for cle in ("p50", "p80"):
        assert isinstance(resultat["distribution_cout"][cle], str)
    assert all(isinstance(s["prix"], str) for s in resultat["scenarios_prix"]["scenarios"])

    faibles = _estimer(taux_marge_scenarios=TAUX, photos=[{
        "photo_id": "p1", "resolution_largeur": 500, "resolution_hauteur": 2000, "eclairage": 7,
        "angle": "face", "reference_echelle": None}])
    assert faibles["estimation"]["prix_bloque"] is True
    assert {cle: faibles[cle] for cle in SOEURS} == dict.fromkeys(SOEURS)
