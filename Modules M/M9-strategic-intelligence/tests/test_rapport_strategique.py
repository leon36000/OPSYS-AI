import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m9_strategic_intelligence import contrats, rapport_strategique


def _rapport_complet():
    valeurs = (None, "", [], {}, 0)
    return {
        cle: valeurs[index % len(valeurs)]
        for index, cle in enumerate(contrats.CHAMPS_RAPPORT_STRATEGIQUE)
    }


def _code_rejet(rapport):
    verdict = rapport_strategique.valider_rapport_strategique(rapport)

    assert isinstance(verdict, tuple)
    assert len(verdict) == 2
    assert verdict[0] is False
    assert isinstance(verdict[1], str)
    assert verdict[1].startswith("REJ-")

    return verdict[1]


@pytest.fixture
def code_structure_invalide():
    return _code_rejet([])


@pytest.fixture
def code_cle_manquante():
    rapport = _rapport_complet()
    rapport.pop(next(iter(contrats.CHAMPS_RAPPORT_STRATEGIQUE)))
    return _code_rejet(rapport)


@pytest.fixture
def code_cle_en_trop():
    rapport = _rapport_complet()
    rapport["commentaire_libre"] = None
    return _code_rejet(rapport)


def test_rapport_avec_exactement_les_cles_attendues_est_valide():
    rapport = _rapport_complet()

    assert set(rapport.keys()) == contrats.CHAMPS_RAPPORT_STRATEGIQUE
    assert rapport_strategique.valider_rapport_strategique(rapport) == (True, None)


@pytest.mark.parametrize("rapport", [[], "texte", None, 42])
def test_rapport_non_dict_est_rejete_avec_le_meme_code_structure(
    rapport, code_structure_invalide
):
    assert _code_rejet(rapport) == code_structure_invalide


def test_rapport_avec_une_cle_manquante_est_rejete_distinctement(
    code_structure_invalide, code_cle_manquante
):
    assert code_cle_manquante != code_structure_invalide


def test_rapport_avec_une_cle_en_trop_est_rejete_distinctement(
    code_structure_invalide, code_cle_manquante, code_cle_en_trop
):
    assert code_cle_en_trop != code_structure_invalide
    assert code_cle_en_trop != code_cle_manquante


def test_cle_manquante_est_prioritaire_sur_cle_en_trop(
    code_cle_manquante, code_cle_en_trop
):
    rapport = _rapport_complet()
    rapport.pop(next(iter(contrats.CHAMPS_RAPPORT_STRATEGIQUE)))
    rapport["cle_inconnue"] = None

    assert len(rapport) == len(contrats.CHAMPS_RAPPORT_STRATEGIQUE)
    assert _code_rejet(rapport) == code_cle_manquante
    assert _code_rejet(rapport) != code_cle_en_trop


def test_rapport_vide_est_rejete_comme_cle_manquante(code_cle_manquante):
    assert _code_rejet({}) == code_cle_manquante


def test_validation_n_accepte_qu_un_seul_argument_positionnel():
    with pytest.raises(TypeError):
        rapport_strategique.valider_rapport_strategique(_rapport_complet(), None)
