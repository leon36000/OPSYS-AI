"""Trace d'origine immuable pour les estimations M3 de durée."""

import sys
from decimal import Decimal
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import contrats, estimation, registre, trace_calibration_temps  # noqa: E402

SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
PHOTO = {
    "photo_id": "p1", "resolution_largeur": 3000, "resolution_hauteur": 2000,
    "eclairage": 7, "angle": "face", "reference_echelle": {"type": "porte", "dimensions_connues": True},
}
BAREME = {
    "version": "calibration-test-1", "unite": "pi2", "tarif_secret": "ne-doit-pas-etre-stocke",
    "postes": {"ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0,
                               "duree_minutes_par_unite": 2.5}},
}
FIXTURE_FICTIVE = {"fictif": True, "bareme": BAREME, "photos": [PHOTO], "seuils": SEUILS}


def _run(bareme=FIXTURE_FICTIVE["bareme"], quantite=1200.0, photos=None, journal=None,
         calibration_candidate=None):
    journal = journal if journal is not None else registre.Registre()
    resultat = estimation.orchestrer_estimation(
        contrat={"lead_id": "lead-trace", "conversation_id": "conv-trace", "type_travaux": "ravalement",
                  "ville": "Quebec", "canal": "formulaire_web", "contact": {"nom": "Test", "telephone": "5145550000"},
                  "urgence_declaree": False},
        marqueur={"readiness_ok": True, "lead_id": "lead-trace", "hash_tete_registre": "f" * 64,
                  "horodatage": "2026-09-28T10:00:00Z", "empreinte": "a" * 64},
        photos=FIXTURE_FICTIVE["photos"] if photos is None else photos,
        seuils=FIXTURE_FICTIVE["seuils"], bareme=bareme,
        quantite=quantite, plancher_rentable=9000, registre_cible=journal, graine=42,
        calibration_candidate=calibration_candidate,
    )
    return resultat, journal


def test_trace_hash_chain_exact_inputs_is_versioned_and_replay_stable():
    first, journal_first = _run()
    second, journal_second = _run()
    trace = journal_first.lire()[0]["charge"]["trace_calibration_temps"]
    assert trace == journal_second.lire()[0]["charge"]["trace_calibration_temps"]
    assert trace == {
        "version_schema": 2,
        "type_service": "ravalement",
        "etat_type_service": "presente",
        "quantite": "1200.0",
        "unite_quantite": "pi2",
        "etat_unite": "presente",
        "bareme_version": "calibration-test-1",
        "etat_bareme_version": "presente",
        "taux_minutes_par_unite": "2.5",
        "duree_estimee_minutes": "3000.00",
        "empreinte_bareme": trace["empreinte_bareme"],
        "provenance": "bareme_fourni",
        "semantique_temps": "non_qualifiee",
    }
    assert len(trace["empreinte_bareme"]) == 64
    assert "tarif_secret" not in repr(trace)
    assert "ne-doit-pas-etre-stocke" not in repr(trace)
    assert first["duree_estimee_minutes"] == second["duree_estimee_minutes"] == trace["duree_estimee_minutes"]
    assert set(first["estimation"]) == set(contrats.CHAMPS_ESTIMATION_V1)
    assert journal_first.valider_chaine() == (True, "")


def test_trace_changes_when_exact_quantity_or_time_rate_changes_without_changing_contract():
    base, journal_a = _run()
    _, journal_b = _run(quantite=1300.0)
    modified = {**BAREME, "postes": {"ravalement": {**BAREME["postes"]["ravalement"],
                                                     "duree_minutes_par_unite": 3.0}}}
    _, journal_c = _run(bareme=modified)
    traces = [j.lire()[0]["charge"]["trace_calibration_temps"] for j in (journal_a, journal_b, journal_c)]
    assert traces[0]["quantite"] != traces[1]["quantite"]
    assert traces[0]["empreinte_bareme"] != traces[2]["empreinte_bareme"]
    assert traces[0]["taux_minutes_par_unite"] != traces[2]["taux_minutes_par_unite"]
    assert tuple(base["estimation"]) == contrats.CHAMPS_ESTIMATION_V1


def test_unit_missing_or_invalid_is_marked_without_changing_existing_price_or_duration():
    base, _ = _run()
    for unit, status in ((None, "absente"), ("x" * 200, "invalide"), (7, "invalide")):
        bareme = {**BAREME, "unite": unit}
        result, journal = _run(bareme=bareme)
        trace = journal.lire()[0]["charge"]["trace_calibration_temps"]
        assert trace["unite_quantite"] is None
        assert trace["etat_unite"] == status
        assert result["duree_estimee_minutes"] == base["duree_estimee_minutes"]
        assert result["prix_recommande"] == base["prix_recommande"]
        assert result["estimation"]["intervalle_confiance"] == base["estimation"]["intervalle_confiance"]


def test_no_trace_when_time_is_absent_or_estimation_is_blocked():
    no_rate = {"version": "v1", "unite": "pi2", "postes": {"ravalement": {
        "cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}}}
    _, journal_absent = _run(bareme=no_rate)
    assert "trace_calibration_temps" not in journal_absent.lire()[0]["charge"]
    blocked, journal_blocked = _run(photos=[{**PHOTO, "resolution_largeur": 10}])
    assert blocked["estimation"]["prix_bloque"] is True
    assert "trace_calibration_temps" not in journal_blocked.lire()[0]["charge"]


def test_active_candidate_consumed_only_for_exact_scope_and_writes_schema3_without_price_effect():
    bareme = {**BAREME, "semantique_temps": "duree_ecoulee_intervention"}
    baseline, _ = _run(bareme=bareme)
    candidate = {
        "candidate_id": "c" * 64,
        "taux_minutes_par_unite_candidat": "3.5",
        "scope": {
            "type_service": "ravalement", "unite_quantite": "pi2", "bareme_version": bareme["version"],
            "empreinte_bareme": trace_calibration_temps.empreinte_bareme(bareme),
            "quantite_exacte": "1200.0", "taux_minutes_par_unite_reference": "2.5",
            "parent_calibration_version_id": None,
        },
    }
    journal = registre.Registre()
    active, _ = _run(bareme=bareme, journal=journal, calibration_candidate=candidate)
    trace = journal.lire()[0]["charge"]["trace_calibration_temps"]
    assert trace["version_schema"] == 3
    assert trace["taux_minutes_par_unite_source"] == "2.5"
    assert trace["taux_minutes_par_unite"] == "3.5"
    assert trace["calibration_version_id"] == "c" * 64
    assert trace["duree_estimee_minutes"] == "4200.00"
    assert active["estimation"]["intervalle_confiance"] == baseline["estimation"]["intervalle_confiance"]
    assert active["estimation"] == baseline["estimation"] | {"hash_maillon": active["estimation"]["hash_maillon"]}
    assert journal.valider_chaine() == (True, "")


def test_scope_decimal_equivalent_quantite_float_and_taux_decimal_are_considered_exact():
    bareme = {**BAREME, "semantique_temps": "duree_ecoulee_intervention"}
    candidate = {
        "candidate_id": "e" * 64,
        "taux_minutes_par_unite_candidat": "3.5",
        "scope": {
            "type_service": "ravalement", "unite_quantite": "pi2", "bareme_version": bareme["version"],
            "empreinte_bareme": trace_calibration_temps.empreinte_bareme(bareme),
            "quantite_exacte": "1200", "taux_minutes_par_unite_reference": "2.50",
            "parent_calibration_version_id": None,
        },
    }
    resultat, journal = _run(bareme=bareme, quantite=1200.0, calibration_candidate=candidate)
    [trace] = [m["charge"]["trace_calibration_temps"] for m in journal.lire()]
    assert resultat["accepte"] is True
    assert trace["version_schema"] == 3
    assert trace["quantite"] == "1200.0"
    assert trace["taux_minutes_par_unite_source"] == "2.5"
    assert trace["taux_minutes_par_unite"] == "3.5"
    assert trace["duree_estimee_minutes"] == "4200.00"


def test_invalid_time_rate_refuses_before_register_write():
    invalid = {**BAREME, "postes": {"ravalement": {**BAREME["postes"]["ravalement"],
                                                 "duree_minutes_par_unite": -1}}}
    result, journal = _run(bareme=invalid)
    assert result["accepte"] is False
    assert result["etape"] == "duree_main_doeuvre"
    assert journal.lire() == []


def test_decimal_rate_is_preserved_exactly_in_the_trace():
    bareme = {**BAREME, "postes": {"ravalement": {**BAREME["postes"]["ravalement"],
                                                   "duree_minutes_par_unite": Decimal("0.1250")}}}
    result, journal = _run(bareme=bareme, quantite=1200.0)
    trace = journal.lire()[0]["charge"]["trace_calibration_temps"]
    assert trace["taux_minutes_par_unite"] == "0.1250"
    assert trace["duree_estimee_minutes"] == "150.00000"
    assert result["duree_estimee_minutes"] == trace["duree_estimee_minutes"]


def test_semantique_duree_ecoulee_n_est_qualifiee_que_sur_declaration_exacte():
    declared = {**BAREME, "semantique_temps": "duree_ecoulee_intervention"}
    _, journal_declared = _run(bareme=declared)
    _, journal_absent = _run()
    _, journal_alias = _run(bareme={**BAREME, "semantique_temps": "duree ecoulee intervention"})

    assert journal_declared.lire()[0]["charge"]["trace_calibration_temps"]["semantique_temps"] == (
        "duree_ecoulee_intervention"
    )
    assert journal_absent.lire()[0]["charge"]["trace_calibration_temps"]["semantique_temps"] == "non_qualifiee"
    assert journal_alias.lire()[0]["charge"]["trace_calibration_temps"]["semantique_temps"] == "non_qualifiee"


def test_fingerprint_normalization_distinguishes_decimal_from_lookalike_source_structure():
    from m3_estimation import trace_calibration_temps

    decimal_node = trace_calibration_temps._source_canonique(Decimal("1"))
    list_node = trace_calibration_temps._source_canonique(["decimal", "1"])
    assert registre._encoder_canonique(decimal_node) != registre._encoder_canonique(list_node)
