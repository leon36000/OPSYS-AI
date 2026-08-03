import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m6_material_control.catalogue import resoudre_prix


class _RegistreFactice:
    def __init__(self, mouvements):
        self._mouvements = mouvements

    def lire(self):
        return self._mouvements


def test_resout_le_prix_depuis_le_catalogue():
    catalogue = {
        "version": "v1",
        "unite_monetaire": "CAD",
        "postes": {
            "MAT-001": {
                "cout_unitaire": 17.35,
                "libelle": "Plaque de bois",
            }
        },
    }
    registre = _RegistreFactice([])

    resultat = resoudre_prix("MAT-001", catalogue, registre)

    assert resultat["verdict_resolution_prix"] == "PRIX_CATALOGUE"
    assert resultat["cout_unitaire_resolu"] == 17.35


def test_resout_le_prix_historique_du_mouvement_reception_a_l_index_le_plus_eleve():
    catalogue = {
        "version": "v1",
        "unite_monetaire": "CAD",
        "postes": {},
    }
    registre = _RegistreFactice(
        [
            {
                "index": 2,
                "type_mouvement": "RECEPTION",
                "materiau_id": "MAT-002",
                "cout_unitaire": 8.5,
            },
            {
                "index": 3,
                "type_mouvement": "CONSOMMATION",
                "materiau_id": "MAT-002",
                "cout_unitaire": None,
            },
            {
                "index": 5,
                "type_mouvement": "RECEPTION",
                "materiau_id": "MAT-002",
                "cout_unitaire": 9.75,
            },
        ]
    )

    resultat = resoudre_prix("MAT-002", catalogue, registre)

    assert resultat["verdict_resolution_prix"] == "PRIX_HISTORIQUE_FALLBACK"
    assert resultat["cout_unitaire_resolu"] == 9.75


def test_retourne_indetermine_sans_catalogue_ni_reception_historique():
    catalogue = {
        "version": "v1",
        "unite_monetaire": "CAD",
        "postes": {},
    }
    registre = _RegistreFactice([])

    resultat = resoudre_prix("MAT-003", catalogue, registre)

    assert resultat["verdict_resolution_prix"] == "INDETERMINE"
    assert resultat["cout_unitaire_resolu"] is None


def test_catalogue_none_est_traite_comme_une_absence_de_couverture():
    registre = _RegistreFactice([])

    resultat = resoudre_prix("MAT-004", None, registre)

    assert resultat["verdict_resolution_prix"] == "INDETERMINE"
    assert resultat["cout_unitaire_resolu"] is None


def test_une_reception_pour_un_autre_materiau_n_influence_pas_la_resolution():
    catalogue = {
        "version": "v1",
        "unite_monetaire": "CAD",
        "postes": {},
    }
    registre = _RegistreFactice(
        [
            {
                "index": 7,
                "type_mouvement": "RECEPTION",
                "materiau_id": "MAT-AUTRE",
                "cout_unitaire": 42.0,
            }
        ]
    )

    resultat = resoudre_prix("MAT-005", catalogue, registre)

    assert resultat["verdict_resolution_prix"] == "INDETERMINE"
    assert resultat["cout_unitaire_resolu"] is None


def test_une_reception_sans_cout_unitaire_ne_fournit_pas_de_fallback():
    catalogue = {
        "version": "v1",
        "unite_monetaire": "CAD",
        "postes": {},
    }
    registre = _RegistreFactice(
        [
            {
                "index": 11,
                "type_mouvement": "RECEPTION",
                "materiau_id": "MAT-006",
                "cout_unitaire": None,
            }
        ]
    )

    resultat = resoudre_prix("MAT-006", catalogue, registre)

    assert resultat["verdict_resolution_prix"] == "INDETERMINE"
    assert resultat["cout_unitaire_resolu"] is None
