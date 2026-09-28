import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m8_analytics import alertes, qualite  # noqa: E402

_DEFINITION = {
    "metric_id": "m4_duree_reelle_minutes",
    "departement_proprietaire": "m04-field-ops",
    "unite": "min",
    "source": "Module M4 — WCT",
    "fraicheur_attendue_jours": 2,
    "regles_qualite": {"plage_min": 0, "plage_max": None},
}


def test_proposer_action_donnee_absente_nomme_le_departement_et_la_source():
    evaluation = qualite.evaluer_presence(_DEFINITION["metric_id"], 0, None)

    alerte = alertes.proposer_action(evaluation, _DEFINITION)

    assert alerte["type_alerte"] == qualite.VERDICT_DONNEE_ABSENTE
    assert alerte["a_qui"] == "m04-field-ops"
    assert alerte["source"] == "Module M4 — WCT"
    assert _DEFINITION["metric_id"] in alerte["quoi"]
    assert alerte["preuve"] == {"metric_id": _DEFINITION["metric_id"], "n": 0}
    # DA-M8-07 : jamais un champ de cause ou de responsabilité, seulement le fait mesuré.
    assert set(alerte) == {"type_alerte", "quoi", "a_qui", "pourquoi", "preuve", "source"}


def test_proposer_action_donnee_perimee_chiffre_la_preuve():
    evaluation = qualite.evaluer_fraicheur(_DEFINITION["metric_id"], 5.0, 2)

    alerte = alertes.proposer_action(evaluation, _DEFINITION)

    assert alerte["type_alerte"] == qualite.VERDICT_DONNEE_PERIMEE
    assert alerte["preuve"] == {
        "metric_id": _DEFINITION["metric_id"],
        "fraicheur_jours": 5.0,
        "fraicheur_attendue_jours": 2,
    }
    assert "5.00" in alerte["pourquoi"]
    assert "2" in alerte["pourquoi"]


def test_proposer_action_hors_plage_chiffre_la_preuve():
    evaluation = qualite.evaluer_plage(_DEFINITION["metric_id"], -3.0, 0, None)

    alerte = alertes.proposer_action(evaluation, _DEFINITION)

    assert alerte["type_alerte"] == qualite.VERDICT_HORS_PLAGE
    assert alerte["preuve"]["valeur"] == -3.0
    assert alerte["preuve"]["plage_min"] == 0


def test_proposer_action_verdict_inconnu_leve_value_error_jamais_une_action_inventee():
    evaluation = {"metric_id": "m", "verdict": "REJ-INCONNU"}

    with pytest.raises(ValueError, match="REJ-INCONNU"):
        alertes.proposer_action(evaluation, _DEFINITION)


# ---------------------------------------------------------------------------
# T3.1-suite : doublon d'observation et incohérence entre séries.
# ---------------------------------------------------------------------------


def test_proposer_action_doublon_nomme_les_horodatages_en_double():
    evaluation = qualite.evaluer_unicite(
        _DEFINITION["metric_id"], ["2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"]
    )

    alerte = alertes.proposer_action(evaluation, _DEFINITION)

    assert alerte["type_alerte"] == qualite.VERDICT_DOUBLON
    assert alerte["a_qui"] == "m04-field-ops"
    assert _DEFINITION["metric_id"] in alerte["quoi"]
    assert "2026-01-01T00:00:00Z" in alerte["pourquoi"]
    assert alerte["preuve"] == {
        "metric_id": _DEFINITION["metric_id"],
        "horodatages_doublons": {"2026-01-01T00:00:00Z": 2},
        "n_observations": 2,
    }
    # DA-M8-07 : jamais un champ de cause ou de responsabilité.
    assert set(alerte) == {"type_alerte", "quoi", "a_qui", "pourquoi", "preuve", "source"}


def test_proposer_action_incoherence_chiffre_la_preuve():
    composantes = {"m4_autre_composante": {"coefficient": 1.0, "valeur": 10.0}}
    evaluation = qualite.evaluer_coherence(_DEFINITION["metric_id"], 100.0, composantes, 0.01)

    alerte = alertes.proposer_action(evaluation, _DEFINITION)

    assert alerte["type_alerte"] == qualite.VERDICT_INCOHERENT
    assert _DEFINITION["metric_id"] in alerte["quoi"]
    assert alerte["preuve"]["valeur"] == 100.0
    assert alerte["preuve"]["valeur_attendue"] == 10.0
    assert alerte["preuve"]["ecart"] == 90.0
    assert alerte["preuve"]["composantes"] == composantes
    assert set(alerte) == {"type_alerte", "quoi", "a_qui", "pourquoi", "preuve", "source"}
