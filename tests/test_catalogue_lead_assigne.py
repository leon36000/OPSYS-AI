"""PLAN T1.4-m : `m2.lead_assigne` est versionné par un rang, de façon ADDITIVE (catalogue `opsys.evenement/v1`).

Le contrat d'origine (PLAN T1.4-k2, trois clés requises) reste gelé : toute charge valide avant reste valide, et le
rang 1 est octet pour octet celui d'avant. `rang` et `proprietaire_precedent` sont des clés optionnelles, présentes
ensemble et seulement pour une réassignation (rang >= 2). Ce fichier pin le gel, la forme des nouvelles clés, et le
lien avec la construction de la charge par M2 (`assignation.fait_assigne`) : ce que M2 publie est ce que le catalogue
accepte, et deux leads ne partagent jamais un identifiant d'événement. Données fictives (AGENTS.md).
"""

from __future__ import annotations

import copy

import pytest
from m2_revenue_crm import assignation

from opsys import evenements
from opsys.evenements import schemas

FICTIF = True
TYPE = "m2.lead_assigne"
H = "2026-09-01T09:05:00-04:00"
V1 = {"lead_id": "lead-1", "proprietaire": "vendeur.un", "horodatage_assignation": H}
RANG_2 = {**V1, "proprietaire": "vendeur.deux", "rang": 2, "proprietaire_precedent": "vendeur.un"}

# Les trois clés du contrat d'origine (T1.4-k2), telles qu'elles étaient : le gel.
PROPRIETES_V1 = {
    "lead_id": {"type": "string", "minLength": 1},
    "proprietaire": {"type": "string", "minLength": 1},
    "horodatage_assignation": {"type": "string"},
}


def _erreurs(charge):
    return schemas.erreurs_charge(TYPE, charge)


# -- le gel du contrat d'origine ---------------------------------------------------------------------------
def test_une_charge_de_t1_4_k2_reste_valide_octet_pour_octet():
    assert _erreurs(V1) == []


def test_les_trois_cles_d_origine_restent_requises_et_gardent_leur_forme():
    schema = schemas.schema(TYPE)

    assert schema["required"] == ["lead_id", "proprietaire", "horodatage_assignation"]
    for cle, forme in PROPRIETES_V1.items():
        assert {k: v for k, v in schema["properties"][cle].items() if k != "description"} == forme, cle
    assert schema["additionalProperties"] is False
    assert schema["$id"] == "opsys.evenement/v1/m2.lead_assigne"


@pytest.mark.parametrize("cle", sorted(PROPRIETES_V1))
def test_retirer_une_cle_d_origine_reste_un_refus(cle):
    charge = {k: v for k, v in V1.items() if k != cle}

    assert any(cle in erreur for erreur in _erreurs(charge))


def test_seules_deux_cles_s_ajoutent_et_aucune_n_est_requise():
    schema = schemas.schema(TYPE)

    assert set(schema["properties"]) == set(PROPRIETES_V1) | {"rang", "proprietaire_precedent"}
    assert not {"rang", "proprietaire_precedent"} & set(schema["required"])


# -- les nouvelles clés -------------------------------------------------------------------------------------
def test_une_reassignation_porte_son_rang_et_le_proprietaire_qu_elle_remplace():
    assert _erreurs(RANG_2) == []
    assert _erreurs({**RANG_2, "rang": 3, "proprietaire_precedent": "vendeur.deux"}) == []


@pytest.mark.parametrize("modification", [
    {"proprietaire_precedent": None},  # `rang` sans son précédent
    {"rang": None},  # le précédent sans `rang`
    {"rang": 1},  # le rang 1 s'écrit sans la clé, une seule façon
    {"rang": 0},
    {"rang": -2},
    {"rang": "2"},
    {"rang": 2.5},
    {"rang": True},
    {"proprietaire_precedent": ""},
    {"proprietaire_precedent": 12},
    {"inconnue": "x"},
], ids=["rang-sans-precedent", "precedent-sans-rang", "rang-un-explicite", "rang-zero", "rang-negatif", "rang-texte",
        "rang-decimal", "rang-booleen", "precedent-vide", "precedent-non-texte", "cle-inconnue"])
def test_une_charge_de_reassignation_mal_formee_est_refusee(modification):
    charge = copy.deepcopy(RANG_2)
    for cle, valeur in modification.items():
        if valeur is None:
            del charge[cle]
        else:
            charge[cle] = valeur

    assert _erreurs(charge) != []


# -- ce que M2 construit, le catalogue l'accepte -------------------------------------------------------------
@pytest.mark.parametrize("rang", [1, 2, 3, 10])
@pytest.mark.parametrize("lead_id", ["lead-1", "foo", "2-foo", "reassigne-2-foo", "r2", "a b", "é"])
def test_la_charge_construite_par_m2_est_conforme_au_catalogue_pour_chaque_rang(lead_id, rang):
    _identifiant, charge = assignation.fait_assigne(
        lead_id, "vendeur.un", H, rang, None if rang == 1 else "vendeur.deux")

    assert _erreurs(charge) == []
    assert ("rang" in charge) is (rang != 1)


def test_le_rang_un_de_m2_est_exactement_la_charge_d_origine():
    assert assignation.fait_assigne("lead-1", "vendeur.un", H) == ("m2-lead-assigne-lead-1", V1)


def test_les_identifiants_de_deux_leads_ne_se_confondent_pas_au_bus(session):
    """`lead_id` est une chaîne libre : `publier` ignore en silence un second fait sous un identifiant déjà pris."""
    faits = [
        assignation.fait_assigne("foo", "vendeur.un", H),
        assignation.fait_assigne("foo", "vendeur.deux", H, 2, "vendeur.un"),
        assignation.fait_assigne("2-foo", "vendeur.trois", H),
        assignation.fait_assigne("reassigne-2-foo", "vendeur.quatre", H),
    ]
    with session():
        for evenement_id, charge in faits:
            assert evenements.publier(TYPE, "m02-revenue-crm", charge, evenement_id=evenement_id) == evenement_id
        for evenement_id, charge in faits:
            assert evenements.charge_publiee(TYPE, evenement_id) == charge


def test_le_bus_accepte_une_charge_de_reassignation_et_refuse_une_charge_incomplete(session):
    with session():
        assert evenements.publier(TYPE, "m02-revenue-crm", RANG_2, evenement_id="m2-lead-reassigne-2-lead-1")
        with pytest.raises(evenements.ChargeInvalide):
            evenements.publier(
                TYPE, "m02-revenue-crm", {k: v for k, v in RANG_2.items() if k != "proprietaire_precedent"},
                evenement_id="m2-lead-reassigne-2-lead-2")
        assert evenements.charge_publiee(TYPE, "m2-lead-reassigne-2-lead-2") is None
