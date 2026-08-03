import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m6_material_control import materiel


def wct_valide():
    return {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "lead_id": "lead-1",
        "technicien_id": "tech-1",
        "horodatage_completion": "2025-01-01T00:00:00Z",
        "fix_gps_completion": {"latitude": 1.0, "longitude": 2.0},
        "duree_reelle_minutes": 30,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M6"],
        "devis_id": None,
    }


class RegistreVide:
    def lire(self):
        return []


def test_une_ligne_consommee_malformee_produit_un_rejet_nomme_jamais_une_exception():
    formulaire = {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "lignes_consommees": [{"champ_inconnu": "valeur"}],
    }

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        RegistreVide(),
    )

    assert confirmation is None
    assert code_verdict == "REJ-FORMULAIRE-LIGNE-INVALIDE"


def test_consommation_materiaux_nominale_continue_de_fonctionner():
    formulaire = {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "lignes_consommees": [
            {"materiau_id": "MAT-1", "quantite": 3.0}
        ],
    }

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        RegistreVide(),
    )

    assert code_verdict is None
    assert confirmation == {
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "materiaux_confirmes": [
            {"materiau_id": "MAT-1", "quantite_declaree": 3.0}
        ],
        "stock_restant": [
            {"materiau_id": "MAT-1", "quantite": -3.0}
        ],
    }


def test_lignes_consommees_none_produit_un_rejet_nomme_jamais_une_exception():
    formulaire = {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "lignes_consommees": None,
    }

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        RegistreVide(),
    )

    assert confirmation is None
    assert code_verdict == "REJ-FORMULAIRE-LIGNE-INVALIDE"


def test_quantite_chaine_produit_un_rejet_nomme_jamais_une_exception():
    formulaire = {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "lignes_consommees": [
            {"materiau_id": "MAT-1", "quantite": "trois"}
        ],
    }

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        RegistreVide(),
    )

    assert confirmation is None
    assert code_verdict == "REJ-FORMULAIRE-LIGNE-INVALIDE"


def test_quantite_bool_produit_un_rejet_nomme_jamais_une_exception():
    for quantite in (True, False):
        formulaire = {
            "wct_id": "wct-1",
            "intervention_id": "intervention-1",
            "chantier_id": "CHANTIER-1",
            "lignes_consommees": [
                {"materiau_id": "MAT-1", "quantite": quantite}
            ],
        }

        confirmation, code_verdict = materiel.consommer_materiaux(
            wct_valide(),
            formulaire,
            RegistreVide(),
        )

        assert confirmation is None
        assert code_verdict == "REJ-FORMULAIRE-LIGNE-INVALIDE"
