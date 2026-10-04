"""Cycle de vie fictif d'une candidate de durée; seules des APIs métier pures."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import calibration_versions  # noqa: E402
from m3_estimation.outils import outils as m3_outils  # noqa: E402

from opsys.outils import Autonomie, Niveau  # noqa: E402


def _rapport_source() -> dict:
    rapport = {
        "statut": "candidate", "candidate_active": False,
        "protocole_version": "cohortes-r32-v1",
        "coupure_utc": "2025-12-01T00:00:00Z",
        "source_horizon_utc": "2025-12-10T00:00:00Z",
        "holdout_cutoff_utc": "2026-01-01T00:00:00Z",
        "provenance_observations": [
            {"wct_id": f"train-{i}", "chantier_sha256": f"{i + 1:064x}",
             "m3_source_hash": f"{i + 101:064x}", "m4_wct_hash": f"{i + 201:064x}", "partition": "train"}
            for i in range(30)
        ],
        "segments": [{
            "type_service": "gouttieres", "unite_quantite": "pi_lin", "bareme_version": "bar-1",
            "quantite_exacte": "10", "taux_minutes_par_unite_source": "10",
            "taux_minutes_par_unite_candidat": "9", "statut": "candidate",
            "empreinte_bareme": "c" * 64,
            "train": {"chantiers": 30},
        }],
    }
    prefix = {
        "version": "m03-wct-prefix/1",
        "entrees": [{"rang_registre": i, "maillon": f"fictif-{i}"} for i in range(30)],
    }
    rapport["source_wct_prefix"] = {
        "count": 30,
        "sha256": hashlib.sha256(json.dumps(prefix, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "wct_id_hashes": sorted(
            calibration_versions.empreinte_identifiant_wct(f"train-{i}") for i in range(30)
        ),
    }
    rapport["rapport_sha256"] = hashlib.sha256(
        json.dumps(rapport, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    return rapport


def _observations_holdout(count: int = 30) -> list[dict]:
    return [{
        "wct_id": f"hold-{i}", "chantier_id": f"future-{i}", "intervention_id": f"int-{i}",
        "devis_id": f"devis-{i}", "horodatage_debut": "2026-01-02T09:00:00Z",
        "horodatage_completion": "2026-01-02T10:30:00Z", "statut": "completed_verified",
        "duree_estimee_minutes": "100", "duree_reelle_minutes": 90,
        "type_service": "gouttieres", "quantite": "10", "unite_quantite": "pi_lin",
            "taux_minutes_par_unite": "10", "bareme_version": "bar-1",
        "empreinte_bareme": "c" * 64, "calibration_version_id": None,
        "preuve": {
            "m3_source_hash": f"{i + 10001:064x}", "m4_wct_hash": f"{i + 20001:064x}",
            "liaison_exacte": True, "chaine_m3_valide": True, "schema_trace": 2,
            "semantique_trace": "duree_ecoulee_intervention", "semantique_reel": "duree_ecoulee_intervention",
            "unite_duree_estimee": "minute", "unite_duree_reelle": "minute",
        },
    } for i in range(count)]


def test_holdout_preregistre_comparatif_active_owner_et_rollback_append_only():
    journal = []
    result = calibration_versions.proposer_candidate(
        journal, _rapport_source(), politique=copy.deepcopy(calibration_versions.POLITIQUE_INITIALE),
    )
    assert result["statut"] == "proposee"
    candidate = result["candidates"][0]
    assert candidate["candidate_active"] is False
    assert candidate["politique"]["version"] == "m3-time-promotion-policy/1"
    assert candidate["holdout_cutoff_utc"] == "2026-01-01T00:00:00Z"
    assert candidate["source_wct_prefix"] == _rapport_source()["source_wct_prefix"]
    assert candidate["source_wct_hashes_vus"] == _rapport_source()["source_wct_prefix"]["wct_id_hashes"]

    evaluation = calibration_versions.evaluer_candidate(journal, candidate["candidate_id"], _observations_holdout())
    assert evaluation["statut"] == "acceptable"
    assert evaluation["mae_baseline_minutes"] == "10"
    assert evaluation["mae_candidate_minutes"] == "0"
    from decimal import Decimal
    assert Decimal(evaluation["borne_basse_amelioration_minutes"]) > 0
    assert evaluation["candidate_active"] is False

    avant = copy.deepcopy(journal)
    refuse = calibration_versions.activer_candidate(
        journal, candidate["candidate_id"], active_version_attendue=None,
        approbateur={"personne": "gestionnaire", "role": "admin"},
    )
    assert refuse["accepte"] is False
    assert journal == avant

    active = calibration_versions.activer_candidate(
        journal, candidate["candidate_id"], active_version_attendue=None,
        approbateur={"personne": "nathan_owner", "role": "nathan_owner"},
    )
    assert active["accepte"] is True
    assert calibration_versions.version_active(journal, "gouttieres", "pi_lin", "bar-1", "c" * 64,
                                               "10", "10") is not None
    assert calibration_versions.version_active(journal, "gouttieres", "pi_lin", "bar-1", "c" * 64,
                                               "10.0", "10.00") is not None
    assert calibration_versions.version_active(journal, "gouttieres", "pi_lin", "bar-1", "c" * 64,
                                               "10.1", "10") is None

    longueur_avant_rollback = len(journal)
    retour = calibration_versions.revoquer_candidate(
        journal, active_version_attendue=candidate["candidate_id"], approbateur={
            "personne": "nathan_owner", "role": "nathan_owner",
        },
    )
    assert retour["accepte"] is True
    assert len(journal) == longueur_avant_rollback + 1
    assert calibration_versions.version_active(journal, "gouttieres", "pi_lin", "bar-1", "c" * 64,
                                               "10", "10") is None
    assert journal[0] == avant[0]


def test_population_insuffisante_et_rejeu_holdout_interdisent_activation():
    journal = []
    result = calibration_versions.proposer_candidate(
        journal, _rapport_source(), politique=copy.deepcopy(calibration_versions.POLITIQUE_INITIALE),
    )
    candidate = result["candidates"][0]
    observations = _observations_holdout(29)
    evaluation = calibration_versions.evaluer_candidate(journal, candidate["candidate_id"], observations)
    assert evaluation["statut"] == "insuffisant"
    assert evaluation["candidate_active"] is False
    refused = calibration_versions.activer_candidate(
        journal, candidate["candidate_id"], active_version_attendue=None,
        approbateur={"personne": "nathan_owner", "role": "nathan_owner"},
    )
    assert refused["accepte"] is False

    autre_rapport = _rapport_source()
    autre_rapport.pop("rapport_sha256")
    autre_rapport["source_horizon_utc"] = "2025-12-11T00:00:00Z"
    autre_rapport["rapport_sha256"] = hashlib.sha256(
        json.dumps(autre_rapport, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    autre_result = calibration_versions.proposer_candidate(
        journal, autre_rapport,
        politique=copy.deepcopy(calibration_versions.POLITIQUE_INITIALE),
    )
    autre = autre_result["candidates"][0]
    rejeu = calibration_versions.evaluer_candidate(journal, autre["candidate_id"], observations)
    assert rejeu["statut"] == "refuse"
    assert "holdout_deja_utilise" in rejeu["raisons"]
    assert calibration_versions.version_active(journal, "gouttieres", "pi_lin", "bar-1", "c" * 64,
                                               "10", "10") is None


def test_policy_v1_ne_peut_pas_etre_abaissee_sous_la_meme_version_et_rapport_hash_est_verifie():
    journal = []
    weakened = copy.deepcopy(calibration_versions.POLITIQUE_INITIALE)
    weakened["minimum_chantiers_train"] = 1
    refuse = calibration_versions.proposer_candidate(journal, _rapport_source(), politique=weakened)
    assert refuse["statut"] == "refuse"
    assert "politique_version_ou_parametres_invalides" in refuse["raisons"]
    assert journal == []

    falsifie = _rapport_source()
    falsifie["segments"][0]["taux_minutes_par_unite_candidat"] = "1"
    refuse = calibration_versions.proposer_candidate(
        journal, falsifie, politique=copy.deepcopy(calibration_versions.POLITIQUE_INITIALE),
    )
    assert refuse["statut"] == "refuse"
    assert "rapport_source_hash_invalide" in refuse["raisons"]
    assert journal == []


def test_tools_catalogue_n4_et_rejettent_activation_directe_sans_approbation():
    par_nom = {outil.nom: outil for outil in m3_outils()}
    for nom in ("m3_activer_candidate_calibration", "m3_rollback_candidate_calibration"):
        outil = par_nom[nom]
        assert outil.autonomie is Autonomie.T2
        assert outil.niveau_effectif is Niveau.N4
        assert "approbateur" not in outil.parametres["properties"]
    for nom in ("m3_proposer_calibration_temps", "m3_evaluer_candidate_calibration"):
        assert par_nom[nom].autonomie is Autonomie.T1
        assert par_nom[nom].niveau_effectif is Niveau.N2
    assert par_nom["m3_activer_candidate_calibration"].fonction(
        candidate_id="a" * 64, active_version_attendue=None,
    )["accepte"] is False
    assert par_nom["m3_rollback_candidate_calibration"].fonction(candidate_id="a" * 64)["accepte"] is False


def test_cutoff_holdout_avant_horizon_train_est_refuse_apres_hash_recalcule():
    journal = []
    rapport = _rapport_source()
    rapport["holdout_cutoff_utc"] = "2025-12-09T00:00:00Z"
    rapport.pop("rapport_sha256")
    rapport["rapport_sha256"] = hashlib.sha256(
        json.dumps(rapport, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    result = calibration_versions.proposer_candidate(
        journal, rapport, politique=copy.deepcopy(calibration_versions.POLITIQUE_INITIALE),
    )
    assert result["statut"] == "refuse"
    assert "provenance_rapport_incomplete" in result["raisons"]
    assert journal == []


def test_cutoff_entier_chantier_est_exclu_du_holdout():
    journal = []
    proposed = calibration_versions.proposer_candidate(
        journal, _rapport_source(), politique=copy.deepcopy(calibration_versions.POLITIQUE_INITIALE),
    )
    candidate_id = proposed["candidates"][0]["candidate_id"]
    observations = _observations_holdout()
    observations[0] = {
        **observations[0], "horodatage_debut": "2025-12-31T23:00:00Z",
        "horodatage_completion": "2026-01-02T10:30:00Z",
    }
    result = calibration_versions.evaluer_candidate(journal, candidate_id, observations)
    assert result["statut"] == "insuffisant"
    assert result["compteurs_refus_holdout"]["holdout_pas_futur"] == 1
    assert result["holdout_chantiers"] == 29
    assert result["candidate_active"] is False


def test_cas_refuse_la_promotion_si_la_version_attendue_ne_correspond_pas():
    journal = []
    proposed = calibration_versions.proposer_candidate(
        journal, _rapport_source(), politique=copy.deepcopy(calibration_versions.POLITIQUE_INITIALE),
    )
    candidate_id = proposed["candidates"][0]["candidate_id"]
    evaluation = calibration_versions.evaluer_candidate(journal, candidate_id, _observations_holdout())
    assert evaluation["statut"] == "acceptable"

    autre_rapport = _rapport_source()
    autre_rapport.pop("rapport_sha256")
    for index, source in enumerate(autre_rapport["provenance_observations"]):
        source["wct_id"] = f"train-branch-{index}"
        source["chantier_sha256"] = f"{index + 1001:064x}"
        source["m3_source_hash"] = f"{index + 2001:064x}"
        source["m4_wct_hash"] = f"{index + 3001:064x}"
    autre_rapport["source_wct_prefix"]["wct_id_hashes"] = sorted(
        calibration_versions.empreinte_identifiant_wct(source["wct_id"])
        for source in autre_rapport["provenance_observations"]
    )
    autre_rapport["rapport_sha256"] = hashlib.sha256(
        json.dumps(autre_rapport, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    second_proposal = calibration_versions.proposer_candidate(
        journal, autre_rapport, politique=copy.deepcopy(calibration_versions.POLITIQUE_INITIALE),
    )
    assert second_proposal["statut"] == "proposee"
    [second_candidate] = second_proposal["candidates"]
    second_holdout = _observations_holdout()
    for index, observation in enumerate(second_holdout):
        observation["wct_id"] = f"hold-branch-{index}"
        observation["chantier_id"] = f"future-branch-{index}"
        observation["preuve"]["m3_source_hash"] = f"{index + 40001:064x}"
        observation["preuve"]["m4_wct_hash"] = f"{index + 50001:064x}"
    second_evaluation = calibration_versions.evaluer_candidate(
        journal, second_candidate["candidate_id"], second_holdout,
    )
    assert second_evaluation["statut"] == "acceptable"
    owner = {"personne": "nathan_owner", "role": "nathan_owner"}
    active = calibration_versions.activer_candidate(
        journal, candidate_id, active_version_attendue=None, approbateur=owner,
    )
    assert active["accepte"] is True
    avant = copy.deepcopy(journal)
    conflit = calibration_versions.activer_candidate(
        journal, second_candidate["candidate_id"], active_version_attendue=None, approbateur=owner,
    )
    assert conflit["accepte"] is False
    assert "active_version_conflit" in conflit["raisons"]
    assert journal == avant


def test_gardes_holdout_couverture_p80_bootstrap_et_erreur_moyenne():
    def evaluer_avec(durees: list[int], numerator: int = 30, denominator: int = 30):
        journal = []
        proposed = calibration_versions.proposer_candidate(
            journal, _rapport_source(), politique=copy.deepcopy(calibration_versions.POLITIQUE_INITIALE),
        )
        candidate_id = proposed["candidates"][0]["candidate_id"]
        rows = _observations_holdout()
        rows = [{**row, "duree_reelle_minutes": duree} for row, duree in zip(rows, durees, strict=True)]
        return calibration_versions.evaluer_candidate(
            journal, candidate_id, rows,
            couverture_numerateur=numerator, couverture_denominateur=denominator,
        )

    p80_and_coverage = evaluer_avec([90] * 21 + [120] * 9, numerator=26)
    assert "garde_p80_regression" in p80_and_coverage["raisons"]
    assert "couverture_insuffisante" in p80_and_coverage["raisons"]
    assert p80_and_coverage["candidate_active"] is False

    bootstrap = evaluer_avec([90] * 18 + [100] * 12)
    assert bootstrap["statut"] == "insuffisant"
    assert "borne_bootstrap_non_positive" in bootstrap["raisons"]
    assert bootstrap["candidate_active"] is False

    mae = evaluer_avec([100] * 30)
    assert "amelioration_minutes_insuffisante" in mae["raisons"]
    assert "amelioration_relative_insuffisante" in mae["raisons"]
    assert mae["candidate_active"] is False
