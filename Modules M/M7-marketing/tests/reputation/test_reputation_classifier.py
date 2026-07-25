"""Tests — classificateur déterministe d'avis (REJ-0040 : aucun score LLM).

TDD RED capturé : ces tests ont été écrits AVANT l'implémentation de classifier.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ajout du module src/reputation au sys.path
# ---------------------------------------------------------------------------
_M7 = Path(__file__).resolve().parents[2]
_REPUTATION = _M7 / "src" / "reputation"
for _p in (str(_REPUTATION),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import classifier  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _avis(note: int, texte: str = "", id_: str = "avis-x") -> dict:
    return {"id": id_, "note": note, "texte": texte}


# ---------------------------------------------------------------------------
# Tests — règle 1 : litige (priorité maximale)
# ---------------------------------------------------------------------------

def test_litige_par_mot_cle_reclamation():
    """'réclamation' dans le texte → litige (indépendant de la note)."""
    a = _avis(5, "Après réclamation, une équipe est revenue.")
    assert classifier.classifier_avis(a) == "litige"


def test_litige_par_mot_cle_plainte():
    """'plainte' dans le texte → litige."""
    a = _avis(4, "J'ai déposé une plainte formelle.")
    assert classifier.classifier_avis(a) == "litige"


def test_litige_par_mot_cle_remboursement():
    """'remboursement' dans le texte → litige."""
    a = _avis(3, "Je demande un remboursement immédiat.")
    assert classifier.classifier_avis(a) == "litige"


def test_litige_priorite_sur_urgence():
    """Litige est prioritaire sur urgence (même note ≤ 2)."""
    a = _avis(1, "Plainte déposée pour mauvaise exécution.")
    assert classifier.classifier_avis(a) == "litige"


def test_litige_priorite_sur_eloge():
    """Litige est prioritaire même si la note est 5."""
    a = _avis(5, "Service excellent mais j'ai dû faire une réclamation.")
    assert classifier.classifier_avis(a) == "litige"


# ---------------------------------------------------------------------------
# Tests — règle 2 : urgence (note ≤ 2 OU mot-clé)
# ---------------------------------------------------------------------------

def test_urgence_note_1():
    """Note 1 sans mot-clé spécial → urgence."""
    a = _avis(1, "Très mauvaise expérience. Le chantier a été abandonné.")
    assert classifier.classifier_avis(a) == "urgence"


def test_urgence_note_2():
    """Note 2 → urgence."""
    a = _avis(2, "Déçu par la prestation.")
    assert classifier.classifier_avis(a) == "urgence"


def test_urgence_par_mot_cle_urgence():
    """Mot 'urgence' dans le texte → urgence (quelle que soit la note)."""
    a = _avis(5, "Urgence plomberie prise en charge en moins de deux heures.")
    assert classifier.classifier_avis(a) == "urgence"


def test_urgence_par_mot_cle_urgent():
    """Mot 'urgent' dans le texte → urgence."""
    a = _avis(4, "Problème urgent à régler rapidement.")
    assert classifier.classifier_avis(a) == "urgence"


def test_urgence_par_mot_cle_rapidement():
    """Mot 'rapidement' dans le texte avec note ≥ 3 → urgence."""
    a = _avis(3, "Il faudrait intervenir rapidement.")
    assert classifier.classifier_avis(a) == "urgence"


# ---------------------------------------------------------------------------
# Tests — règle 3 : éloge (note = 5 OU mot-clé)
# ---------------------------------------------------------------------------

def test_eloge_note_5_sans_mot_cle():
    """Note 5 sans mot-clé → éloge."""
    a = _avis(5, "Travaux de maçonnerie réalisés rapidement — ah, dans les temps.")
    # "rapidement" → urgence, donc testons sans ce mot
    a = _avis(5, "Service de qualité, tout s'est bien passé.")
    assert classifier.classifier_avis(a) == "eloge"


def test_eloge_par_mot_cle_excellent():
    """Mot 'excellent' dans le texte → éloge (note 4)."""
    a = _avis(4, "Service excellent, je recommande.")
    assert classifier.classifier_avis(a) == "eloge"


def test_eloge_par_mot_cle_impeccable():
    """Mot 'impeccable' dans le texte → éloge."""
    a = _avis(4, "Travail impeccable, équipe sérieuse.")
    assert classifier.classifier_avis(a) == "eloge"


def test_eloge_par_mot_cle_recommande():
    """Mot 'recommande' dans le texte → éloge."""
    a = _avis(3, "Je recommande sans hésitation.")
    assert classifier.classifier_avis(a) == "eloge"


# ---------------------------------------------------------------------------
# Tests — règle 4 : neutre (cas résiduel)
# ---------------------------------------------------------------------------

def test_neutre_note_3_sans_mot_cle():
    """Note 3, texte sans mot-clé → neutre."""
    a = _avis(3, "Service correct mais sans plus, communication average.")
    assert classifier.classifier_avis(a) == "neutre"


def test_neutre_note_4_sans_mot_cle():
    """Note 4, texte sans mot-clé → neutre."""
    a = _avis(4, "Bon service dans l'ensemble, délai de rappel un peu long.")
    assert classifier.classifier_avis(a) == "neutre"


# ---------------------------------------------------------------------------
# Tests — catégories valides
# ---------------------------------------------------------------------------

def test_categories_expose_valeurs_attendues():
    """CATEGORIES expose les 4 valeurs attendues."""
    assert classifier.CATEGORIES == frozenset({"litige", "urgence", "eloge", "neutre"})


# ---------------------------------------------------------------------------
# Tests — robustesse
# ---------------------------------------------------------------------------

def test_note_manquante_leve_valueerror():
    """ValueError si 'note' est absente."""
    with pytest.raises(ValueError):
        classifier.classifier_avis({"id": "x", "texte": "ok"})


def test_note_hors_limites_leve_valueerror():
    """ValueError si note hors [1, 5]."""
    with pytest.raises(ValueError):
        classifier.classifier_avis(_avis(6, "ok"))
    with pytest.raises(ValueError):
        classifier.classifier_avis(_avis(0, "ok"))


def test_texte_absent_ne_plante_pas():
    """texte absent → fonctionne (traité comme chaîne vide)."""
    a = {"id": "x", "note": 3}
    result = classifier.classifier_avis(a)
    assert result in classifier.CATEGORIES


def test_classifier_zero_reseau():
    """classifier.py n'importe pas urllib ni socket."""
    import ast as _ast

    source = (_REPUTATION / "classifier.py").read_text(encoding="utf-8")
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


def test_classifier_aucun_score_llm():
    """classifier.py ne contient pas d'import de bibliothèques LLM (REJ-0040)."""
    import ast as _ast

    source = (_REPUTATION / "classifier.py").read_text(encoding="utf-8")
    tree = _ast.parse(source)
    modules_interdits = {"openai", "anthropic", "litellm", "requests", "httpx"}
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                assert alias.name not in modules_interdits, (
                    f"Import interdit '{alias.name}' dans classifier.py (REJ-0040)"
                )
        elif isinstance(node, _ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            assert module not in modules_interdits, (
                f"Import interdit '{node.module}' dans classifier.py (REJ-0040)"
            )


def test_classifier_deterministe():
    """Même avis → même catégorie à chaque appel."""
    a = _avis(2, "Déçu par la prestation.")
    result1 = classifier.classifier_avis(a)
    result2 = classifier.classifier_avis(a)
    assert result1 == result2
