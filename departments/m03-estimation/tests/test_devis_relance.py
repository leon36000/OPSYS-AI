"""Tests de la relance devis sans réponse (PLAN T2.3, `devis_relance.py`)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import devis_durable, devis_relance, verdicts  # noqa: E402

_CODES_EXERCES_PAR_CE_FICHIER = {"REJ-RELANCE-HORODATAGE-INVALIDE", "REJ-RELANCE-DELAI-INVALIDE"}


def _devis(**surcharges):
    devis = {
        "devis_id": "M3-DEVIS-relance-001",
        "lead_id": "lead-relance-1",
        "chantier_id": None,
        "statut": "brouillon",
        "horodatage": "2026-09-01T10:00:00-04:00",
    }
    devis.update(surcharges)
    return devis


def test_statuts_sans_reponse_copie_devis_durable():
    """Copie épinglée (décision #109) : confrontée au SOURCE de devis_durable, jamais importée."""
    assert devis_relance.STATUTS_SANS_REPONSE == ("brouillon", "envoye")
    assert set(devis_relance.STATUTS_SANS_REPONSE) < set(devis_durable.STATUTS_DEVIS)
    assert "accepte" in devis_durable.STATUTS_DEVIS
    assert "accepte" not in devis_relance.STATUTS_SANS_REPONSE


# --------------------------------------------------------------------------------------- nominal
def test_devis_sans_reponse_au_dela_du_delai_produit_un_fait():
    fait, verdict = devis_relance.construire_fait_devis_sans_reponse(
        _devis(), "2026-09-28T10:00:00-04:00", 14
    )
    assert verdict is None
    assert fait == {
        "devis_id": "M3-DEVIS-relance-001",
        "lead_id": "lead-relance-1",
        "chantier_id": None,
        "statut": "brouillon",
        "horodatage_devis": "2026-09-01T10:00:00-04:00",
        "horodatage_reference": "2026-09-28T10:00:00-04:00",
        "delai_relance_jours": 14,
    }


def test_devis_envoye_egalement_couvert():
    fait, verdict = devis_relance.construire_fait_devis_sans_reponse(
        _devis(statut="envoye"), "2026-09-28T10:00:00-04:00", 14
    )
    assert verdict is None
    assert fait is not None
    assert fait["statut"] == "envoye"


def test_exactement_au_delai_declenche_la_relance():
    """La comparaison est `>=` : exactement 14 jours après doit déclencher, pas seulement au-delà."""
    fait, verdict = devis_relance.construire_fait_devis_sans_reponse(
        _devis(horodatage="2026-09-14T10:00:00-04:00"), "2026-09-28T10:00:00-04:00", 14
    )
    assert verdict is None
    assert fait is not None


# ---------------------------------------------------------------------------- non-événements
def test_devis_accepte_nest_jamais_sans_reponse():
    fait, verdict = devis_relance.construire_fait_devis_sans_reponse(
        _devis(statut="accepte"), "2026-09-28T10:00:00-04:00", 14
    )
    assert verdict is None
    assert fait is None


def test_delai_non_atteint_ne_produit_aucun_fait():
    fait, verdict = devis_relance.construire_fait_devis_sans_reponse(
        _devis(horodatage="2026-09-20T10:00:00-04:00"), "2026-09-28T10:00:00-04:00", 14
    )
    assert verdict is None
    assert fait is None


def test_juste_sous_le_delai_ne_declenche_pas():
    fait, verdict = devis_relance.construire_fait_devis_sans_reponse(
        _devis(horodatage="2026-09-14T10:00:01-04:00"), "2026-09-28T10:00:00-04:00", 14
    )
    assert verdict is None
    assert fait is None


# ------------------------------------------------------------------------------- fail-closed
@pytest.mark.parametrize(
    "delai_invalide", [0, -1, 1.5, "14", True], ids=["zero", "negatif", "flottant", "chaine", "booleen"]
)
def test_delai_relance_jours_invalide_est_rejete(delai_invalide):
    fait, verdict = devis_relance.construire_fait_devis_sans_reponse(
        _devis(), "2026-09-28T10:00:00-04:00", delai_invalide
    )
    assert fait is None
    assert verdict is not None
    assert verdict["code"] == "REJ-RELANCE-DELAI-INVALIDE"


@pytest.mark.parametrize(
    "horodatage_invalide",
    ["", "pas-une-date", "2026-09-28T10:00:00", None, 42],
    ids=["vide", "non_iso", "sans_fuseau", "none", "entier"],
)
def test_horodatage_reference_invalide_est_rejete(horodatage_invalide):
    fait, verdict = devis_relance.construire_fait_devis_sans_reponse(_devis(), horodatage_invalide, 14)
    assert fait is None
    assert verdict is not None
    assert verdict["code"] == "REJ-RELANCE-HORODATAGE-INVALIDE"


@pytest.mark.parametrize(
    "horodatage_devis_invalide",
    ["", "pas-une-date", "2026-09-01T10:00:00", None],
    ids=["vide", "non_iso", "sans_fuseau", "none"],
)
def test_horodatage_devis_invalide_est_rejete(horodatage_devis_invalide):
    fait, verdict = devis_relance.construire_fait_devis_sans_reponse(
        _devis(horodatage=horodatage_devis_invalide), "2026-09-28T10:00:00-04:00", 14
    )
    assert fait is None
    assert verdict is not None
    assert verdict["code"] == "REJ-RELANCE-HORODATAGE-INVALIDE"


@pytest.mark.parametrize(
    "devis_invalide",
    [{}, {"statut": "brouillon"}, {"horodatage": "2026-09-01T10:00:00-04:00"}, "pas-un-dict", None],
    ids=["vide", "sans_horodatage", "sans_statut", "chaine", "none"],
)
def test_devis_malforme_est_rejete(devis_invalide):
    fait, verdict = devis_relance.construire_fait_devis_sans_reponse(
        devis_invalide, "2026-09-28T10:00:00-04:00", 14
    )
    assert fait is None
    assert verdict is not None
    assert verdict["code"] == "REJ-RELANCE-HORODATAGE-INVALIDE"


# ------------------------------------------------------------------------------- catalogue fermé
def test_tous_les_codes_exerces_appartiennent_au_catalogue():
    assert set(verdicts.CODES_M3_LIST) >= _CODES_EXERCES_PAR_CE_FICHIER
    for code in _CODES_EXERCES_PAR_CE_FICHIER:
        assert verdicts.est_verdict(code)


def test_est_sans_reponse_expose_directement():
    resultat, verdict = devis_relance.est_sans_reponse(_devis(), "2026-09-28T10:00:00-04:00", 14)
    assert verdict is None
    assert resultat is True
