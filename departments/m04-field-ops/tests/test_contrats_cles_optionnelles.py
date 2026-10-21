"""PLAN T2.2 — M4 accepte les clés OPTIONNELLES du LeadQualifie à l'identique de M2.

Absentes : aucune faute. Présentes : `source`/`campagne` chaînes non vides, `utm` dictionnaire
non vide à sous-clés fermées et valeurs chaînes non vides ; sinon REJ-CONTRAT-INVALIDE, le code
de M2. Toute autre clé reste refusée.
"""

import m4_field_ops.contrats as contrats_mod
import pytest


def _contrat(**optionnels):
    contrat = {
        "lead_id": "L01",
        "conversation_id": "C01",
        "type_travaux": "renovation_totale",
        "ville": "Laval",
        "canal": "telephone",
        "contact": {"nom": "Tremblay"},
        "urgence_declaree": False,
    }
    contrat.update(optionnels)
    return contrat


def test_copies_alignees_sur_m2():
    assert contrats_mod.CHAMPS_CONTRAT_OPTIONNELS == ("source", "utm", "campagne")
    assert contrats_mod.CLES_UTM == ("utm_source", "utm_medium", "utm_campaign", "utm_content")


def test_trois_cles_optionnelles_acceptees():
    assert contrats_mod.valider_structure(_contrat(
        source="facebook", campagne="printemps",
        utm={"utm_source": "facebook", "utm_medium": "cpc", "utm_campaign": "printemps"},
    )) == (True, "")


def test_absence_des_cles_optionnelles_acceptee():
    assert contrats_mod.valider_structure(_contrat()) == (True, "")


@pytest.mark.parametrize("cle, valeur", [
    ("source", ""),
    ("source", 3),
    ("campagne", None),
    ("utm", {}),
    ("utm", "utm_source=facebook"),
    ("utm", {"utm_source": ""}),
    ("utm", {"utm_term": "gouttieres"}),
])
def test_forme_invalide_refusee_comme_chez_m2(cle, valeur):
    assert contrats_mod.valider_structure(_contrat(**{cle: valeur})) == (
        False, "REJ-CONTRAT-INVALIDE")


def test_cle_inconnue_toujours_refusee():
    assert contrats_mod.valider_structure(_contrat(source="google", utm_source="google")) == (
        False, "REJ-CONTRAT-INVALIDE")
