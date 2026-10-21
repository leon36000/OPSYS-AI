from m10_memoire import encodage


def test_encoder_canonique_est_stable_pour_les_types_supportes():
    valeurs = (
        "texte",
        42,
        3.14,
        True,
        None,
        ["liste", 1, False],
        {"cle": "valeur", "nombre": 2},
        ("tuple", None),
        {"ensemble", "valeur"},
    )

    assert encodage.encoder_canonique(*valeurs) == encodage.encoder_canonique(*valeurs)


def test_encoder_canonique_evite_les_collisions_de_concatenation_naive():
    assert encodage.encoder_canonique("ab", "c") != encodage.encoder_canonique("a", "bc")


def test_empreinte_retourne_un_sha256_hexadecimal_deterministe():
    premiere = encodage.empreinte("memoire", 42, {"a": [True, None]})
    seconde = encodage.empreinte("memoire", 42, {"a": [True, None]})

    assert premiere == seconde
    assert len(premiere) == 64
    assert all(caractere in "0123456789abcdef" for caractere in premiere)


def test_encoder_canonique_refuse_les_types_non_supportes():
    try:
        encodage.encoder_canonique(object())
    except TypeError:
        pass
    else:
        raise AssertionError("encoder_canonique doit refuser les types non supportés")


def test_ordre_insertion_cles_dict_n_affecte_pas_encodage():
    premier = {"a": 1, "b": 2}
    second = {"b": 2, "a": 1}

    assert encodage.encoder_canonique(premier) == encodage.encoder_canonique(second)


def test_encoder_canonique_distingue_liste_et_tuple():
    assert encodage.encoder_canonique(["a"]) != encodage.encoder_canonique(("a",))


def test_encoder_canonique_distingue_set_et_liste():
    assert encodage.encoder_canonique({"a"}) != encodage.encoder_canonique(["a"])
