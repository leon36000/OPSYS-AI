import re

import pytest
from m8_analytics import encodage


def test_encoder_canonique_est_stable_pour_les_types_simples_supportes():
    valeurs = (
        "snapshot",
        42,
        3.14,
        True,
        None,
        ["liste", 1],
        {"cle": "valeur"},
        ("tuple", 2),
        {"ensemble", 3},
    )

    resultat = encodage.encoder_canonique(*valeurs)

    assert isinstance(resultat, str)
    assert resultat == encodage.encoder_canonique(*valeurs)


def test_encoder_canonique_evite_les_collisions_de_concatenation_naive():
    assert encodage.encoder_canonique("ab", "c") != encodage.encoder_canonique(
        "a", "bc"
    )


def test_empreinte_retourne_un_sha256_hex_deterministe():
    premiere = encodage.empreinte("module-A", {"mesure": 12.5}, None)
    seconde = encodage.empreinte("module-A", {"mesure": 12.5}, None)

    assert isinstance(premiere, str)
    assert re.fullmatch(r"[0-9a-f]{64}", premiere)
    assert premiere == seconde


def test_encoder_canonique_refuse_un_type_non_supporte():
    with pytest.raises(TypeError):
        encodage.encoder_canonique(object())


def test_encoder_canonique_ignore_l_ordre_d_insertion_des_cles_dict():
    premier = {"a": 1, "b": 2}
    second = {"b": 2, "a": 1}

    assert encodage.encoder_canonique(premier) == encodage.encoder_canonique(second)
