"""Les reçus de calcul de M2 (score, calibration, analytique, prévision) : format de M5, empreintes, rejeu.

Un reçu de M2 est un reçu `recu-calcul.v1` du moteur de calcul de M5, construit par le pont du socle : l'outil de M5
le vérifie tel quel, M2 le REJOUE. Données fictives."""

from __future__ import annotations

import copy
import inspect
import json

import pytest
from m2_revenue_crm import calibration_scoring, moteurs_commerciaux, previsions, scoring

from opsys import recu_calcul_pont

FICTIF = True
FAITS = calibration_scoring.jeu_fictif(2, 3)[0]["faits"]
SERIE = {"serie": [3, 5, 4, 6, 5, 7, 6, 8, 7, 9, 8, 10, 9, 11], "unite": "semaine", "nom": "leads_ingeres"}
PARAM_P = {
    "methode": "moyenne_mobile",
    "fenetre": 3,
    "alpha": None,
    "horizon": 3,
    "niveau": 80,
    "graine": 42,
    "repetitions": 300,
    "periodes_minimum": 12,
    "evenements_minimum": 20,
}


def _recus():
    return {
        "score": moteurs_commerciaux.produire("score_lead", scoring.VERSION, FAITS, None)[0],
        "calibration": moteurs_commerciaux.produire(
            "calibration_score_lead", scoring.VERSION, {"graine": 3, "n": 300}, None
        )[0],
        "prevision": moteurs_commerciaux.produire("prevision_commerciale", "1.0.0", SERIE, PARAM_P)[0],
        "analytique": moteurs_commerciaux.produire(
            "analytique_pipeline",
            "1.0.0",
            {
                "leads": [
                    {
                        "statut": "nouveau",
                        "ingere_s": 0,
                        "qualifie_s": None,
                        "converti_s": None,
                        "perdu_s": None,
                        "valeur_cents": None,
                    }
                ]
            },
            {"graine": 1, "repetitions": 300, "niveau": 80},
        )[0],
    }


@pytest.fixture(scope="module")
def recus():
    r = _recus()
    assert all(r.values()), r
    return r


def test_chaque_recu_est_au_format_de_m5_et_verifiable_par_l_outil_de_m5(recus):
    from m5_financecore import recu_calcul

    for nom, recu in recus.items():
        assert recu["format"] == "recu-calcul.v1" and recu["type"] == "RECU_CALCUL", nom
        assert recu_calcul.verifier(recu) == (True, ""), nom
        assert recu_calcul_pont.verifier(recu) == (True, ""), nom
        assert len(recu["empreinte"]) == 64 and len(recu["empreinte_entrees"]) == 64
        assert recu["mention"].startswith("À valider auprès d'un comptable (CPA)")


def test_chaque_recu_se_rejoue_a_l_identique_apres_un_aller_retour_json(recus):
    for nom, recu in recus.items():
        voyage = json.loads(json.dumps(recu))
        rejeu, verdict = moteurs_commerciaux.rejouer(voyage)
        assert verdict is None and rejeu["identique"] is True, nom
        assert rejeu["empreinte_recue"] == rejeu["empreinte_recalculee"] == recu["empreinte"]


def test_un_chiffre_retouche_une_entree_retouchee_ou_un_champ_en_trop_est_refuse(recus):
    for nom, recu in recus.items():
        retouche = copy.deepcopy(recu)
        retouche["avertissements"] = [*retouche["avertissements"], "ajout"]
        assert moteurs_commerciaux.rejouer(retouche)[1]["code"] == "REJ-PREV-RECU-INVALIDE", nom
        en_trop = {**recu, "extra": 1}
        assert moteurs_commerciaux.rejouer(en_trop)[1]["code"] == "REJ-PREV-RECU-INVALIDE", nom
    forge = copy.deepcopy(recus["prevision"])
    forge["entrees"]["serie"][0] = 99
    assert moteurs_commerciaux.rejouer(forge)[1]["code"] == "REJ-PREV-RECU-INVALIDE", (
        "empreinte_entrees ne correspond plus"
    )


def test_un_resultat_forge_avec_des_empreintes_refaites_est_decouvert_par_le_rejeu(recus):
    recu = copy.deepcopy(recus["score"])
    recu["resultat"]["score"] = "99.99"
    refait = recu_calcul_pont.construire(
        moteur=recu["moteur"],
        version_moteur=recu["version_moteur"],
        methode=recu["methode"],
        precision=recu["precision"],
        parametres=recu["parametres"],
        entrees=recu["entrees"],
        resultat=recu["resultat"],
        avertissements=recu["avertissements"],
    )
    assert recu_calcul_pont.verifier(refait) == (True, ""), "les empreintes sont cohérentes avec le contenu forgé"
    rejeu, verdict = moteurs_commerciaux.rejouer(refait)
    assert verdict is None and rejeu["identique"] is False, "mais le calcul refait ne donne pas ce résultat"


def test_compact_moteur_inconnu_et_forme_invalide(recus):
    compact = recu_calcul_pont.compacter(recus["prevision"])
    assert (
        recu_calcul_pont.verifier(compact) == (True, "")
        and moteurs_commerciaux.rejouer(compact)[1]["code"] == "REJ-PREV-RECU-INVALIDE"
    )
    inconnu = copy.deepcopy(recus["score"])
    inconnu["moteur"] = "autre"
    assert moteurs_commerciaux.rejouer(inconnu)[1]["code"] == "REJ-PREV-RECU-INVALIDE"
    ancienne = copy.deepcopy(recus["score"])
    ancienne["version_moteur"] = "0.9.0"
    assert moteurs_commerciaux.rejouer(ancienne)[1]["code"] == "REJ-PREV-RECU-INVALIDE"
    for x in (None, [], "x", 3, {}):
        assert moteurs_commerciaux.rejouer(x)[1]["code"] == "REJ-PREV-RECU-INVALIDE"


def test_la_version_du_moteur_et_les_parametres_sont_dans_le_recu(recus):
    assert recus["score"]["version_moteur"] == scoring.VERSION and recus["score"]["parametres"] == {}
    assert recus["prevision"]["parametres"]["graine"] == 42 and recus["prevision"]["parametres"]["repetitions"] == 300
    assert recus["prevision"]["entrees"]["serie"] == SERIE["serie"]
    assert recus["analytique"]["parametres"] == {"graine": 1, "repetitions": 300, "niveau": 80}


def test_les_moteurs_refusent_comme_les_fonctions_pures():
    assert (
        moteurs_commerciaux.produire("score_lead", scoring.VERSION, {**FAITS, "age": 30}, None)[1]["code"]
        == "REJ-SCORE-CHAMP-INTERDIT"
    )
    assert (
        moteurs_commerciaux.produire("score_lead", scoring.VERSION, FAITS, {"x": 1})[1]["code"]
        == "REJ-SCORE-FAITS-INVALIDES"
    )
    assert moteurs_commerciaux.produire("prevision_commerciale", "1.0.0", {**SERIE, "serie": [1] * 5}, PARAM_P)[1][
        "code"
    ] == ("REJ-PREV-ECHANTILLON-INSUFFISANT")
    assert moteurs_commerciaux.produire("calibration_score_lead", scoring.VERSION, {"graine": 3}, None)[1]["code"] == (
        "REJ-PREV-PARAMETRE-INVALIDE"
    )
    assert moteurs_commerciaux.produire("inconnu", "1", {}, None)[1]["code"] == "REJ-PREV-RECU-INVALIDE"


def test_aucun_import_entre_departements_dans_les_modules_commerciaux():
    """#109 : M2 n'importe pas M5 ; le pont du socle est le seul chemin."""
    import m2_revenue_crm.calibration_scoring as c
    import m2_revenue_crm.coach as co
    import m2_revenue_crm.moteurs_commerciaux as mc
    import m2_revenue_crm.outils_ventes as ov
    import m2_revenue_crm.previsions as pv
    import m2_revenue_crm.propriete as pr
    import m2_revenue_crm.scoring as sc
    import m2_revenue_crm.scoring_faits as sf
    import m2_revenue_crm.valeurs as va

    for module in (c, co, mc, ov, pv, pr, sc, sf, va, previsions):
        source = inspect.getsource(module)
        for autre in (
            "m1_front_office",
            "m3_estimation",
            "m4_field_ops",
            "m5_financecore",
            "m6_material_control",
            "m7_marketing",
            "m8_analytics",
            "m9_strategic",
            "m10_memoire",
        ):
            assert f"import {autre}" not in source and f"from {autre}" not in source, (module.__name__, autre)
