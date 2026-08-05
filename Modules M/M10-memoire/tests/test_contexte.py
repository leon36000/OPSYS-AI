import sys
from copy import deepcopy
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m10_memoire import contrats, contexte, registre


HORODATAGE = "2026-08-04T12:00:00+00:00"


def _evenement(valeur="origine"):
    return {
        "type_entree": "evenement_memorise",
        "horodatage": HORODATAGE,
        "valeur": valeur,
    }


def _dossier():
    return {
        "evenement": "Modification du module X",
        "resume": "Ajout d'une garde",
        "preuves": "Tests verts",
        "impact": "Aucun appelant cassé",
        "prochaine_action": "Ouvrir la PR",
        "references_decisions": ["DEC-001"],
    }


def test_contexte_suffisant_accepte_un_dossier_complet():
    verdict, erreur = contexte.contexte_suffisant(_dossier())

    assert verdict is True
    assert erreur is None


def test_contexte_suffisant_refuse_ce_qui_n_est_pas_un_dict():
    verdict, erreur = contexte.contexte_suffisant(["pas", "un", "dict"])

    assert verdict is False
    assert isinstance(erreur, str)
    assert erreur.startswith("REJ-")


@pytest.mark.parametrize(
    "dossier",
    [
        {
            cle: valeur
            for cle, valeur in _dossier().items()
            if cle != "preuves"
        },
        {**_dossier(), "cle_en_trop": "interdite"},
    ],
)
def test_contexte_suffisant_refuse_les_structures_aux_cles_non_exactes(dossier):
    verdict, erreur = contexte.contexte_suffisant(dossier)

    assert verdict is False
    assert isinstance(erreur, str)
    assert erreur.startswith("REJ-")


@pytest.mark.parametrize(
    "champ,valeur",
    [
        ("evenement", ""),
        ("resume", 42),
    ],
)
def test_contexte_suffisant_refuse_un_champ_texte_vide_ou_non_texte(champ, valeur):
    dossier = _dossier()
    dossier[champ] = valeur

    verdict, erreur = contexte.contexte_suffisant(dossier)
    _, erreur_structure = contexte.contexte_suffisant({})
    dossier_references_vides = _dossier()
    dossier_references_vides["references_decisions"] = []
    _, erreur_references = contexte.contexte_suffisant(dossier_references_vides)

    assert verdict is False
    assert isinstance(erreur, str)
    assert erreur != erreur_structure
    assert erreur != erreur_references


def test_contexte_suffisant_refuse_les_references_de_decisions_vides():
    dossier = _dossier()
    dossier["references_decisions"] = []

    verdict, erreur = contexte.contexte_suffisant(dossier)
    _, erreur_structure = contexte.contexte_suffisant({})
    dossier_texte_invalide = _dossier()
    dossier_texte_invalide["preuves"] = ""
    _, erreur_texte = contexte.contexte_suffisant(dossier_texte_invalide)

    assert verdict is False
    assert isinstance(erreur, str)
    assert erreur != erreur_structure
    assert erreur != erreur_texte


@pytest.mark.parametrize(
    "dossier",
    [
        None,
        [],
        {},
        {**_dossier(), "inattendu": "x"},
        {**_dossier(), "impact": ""},
        {**_dossier(), "references_decisions": []},
    ],
)
def test_contexte_suffisant_ne_leve_jamais_et_retourne_un_refus(dossier):
    try:
        verdict, erreur = contexte.contexte_suffisant(dossier)
    except SystemExit:
        pytest.fail("contexte_suffisant ne doit jamais lever SystemExit")

    assert verdict is False
    assert isinstance(erreur, str)
    assert erreur.startswith("REJ-")


def test_tracer_refus_contexte_ne_trace_rien_si_dossier_suffisant():
    registre_cible = registre.Registre()

    maillon, erreur = contexte.tracer_refus_contexte(
        _dossier(), registre_cible, HORODATAGE
    )

    assert maillon is None
    assert erreur is None
    assert registre_cible.lire() == []


def test_tracer_refus_contexte_ecrit_le_code_du_refus():
    registre_cible = registre.Registre()
    dossier = _dossier()
    dossier["references_decisions"] = []
    _, code_attendu = contexte.contexte_suffisant(dossier)

    maillon, code = contexte.tracer_refus_contexte(
        dossier, registre_cible, HORODATAGE
    )

    assert maillon is not None
    assert code == code_attendu
    assert maillon["type_entree"] == "revision_signalee"
    assert code in maillon.values()
    assert len(registre_cible.lire()) == 1


def test_construire_reference_a_exactement_les_trois_cles_attendues():
    registre_cible = registre.Registre()
    ligne_id = registre_cible.ajouter(_evenement())
    maillon = registre_cible.lire()[-1]

    reference = contexte.construire_reference(
        maillon, "registre-memoire", registre_cible
    )

    assert set(reference) == contrats.CHAMPS_REFERENCE_MEMOIRE
    assert reference["ligne_id"] == ligne_id
    assert reference["registre"] == "registre-memoire"
    assert reference["hash_tete"] == registre_cible.tete()


def test_verifier_reference_accepte_une_reference_legitime():
    registre_cible = registre.Registre()
    registre_cible.ajouter(_evenement())
    maillon = registre_cible.lire()[-1]
    reference = contexte.construire_reference(
        maillon, "registre-memoire", registre_cible
    )

    verdict, erreur = contexte.verifier_reference(reference, registre_cible)

    assert verdict is True
    assert erreur is None


def test_verifier_reference_detecte_un_ligne_id_forgee():
    registre_cible = registre.Registre()
    registre_cible.ajouter(_evenement())
    reference = contexte.construire_reference(
        registre_cible.lire()[-1], "registre-memoire", registre_cible
    )
    reference_forgee = deepcopy(reference)
    reference_forgee["ligne_id"] = "ligne-inventee"

    verdict, erreur = contexte.verifier_reference(reference_forgee, registre_cible)

    assert verdict is False
    assert isinstance(erreur, str)


def test_verifier_reference_detecte_un_hash_tete_incoherent():
    registre_cible = registre.Registre()
    registre_cible.ajouter(_evenement())
    reference = contexte.construire_reference(
        registre_cible.lire()[-1], "registre-memoire", registre_cible
    )
    reference_incoherente = deepcopy(reference)
    reference_incoherente["hash_tete"] = "hash-incoherent"

    verdict, erreur = contexte.verifier_reference(
        reference_incoherente, registre_cible
    )

    assert verdict is False
    assert isinstance(erreur, str)
