"""Tests du contrat PreuvesCompletion — T1.1-b#3."""
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import m4_field_ops.preuves as preuves_mod


def _preuves_valides(**overrides):
    base = {
        "checklist_complete": True,
        "photos_apres": ["photo1.jpg"],
        "notes": "Aucun imprévu.",
        "signature": None,
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------ constantes épinglées
def test_constantes_epinglees():
    assert preuves_mod.CLES_PREUVES_COMPLETION == (
        "checklist_complete", "photos_apres", "notes", "signature",
    )


# ------------------------------------------------------------------ cas nominal
def test_preuves_valides_sans_signature_requise():
    ok, verdict = preuves_mod.valider_preuves_completion(_preuves_valides(), signature_requise=False)
    assert ok is True
    assert verdict is None


def test_preuves_valides_avec_signature_requise():
    preuves = _preuves_valides(signature="Jean Tremblay")
    ok, verdict = preuves_mod.valider_preuves_completion(preuves, signature_requise=True)
    assert ok is True
    assert verdict is None


def test_notes_vide_toleree():
    """« Aucun imprévu » est une note légitime : notes vide n'est PAS un manque,
    contrairement à photos_apres ou checklist_complete."""
    ok, verdict = preuves_mod.valider_preuves_completion(_preuves_valides(notes=""), signature_requise=False)
    assert ok is True
    assert verdict is None


# ------------------------------------------------------------------ structure
def test_preuves_non_dict_refuse():
    ok, verdict = preuves_mod.valider_preuves_completion(["pas un objet"], signature_requise=False)
    assert ok is False
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


@pytest.mark.parametrize("cle_manquante", ["checklist_complete", "photos_apres", "notes", "signature"])
def test_champ_manquant_refuse_nomme(cle_manquante):
    preuves = _preuves_valides()
    del preuves[cle_manquante]
    ok, verdict = preuves_mod.valider_preuves_completion(preuves, signature_requise=False)
    assert ok is False
    assert verdict["code"] == "REJ-CHAMP-MANQUANT"
    assert cle_manquante in verdict["detail"]


def test_cle_etrangere_refusee():
    preuves = _preuves_valides()
    preuves["materiel_utilise"] = []
    ok, verdict = preuves_mod.valider_preuves_completion(preuves, signature_requise=False)
    assert ok is False
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


# ------------------------------------------------------------------ checklist_complete
@pytest.mark.parametrize("valeur_bad", [1, 0, "true", None, []])
def test_checklist_complete_non_booleen_refuse(valeur_bad):
    ok, verdict = preuves_mod.valider_preuves_completion(
        _preuves_valides(checklist_complete=valeur_bad), signature_requise=False,
    )
    assert ok is False
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_checklist_non_terminee_refusee_fail_closed():
    ok, verdict = preuves_mod.valider_preuves_completion(
        _preuves_valides(checklist_complete=False), signature_requise=False,
    )
    assert ok is False
    assert verdict["code"] == "REJ-CHAMP-VIDE"


# ------------------------------------------------------------------ photos_apres
def test_photos_apres_vide_refusee():
    ok, verdict = preuves_mod.valider_preuves_completion(
        _preuves_valides(photos_apres=[]), signature_requise=False,
    )
    assert ok is False
    assert verdict["code"] == "REJ-CHAMP-VIDE"


@pytest.mark.parametrize("photos_bad", ["une-seule-chaine", {"a": 1}, [1, 2], ["ok", ""]])
def test_photos_apres_mal_formees_refusees(photos_bad):
    ok, verdict = preuves_mod.valider_preuves_completion(
        _preuves_valides(photos_apres=photos_bad), signature_requise=False,
    )
    assert ok is False
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


# ------------------------------------------------------------------ notes
@pytest.mark.parametrize("notes_bad", [None, 42, ["notes"]])
def test_notes_non_chaine_refusee(notes_bad):
    ok, verdict = preuves_mod.valider_preuves_completion(
        _preuves_valides(notes=notes_bad), signature_requise=False,
    )
    assert ok is False
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


# ------------------------------------------------------------------ signature_requise / signature
@pytest.mark.parametrize("signature_requise_bad", [1, 0, "true", None])
def test_signature_requise_non_booleenne_refusee(signature_requise_bad):
    ok, verdict = preuves_mod.valider_preuves_completion(_preuves_valides(), signature_requise=signature_requise_bad)
    assert ok is False
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


@pytest.mark.parametrize("signature_bad", [None, ""])
def test_signature_manquante_alors_que_requise_refusee(signature_bad):
    ok, verdict = preuves_mod.valider_preuves_completion(
        _preuves_valides(signature=signature_bad), signature_requise=True,
    )
    assert ok is False
    assert verdict["code"] == "REJ-CHAMP-MANQUANT"


def test_signature_non_requise_absente_acceptee():
    ok, verdict = preuves_mod.valider_preuves_completion(
        _preuves_valides(signature=None), signature_requise=False,
    )
    assert ok is True
    assert verdict is None


def test_signature_type_invalide_hors_exigence_refusee():
    ok, verdict = preuves_mod.valider_preuves_completion(
        _preuves_valides(signature=123), signature_requise=False,
    )
    assert ok is False
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


# ------------------------------------------------------------------ ordre des contrôles (première faute)
def test_ordre_controle_checklist_avant_photos():
    """checklist_complete est vérifié AVANT photos_apres (ordre épinglé) :
    les deux manquent, le verdict porte sur checklist_complete."""
    preuves = _preuves_valides(checklist_complete=False, photos_apres=[])
    ok, verdict = preuves_mod.valider_preuves_completion(preuves, signature_requise=False)
    assert ok is False
    assert "checklist" in verdict["detail"].lower()
