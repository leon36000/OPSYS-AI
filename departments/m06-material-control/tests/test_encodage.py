import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import re

import pytest

from m6_material_control.encodage import encoder_canonique, empreinte


def test_empreinte_retourne_sha256_hex_minuscule():
    resultat = empreinte("a", "b")

    assert isinstance(resultat, str)
    assert re.fullmatch(r"[0-9a-f]{64}", resultat)


def test_empreinte_est_reproductible():
    assert empreinte("a", "b") == empreinte("a", "b")


def test_encoder_canonique_prefixe_les_longueurs_pour_eviter_ambiguite_concatenee():
    assert encoder_canonique("ab", "c") != encoder_canonique("a", "bc")


def test_encoder_canonique_refuse_un_type_non_supporte():
    with pytest.raises(TypeError):
        encoder_canonique(object())

