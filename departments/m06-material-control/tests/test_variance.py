import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m6_material_control import variance


class RegistreFactice:
    def __init__(self, mouvements):
        self._mouvements = mouvements

    def lire(self):
        return self._mouvements


def test_variance_sans_ecart_avec_reception_prealable():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MAT-1",
                "quantite": 10.0,
            }
        ]
    )

    resultat = variance.evaluer_variance(
        "CHANTIER-1",
        "MAT-1",
        10.0,
        registre,
    )

    assert resultat == {
        "chantier_id": "CHANTIER-1",
        "materiau_id": "MAT-1",
        "verdict_variance": "AUCUN_ECART",
        "quantite_theorique": 10.0,
        "quantite_comptee": 10.0,
        "ecart": 0.0,
        "note_investigation": None,
    }


def test_variance_inferieure_au_stock_theorique_avec_ecart_signe_et_sans_note():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MAT-1",
                "quantite": 10.0,
            }
        ]
    )

    resultat = variance.evaluer_variance(
        "CHANTIER-1",
        "MAT-1",
        7.0,
        registre,
    )

    assert resultat["verdict_variance"] == "STOCK_INFERIEUR_AU_THEORIQUE"
    assert resultat["quantite_theorique"] == 10.0
    assert resultat["quantite_comptee"] == 7.0
    assert resultat["ecart"] == -3.0
    assert resultat["note_investigation"] is None


def test_variance_superieure_au_stock_theorique_avec_ecart_signe():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MAT-1",
                "quantite": 10.0,
            }
        ]
    )

    resultat = variance.evaluer_variance(
        "CHANTIER-1",
        "MAT-1",
        13.0,
        registre,
    )

    assert resultat["verdict_variance"] == "STOCK_SUPERIEUR_AU_THEORIQUE"
    assert resultat["quantite_theorique"] == 10.0
    assert resultat["quantite_comptee"] == 13.0
    assert resultat["ecart"] == 3.0


def test_variance_indeterminee_sans_mouvement_prealable_meme_si_comptage_non_nul():
    registre = RegistreFactice([])

    resultat = variance.evaluer_variance(
        "CHANTIER-1",
        "MAT-1",
        5.0,
        registre,
    )

    assert resultat["verdict_variance"] == "INDETERMINE"
    assert resultat["quantite_theorique"] == 0.0
    assert resultat["quantite_comptee"] == 5.0
    assert resultat["ecart"] == 0.0


def test_variance_inventaire_precedente_ne_rend_pas_le_couple_determine():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "VARIANCE_INVENTAIRE",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MAT-1",
                "quantite": 5.0,
            }
        ]
    )

    resultat = variance.evaluer_variance(
        "CHANTIER-1",
        "MAT-1",
        5.0,
        registre,
    )

    assert resultat["verdict_variance"] == "INDETERMINE"
    assert resultat["quantite_theorique"] == 0.0
    assert resultat["ecart"] == 0.0


def test_reception_d_un_autre_chantier_n_isole_pas_le_couple_demande():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-AUTRE",
                "materiau_id": "MAT-1",
                "quantite": 10.0,
            }
        ]
    )

    resultat = variance.evaluer_variance(
        "CHANTIER-1",
        "MAT-1",
        5.0,
        registre,
    )

    assert resultat["verdict_variance"] == "INDETERMINE"
    assert resultat["quantite_theorique"] == 0.0
    assert resultat["ecart"] == 0.0


def test_reception_d_un_autre_materiau_n_isole_pas_le_couple_demande():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MAT-AUTRE",
                "quantite": 10.0,
            }
        ]
    )

    resultat = variance.evaluer_variance(
        "CHANTIER-1",
        "MAT-1",
        5.0,
        registre,
    )

    assert resultat["verdict_variance"] == "INDETERMINE"
    assert resultat["quantite_theorique"] == 0.0
    assert resultat["ecart"] == 0.0
