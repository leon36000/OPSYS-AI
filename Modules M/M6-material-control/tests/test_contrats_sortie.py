import ast
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m6_material_control import contrats_sortie


CLES_MONETAIRES_INTERDITES = {
    "cout_unitaire",
    "cout",
    "prix",
    "montant",
    "devise",
    "unite_monetaire",
    "montant_total_estime",
}


def collecter_cles_recursivement(valeur):
    cles = set()

    if isinstance(valeur, dict):
        for cle, sous_valeur in valeur.items():
            cles.add(cle)
            cles.update(collecter_cles_recursivement(sous_valeur))
    elif isinstance(valeur, list):
        for element in valeur:
            cles.update(collecter_cles_recursivement(element))

    return cles


def test_construire_confirmation_consommation_terrain_assemble_les_donnees():
    lignes_consommees = [
        {"materiau_id": "MAT-1", "quantite": 3.0},
        {"materiau_id": "MAT-2", "quantite": 1.5},
    ]
    stock_restant = [
        {"materiau_id": "MAT-1", "quantite": 7.0},
        {"materiau_id": "MAT-2", "quantite": 2.5},
    ]

    confirmation = contrats_sortie.construire_confirmation_consommation_terrain(
        "intervention-1",
        "CHANTIER-1",
        lignes_consommees,
        stock_restant,
    )

    assert confirmation == {
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "materiaux_confirmes": [
            {"materiau_id": "MAT-1", "quantite_declaree": 3.0},
            {"materiau_id": "MAT-2", "quantite_declaree": 1.5},
        ],
        "stock_restant": [
            {"materiau_id": "MAT-1", "quantite": 7.0},
            {"materiau_id": "MAT-2", "quantite": 2.5},
        ],
    }


def test_confirmation_consommation_terrain_ne_contient_aucune_cle_monetaire():
    confirmation = contrats_sortie.construire_confirmation_consommation_terrain(
        "intervention-1",
        "CHANTIER-1",
        [{"materiau_id": "MAT-1", "quantite": 3.0}],
        [{"materiau_id": "MAT-1", "quantite": 7.0}],
    )

    cles = collecter_cles_recursivement(confirmation)

    assert not cles.intersection(CLES_MONETAIRES_INTERDITES)


def test_le_paquet_ne_contient_aucune_cle_de_paiement_dans_ses_litteraux_dict():
    cles_paiement_interdites = {
        "statut_paiement",
        "virement",
        "reference_bancaire",
        "mode_paiement",
    }

    for fichier in Path(_SRC / "m6_material_control").rglob("*.py"):
        if fichier.name == "__init__.py":
            continue

        arbre = ast.parse(fichier.read_text(encoding="utf-8"), filename=str(fichier))

        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Dict):
                continue

            for cle in noeud.keys:
                if (
                    isinstance(cle, ast.Constant)
                    and isinstance(cle.value, str)
                ):
                    assert cle.value not in cles_paiement_interdites, (
                        f"{fichier}: {cle.value}"
                    )

