import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"


class RegistreFactice:
    def __init__(self, maillons):
        self._maillons = maillons

    def lire(self) -> list[dict]:
        return list(self._maillons)


def _reorder():
    from m6_material_control import reorder

    return reorder


def test_retourne_un_signal_si_le_stock_est_strictement_inferieur_au_seuil():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MAT-1",
                "quantite": 4.0,
            },
            {
                "type_mouvement": "CONSOMMATION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MAT-1",
                "quantite": -1.0,
            },
        ]
    )
    seuils = [
        {
            "chantier_id": "CHANTIER-1",
            "materiau_id": "MAT-1",
            "seuil_quantite": 5.0,
        }
    ]

    resultat = _reorder().evaluer_reorder(
        "CHANTIER-1",
        "MAT-1",
        seuils,
        registre,
    )

    assert resultat == {
        "chantier_id": "CHANTIER-1",
        "materiau_id": "MAT-1",
        "stock_actuel": 3.0,
        "seuil_quantite": 5.0,
        "quantite_suggeree": 2.0,
    }


def test_ne_retourne_rien_si_le_stock_est_exactement_egal_au_seuil():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-2",
                "materiau_id": "MAT-2",
                "quantite": 5.0,
            }
        ]
    )
    seuils = [
        {
            "chantier_id": "CHANTIER-2",
            "materiau_id": "MAT-2",
            "seuil_quantite": 5.0,
        }
    ]

    resultat = _reorder().evaluer_reorder(
        "CHANTIER-2",
        "MAT-2",
        seuils,
        registre,
    )

    assert resultat is None


def test_ne_retourne_rien_si_le_stock_est_strictement_superieur_au_seuil():
    registre = RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-3",
                "materiau_id": "MAT-3",
                "quantite": 7.0,
            }
        ]
    )
    seuils = [
        {
            "chantier_id": "CHANTIER-3",
            "materiau_id": "MAT-3",
            "seuil_quantite": 5.0,
        }
    ]

    resultat = _reorder().evaluer_reorder(
        "CHANTIER-3",
        "MAT-3",
        seuils,
        registre,
    )

    assert resultat is None


def test_absence_de_seuil_pour_le_couple_demande_ne_cree_pas_de_seuil_implicite():
    registre = RegistreFactice([])
    seuils = [
        {
            "chantier_id": "AUTRE-CHANTIER",
            "materiau_id": "AUTRE-MATERIAU",
            "seuil_quantite": 100.0,
        },
        {
            "chantier_id": "CHANTIER-4",
            "materiau_id": "AUTRE-MATERIAU",
            "seuil_quantite": 100.0,
        },
    ]

    resultat = _reorder().evaluer_reorder(
        "CHANTIER-4",
        "MAT-4",
        seuils,
        registre,
    )

    assert resultat is None


def test_un_seuil_pour_un_autre_materiau_du_meme_chantier_n_est_jamais_applique():
    registre = RegistreFactice([])
    seuils = [
        {
            "chantier_id": "CHANTIER-5",
            "materiau_id": "MAT-AUTRE",
            "seuil_quantite": 10.0,
        }
    ]

    resultat = _reorder().evaluer_reorder(
        "CHANTIER-5",
        "MAT-DEMANDE",
        seuils,
        registre,
    )

    assert resultat is None


def test_reorder_ne_contient_aucun_appel_ou_nom_interdit():
    source_path = Path(_SRC / "m6_material_control" / "reorder.py")
    arbre = ast.parse(source_path.read_text(encoding="utf-8"))

    mots_interdits = ("commande", "paiement", "payer")
    violations = []

    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nom = noeud.name.lower()
            if any(mot in nom for mot in mots_interdits):
                violations.append(noeud.name)

        if isinstance(noeud, ast.Call):
            nom_fonction = None
            if isinstance(noeud.func, ast.Name):
                nom_fonction = noeud.func.id
            elif isinstance(noeud.func, ast.Attribute):
                nom_fonction = noeud.func.attr

            if nom_fonction is not None:
                nom = nom_fonction.lower()
                if any(mot in nom for mot in mots_interdits):
                    violations.append(nom_fonction)

    assert violations == []
