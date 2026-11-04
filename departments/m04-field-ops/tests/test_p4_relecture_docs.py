"""Cohérence documentaire de P4-04 / P4-05 (défaut A9 de la relecture adverse).

Les trois documents qui niaient encore le retard mesuré ou la replanification outillée sont vérifiés ici : README M4,
ROLES et l'architecture BMAD du département. Repris de `tests_relecture/test_doc_replanification_obsolete.py`.
"""

from __future__ import annotations

from pathlib import Path

_RACINE = Path(__file__).resolve().parents[3]

AFFIRMATIONS_PERIMEES = (
    (_RACINE / "departments" / "m04-field-ops" / "README.md",
     "aucun outil ni aucune cédule ne la porte"),
    (_RACINE / "docs" / "architecture" / "ROLES.md",
     "Le retard sur la cédule n'est PAS mesuré"),
    (_RACINE / "departments" / "m04-field-ops" / "docs" / "bmad" / "03-ARCHITECTURE.md",
     "Le retard sur la cédule n'est pas mesurable"),
)


def test_les_docs_ne_nient_plus_le_retard_mesure_ni_la_replanification():
    for chemin, phrase in AFFIRMATIONS_PERIMEES:
        texte = chemin.read_text(encoding="utf-8")
        assert phrase not in texte, (
            f"{chemin.relative_to(_RACINE)} affirme encore « {phrase} », alors que "
            "m4_replanifier_intervention (P4-05) et retards_cedule (P4-04) existent")
