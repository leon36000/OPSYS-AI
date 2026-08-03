import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m5_financecore import contrats


def test_champs_mouvement_financier_constante_exacte():
    assert isinstance(contrats.CHAMPS_MOUVEMENT_FINANCIER, frozenset)
    assert contrats.CHAMPS_MOUVEMENT_FINANCIER == frozenset(
        {
            "montant",
            "type_mouvement",
            "horodatage",
            "classe_retention",
            "source",
        }
    )


def test_types_mouvement_et_classes_retention_constantes():
    assert isinstance(contrats.TYPE_MOUVEMENT, tuple)
    assert set(contrats.TYPE_MOUVEMENT) == {
        "ENCAISSEMENT",
        "DECAISSEMENT",
        "PROVISION",
        "AJUSTEMENT",
        "AUTRE",
    }
    assert "AUTRE" in contrats.TYPE_MOUVEMENT

    assert isinstance(contrats.CLASSE_RETENTION, tuple)
    assert set(contrats.CLASSE_RETENTION) == {"FISCALE_6_ANS", "STANDARD"}

