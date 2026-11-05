"""Le schéma JSON public des photos doit refléter les gardes métier M3."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from m3_estimation.outils import outils
from opsys.outils import executer

SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
PHOTO = {
    "photo_id": "photo-fictive-1",
    "resolution_largeur": 1600,
    "resolution_hauteur": 1200,
    "eclairage": 7,
    "angle": "face",
    "reference_echelle": None,
}
MARQUEUR = {
    "readiness_ok": True,
    "lead_id": "lead-fictif-1",
    "hash_tete_registre": "a" * 64,
    "horodatage": "2026-10-01T10:00:00-04:00",
    "empreinte": "b" * 64,
}
CONTRAT = {
    "lead_id": "lead-fictif-1",
    "conversation_id": "conversation-fictive-1",
    "type_travaux": "ravalement",
    "ville": "Quebec",
    "canal": "formulaire_web",
    "contact": {},
    "urgence_declaree": False,
}


def _outils():
    return {outil.nom: outil for outil in outils()}


def _args_qualifier(*, photo=None, seuils=None):
    return {
        "photos": [deepcopy(PHOTO if photo is None else photo)],
        "seuils": deepcopy(SEUILS if seuils is None else seuils),
    }


def _erreurs_schema(outil, arguments):
    return list(Draft202012Validator(outil.parametres).iter_errors(arguments))


def _resultat_public(outil, arguments):
    resultat = executer(outil, arguments)
    assert resultat["ok"] is True
    return resultat["resultat"]


def test_les_trois_outils_publics_reutilisent_le_schema_photo_ferme():
    publics = _outils()
    noms = ("m3_estimer_projet", "m3_qualifier_photos", "m3_classifier_confiance")
    schemas = []
    for nom in noms:
        schema = publics[nom].parametres
        if nom == "m3_estimer_projet":
            schemas.append((schema["properties"]["photos"]["items"], schema["properties"]["seuils"]))
        else:
            schemas.append((schema["properties"]["photos"]["items"], schema["properties"]["seuils"]))
    assert schemas[0] == schemas[1] == schemas[2]


def test_entrees_valides_acceptent_les_entiers_json_meme_lexes_comme_flottants():
    publics = _outils()
    photo = {
        **PHOTO,
        "resolution_largeur": 1600.0,
        "resolution_hauteur": 1200.0,
        "reference_echelle": {"type": "porte", "dimensions_connues": True},
    }
    arguments = _args_qualifier(photo=photo, seuils={"resolution_minimale": 1000.0, "eclairage_minimal": 4.0})

    for nom in ("m3_qualifier_photos", "m3_classifier_confiance"):
        outil = publics[nom]
        assert _erreurs_schema(outil, arguments) == []
        resultat = _resultat_public(outil, arguments)
        assert resultat["accepte"] is True
        if nom == "m3_qualifier_photos":
            assert resultat["resultat"]["photos_acceptables"] is True
        else:
            assert resultat["resultat"]["niveau_confiance"] == "REFERENCE_ECHELLE"


@pytest.mark.parametrize(
    "photo,seuils",
    [
        ({**PHOTO, "resolution_largeur": 1, "resolution_hauteur": 1, "eclairage": 0},
         {"resolution_minimale": 1, "eclairage_minimal": 0}),
        ({**PHOTO, "resolution_largeur": 1, "resolution_hauteur": 1, "eclairage": 10},
         {"resolution_minimale": 1, "eclairage_minimal": 10}),
    ],
    ids=["bornes-inclusives-zero", "bornes-inclusives-dix"],
)
def test_schema_et_execution_acceptent_les_bornes_inclusives(photo, seuils):
    publics = _outils()
    arguments = _args_qualifier(photo=photo, seuils=seuils)

    for nom in ("m3_qualifier_photos", "m3_classifier_confiance"):
        outil = publics[nom]
        assert _erreurs_schema(outil, arguments) == []
        resultat = _resultat_public(outil, arguments)
        assert resultat["accepte"] is True


@pytest.mark.parametrize(
    "arguments",
    [
        _args_qualifier(photo={**PHOTO, "exif_libre": "fictif"}),
        _args_qualifier(photo={**PHOTO, "photo_id": " "}),
        _args_qualifier(photo={**PHOTO, "angle": "  "}),
        _args_qualifier(photo={**PHOTO, "resolution_largeur": 0}),
        _args_qualifier(photo={**PHOTO, "resolution_largeur": True}),
        _args_qualifier(photo={**PHOTO, "resolution_largeur": 1600.5}),
        _args_qualifier(photo={**PHOTO, "eclairage": True}),
        _args_qualifier(photo={**PHOTO, "eclairage": -0.1}),
        _args_qualifier(photo={**PHOTO, "eclairage": 10.1}),
        _args_qualifier(photo={**PHOTO, "reference_echelle": {"type": "porte"}}),
        _args_qualifier(photo={
            **PHOTO, "reference_echelle": {"type": "porte", "dimensions_connues": True, "autre": "fictif"},
        }),
        _args_qualifier(photo={
            **PHOTO, "reference_echelle": {"type": "  ", "dimensions_connues": True},
        }),
        _args_qualifier(seuils={"resolution_minimale": 1000, "eclairage_minimal": 4, "autre": "fictif"}),
        _args_qualifier(seuils={"resolution_minimale": 0, "eclairage_minimal": 4}),
        _args_qualifier(seuils={"resolution_minimale": True, "eclairage_minimal": 4}),
        _args_qualifier(seuils={"resolution_minimale": 1000.5, "eclairage_minimal": 4}),
        _args_qualifier(seuils={"resolution_minimale": 1000, "eclairage_minimal": False}),
        _args_qualifier(seuils={"resolution_minimale": 1000, "eclairage_minimal": -0.1}),
        _args_qualifier(seuils={"resolution_minimale": 1000, "eclairage_minimal": 10.1}),
    ],
    ids=[
        "photo-cle-extra", "photo-id-blanc", "angle-blanc", "largeur-nulle", "largeur-bool",
        "largeur-fractionnaire", "eclairage-bool", "eclairage-negatif", "eclairage-superieur-10",
        "reference-manquante", "reference-cle-extra", "reference-type-blanc", "seuil-cle-extra",
        "seuil-resolution-nulle", "seuil-resolution-bool", "seuil-resolution-fractionnaire",
        "seuil-eclairage-bool", "seuil-eclairage-negatif", "seuil-eclairage-superieur-10",
    ],
)
def test_schema_et_execution_refusent_les_entrees_photo_ou_seuils_invalides(arguments):
    publics = _outils()
    for nom in ("m3_qualifier_photos", "m3_classifier_confiance"):
        outil = publics[nom]
        assert _erreurs_schema(outil, arguments)
        resultat = _resultat_public(outil, arguments)
        assert resultat["accepte"] is False
        assert resultat["verdict"]["code"] in {"REJ-PHOTOS-INVALIDES", "REJ-SEUILS-INVALIDES"}


def test_le_champ_reference_echelle_est_requis_meme_s_il_est_nullable():
    publics = _outils()
    photo = dict(PHOTO)
    del photo["reference_echelle"]
    arguments = _args_qualifier(photo=photo)

    for nom in ("m3_qualifier_photos", "m3_classifier_confiance"):
        outil = publics[nom]
        assert _erreurs_schema(outil, arguments)
        resultat = _resultat_public(outil, arguments)
        assert resultat["accepte"] is False
        assert resultat["verdict"]["code"] == "REJ-PHOTOS-INVALIDES"


def test_photo_vide_est_conforme_mais_renvoie_une_qualification_bloquee():
    outil = _outils()["m3_qualifier_photos"]
    arguments = {"photos": [], "seuils": SEUILS}

    assert _erreurs_schema(outil, arguments) == []
    resultat = _resultat_public(outil, arguments)
    assert resultat["accepte"] is True
    assert resultat["resultat"]["photos_acceptables"] is False
