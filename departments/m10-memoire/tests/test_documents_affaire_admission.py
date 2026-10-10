"""Admission pure fictive, sans état courant, autorité ni snapshot documentaire."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
from m10_memoire import documents_affaire as d

FICTIF = True
REF = {"registre": "documents_affaire", "index": 511, "ligne_id": "a" * 64}
DEPOT = {
    "affaire_id": "chantier-fictif", "document_ref": None, "version_precedente": None,
    "titre": "Titre fictif", "corps": "Aé😀\r\nZ", "confidentialite": "INTERNAL",
}


def _commande(operation):
    if operation == "deposer":
        return copy.deepcopy(DEPOT)
    args = {"affaire_id": "chantier-fictif", "document_ref": copy.deepcopy(REF), "activation_attendue": None}
    args["version_source" if operation == "activer" else "code_motif"] = (
        copy.deepcopy(REF) if operation == "activer" else "RETRAIT_ACCES"
    )
    return args


@pytest.mark.parametrize("operation", ["deposer", "activer", "retirer"])
def test_copie_sans_snapshot_ni_horloge_ou_contexte(operation, monkeypatch):
    def interdit(*args, **kwargs):
        raise AssertionError("un état courant a été consulté")
    for name in ("_analyse", "_contexte", "_index", "_sceller"):
        monkeypatch.setattr(d, name, interdit)
    args = _commande(operation)
    resultat = d.valider_commande(operation, args)
    assert resultat == args and resultat is not args
    if operation != "deposer":
        assert resultat["document_ref"] is not args["document_ref"]
        resultat["document_ref"]["index"] = 0
        assert args["document_ref"]["index"] == 511
    assert Path(d.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[3])


@pytest.mark.parametrize("operation,args", [
    (None, DEPOT), (True, DEPOT), ("inconnu", DEPOT), ("deposer", None), ("deposer", []),
    ("deposer", {**DEPOT, "fictif": True}), ("deposer", {**DEPOT, "affaire_id": "invalide/affaire"}),
    ("deposer", {**DEPOT, "corps": ""}), ("deposer", {**DEPOT, "corps": "x" * 2001}),
    ("deposer", {**DEPOT, "corps": "\ud800"}), ("deposer", {**DEPOT, "titre": " "}),
    ("deposer", {**DEPOT, "titre": "t" * 121}), ("deposer", {**DEPOT, "confidentialite": "FINANCIAL"}),
    ("deposer", {**DEPOT, "document_ref": REF, "version_precedente": None}),
    ("deposer", {**DEPOT, "version_precedente": REF}),
    ("deposer", {**DEPOT, "document_ref": {**REF, "index": True}, "version_precedente": REF}),
    ("deposer", {**DEPOT, "document_ref": {**REF, "index": 512}, "version_precedente": REF}),
    ("deposer", {**DEPOT, "document_ref": {**REF, "registre": "autre"}, "version_precedente": REF}),
    ("deposer", {**DEPOT, "document_ref": {**REF, "ligne_id": "A" * 64}, "version_precedente": REF}),
])
def test_refus_ferme_sans_echo_des_entrees(operation, args):
    avant = copy.deepcopy(args)
    with pytest.raises(d.RefusDocument) as exc:
        d.valider_commande(operation, args)
    assert args == avant
    assert exc.value.code.startswith("REJ-M10-DOC-")
    assert "Aé😀" not in str(exc.value) and "chantier-fictif" not in str(exc.value)


@pytest.mark.parametrize("operation,champ,valeur", [
    ("activer", "document_ref", None), ("activer", "version_source", None),
    ("activer", "activation_attendue", {}), ("retirer", "code_motif", "PURGER"),
    ("retirer", "activation_attendue", {**REF, "index": -1}),
])
def test_etat_scalaires_et_refs_sans_verifier_leur_presence(operation, champ, valeur):
    args = _commande(operation)
    args[champ] = valeur
    with pytest.raises(d.RefusDocument):
        d.valider_commande(operation, args)


def test_bornes_utf8_exactes_et_references_copiees_sans_cas():
    args = {**DEPOT, "corps": "😀" * 2000, "titre": "é" * 120,
            "document_ref": copy.deepcopy(REF), "version_precedente": copy.deepcopy(REF)}
    avant = copy.deepcopy(args)
    resultat = d.valider_commande("deposer", args)
    assert len(resultat["corps"].encode("utf-8")) == 8000
    assert resultat == avant and resultat["corps"] == args["corps"]
    resultat["version_precedente"]["index"] = 0
    assert args == avant


def test_sous_classes_ne_sont_jamais_executees():
    class Texte(str):
        def encode(self, *args, **kwargs):
            raise AssertionError("méthode arbitraire exécutée")
    with pytest.raises(d.RefusDocument):
        d.valider_commande(Texte("deposer"), DEPOT)
    with pytest.raises(d.RefusDocument):
        d.valider_commande("deposer", {**DEPOT, "corps": Texte("corps")})
