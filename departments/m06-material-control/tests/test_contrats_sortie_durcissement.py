import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest

from m6_material_control import contrats_sortie


def test_une_cle_monetaire_glissee_dans_stock_restant_est_detectee_et_rejetee():
    stock_restant_malforme = [
        {"materiau_id": "MAT-1", "quantite": 5.0, "cout_unitaire": 12.5}
    ]

    with pytest.raises(ValueError):
        contrats_sortie.construire_confirmation_consommation_terrain(
            "intervention-1",
            "CHANTIER-1",
            [{"materiau_id": "MAT-1", "quantite": 3.0}],
            stock_restant_malforme,
        )


def test_confirmation_consommation_terrain_nominale_continue_de_fonctionner():
    confirmation = contrats_sortie.construire_confirmation_consommation_terrain(
        "intervention-1",
        "CHANTIER-1",
        [{"materiau_id": "MAT-1", "quantite": 3.0}],
        [{"materiau_id": "MAT-1", "quantite": 5.0}],
    )

    assert confirmation == {
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "materiaux_confirmes": [
            {"materiau_id": "MAT-1", "quantite_declaree": 3.0}
        ],
        "stock_restant": [
            {"materiau_id": "MAT-1", "quantite": 5.0}
        ],
    }

