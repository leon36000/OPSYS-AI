"""Tests — métriques réputation déterministes (alignées m7-metrics, REJ-0040).

TDD RED capturé : ces tests ont été écrits AVANT l'implémentation de metrics.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from m7_marketing.reputation import metrics

_M7 = Path(__file__).resolve().parents[2]
_REPUTATION = _M7 / "src" / "m7_marketing" / "reputation"

# ---------------------------------------------------------------------------
# Données de test
# ---------------------------------------------------------------------------

_AVIS = [
    {"id": "a1", "note": 5, "date": "2026-01-01", "texte": "Excellent."},
    {"id": "a2", "note": 4, "date": "2026-01-05", "texte": "Bon service."},
    {"id": "a3", "note": 3, "date": "2026-01-10", "texte": "Correct."},
    {"id": "a4", "note": 2, "date": "2026-01-15", "texte": "Déçu."},
    {"id": "a5", "note": 1, "date": "2026-01-20", "texte": "Très mauvais."},
]

_REPONSES = [
    {"avis_id": "a1", "approval_status": "PROPOSE", "date_traitement": "2026-01-03"},
    {"avis_id": "a3", "approval_status": "PROPOSE", "date_traitement": "2026-01-12"},
]

_CLASSIFICATIONS = ["eloge", "neutre", "neutre", "urgence", "urgence"]


# ---------------------------------------------------------------------------
# Tests — calculer_repartition_notes
# ---------------------------------------------------------------------------

def test_repartition_notes_contient_toutes_notes():
    """Toutes les notes 1-5 figurent dans la répartition (même à 0)."""
    rep = metrics.calculer_repartition_notes(_AVIS)
    for note in range(1, 6):
        assert note in rep


def test_repartition_notes_valeurs_correctes():
    """Chaque note est comptée correctement."""
    rep = metrics.calculer_repartition_notes(_AVIS)
    assert rep[5] == 1
    assert rep[4] == 1
    assert rep[3] == 1
    assert rep[2] == 1
    assert rep[1] == 1


def test_repartition_notes_liste_vide():
    """Liste vide → toutes les notes à 0."""
    rep = metrics.calculer_repartition_notes([])
    assert all(rep[n] == 0 for n in range(1, 6))


def test_repartition_notes_note_absente_est_zero():
    """Note 1 absente → rep[1] == 0."""
    avis = [{"id": "x", "note": 5}, {"id": "y", "note": 5}]
    rep = metrics.calculer_repartition_notes(avis)
    assert rep[1] == 0
    assert rep[5] == 2


# ---------------------------------------------------------------------------
# Tests — calculer_note_moyenne
# ---------------------------------------------------------------------------

def test_note_moyenne_correcte():
    """Moyenne correcte sur 5 avis (notes 1-5 → 3.0)."""
    assert metrics.calculer_note_moyenne(_AVIS) == pytest.approx(3.0)


def test_note_moyenne_liste_vide_est_zero():
    """Liste vide → 0.0."""
    assert metrics.calculer_note_moyenne([]) == 0.0


def test_note_moyenne_un_seul_avis():
    """Un seul avis note 4 → 4.0."""
    assert metrics.calculer_note_moyenne([{"id": "x", "note": 4}]) == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Tests — calculer_taux_reponse
# ---------------------------------------------------------------------------

def test_taux_reponse_partiel():
    """2 réponses sur 5 avis → taux = 0.4."""
    taux = metrics.calculer_taux_reponse(_AVIS, _REPONSES)
    assert taux == pytest.approx(0.4)


def test_taux_reponse_zero_reponses():
    """0 réponses → taux = 0.0."""
    assert metrics.calculer_taux_reponse(_AVIS, []) == pytest.approx(0.0)


def test_taux_reponse_toutes_traitees():
    """Toutes les réponses fournies → taux = 1.0."""
    reponses_toutes = [{"avis_id": a["id"]} for a in _AVIS]
    assert metrics.calculer_taux_reponse(_AVIS, reponses_toutes) == pytest.approx(1.0)


def test_taux_reponse_liste_vide_avis():
    """Avis vide → 0.0 (pas de division par zéro)."""
    assert metrics.calculer_taux_reponse([], []) == pytest.approx(0.0)


def test_taux_reponse_reponse_inconnue_ignoree():
    """avis_id inexistant dans la liste d'avis est ignoré."""
    reponses = [{"avis_id": "inconnu"}]
    taux = metrics.calculer_taux_reponse(_AVIS, reponses)
    assert taux == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests — calculer_repartition_categories
# ---------------------------------------------------------------------------

def test_repartition_cats_contient_toutes_categories():
    """Toutes les catégories figurent dans la répartition."""
    rep = metrics.calculer_repartition_categories(_CLASSIFICATIONS)
    for cat in ("litige", "urgence", "eloge", "neutre"):
        assert cat in rep


def test_repartition_cats_valeurs_correctes():
    """Comptage correct des catégories."""
    rep = metrics.calculer_repartition_categories(_CLASSIFICATIONS)
    assert rep["eloge"] == 1
    assert rep["neutre"] == 2
    assert rep["urgence"] == 2
    assert rep["litige"] == 0


def test_repartition_cats_liste_vide():
    """Liste vide → toutes les catégories à 0."""
    rep = metrics.calculer_repartition_categories([])
    assert all(rep[c] == 0 for c in ("litige", "urgence", "eloge", "neutre"))


# ---------------------------------------------------------------------------
# Tests — calculer_delai_moyen
# ---------------------------------------------------------------------------

def test_delai_moyen_correct():
    """Délai moyen calculé correctement : (2 + 2) / 2 = 2.0 jours."""
    # a1 : 2026-01-01 → traitement 2026-01-03 = 2 jours
    # a3 : 2026-01-10 → traitement 2026-01-12 = 2 jours
    delai = metrics.calculer_delai_moyen(_AVIS, _REPONSES)
    assert delai == pytest.approx(2.0)


def test_delai_moyen_sans_date_traitement_retourne_none():
    """Réponses sans date_traitement → None."""
    reponses = [{"avis_id": "a1", "approval_status": "PROPOSE"}]
    assert metrics.calculer_delai_moyen(_AVIS, reponses) is None


def test_delai_moyen_liste_vide_retourne_none():
    """Listes vides → None."""
    assert metrics.calculer_delai_moyen([], []) is None


# ---------------------------------------------------------------------------
# Tests — calculer_metriques (intégration)
# ---------------------------------------------------------------------------

def test_calculer_metriques_retourne_dict():
    """calculer_metriques() retourne un dict."""
    result = metrics.calculer_metriques(_AVIS, _REPONSES, _CLASSIFICATIONS)
    assert isinstance(result, dict)


def test_calculer_metriques_cles_alignees_m7():
    """Les clés retournées correspondent aux ids définis dans m7-metrics.v1.yaml."""
    result = metrics.calculer_metriques(_AVIS, _REPONSES, _CLASSIFICATIONS)
    cles_attendues = {
        "m7_rep_total_avis",
        "m7_rep_repartition_notes",
        "m7_rep_note_moyenne",
        "m7_rep_taux_reponse",
        "m7_rep_repartition_cats",
        "m7_rep_delai_moyen_jours",
    }
    assert cles_attendues.issubset(set(result.keys()))


def test_calculer_metriques_total_avis():
    """m7_rep_total_avis correspond au nombre d'avis."""
    result = metrics.calculer_metriques(_AVIS)
    assert result["m7_rep_total_avis"] == len(_AVIS)


def test_calculer_metriques_ids_dans_yaml():
    """Les ids de métriques réputation figurent dans m7-metrics.v1.yaml."""
    yaml_path = _M7 / "metrics" / "m7-metrics.v1.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    ids_yaml = {m["id"] for m in data.get("metrics", [])}
    for cle in (
        "m7_rep_total_avis",
        "m7_rep_repartition_notes",
        "m7_rep_note_moyenne",
        "m7_rep_taux_reponse",
        "m7_rep_repartition_cats",
        "m7_rep_delai_moyen_jours",
    ):
        assert cle in ids_yaml, f"Métrique '{cle}' absente de m7-metrics.v1.yaml"


def test_calculer_metriques_sans_reponses_ni_classifications():
    """Appel minimal (avis uniquement) ne plante pas."""
    result = metrics.calculer_metriques(_AVIS)
    assert result["m7_rep_taux_reponse"] == pytest.approx(0.0)
    assert result["m7_rep_delai_moyen_jours"] is None


def test_metrics_zero_reseau():
    """metrics.py n'importe pas urllib ni socket."""
    import ast as _ast

    source = (_REPUTATION / "metrics.py").read_text(encoding="utf-8")
    tree = _ast.parse(source)
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                assert "urllib" not in alias.name
                assert "socket" not in alias.name
        elif isinstance(node, _ast.ImportFrom):
            module = node.module or ""
            assert "urllib" not in module
            assert "socket" not in module
