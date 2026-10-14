"""livre_prix.py — PLAN T2.4 (M6.3). Module pur : `registre_cible` est une simple liste Python en
mémoire ici."""

from __future__ import annotations

import copy

import pytest
from m6_material_control import contrats, livre_prix


def test_enregistrer_prix_nominal():
    registre: list[dict] = []
    entree, verdict = livre_prix.enregistrer_prix(
        "MAT-1", "gentek", 12.5, "CAD", "2026-01-01", registre
    )
    assert verdict is None
    assert entree == {
        "materiau_id": "MAT-1", "fournisseur_id": "gentek", "prix_unitaire": 12.5,
        "devise": "CAD", "date_effet": "2026-01-01", "source_document": None,
    }
    assert registre == [entree]


def test_enregistrer_prix_source_document_optionnelle():
    registre: list[dict] = []
    entree, verdict = livre_prix.enregistrer_prix(
        "MAT-1", "gentek", 12.5, "CAD", "2026-01-01", registre, source_document="FACTURE-42"
    )
    assert verdict is None
    assert entree["source_document"] == "FACTURE-42"


def test_enregistrer_prix_zero_refuse_nomme():
    entree, verdict = livre_prix.enregistrer_prix("MAT-1", "gentek", 0.0, "CAD", "2026-01-01", [])
    assert entree is None
    assert verdict["code"] == "REJ-PRIX-INVALIDE"


def test_enregistrer_prix_negatif_refuse_nomme():
    entree, verdict = livre_prix.enregistrer_prix("MAT-1", "gentek", -5.0, "CAD", "2026-01-01", [])
    assert entree is None
    assert verdict["code"] == "REJ-PRIX-INVALIDE"


def test_enregistrer_prix_non_numerique_refuse_nomme():
    entree, verdict = livre_prix.enregistrer_prix("MAT-1", "gentek", "12.5", "CAD", "2026-01-01", [])
    assert entree is None
    assert verdict["code"] == "REJ-PRIX-INVALIDE"


def test_enregistrer_champ_texte_vide_refuse_nomme():
    entree, verdict = livre_prix.enregistrer_prix("", "gentek", 12.5, "CAD", "2026-01-01", [])
    assert entree is None
    assert verdict["code"] == "REJ-PRIX-STRUCTURE-INVALIDE"


def test_enregistrer_clef_interdite_refusee_nommee():
    entree, verdict = livre_prix.enregistrer_prix(
        "MAT-1", "gentek", 12.5, "CAD", "2026-01-01", [], source_document={"prix_vente": 1}
    )
    assert entree is None
    assert verdict["code"] == "REJ-FRONTIERE-VIOLEE"


def test_prix_en_vigueur_aucune_entree_rend_none():
    assert livre_prix.prix_en_vigueur("MAT-1", "gentek", []) is None


def test_prix_en_vigueur_est_le_dernier_ajoute_jamais_par_date():
    registre: list[dict] = []
    # date_effet volontairement DANS LE DÉSORDRE : la sélection suit l'ORDRE D'ÉCRITURE
    # (DA-M6-10, même raisonnement), jamais une comparaison de date_effet.
    livre_prix.enregistrer_prix("MAT-1", "gentek", 10.0, "CAD", "2026-06-01", registre)
    livre_prix.enregistrer_prix("MAT-1", "gentek", 12.0, "CAD", "2026-01-01", registre)
    entree = livre_prix.prix_en_vigueur("MAT-1", "gentek", registre)
    assert entree["prix_unitaire"] == 12.0


def test_prix_en_vigueur_isole_par_fournisseur():
    registre: list[dict] = []
    livre_prix.enregistrer_prix("MAT-1", "gentek", 10.0, "CAD", "2026-01-01", registre)
    livre_prix.enregistrer_prix("MAT-1", "royal", 15.0, "CAD", "2026-01-01", registre)
    assert livre_prix.prix_en_vigueur("MAT-1", "gentek", registre)["prix_unitaire"] == 10.0
    assert livre_prix.prix_en_vigueur("MAT-1", "royal", registre)["prix_unitaire"] == 15.0


def test_resoudre_prix_po_trouve_rend_prix_livre():
    registre: list[dict] = []
    livre_prix.enregistrer_prix("MAT-1", "gentek", 10.0, "CAD", "2026-01-01", registre)
    resolution = livre_prix.resoudre_prix_po("MAT-1", "gentek", registre)
    assert resolution["verdict_prix"] == "PRIX_LIVRE"
    assert resolution["prix_unitaire"] == 10.0
    assert resolution["devise"] == "CAD"


def test_resoudre_prix_po_absent_rend_indetermine_jamais_invente():
    resolution = livre_prix.resoudre_prix_po("MAT-INCONNU", "gentek", [])
    assert resolution == {
        "verdict_prix": "INDETERMINE",
        "prix_unitaire": None,
        "devise": None,
        "date_effet": None,
        "source_document": None,
        "marquage_source": None,
    }


@pytest.mark.parametrize("source,marque", [(None, "FALLBACK_PRICE_BOOK"), ("FACT-FICTIF", "SOURCE_DECLAREE")])
def test_provenance_prix_derivee_sans_reecrire_livre(source, marque):
    registre = []
    livre_prix.enregistrer_prix("MAT-FICTIF", "gentek", 12.5, "CAD", "2026-01-01", registre, source)
    avant = copy.deepcopy(registre)
    resolution = livre_prix.resoudre_prix_po("MAT-FICTIF", "gentek", registre)
    assert resolution["marquage_source"] == marque
    assert resolution["source_document"] == source
    assert resolution["prix_unitaire"] == 12.5
    assert registre == avant
    assert set(registre[0]) == {
        "materiau_id",
        "fournisseur_id",
        "prix_unitaire",
        "devise",
        "date_effet",
        "source_document",
    }
    assert contrats.VERDICT_PRIX_PO == ("PRIX_LIVRE", "INDETERMINE")


@pytest.mark.parametrize(
    "livre",
    [
        [],
        [
            {
                "materiau_id": "MAT-FICTIF",
                "fournisseur_id": "royal",
                "prix_unitaire": 12.5,
                "devise": "CAD",
                "date_effet": "2026-01-01",
                "source_document": "FACT-FICTIF",
            }
        ],
    ],
)
def test_prix_absent_ou_autre_fournisseur_sans_provenance_inventee(livre):
    avant = copy.deepcopy(livre)
    resolution = livre_prix.resoudre_prix_po("MAT-FICTIF", "gentek", livre)
    assert resolution["verdict_prix"] == "INDETERMINE"
    assert resolution["marquage_source"] is None
    assert resolution["prix_unitaire"] is resolution["date_effet"] is resolution["source_document"] is None
    assert livre == avant
