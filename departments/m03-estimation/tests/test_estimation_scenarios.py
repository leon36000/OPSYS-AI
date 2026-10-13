"""PLAN T4.11 : P50, P80, facteurs dominants et scénarios de prix dans la chaîne d'estimation (`estimation.py`).

`scenarios.py` est éprouvé seul par `test_scenarios.py` ; ici, le CÂBLAGE de l'orchestrateur pur, sur un registre en
mémoire. Ce que ces tests prouvent :

- `EstimationV1` reste gelé : mêmes douze clés, mêmes valeurs, même `hash_maillon`, que des scénarios soient demandés ou
  non ; les trois clés nouvelles sont des clés SŒURS de la réponse, jamais dans `estimation` ni dans la charge du
  registre ;
- photos faibles : prix bloqué, donc ni P50, ni facteur, ni scénario (`None`), jamais un montant sans intervalle ;
- P50 et P80 viennent des MÊMES tirages que l'intervalle de l'estimation, avec ou sans mode PERT ;
- sans taux, aucun prix et un verdict par scénario ; les `elements_manquants` restent ceux d'avant ;
- une demande de scénarios mal formée refuse AVANT toute écriture au registre ;
- la réponse reste sous la limite de sortie d'un outil, même avec beaucoup de matériaux et trois alertes rouges.

Données fictives (`fictif: true`).
"""

from __future__ import annotations

import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import contrats, estimation, monte_carlo, registre, scenarios  # noqa: E402

from opsys import jetons  # noqa: E402
from opsys.outils import vers_json  # noqa: E402

FICTIF = True
CENT = Decimal("0.01")
SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
BAREME = {
    "version": "2026.1",
    "unite": "pi2",
    "postes": {"ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}},
}
TAUX = {"prudent": "0.40", "normal": "0.30", "agressif": "0.15"}
SOEURS = scenarios.CHAMPS_SOEURS_ESTIMATION


def _contrat(**surcharges):
    contrat = {
        "lead_id": "lead-scenarios-001",
        "conversation_id": "conv-scenarios-001",
        "type_travaux": "ravalement",
        "ville": "Quebec",
        "canal": "formulaire_web",
        "contact": {"nom": "Durand", "telephone": "5145550000"},
        "urgence_declaree": False,
    }
    contrat.update(surcharges)
    return contrat


def _marqueur():
    return {
        "readiness_ok": True,
        "lead_id": "lead-scenarios-001",
        "hash_tete_registre": "f" * 64,
        "horodatage": "2026-09-28T10:00:00-04:00",
        "empreinte": "a" * 64,
    }


def _photo(i=1, reference=None, largeur=3000):
    return {
        "photo_id": f"p{i}", "resolution_largeur": largeur, "resolution_hauteur": 2000, "eclairage": 7,
        "angle": "face", "reference_echelle": reference,
    }


def _orchestrer(**surcharges):
    parametres = {
        "contrat": _contrat(),
        "marqueur": _marqueur(),
        "photos": [_photo(1, reference={"type": "porte", "dimensions_connues": True})],
        "seuils": SEUILS,
        "bareme": BAREME,
        "quantite": 1200,
        "plancher_rentable": 9000,
        "registre_cible": registre.Registre(),
        "graine": 42,
    }
    parametres.update(surcharges)
    return estimation.orchestrer_estimation(**parametres)


def _arrondi(valeur):
    return Decimal(str(valeur)).quantize(CENT, rounding=ROUND_HALF_UP)


# ============================================================================ EstimationV1 reste gelé
def test_les_trois_cles_soeurs_sont_a_cote_d_estimation_v1_jamais_dedans():
    reponse = _orchestrer(taux_scenarios=TAUX)
    assert reponse["accepte"] is True
    assert set(SOEURS) <= set(reponse)
    assert set(reponse["estimation"]) == set(contrats.CHAMPS_ESTIMATION_V1)
    assert not set(SOEURS) & set(reponse["estimation"])
    assert all(reponse[cle] is not None for cle in SOEURS)


def test_estimation_v1_ne_change_ni_de_cle_ni_de_valeur_ni_d_empreinte_quand_des_scenarios_sont_demandes():
    sans = _orchestrer(registre_cible=registre.Registre())
    avec = _orchestrer(
        registre_cible=registre.Registre(), taux_scenarios=TAUX,
        taux_scenarios_configures={"prudent": "0.9"}, seuils_revue={"minimum_rentable_cad": 10**9})
    assert avec["estimation"] == sans["estimation"]  # hash_maillon compris : la version n'a pas bougé
    for cle in ("prix_recommande", "duree_estimee_minutes", "elements_manquants", "niveau_confiance_hierarchie"):
        assert avec[cle] == sans[cle]


@pytest.mark.parametrize("bloque", [False, True])
def test_la_charge_du_registre_ne_porte_aucune_cle_soeur_ni_taux_ni_montant_de_scenario(bloque):
    photos = [_photo(largeur=640)] if bloque else [_photo(reference={"type": "porte", "dimensions_connues": True})]
    journal = registre.Registre()
    reponse = _orchestrer(
        registre_cible=journal, photos=photos,
        taux_scenarios=TAUX, seuils_revue={"minimum_rentable_cad": 10**9})
    assert reponse["accepte"] is True
    (maillon,) = journal.lire()
    assert not set(SOEURS) & set(maillon["charge"])
    assert set(maillon["charge"]) == {
        "devis_id", "lead_id", "empreinte_marqueur_m2", "niveau_confiance", "bareme_version", "graine_monte_carlo",
        "faits_revue"}
    faits = maillon["charge"]["faits_revue"]
    # Un seul ajout autorisé : faits natifs hashés, jamais taux ou montants des scénarios.
    assert faits == {
        "version": "m3.faits-revue/v1", "prix_bloque": bloque,
        "verdict_estimation": "QUALITE_ENTREE_INSUFFISANTE" if bloque else "AUCUN_BLOCAGE",
        "niveau_confiance_hierarchie": "INDETERMINE" if bloque else "REFERENCE_ECHELLE",
        "alerte_plancher": False,
    }
    assert type(faits["prix_bloque"]) is bool and type(faits["alerte_plancher"]) is bool
    assert all(isinstance(faits[cle], str) for cle in
               ("version", "verdict_estimation", "niveau_confiance_hierarchie"))
    assert not set(SOEURS) & set(faits)
    assert set(reponse["estimation"]) == set(contrats.CHAMPS_ESTIMATION_V1)
    sans = _orchestrer(registre_cible=registre.Registre(), photos=photos)
    assert reponse["estimation"] == sans["estimation"]  # même hash, scénarios étrangers aux faits canoniques
    assert journal.valider_chaine() == (True, "")


def test_les_taux_des_scenarios_ne_changent_pas_le_prix_recommande():
    a = _orchestrer(taux_marge="0.35")
    b = _orchestrer(taux_marge="0.35", taux_scenarios={"normal": "0.99"})
    assert a["prix_recommande"] == b["prix_recommande"] is not None


def test_meme_demande_memes_scenarios_bit_a_bit_sur_deux_registres_vierges():
    a = _orchestrer(taux_scenarios=TAUX, seuils_revue={"minimum_rentable_cad": 15000})
    b = _orchestrer(taux_scenarios=TAUX, seuils_revue={"minimum_rentable_cad": 15000})
    assert {cle: a[cle] for cle in SOEURS} == {cle: b[cle] for cle in SOEURS}


# ================================================================================== voie bloquée
def test_des_photos_faibles_bloquent_le_prix_donc_aucun_p50_aucun_scenario():
    """« Photos insuffisantes bloquent tout prix final » (DEFINITION-PRODUIT §7 M3, preuve de complétion)."""
    reponse = _orchestrer(photos=[_photo(1, largeur=500)], taux_scenarios=TAUX,
                          seuils_revue={"minimum_rentable_cad": 1})
    assert reponse["accepte"] is True
    assert reponse["estimation"]["prix_bloque"] is True
    assert {cle: reponse[cle] for cle in SOEURS} == dict.fromkeys(SOEURS)
    assert reponse["prix_recommande"] is None


def test_un_bareme_sans_poste_pour_le_service_bloque_avant_toute_cle_soeur():
    reponse = _orchestrer(bareme={"version": "v", "unite": "u", "postes": {"extension": {
        "cout_unitaire_min": 1.0, "cout_unitaire_max": 2.0}}}, taux_scenarios=TAUX)
    assert reponse["accepte"] is False
    assert reponse["etape"] == "intervalle"
    assert not set(SOEURS) & set(reponse)


# ================================================================== mêmes tirages que l'intervalle
@pytest.mark.parametrize("bareme", [
    BAREME,
    {"version": "2026.1", "unite": "pi2", "postes": {"ravalement": {
        "cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0, "cout_unitaire_mode": 9.0}}},
], ids=["uniforme", "pert"])
@pytest.mark.parametrize("graine", [1, 7, 20260929])
def test_p50_et_p80_viennent_des_memes_tirages_que_l_intervalle_de_l_estimation(bareme, graine):
    reponse = _orchestrer(bareme=bareme, graine=graine)
    intervalle = reponse["estimation"]["intervalle_confiance"]
    distribution = reponse["distribution_cout"]
    assert distribution["graine"] == reponse["estimation"]["graine_monte_carlo"] == graine
    assert intervalle["borne_basse"] <= float(distribution["p50"]) <= float(distribution["p80"])
    assert float(distribution["p80"]) <= intervalle["borne_haute"]
    # P80 est la borne haute de l'intervalle à 60 % de la MÊME simulation, au cent près de l'arrondi
    soixante, verdict = monte_carlo.simuler_intervalle(bareme, "ravalement", 1200, graine, 0.6)
    assert verdict is None
    assert distribution["p80"] == _arrondi(soixante["borne_haute"])


def test_un_mode_du_bareme_change_l_intervalle_et_p50_p80_dans_la_meme_loi():
    uniforme = _orchestrer()
    pert = _orchestrer(bareme={"version": "2026.1", "unite": "pi2", "postes": {"ravalement": {
        "cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0, "cout_unitaire_mode": 9.0}}})
    assert pert["estimation"]["intervalle_confiance"] != uniforme["estimation"]["intervalle_confiance"]
    assert pert["distribution_cout"]["postes"][0]["loi"] == "PERT"
    assert uniforme["distribution_cout"]["postes"][0]["loi"] == "uniforme"
    assert (pert["distribution_cout"]["p50"], pert["distribution_cout"]["p80"]) != (
        uniforme["distribution_cout"]["p50"], uniforme["distribution_cout"]["p80"])


def test_un_mode_de_travers_refuse_l_estimation_comme_l_intervalle_le_refusait():
    reponse = _orchestrer(bareme={"version": "v", "unite": "u", "postes": {"ravalement": {
        "cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0, "cout_unitaire_mode": 99.0}}})
    assert reponse["accepte"] is False
    assert reponse["etape"] == "intervalle"
    assert "cout_unitaire_mode" in reponse["verdict"]["detail"]


def test_sans_graine_fournie_p50_et_p80_suivent_la_graine_stable_de_l_estimation():
    """Sans `graine`, l'estimation en dérive une, stable, de ses entrées ; P50 et P80 lisent la MÊME, pas une autre."""
    reponse = _orchestrer(graine=None)
    graine = reponse["estimation"]["graine_monte_carlo"]
    assert graine == estimation.graine_stable(BAREME, "ravalement", 1200)
    assert reponse["distribution_cout"]["graine"] == graine
    soixante, _ = monte_carlo.simuler_intervalle(BAREME, "ravalement", 1200, graine, 0.6)
    assert reponse["distribution_cout"]["p80"] == _arrondi(soixante["borne_haute"])


def test_le_facteur_dominant_d_une_estimation_est_son_unique_poste():
    (facteur,) = _orchestrer()["facteurs_dominants"]
    assert facteur["poste"] == "ravalement"
    assert facteur["part_variance"] == Decimal("1.0000")
    assert facteur["amplitude"] == Decimal("7200.00")


# ==================================================================================== les scénarios
def test_sans_aucun_taux_aucun_prix_et_les_elements_manquants_restent_ceux_d_avant():
    reponse = _orchestrer()
    assert reponse["elements_manquants"] == [
        "taux_marge non fourni : aucun prix recommandé calculé (coût seulement disponible)"]
    for scenario in reponse["scenarios_prix"]["scenarios"]:
        assert scenario["prix"] is None
        assert scenario["verdict"]["code"] == "REJ-SCENARIOS-TAUX-ABSENT"


def test_avec_des_taux_les_prix_sont_ceux_de_la_formule_du_paquet_sur_p80_et_p50():
    reponse = _orchestrer(taux_scenarios=TAUX)
    distribution = reponse["distribution_cout"]
    prix = {s["scenario"]: s["prix"] for s in reponse["scenarios_prix"]["scenarios"]}
    assert prix["prudent"] == (distribution["p80"] * Decimal("1.40")).quantize(CENT, rounding=ROUND_HALF_UP)
    assert prix["normal"] == (distribution["p50"] * Decimal("1.30")).quantize(CENT, rounding=ROUND_HALF_UP)
    assert prix["agressif"] == (distribution["p50"] * Decimal("1.15")).quantize(CENT, rounding=ROUND_HALF_UP)
    assert prix["agressif"] < prix["normal"] < prix["prudent"]


def test_les_taux_de_la_configuration_servent_quand_l_appel_se_tait():
    reponse = _orchestrer(taux_scenarios_configures={"prudent": 0.40, "normal": "0.30", "agressif": 0.15})
    scenarios_prix = reponse["scenarios_prix"]["scenarios"]
    assert {s["source_taux"] for s in scenarios_prix} == {"configuration"}
    assert [s["taux_marge"] for s in scenarios_prix] == [Decimal("0.40"), Decimal("0.30"), Decimal("0.15")]


def test_le_minimum_rentable_de_la_configuration_de_la_revue_leve_l_alerte_rouge_dans_la_reponse():
    sans_minimum = _orchestrer(taux_scenarios=TAUX)["scenarios_prix"]
    assert sans_minimum["alerte_rouge"] is None
    assert [m["code"] for m in sans_minimum["non_evaluables"]] == ["PRIX_SOUS_MINIMUM_RENTABLE"]

    prix = {s["scenario"]: s["prix"] for s in sans_minimum["scenarios"]}
    avec_minimum = _orchestrer(
        taux_scenarios=TAUX, seuils_revue={"minimum_rentable_cad": str(prix["normal"])})["scenarios_prix"]
    assert avec_minimum["alerte_rouge"] is True
    par_nom = {s["scenario"]: s for s in avec_minimum["scenarios"]}
    assert par_nom["agressif"]["alerte_rouge"] is True and par_nom["agressif"]["motifs"][0]["gravite"] == "rouge"
    assert par_nom["normal"]["alerte_rouge"] is False and par_nom["prudent"]["alerte_rouge"] is False
    assert avec_minimum["non_evaluables"] == []


def test_un_taux_d_appel_invalide_n_empeche_pas_l_estimation_mais_n_a_pas_de_prix():
    reponse = _orchestrer(taux_scenarios={"normal": "abc", "prudent": "0.4"})
    assert reponse["accepte"] is True and reponse["estimation"]["prix_bloque"] is False
    par_nom = {s["scenario"]: s for s in reponse["scenarios_prix"]["scenarios"]}
    assert par_nom["normal"]["verdict"]["code"] == "REJ-SCENARIOS-TAUX-INVALIDE"
    assert par_nom["normal"]["prix"] is None
    assert par_nom["prudent"]["prix"] is not None


@pytest.mark.parametrize(
    "taux", ["0.3", ["normal"], {"normal": "0.3", "moyen": "0.2"}], ids=["texte", "liste", "inconnu"])
def test_une_demande_de_scenarios_mal_formee_refuse_avant_toute_ecriture_au_registre(taux):
    journal = registre.Registre()
    reponse = _orchestrer(registre_cible=journal, taux_scenarios=taux)
    assert reponse["accepte"] is False
    assert reponse["etape"] == "scenarios"
    assert reponse["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"
    assert journal.lire() == []


def test_une_configuration_de_travers_ne_bloque_pas_l_estimation():
    reponse = _orchestrer(taux_scenarios_configures="illisible", seuils_revue="illisible")
    assert reponse["accepte"] is True and reponse["estimation"]["prix_bloque"] is False
    assert all(s["verdict"]["code"] == "REJ-SCENARIOS-TAUX-INVALIDE" for s in reponse["scenarios_prix"]["scenarios"])


@pytest.fixture
def _services(declarer_services):
    declarer_services()


def test_un_lead_v2_est_estime_sur_le_poste_de_son_service(_services):
    """Le service d'un lead v2 (taxonomie du socle) est le poste : le même tirage sert l'intervalle et P50/P80."""
    contrat = {
        "schema_version": 2, "lead_id": "lead-scenarios-001", "conversation_id": "conv-scenarios-001",
        "service": "revetement", "ville": "Quebec", "canal": "formulaire",
        "contact": {"nom": "Durand", "telephone": "5145550000"}, "urgence_declaree": False,
    }
    bareme = {"version": "2026.1", "unite": "pi2", "postes": {"revetement": {
        "cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}}}
    reponse = _orchestrer(contrat=contrat, bareme=bareme, taux_scenarios=TAUX)
    assert reponse["accepte"] is True, reponse
    assert reponse["distribution_cout"]["postes"][0]["poste"] == "revetement"
    assert reponse["facteurs_dominants"][0]["poste"] == "revetement"
    assert all(s["prix"] is not None for s in reponse["scenarios_prix"]["scenarios"])


# ============================================================================ taille et types de sortie
def test_aucun_montant_de_la_reponse_n_est_un_flottant_hors_du_contrat_gele():
    reponse = _orchestrer(taux_scenarios=TAUX, seuils_revue={"minimum_rentable_cad": 10**9})
    for cle in SOEURS:
        assert _sans_flottant(reponse[cle]), cle


def _sans_flottant(objet):
    if isinstance(objet, float):
        return False
    if isinstance(objet, dict):
        return all(_sans_flottant(v) for v in objet.values())
    if isinstance(objet, (list, tuple)):
        return all(_sans_flottant(v) for v in objet)
    return True


def test_la_reponse_du_pire_cas_reste_sous_la_limite_de_sortie_d_un_outil():
    """Douze matériaux, une durée, un prix recommandé, un mode PERT, trois taux, trois alertes rouges avec leur motif :
    la réponse sérialisée tient dans `jetons.LIMITE_SORTIE_DEFAUT`, sinon `Capacites` la tronquerait en aperçu."""
    materiaux = [
        {"materiau": f"Matériau fictif numéro {i:02d} du revêtement", "sku": f"SKU-FICTIF-{i:04d}",
         "quantite_par_unite": "0.125", "unite": "pi2", "facteur_perte": "0.10"}
        for i in range(12)
    ]
    bareme = {"version": "2026.1-fictive", "unite": "pi2", "postes": {"ravalement": {
        "cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0, "cout_unitaire_mode": 9.0,
        "duree_minutes_par_unite": 2.5, "materiaux": materiaux}}}
    reponse = _orchestrer(bareme=bareme, taux_marge="0.35", taux_scenarios=TAUX,
                          seuils_revue={"minimum_rentable_cad": 10**9})
    assert reponse["accepte"] is True, reponse
    assert reponse["scenarios_prix"]["alerte_rouge"] is True
    assert all(s["alerte_rouge"] for s in reponse["scenarios_prix"]["scenarios"])
    taille = len(json.dumps({"ok": True, "resultat": vers_json(reponse)}, ensure_ascii=False))
    assert taille < jetons.LIMITE_SORTIE_DEFAUT, f"{taille} caractères : la sortie serait tronquée"
