"""Tests anti-mutants: les liens inter-registres invalides restent indéterminés par matériau."""

from __future__ import annotations

import copy

import m6_material_control.outils as m6_outils
import pytest
from m6_material_control import emplacements, reorder

from opsys import stockage
from opsys.outils import executer_atomique


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm6-reorder-reference-mutants-fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        yield url
    finally:
        stockage.liberer()


def _outil(nom):
    return next(outil for outil in m6_outils.outils() if outil.nom == nom)


def _recevoir(material, chantier, po, date, *, statut):
    details = [{"materiau_id": material, "statut_ligne": statut}]
    if statut == "endommage":
        details[0]["photos"] = ["fichier:sha256:" + "bc" * 32]
    return executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": {
            "po_id": po,
            "chantier_id": chantier,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": 5.0}],
            "horodatage": date,
        },
        "reception_po": {
            "po_id": po,
            "chantier_id": chantier,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": 5.0}],
            "horodatage": date,
        },
        "details_reception": details,
        "lieu_livraison": {"type": "depot"},
        "seuils_reorder": [{"chantier_id": chantier, "materiau_id": material, "seuil_quantite": 10.0}],
    })


def _reecrire_chaine_transferts(maillons):
    precedent = emplacements._HASH_PRECEDENT_INITIAL
    for index, maillon in enumerate(maillons):
        maillon["index"] = index
        maillon["hash_precedent"] = precedent
        maillon["hash_maillon"] = emplacements._empreinte(maillon)
        precedent = maillon["hash_maillon"]


def _indetermines(material, mouvements, transferts, *chantiers):
    seuils = [
        {"chantier_id": chantier, "materiau_id": material, "seuil_quantite": 10.0}
        for chantier in chantiers
    ]
    return {
        (item["chantier_id"], item["materiau_id"])
        for item in reorder.paires_indeterminees(seuils, mouvements, transferts)
    }


def _lire_registres():
    with stockage.transaction():
        return (
            copy.deepcopy(stockage.maillons("m06-material-control", "principal")),
            copy.deepcopy(stockage.maillons("m06-material-control", "emplacements")),
        )


def test_index_absent_ou_autre_materiau_refuse_une_attribution_trop_precise(base):
    material, other_material = "mat-mut-ref-a", "mat-mut-ref-other"
    a, b, other = "CH-mut-ref-a", "CH-mut-ref-b", "CH-mut-ref-other"
    for mat, chantier, po, date, status in (
        (material, a, "PO-mut-a", "2026-11-01T11:00:00-04:00", "endommage"),
        (material, b, "PO-mut-b", "2026-11-02T11:00:00-04:00", "conforme"),
        (other_material, other, "PO-mut-other", "2026-11-03T11:00:00-04:00", "conforme"),
    ):
        response = _recevoir(mat, chantier, po, date, statut=status)
        assert response["ok"] and response["resultat"]["accepte"] is True
    mouvements, transferts = _lire_registres()

    missing = copy.deepcopy(transferts)
    for maillon in missing:
        reference = maillon.get("reference_source")
        if reference and maillon["materiau_id"] == material and maillon["vers"].get("type") == "rebut":
            reference["mouvement"]["index"] = 999
            reference["mouvement"]["hash_maillon"] = "a" * 64
    _reecrire_chaine_transferts(missing)
    assert emplacements.valider_chaine(missing)[0]
    assert _indetermines(material, mouvements, missing, a, b) == {(a, material), (b, material)}

    wrong_material = copy.deepcopy(transferts)
    source_other = next(item for item in mouvements if item["materiau_id"] == other_material)
    for maillon in wrong_material:
        reference = maillon.get("reference_source")
        if reference and maillon["materiau_id"] == material and maillon["vers"].get("type") == "rebut":
            reference["mouvement"] = {
                "registre": "principal",
                "index": source_other["index"],
                "hash_maillon": source_other["hash_maillon"],
            }
            reference["hash_reception"] = source_other["hash_maillon"]
    _reecrire_chaine_transferts(wrong_material)
    assert emplacements.valider_chaine(wrong_material)[0]
    assert _indetermines(material, mouvements, wrong_material, a, b) == {(a, material), (b, material)}


def test_hash_source_different_a_index_valide_refuse_l_attribution(base):
    material, a, b = "mat-mut-hash", "CH-mut-hash-a", "CH-mut-hash-b"
    for chantier, po, date, status in (
        (a, "PO-mut-hash-a", "2026-11-04T11:00:00-04:00", "endommage"),
        (b, "PO-mut-hash-b", "2026-11-05T11:00:00-04:00", "conforme"),
    ):
        response = _recevoir(material, chantier, po, date, statut=status)
        assert response["ok"] and response["resultat"]["accepte"] is True
    mouvements, transferts = _lire_registres()
    source_b = next(item for item in mouvements if item["chantier_id"] == b)
    altered = copy.deepcopy(transferts)
    for maillon in altered:
        reference = maillon.get("reference_source")
        if reference and maillon["materiau_id"] == material and maillon["vers"].get("type") == "rebut":
            # Index de A, hash d'un mouvement B valide: seul le contrôle hash/index l'attrape.
            reference["mouvement"]["hash_maillon"] = source_b["hash_maillon"]
    _reecrire_chaine_transferts(altered)
    assert emplacements.valider_chaine(altered)[0]
    assert _indetermines(material, mouvements, altered, a, b) == {(a, material), (b, material)}


def test_hash_reception_d_un_autre_chantier_est_indetermine(base):
    material, a, b = "mat-mut-head", "CH-mut-head-a", "CH-mut-head-b"
    first = _recevoir(material, a, "PO-mut-head-a", "2026-11-06T11:00:00-04:00", statut="endommage")
    second = _recevoir(material, b, "PO-mut-head-b", "2026-11-07T11:00:00-04:00", statut="conforme")
    assert first["ok"] and second["ok"]
    mouvements, transferts = _lire_registres()
    head_b = next(item for item in mouvements if item["chantier_id"] == b)
    altered = copy.deepcopy(transferts)
    for maillon in altered:
        reference = maillon.get("reference_source")
        if reference and maillon["materiau_id"] == material and maillon["vers"].get("type") == "rebut":
            # Source reste A; la tête, plus récente, est maintenant une réception de B.
            reference["hash_reception"] = head_b["hash_maillon"]
    _reecrire_chaine_transferts(altered)
    assert emplacements.valider_chaine(altered)[0]
    # Sans la cohérence du chantier source/tête, le rebut serait localisé à A seul.
    assert _indetermines(material, mouvements, altered, a, b) == {(a, material), (b, material)}
