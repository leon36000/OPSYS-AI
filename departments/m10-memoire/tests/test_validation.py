import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m10_memoire import validation

import pytest


def _evenement_valide():
    return {
        "evenement": "Intervention terminee",
        "resume": "La maintenance a ete effectuee.",
        "preuves": "Rapport signe",
        "impact": "Service retabli",
        "prochaine_action": "Cloturer le dossier",
    }


def _decision_valide():
    return {
        "decision_id": "DEC-001",
        "raison": "La preuve disponible justifie cette decision.",
        "statut": "proposee",
        "options_ecartees": "Reporter la decision",
    }


def _code_rejet(resultat):
    assert isinstance(resultat, tuple)
    assert len(resultat) == 2
    assert resultat[0] is False
    assert isinstance(resultat[1], str)
    assert resultat[1].startswith("REJ-")
    return resultat[1]


def test_valider_evenement_accepte_structure_et_contenu_valides():
    assert validation.valider_evenement(_evenement_valide()) == (True, None)


@pytest.mark.parametrize("evenement", [[], None, "evenement", 42])
def test_valider_evenement_rejette_les_structures_non_dict(evenement):
    _code_rejet(validation.valider_evenement(evenement))


@pytest.mark.parametrize(
    "evenement",
    [
        {
            "evenement": "Intervention terminee",
            "resume": "La maintenance a ete effectuee.",
            "preuves": "Rapport signe",
            "impact": "Service retabli",
        },
        {
            "evenement": "Intervention terminee",
            "resume": "La maintenance a ete effectuee.",
            "preuves": "Rapport signe",
            "impact": "Service retabli",
            "prochaine_action": "Cloturer le dossier",
            "champ_en_trop": "interdit",
        },
    ],
)
def test_valider_evenement_rejette_cles_manquantes_ou_en_trop(evenement):
    _code_rejet(validation.valider_evenement(evenement))


@pytest.mark.parametrize(
    ("champ", "valeur_invalide"),
    [
        ("evenement", ""),
        ("resume", ""),
        ("preuves", ""),
        ("impact", ""),
        ("prochaine_action", ""),
        ("evenement", 42),
        ("resume", 42),
        ("preuves", 42),
        ("impact", 42),
        ("prochaine_action", 42),
    ],
)
def test_valider_evenement_distingue_contenu_texte_invalide_de_structure(
    champ, valeur_invalide
):
    evenement = _evenement_valide()
    evenement[champ] = valeur_invalide

    code_structure = _code_rejet(validation.valider_evenement({}))
    code_contenu = _code_rejet(validation.valider_evenement(evenement))

    assert code_contenu != code_structure


def test_valider_evenement_n_accepte_qu_un_argument_positionnel():
    with pytest.raises(TypeError):
        validation.valider_evenement(_evenement_valide(), _evenement_valide())


def test_valider_decision_accepte_structure_raison_et_statut_valides():
    assert validation.valider_decision(_decision_valide()) == (True, None)


@pytest.mark.parametrize("decision", [[], None, "decision", 42])
def test_valider_decision_rejette_les_structures_non_dict(decision):
    _code_rejet(validation.valider_decision(decision))


@pytest.mark.parametrize(
    "decision",
    [
        {
            "decision_id": "DEC-001",
            "raison": "La preuve disponible justifie cette decision.",
            "statut": "proposee",
        },
        {
            "decision_id": "DEC-001",
            "raison": "La preuve disponible justifie cette decision.",
            "statut": "proposee",
            "options_ecartees": "Reporter la decision",
            "champ_en_trop": "interdit",
        },
    ],
)
def test_valider_decision_rejette_cles_manquantes_ou_en_trop(decision):
    _code_rejet(validation.valider_decision(decision))


@pytest.mark.parametrize("raison_invalide", ["", 42])
def test_valider_decision_raison_invalide_a_un_code_specifique(raison_invalide):
    decision = _decision_valide()
    decision["raison"] = raison_invalide

    code_structure = _code_rejet(validation.valider_decision({}))
    code_raison = _code_rejet(validation.valider_decision(decision))

    assert code_raison != code_structure


@pytest.mark.parametrize("statut_invalide", ["valide", "FUSIONNE", ""])
def test_valider_decision_rejette_les_statuts_hors_enumeration(statut_invalide):
    decision = _decision_valide()
    decision["statut"] = statut_invalide

    code_statut = _code_rejet(validation.valider_decision(decision))
    code_structure = _code_rejet(validation.valider_decision({}))

    assert code_statut != code_structure


def test_valider_decision_ne_coerce_pas_un_statut_inconnu_vers_indetermine():
    decision = _decision_valide()
    decision["statut"] = "valeur_inconnue"

    resultat = validation.valider_decision(decision)

    assert resultat != (True, None)
    _code_rejet(resultat)


def test_valider_decision_accepte_indetermine_explicite():
    decision = _decision_valide()
    decision["statut"] = "indetermine"

    assert validation.valider_decision(decision) == (True, None)


def test_valider_decision_accepte_options_ecartees_vide():
    decision = _decision_valide()
    decision["options_ecartees"] = ""

    assert validation.valider_decision(decision) == (True, None)


def test_valider_decision_distingue_raison_invalide_et_statut_invalide():
    decision_raison = _decision_valide()
    decision_raison["raison"] = ""

    decision_statut = _decision_valide()
    decision_statut["statut"] = "valide"

    code_raison = _code_rejet(validation.valider_decision(decision_raison))
    code_statut = _code_rejet(validation.valider_decision(decision_statut))

    assert code_raison != code_statut


def test_valider_decision_n_accepte_qu_un_argument_positionnel():
    with pytest.raises(TypeError):
        validation.valider_decision(_decision_valide(), _decision_valide())


def test_construire_verdict_retourne_code_et_detail_fourni():
    decision = _decision_valide()
    decision["statut"] = "valeur_inconnue"
    code = _code_rejet(validation.valider_decision(decision))

    verdict = validation.construire_verdict(code, "Statut non autorise")

    assert isinstance(verdict, dict)
    assert verdict["code"] == code
    assert verdict["detail"] == "Statut non autorise"
