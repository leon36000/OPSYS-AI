import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m5_financecore import encodage


def test_empreinte_est_deterministe():
    assert encodage.empreinte(1, "a", {"x": 1}) == encodage.empreinte(
        1, "a", {"x": 1}
    )


def test_ordre_des_cles_d_un_dict_n_affecte_pas_l_empreinte():
    assert encodage.empreinte({"a": 1, "b": 2}) == encodage.empreinte(
        {"b": 2, "a": 1}
    )


def test_le_prefixage_de_longueur_evite_les_collisions_de_concatenation():
    assert encodage.empreinte("a", "bc") != encodage.empreinte("ab", "c")


def test_empreinte_sans_argument_est_valide():
    resultat = encodage.empreinte()

    assert isinstance(resultat, str)
    assert resultat
    assert len(resultat) == 64
    assert all(caractere in "0123456789abcdef" for caractere in resultat)


def test_encoder_canonique_est_deterministe_pour_un_dict():
    assert encodage.encoder_canonique({"x": 1, "y": 2}) == encodage.encoder_canonique(
        {"y": 2, "x": 1}
    )


