"""The public photo schema and Python runtime must agree on nonblank Unicode strings."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from m3_estimation.outils import outils
from opsys.outils import executer

_PYTHON_WHITESPACE = tuple(
    chr(codepoint) for codepoint in range(0x110000) if chr(codepoint).isspace()
)
_CASES = [
    *((valeur, False) for valeur in _PYTHON_WHITESPACE),
    ("\ufeff", True),
    ("A", True),
    ("\u200b", True),
]
_CASE_IDS = [
    *(f"python-whitespace-U+{ord(valeur):04X}" for valeur in _PYTHON_WHITESPACE),
    "bom-python-nonblank",
    "ascii-visible",
    "zero-width-space-python-nonblank",
]


def _photo():
    return {
        "photo_id": "photo-fictive",
        "resolution_largeur": 1600,
        "resolution_hauteur": 1200,
        "eclairage": 7,
        "angle": "face",
        "reference_echelle": {"type": "porte", "dimensions_connues": True},
    }


def _outil_par_nom(nom):
    return next(outil for outil in outils() if outil.nom == nom)


@pytest.mark.parametrize("champ", ["photo_id", "angle", "reference_echelle.type"])
@pytest.mark.parametrize(
    ("valeur", "acceptee"),
    _CASES,
    ids=_CASE_IDS,
)
def test_schema_jsonschema_et_runtime_public_partagent_la_semantique_strip(champ, valeur, acceptee):
    arguments = {"photos": [_photo()], "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4}}
    photo = arguments["photos"][0]
    if champ == "reference_echelle.type":
        photo["reference_echelle"]["type"] = valeur
    else:
        photo[champ] = valeur

    schema_errors = list(Draft202012Validator(_outil_par_nom("m3_qualifier_photos").parametres).iter_errors(arguments))
    assert bool(schema_errors) is (not acceptee)

    for nom in ("m3_qualifier_photos", "m3_classifier_confiance"):
        resultat = executer(_outil_par_nom(nom), arguments)["resultat"]
        assert resultat["accepte"] is acceptee, (nom, champ, repr(valeur), resultat)


def test_schema_unicode_est_identique_sur_les_trois_outils_publics():
    motifs = []
    for nom in ("m3_estimer_projet", "m3_qualifier_photos", "m3_classifier_confiance"):
        schema = _outil_par_nom(nom).parametres
        motifs.append((
            schema["properties"]["photos"]["items"]["properties"]["photo_id"]["pattern"],
            schema["properties"]["photos"]["items"]["properties"]["angle"]["pattern"],
            schema["properties"]["photos"]["items"]["properties"]["reference_echelle"]["properties"]["type"]["pattern"],
        ))
    assert motifs[0] == motifs[1] == motifs[2]


def test_pattern_est_conforme_aux_espaces_python_dans_ecmascript_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js absent; les essais Python restent exécutés")

    schema = _outil_par_nom("m3_qualifier_photos").parametres
    pattern = schema["properties"]["photos"]["items"]["properties"]["photo_id"]["pattern"]
    cases = [{"value": valeur, "expected": acceptee} for valeur, acceptee in _CASES]
    script = Path(__file__).with_name("test_photo_schema_whitespace_ecmascript.mjs")
    resultat = subprocess.run(
        [node, str(script)],
        input=json.dumps({"pattern": pattern, "cases": cases}, ensure_ascii=True),
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert resultat.returncode == 0, resultat.stderr
