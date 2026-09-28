"""Test inter-départements : cohérence du contrat SnapshotModule entre M8 et M9.

M9 réutilise SnapshotModule "tel quel" de m8_analytics (PRD M9 §5.1, patron
mesuré) : les deux départements DOIVENT accepter/rejeter exactement les mêmes
formes de `valeurs`, sinon un snapshot valide pour l'un serait un rejet
silencieusement incohérent pour l'autre. Avant le correctif de
m8_analytics/validation.py, une valeur NUMÉRIQUE était acceptée par M8 mais
déjà rejetée par M9 (m9_strategic_intelligence/validation.py:22) — ce test
verrouille la cohérence désormais rétablie.
"""

import sys
from pathlib import Path

_SRC_M8 = Path(__file__).resolve().parents[2] / "m08-analytics" / "src"
_SRC_M9 = Path(__file__).resolve().parents[1] / "src"
for _chemin in (_SRC_M8, _SRC_M9):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

from m8_analytics import validation as m8_validation
from m9_strategic_intelligence import validation as m9_validation

_DICTIONNAIRE_M8 = {"M7-marketing": {"m7_cpl": {}}}


def _snapshot(valeur):
    return {
        "module_source": "M7-marketing",
        "horodatage": "2026-01-01T00:00:00Z",
        "valeurs": {"m7_cpl": valeur},
    }


def test_valeur_numerique_est_rejetee_par_les_deux_departements():
    snapshot = _snapshot(42.0)

    valide_m8, code_m8 = m8_validation.valider_snapshot(snapshot, _DICTIONNAIRE_M8)
    valide_m9, code_m9 = m9_validation.valider_snapshot(snapshot)

    assert valide_m8 is False
    assert valide_m9 is False
    assert isinstance(code_m8, str) and code_m8.startswith("REJ-")
    assert isinstance(code_m9, str) and code_m9.startswith("REJ-")


def test_valeur_booleenne_est_rejetee_par_les_deux_departements():
    snapshot = _snapshot(True)

    valide_m8, _ = m8_validation.valider_snapshot(snapshot, _DICTIONNAIRE_M8)
    valide_m9, _ = m9_validation.valider_snapshot(snapshot)

    assert valide_m8 is False
    assert valide_m9 is False


def test_valeur_texte_est_acceptee_par_les_deux_departements():
    snapshot = _snapshot("42.0")

    valide_m8, verdict_m8 = m8_validation.valider_snapshot(snapshot, _DICTIONNAIRE_M8)
    valide_m9, verdict_m9 = m9_validation.valider_snapshot(snapshot)

    assert (valide_m8, verdict_m8) == (True, None)
    assert (valide_m9, verdict_m9) == (True, None)


def test_snapshot_sans_valeurs_est_accepte_par_les_deux_departements():
    snapshot = {
        "module_source": "M7-marketing",
        "horodatage": "2026-01-01T00:00:00Z",
        "valeurs": {},
    }

    assert m8_validation.valider_snapshot(snapshot, _DICTIONNAIRE_M8) == (True, None)
    assert m9_validation.valider_snapshot(snapshot) == (True, None)
