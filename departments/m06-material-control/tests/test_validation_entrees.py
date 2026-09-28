import ast
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m6_material_control import frontieres
from m6_material_control import validation
from m6_material_control import verdicts


@pytest.fixture
def wct_valide():
    return {
        "wct_id": "wct-001",
        "intervention_id": "intervention-001",
        "lead_id": "lead-001",
        "technicien_id": "technicien-001",
        "horodatage_completion": "2025-01-15T10:30:00+00:00",
        "fix_gps_completion": {
            "latitude": 48.8566,
            "longitude": 2.3522,
        },
        "duree_reelle_minutes": 90,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M6", "M5", "M2"],
        "devis_id": None,
    }


@pytest.fixture
def formulaire_valide():
    return {
        "wct_id": "wct-001",
        "intervention_id": "intervention-001",
        "chantier_id": "chantier-001",
        "lignes_consommees": [
            {
                "materiau_id": "isolant-laine-roche",
                "quantite": 12.5,
            },
        ],
    }


def test_valider_wct_accepte_un_wct_avec_douze_cles_et_consommateur_m6(wct_valide):
    assert validation.valider_wct(wct_valide) == (True, None)


def test_valider_wct_rejette_une_cle_manquante_avec_verdict_nomme(wct_valide):
    del wct_valide["devis_id"]

    assert validation.valider_wct(wct_valide) == (
        False,
        "REJ-WCT-CHAMP-MANQUANT",
    )


def test_valider_wct_rejette_une_cle_en_trop_avec_verdict_nomme(wct_valide):
    wct_valide["origine"] = "import-externe"

    assert validation.valider_wct(wct_valide) == (
        False,
        "REJ-WCT-CHAMP-INATTENDU",
    )


def test_valider_wct_rejette_l_absence_de_m6_par_un_verdict_distinct(wct_valide):
    wct_valide["consommateurs_cibles"] = ["M5", "M2"]

    assert validation.valider_wct(wct_valide) == (
        False,
        "REJ-WCT-CONSOMMATEUR-M6-ABSENT",
    )


def test_valider_wct_ne_contient_aucun_appel_encodage_ou_empreinte():
    arbre = ast.parse(Path(validation.__file__).read_text(encoding="utf-8"))
    fonction = next(
        noeud
        for noeud in arbre.body
        if isinstance(noeud, ast.FunctionDef) and noeud.name == "valider_wct"
    )
    appels_interdits = []

    for noeud in ast.walk(fonction):
        if not isinstance(noeud, ast.Call):
            continue
        if isinstance(noeud.func, ast.Name):
            nom = noeud.func.id
        elif isinstance(noeud.func, ast.Attribute):
            nom = noeud.func.attr
        else:
            nom = ""
        if "encod" in nom.lower() or "empreinte" in nom.lower():
            appels_interdits.append(nom)

    assert appels_interdits == []


def test_valider_formulaire_rejette_un_wct_id_incoherent(wct_valide, formulaire_valide):
    formulaire_valide["wct_id"] = "wct-autre"

    assert validation.valider_formulaire_consommation(
        formulaire_valide,
        wct_valide,
    ) == (False, "REJ-FORMULAIRE-WCT-INCOHERENT")


def test_valider_formulaire_accepte_un_formulaire_referencant_le_wct_valide(
    wct_valide,
    formulaire_valide,
):
    assert validation.valider_formulaire_consommation(
        formulaire_valide,
        wct_valide,
    ) == (True, None)


def test_frontieres_rejette_une_cle_interdite_au_sommet_du_wct(wct_valide):
    wct_valide["statut_paiement"] = "en_attente"

    assert frontieres.verifier_frontieres(wct_valide) == (
        False,
        "REJ-FRONTIERE-VIOLEE",
    )


def test_frontieres_rejette_une_cle_interdite_imbriquee_dans_le_fix_gps(wct_valide):
    wct_valide["fix_gps_completion"]["date_execution"] = "2025-01-15"

    assert frontieres.verifier_frontieres(wct_valide) == (
        False,
        "REJ-FRONTIERE-VIOLEE",
    )


def test_frontieres_rejette_une_cle_interdite_dans_une_ligne_consommee(
    formulaire_valide,
):
    formulaire_valide["lignes_consommees"][0]["virement"] = "virement-001"

    assert frontieres.verifier_frontieres(formulaire_valide) == (
        False,
        "REJ-FRONTIERE-VIOLEE",
    )


def test_frontieres_rejette_une_cle_interdite_imbriquee_dans_un_tuple():
    entree = {
        "conteneur": (
            {
                "reference_bancaire": "ref-001",
            },
        ),
    }

    assert frontieres.verifier_frontieres(entree) == (
        False,
        "REJ-FRONTIERE-VIOLEE",
    )


def test_frontieres_n_confond_pas_duree_reelle_minutes_avec_duree(wct_valide):
    assert frontieres.verifier_frontieres(wct_valide) == (True, None)


def test_construire_verdict_conserve_le_code_et_les_details():
    assert verdicts.construire_verdict(
        "REJ-FRONTIERE-VIOLEE",
        chemin="lignes_consommees[0].virement",
    ) == {
        "code": "REJ-FRONTIERE-VIOLEE",
        "chemin": "lignes_consommees[0].virement",
    }
