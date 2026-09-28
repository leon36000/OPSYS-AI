import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m6_material_control import stock


class RegistreFactice:
    def __init__(self, mouvements: list[dict]):
        self._mouvements = mouvements

    def lire(self) -> list[dict]:
        return list(self._mouvements)


def test_deriver_stock_theorique_somme_deux_receptions_pour_le_meme_couple():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MATERIAU-1",
                "quantite": 10.0,
            },
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MATERIAU-1",
                "quantite": 5.0,
            },
        ]
    )

    resultat = stock.deriver_stock_theorique(
        "CHANTIER-1",
        "MATERIAU-1",
        registre,
    )

    assert resultat == 15.0


def test_deriver_stock_theorique_soustrait_une_consommation_du_stock_recu():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MATERIAU-1",
                "quantite": 10.0,
            },
            {
                "type_mouvement": "CONSOMMATION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MATERIAU-1",
                "quantite": -3.0,
            },
        ]
    )

    resultat = stock.deriver_stock_theorique(
        "CHANTIER-1",
        "MATERIAU-1",
        registre,
    )

    assert resultat == 7.0


def test_deriver_stock_theorique_ignore_une_variance_inventaire():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MATERIAU-1",
                "quantite": 10.0,
            },
            {
                "type_mouvement": "VARIANCE_INVENTAIRE",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MATERIAU-1",
                "quantite": -2.0,
            },
        ]
    )

    resultat = stock.deriver_stock_theorique(
        "CHANTIER-1",
        "MATERIAU-1",
        registre,
    )

    assert resultat == 10.0


def test_deriver_stock_theorique_ignore_les_mouvements_d_autres_couples():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-2",
                "materiau_id": "MATERIAU-1",
                "quantite": 20.0,
            },
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MATERIAU-2",
                "quantite": 30.0,
            },
            {
                "type_mouvement": "CONSOMMATION",
                "chantier_id": "CHANTIER-2",
                "materiau_id": "MATERIAU-2",
                "quantite": -4.0,
            },
        ]
    )

    resultat = stock.deriver_stock_theorique(
        "CHANTIER-1",
        "MATERIAU-1",
        registre,
    )

    assert resultat == 0.0


def test_deriver_stock_theorique_retourne_zero_pour_un_registre_vide():
    registre = RegistreFactice([])

    resultat = stock.deriver_stock_theorique(
        "CHANTIER-1",
        "MATERIAU-1",
        registre,
    )

    assert resultat == 0.0


def test_verifier_disponibilite_accepte_une_consommation_inferieure_au_stock():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MATERIAU-1",
                "quantite": 10.0,
            }
        ]
    )

    resultat = stock.verifier_disponibilite_consommation(
        "CHANTIER-1",
        [{"materiau_id": "MATERIAU-1", "quantite": 6.0}],
        registre,
    )

    assert resultat == (True, None)


def test_verifier_disponibilite_accepte_une_consommation_egale_au_stock():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MATERIAU-1",
                "quantite": 10.0,
            }
        ]
    )

    resultat = stock.verifier_disponibilite_consommation(
        "CHANTIER-1",
        [{"materiau_id": "MATERIAU-1", "quantite": 10.0}],
        registre,
    )

    assert resultat == (True, None)


def test_verifier_disponibilite_rejette_une_consommation_insuffisante():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MATERIAU-1",
                "quantite": 10.0,
            }
        ]
    )

    resultat = stock.verifier_disponibilite_consommation(
        "CHANTIER-1",
        [{"materiau_id": "MATERIAU-1", "quantite": 10.1}],
        registre,
    )

    assert resultat == (False, "REJ-STOCK-INSUFFISANT")


def test_verifier_disponibilite_cumule_les_lignes_du_meme_materiau():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MATERIAU-1",
                "quantite": 10.0,
            }
        ]
    )

    resultat = stock.verifier_disponibilite_consommation(
        "CHANTIER-1",
        [
            {"materiau_id": "MATERIAU-1", "quantite": 6.0},
            {"materiau_id": "MATERIAU-1", "quantite": 6.0},
        ],
        registre,
    )

    assert resultat == (False, "REJ-STOCK-INSUFFISANT")


def test_verifier_disponibilite_rejette_un_chantier_vide():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MATERIAU-1",
                "quantite": 10.0,
            }
        ]
    )

    resultat = stock.verifier_disponibilite_consommation(
        "",
        [{"materiau_id": "MATERIAU-1", "quantite": 1.0}],
        registre,
    )

    assert resultat == (False, "REJ-STOCK-CHANTIER-MANQUANT")


def test_verifier_disponibilite_rejette_un_chantier_none():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MATERIAU-1",
                "quantite": 10.0,
            }
        ]
    )

    resultat = stock.verifier_disponibilite_consommation(
        None,
        [{"materiau_id": "MATERIAU-1", "quantite": 1.0}],
        registre,
    )

    assert resultat == (False, "REJ-STOCK-CHANTIER-MANQUANT")
