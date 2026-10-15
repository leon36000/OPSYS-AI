"""Raccord M3 de cohorte : jointure réelle des contrats M3, projection M4 et candidate inactive."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
_M4_SRC = Path(__file__).resolve().parents[1].parent / "m04-field-ops" / "src"
for _path in (_SRC, _M4_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from m3_estimation import calibration_raccord, devis_durable, registre  # noqa: E402
from m3_estimation.outils import evaluer_calibration_cohortes  # noqa: E402


def _registres_m3(*, accepter=True):
    devis = []
    journal = registre.Registre()
    charge = {
        "devis_id": "DEVIS-COHORTE-1",
        "lead_id": "LEAD-COHORTE-1",
        "empreinte_marqueur_m2": "a" * 64,
        "niveau_confiance": 0.9,
        "bareme_version": "2026.1",
        "graine_monte_carlo": 91,
        "duree_estimee_minutes": "100",
        "trace_calibration_temps": {
            "version_schema": 2,
            "semantique_temps": "duree_ecoulee_intervention",
            "duree_estimee_minutes": "100",
            "type_service": "gouttieres",
            "quantite": "10",
            "unite_quantite": "pi_lin",
            "taux_minutes_par_unite": "10",
            "bareme_version": "2026.1",
        },
    }
    maillon, verdict = journal.ajouter(charge)
    assert verdict is None
    source_hash = maillon["hash_maillon"]
    devis_courant, verdict = devis_durable.creer_devis(
        "DEVIS-COHORTE-1", "LEAD-COHORTE-1", "CHANTIER-COHORTE-1",
        [{"description": "Gouttières", "quantite": "10", "unite": "pi_lin",
          "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
        "0.20", "2025-12-01T12:00:00Z", devis, estimation_source_hash=source_hash,
    )
    assert verdict is None
    if accepter:
        accepte, verdict = devis_durable.marquer_devis_accepte(
            devis_courant["devis_id"], "client-confirmation-fixture", "2025-12-02T12:00:00Z", devis,
        )
        assert verdict is None and accepte["statut"] == "accepte"
    return journal, devis, source_hash


def _projection_m4():
    wct = {
        "wct_id": "WCT-COHORTE-1", "intervention_id": "INT-COHORTE-1",
        "lead_id": "LEAD-COHORTE-1", "technicien_id": "TECH-1",
        "horodatage_completion": "2026-01-03T12:00:00Z", "fix_gps_completion": {},
        "duree_reelle_minutes": 110, "ecart_signale": False, "revue_id": "REVUE-1",
        "hash_maillon": "b" * 64, "consommateurs_cibles": ["M3"],
        "devis_id": "DEVIS-COHORTE-1", "statut": "completed_pending_review",
    }
    return {
        "observations": [{
            "wct": wct, "wct_hash": wct["hash_maillon"],
            "statut_publie": "completed_pending_review", "statut_courant": "completed_verified",
            "horodatage_debut": "2026-01-01T09:00:00Z", "horodatage_depart": "2026-01-01T11:00:00Z",
            "horodatage_completion": "2026-01-03T12:00:00Z", "duree_reelle_minutes": 110,
            "semantique_temps": "duree_ecoulee_intervention", "unite_duree": "minute",
        }],
        "refus": [],
    }


def test_raccord_resout_hash_exact_lead_devis_trace_et_laisse_candidate_inactive():
    journal, devis, _ = _registres_m3()
    rapport = calibration_raccord.construire_rapport(
        coupure_utc="2026-02-01T00:00:00Z", registre_estimations=journal,
        registre_devis=devis, projections_m4=_projection_m4(),
    )
    assert rapport["candidate_active"] is False
    assert rapport["statut"] == "insuffisant"
    assert rapport["refus_jointure_m3"] == {}
    assert rapport["exclusions"] == []
    assert rapport["compteurs"]["observations_distinctes_valides"] == 1
    assert rapport["source_wct_ids"] == "registre_m03_estime_vs_reel"
    assert rapport["completude_corpus_m4"] == "non_prouvee"


def test_raccord_exclut_brouillon_canonique_puis_accepte_meme_source_sans_muter_prix():
    """Le seam reçoit une projection M4 de fixture : aucun chantier réel depuis un brouillon n'est simulé."""
    journal, devis, source_hash = _registres_m3(accepter=False)
    projection = _projection_m4()
    devis_id = projection["observations"][0]["wct"]["devis_id"]
    brouillon, verdict = devis_durable.lire_devis(devis, devis_id)
    assert verdict is None and brouillon["statut"] == "brouillon"
    assert brouillon["estimation_source_hash"] == source_hash
    assert journal.valider_chaine()[0] is True
    avant = copy.deepcopy((journal.lire(), devis, projection))

    rapport = calibration_raccord.construire_rapport(
        coupure_utc="2026-02-01T00:00:00Z", registre_estimations=journal,
        registre_devis=devis, projections_m4=projection,
    )
    assert rapport["refus_jointure_m3"] == {"chaine_devis_non_valide": 1}
    assert rapport["refus_projection_m4"] == []
    assert rapport["compteurs"]["observations_distinctes_valides"] == 0
    assert rapport["candidate_active"] is False
    assert rapport["statut"] == "insuffisant"
    assert (journal.lire(), devis, projection) == avant
    relu, verdict = devis_durable.lire_devis(devis, devis_id)
    assert verdict is None and relu == brouillon

    # Seule l'acceptation canonique change : la source et le WCT concordant restent identiques.
    accepte, verdict = devis_durable.marquer_devis_accepte(
        devis_id, "client-confirmation-fixture", "2025-12-02T12:00:00Z", devis,
    )
    assert verdict is None and accepte["statut"] == "accepte"
    assert accepte["cout_total"] == brouillon["cout_total"]
    assert accepte["prix_total"] == brouillon["prix_total"]
    assert accepte["estimation_source_hash"] == source_hash
    apres_acceptation = copy.deepcopy((journal.lire(), devis, projection))
    rapport_accepte = calibration_raccord.construire_rapport(
        coupure_utc="2026-02-01T00:00:00Z", registre_estimations=journal,
        registre_devis=devis, projections_m4=projection,
    )
    assert rapport_accepte["refus_jointure_m3"] == {}
    assert rapport_accepte["refus_projection_m4"] == []
    assert rapport_accepte["compteurs"]["observations_distinctes_valides"] == 1
    assert rapport_accepte["candidate_active"] is False
    assert (journal.lire(), devis, projection) == apres_acceptation
    assert journal.lire() == avant[0] and projection == avant[2]
    assert devis[0] == avant[1][0]
    relu, verdict = devis_durable.lire_devis(devis, devis_id)
    assert verdict is None and relu == accepte


def test_raccord_refuse_source_hash_absent_meme_si_devis_et_lead_correspondent():
    journal, devis, _ = _registres_m3()
    devis[0]["estimation_source_hash"] = "d" * 64
    rapport = calibration_raccord.construire_rapport(
        coupure_utc="2026-02-01T00:00:00Z", registre_estimations=journal,
        registre_devis=devis, projections_m4=_projection_m4(),
    )
    assert rapport["candidate_active"] is False
    assert rapport["statut"] == "insuffisant"
    assert rapport["refus_jointure_m3"] == {"source_estimation_hash_absent_ou_ambigu": 1}
    assert rapport["compteurs"]["observations_distinctes_valides"] == 0


def test_raccord_refuse_sequence_devis_ambigue():
    journal, devis, _ = _registres_m3()
    devis.insert(1, dict(devis[0]))
    rapport = calibration_raccord.construire_rapport(
        coupure_utc="2026-02-01T00:00:00Z", registre_estimations=journal,
        registre_devis=devis, projections_m4=_projection_m4(),
    )
    assert rapport["candidate_active"] is False
    assert rapport["refus_jointure_m3"] == {"chaine_devis_non_valide": 1}
    assert rapport["compteurs"]["observations_distinctes_valides"] == 0


def test_raccord_refuse_transition_devis_invalide():
    journal, devis, _ = _registres_m3()
    devis[-1]["lead_id"] = "LEAD-FORGE"
    rapport = calibration_raccord.construire_rapport(
        coupure_utc="2026-02-01T00:00:00Z", registre_estimations=journal,
        registre_devis=devis, projections_m4=_projection_m4(),
    )
    assert rapport["candidate_active"] is False
    assert rapport["refus_jointure_m3"] == {"chaine_devis_non_valide": 1}
    assert rapport["compteurs"]["observations_distinctes_valides"] == 0


def test_raccord_preserve_refus_m4_d_un_wct_introuvable_sans_fabriquer_observation():
    journal, devis, _ = _registres_m3()
    projection = {"observations": [], "refus": [{"wct_id": "WCT-ABSENT", "motif": "wct_introuvable"}]}
    rapport = calibration_raccord.construire_rapport(
        coupure_utc="2026-02-01T00:00:00Z", registre_estimations=journal,
        registre_devis=devis, projections_m4=projection,
    )
    assert rapport["candidate_active"] is False
    assert rapport["statut"] == "insuffisant"
    assert rapport["refus_projection_m4"] == projection["refus"]
    assert rapport["compteurs"]["observations_distinctes_valides"] == 0


def test_outil_cohorte_refuse_appel_sans_origine_ni_identite():
    rapport = evaluer_calibration_cohortes("2026-02-01T00:00:00Z")
    assert rapport == {
        "statut": "refuse", "raisons": ["departement_appelant_non_autorise"], "candidate_active": False,
    }
