import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m9_strategic_intelligence import contrats


def test_champs_snapshot_module_est_un_frozenset_exact():
    attendu = frozenset({"module_source", "horodatage", "valeurs"})

    assert isinstance(contrats.CHAMPS_SNAPSHOT_MODULE, frozenset)
    assert contrats.CHAMPS_SNAPSHOT_MODULE == attendu


def test_champs_rapport_strategique_est_un_frozenset_exact():
    attendu = frozenset(
        {
            "etat",
            "diagnostic",
            "preuves",
            "hypotheses",
            "incertitudes",
            "scenarios",
            "recommandations",
            "priorites",
            "impacts",
            "risques",
            "actions",
            "validation",
            "taches_par_departement",
            "suivi",
            "memoire_m10",
        }
    )

    assert isinstance(contrats.CHAMPS_RAPPORT_STRATEGIQUE, frozenset)
    assert contrats.CHAMPS_RAPPORT_STRATEGIQUE == attendu
