import pytest
from m9_strategic_intelligence import validation


def _snapshot_valide():
    return {
        "module_source": "m8_analytics",
        "horodatage": "2026-08-03T12:00:00",
        "valeurs": {"cle1": "42"},
    }


def _code_rejet(snapshot):
    resultat = validation.valider_snapshot(snapshot)

    assert isinstance(resultat, tuple)
    assert len(resultat) == 2
    assert resultat[0] is False
    assert isinstance(resultat[1], str)
    assert resultat[1].startswith("REJ-")

    return resultat[1]


def test_snapshot_structurellement_valide_est_accepte():
    assert validation.valider_snapshot(_snapshot_valide()) == (True, None)


def test_snapshot_avec_valeurs_vides_est_accepte():
    snapshot = _snapshot_valide()
    snapshot["valeurs"] = {}

    assert validation.valider_snapshot(snapshot) == (True, None)


@pytest.mark.parametrize("snapshot", [[], "snapshot", None])
def test_snapshot_qui_n_est_pas_un_dict_est_rejete_comme_structure_invalide(snapshot):
    code = _code_rejet(snapshot)

    assert code == _code_rejet([])


def test_cles_manquantes_en_trop_et_valeurs_non_dict_sont_rejetees_comme_structure_invalide():
    snapshot_cle_manquante = {
        "module_source": "m8_analytics",
        "horodatage": "2026-08-03T12:00:00",
    }
    snapshot_cle_en_trop = _snapshot_valide()
    snapshot_cle_en_trop["extra"] = "interdit"
    snapshot_valeurs_non_dict = _snapshot_valide()
    snapshot_valeurs_non_dict["valeurs"] = []

    code_structure = _code_rejet([])
    assert _code_rejet(snapshot_cle_manquante) == code_structure
    assert _code_rejet(snapshot_cle_en_trop) == code_structure
    assert _code_rejet(snapshot_valeurs_non_dict) == code_structure


@pytest.mark.parametrize(
    "champ,valeur",
    [
        ("module_source", ""),
        ("module_source", 42),
        ("horodatage", ""),
        ("horodatage", 42),
    ],
)
def test_champ_texte_vide_ou_non_texte_est_rejete_distinctement_de_la_structure(
    champ, valeur
):
    snapshot = _snapshot_valide()
    snapshot[champ] = valeur

    code_texte = _code_rejet(snapshot)
    code_structure = _code_rejet([])

    assert code_texte != code_structure


def test_les_deux_champs_texte_invalide_partagent_un_verdict_de_contenu():
    module_source_invalide = _snapshot_valide()
    module_source_invalide["module_source"] = ""
    horodatage_invalide = _snapshot_valide()
    horodatage_invalide["horodatage"] = ""

    assert _code_rejet(module_source_invalide) == _code_rejet(horodatage_invalide)


def test_valeur_interne_non_texte_est_rejetee_distinctement():
    snapshot = _snapshot_valide()
    snapshot["valeurs"] = {"cle1": 42}

    code_valeur_non_texte = _code_rejet(snapshot)
    code_structure = _code_rejet([])
    snapshot_texte_invalide = _snapshot_valide()
    snapshot_texte_invalide["module_source"] = ""
    code_texte_invalide = _code_rejet(snapshot_texte_invalide)

    assert code_valeur_non_texte != code_structure
    assert code_valeur_non_texte != code_texte_invalide


def test_valider_snapshot_n_accepte_qu_un_seul_argument_positionnel():
    with pytest.raises(TypeError):
        validation.valider_snapshot(_snapshot_valide(), {"cle1": "42"})
