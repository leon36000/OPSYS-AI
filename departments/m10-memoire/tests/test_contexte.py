import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m10_memoire import contrats, contexte, registre, validation


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


def test_contexte_suffisant_appelle_reellement_valider_evenement():
    """validation.valider_evenement et construire_verdict existaient et
    étaient testés en isolation mais n'étaient JAMAIS appelés par le chemin
    d'écriture réel (contexte.py dupliquait sa propre boucle de validation des
    5 champs texte) : câblés ici, contexte_suffisant délègue réellement la
    validation du sous-dossier EvenementMemoire à validation.valider_evenement
    plutôt que de la réimplémenter.
    """
    with patch.object(
        validation, "valider_evenement", wraps=validation.valider_evenement
    ) as espion:
        verdict, erreur = contexte.contexte_suffisant(_dossier())

    espion.assert_called_once()
    (evenement_passe,), _ = espion.call_args
    assert evenement_passe == {
        champ: _dossier()[champ] for champ in contrats.CHAMPS_EVENEMENT_MEMOIRE
    }
    assert verdict is True
    assert erreur is None


def test_contexte_suffisant_delegue_le_refus_de_champ_texte_a_valider_evenement():
    dossier = _dossier()
    dossier["preuves"] = ""

    with patch.object(
        validation, "valider_evenement", wraps=validation.valider_evenement
    ) as espion:
        verdict, erreur = contexte.contexte_suffisant(dossier)

    espion.assert_called_once()
    assert verdict is False
    assert erreur == contexte.REJ_CONTEXTE_CHAMP_TEXTE_INVALIDE


def test_tracer_refus_contexte_appelle_reellement_construire_verdict():
    registre_cible = registre.Registre()
    dossier = _dossier()
    dossier["references_decisions"] = []

    with patch.object(
        validation, "construire_verdict", wraps=validation.construire_verdict
    ) as espion:
        maillon, code = contexte.tracer_refus_contexte(
            dossier, registre_cible, HORODATAGE
        )

    espion.assert_called_once_with(code)
    assert maillon is not None
    assert maillon["verdict"] == {"code": code, "detail": None}


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


@pytest.mark.parametrize("registre_invalide", [None, "", 42, []])
def test_verifier_reference_refuse_un_champ_registre_non_texte_ou_vide(registre_invalide):
    """``registre`` (CHAMPS_REFERENCE_MEMOIRE) n'était jamais vérifié : seule
    la présence de la CLÉ comptait, pas la plausibilité de sa VALEUR. Une
    référence avec un champ ``registre`` incohérent (None, vide, ou d'un autre
    type) était acceptée dès lors que ligne_id/hash_tete concordaient.
    """
    registre_cible = registre.Registre()
    registre_cible.ajouter(_evenement())
    reference = contexte.construire_reference(
        registre_cible.lire()[-1], "forge", registre_cible
    )
    reference["registre"] = registre_invalide

    verdict, erreur = contexte.verifier_reference(reference, registre_cible)

    assert verdict is False
    assert isinstance(erreur, str)


def test_verifier_reference_detecte_un_hash_tete_positionne_avant_la_ligne_referencee():
    """``hash_tete`` doit être la tête de chaîne AU MOMENT de l'écriture de la
    référence : il ne peut structurellement jamais désigner un maillon
    antérieur à celui référencé (impossible causalement — ce maillon
    n'existait pas encore quand l'antérieur était la tête). Avant ce
    correctif, seule l'EXISTENCE de ``hash_tete`` quelque part dans la chaîne
    était vérifiée, jamais sa position relative à ``ligne_id`` : un hash_tete
    pointant vers un maillon plus ANCIEN — donc incohérent — passait.
    """
    registre_cible = registre.Registre()
    registre_cible.ajouter(_evenement("premier"))
    premier_ligne_id = registre_cible.lire()[-1]["ligne_id"]
    registre_cible.ajouter(_evenement("second"))
    second_maillon = registre_cible.lire()[-1]

    reference = contexte.construire_reference(second_maillon, "forge", registre_cible)
    reference["hash_tete"] = premier_ligne_id

    verdict, erreur = contexte.verifier_reference(reference, registre_cible)

    assert verdict is False
    assert isinstance(erreur, str)


def test_verifier_reference_accepte_un_hash_tete_avance_depuis_l_ecriture():
    """Non-régression : un hash_tete plus RÉCENT que ligne_id (la chaîne a
    avancé entre l'écriture du maillon et la construction de la référence)
    reste cohérent et donc accepté — seul un hash_tete plus ANCIEN est un
    refus.
    """
    registre_cible = registre.Registre()
    registre_cible.ajouter(_evenement("premier"))
    premier_maillon = registre_cible.lire()[-1]
    registre_cible.ajouter(_evenement("second"))
    dernier_ligne_id = registre_cible.lire()[-1]["ligne_id"]

    reference = contexte.construire_reference(premier_maillon, "forge", registre_cible)
    reference["hash_tete"] = dernier_ligne_id

    assert contexte.verifier_reference(reference, registre_cible) == (True, None)


def test_verifier_reference_rejette_une_reference_sur_une_chaine_falsifiee():
    """Une référence ne vaut que si la chaîne qui la porte est intacte.

    Objection CRITIQUE de la revue scellée (Qwen3.7-Max, round 1 de M10-S005),
    CONFIRMÉE par mesure : vérifier l'existence d'un `ligne_id` ne prouve RIEN sur
    l'intégrité du registre — le contenu d'un maillon peut être altéré sans que son
    `ligne_id` stocké ne change. Une référence `memoire_m10` servie à M9 sur un
    registre corrompu serait un faux feu vert.
    """
    registre_cible = registre.Registre()
    ligne_id = registre_cible.ajouter(_evenement())
    maillon = [m for m in registre_cible.lire() if m["ligne_id"] == ligne_id][0]
    reference = contexte.construire_reference(maillon, "forge", registre_cible)

    assert contexte.verifier_reference(reference, registre_cible) == (True, None)
    assert registre_cible.valider_chaine()[0] is True

    # Altération du CONTENU sans toucher au ligne_id stocké.
    registre_cible._chain[-1]["valeur"] = "FALSIFIEE"

    assert registre_cible.valider_chaine()[0] is False
    valide, code = contexte.verifier_reference(reference, registre_cible)
    assert valide is False
    assert code
