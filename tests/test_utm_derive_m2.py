"""Garde de dérive : M1 valide un `utm` comme M2 le valide (PLAN T4.17-e3).

Un département ne lit pas le code d'un autre : M1 (`m1_front_office.contrats.utm_invalide`) et M2
(`m2_revenue_crm.contrats`, par `valider_structure`) portent chacun leur lecture de la règle du `utm` d'un lead. Ce test
les confronte sur les mêmes entrées, toutes celles qu'on peut fabriquer avec quelques clés et quelques valeurs, pour
qu'elles ne divergent pas : un lead que M1 émet avec un `utm` ne doit jamais être refusé par M2 (il irait en
quarantaine, sans lead chez M2), et M1 ne doit jamais refuser ce que M2 accepte (un `utm` de M7 perdu). Chaque lead
d'essai est complet et valide par ailleurs : seul le `utm` change.
"""

from __future__ import annotations

import itertools

import pytest
from m1_front_office import contrats as contrats_m1
from m2_revenue_crm import contrats as contrats_m2

from opsys import taxonomie

CLES = (*contrats_m2.CLES_UTM, "utm_id", "UTM_SOURCE", "utm_term", "", 7)
VALEURS = ("facebook", "", " ", "Été 2026", "a" * 5000, 0, 1, True, False, None, [], ["a"], {}, {"a": "b"}, 1.5)
NON_DICTIONNAIRES = (
    "", "utm_source=google", 0, 1, True, False, None, [], ["utm_source"], ("utm_source", "google"), 1.5,
)


def _lead(utm) -> dict:
    """Un lead v2 que M2 accepte à tous égards, hors le `utm` (`gouttieres` est déclaré par `declarer_services`)."""
    return {
        "schema_version": 2, "lead_id": "lead-1", "conversation_id": "conv-1", "service": "gouttieres",
        "ville": "Laval", "canal": "formulaire", "contact": {"courriel": "visiteur.fictif@exemple.test"},
        "urgence_declaree": False, "utm": utm,
    }


def _entrees():
    """Tous les dictionnaires d'au plus deux clés (`CLES`) et de valeurs `VALEURS`, puis ce qui n'en est pas un."""
    yield {}
    for cle, valeur in itertools.product(CLES, VALEURS):
        yield {cle: valeur}
    for (cle_a, cle_b), valeur_a, valeur_b in itertools.product(
        itertools.combinations(CLES, 2), ("facebook", "", 1), ("social", "", None)
    ):
        yield {cle_a: valeur_a, cle_b: valeur_b}
    yield dict.fromkeys(contrats_m2.CLES_UTM, "x")
    yield {**dict.fromkeys(contrats_m2.CLES_UTM, "x"), "utm_id": "x"}
    yield from NON_DICTIONNAIRES


def test_les_cles_sont_les_memes_que_celles_de_m2():
    assert contrats_m1._CLES_UTM == contrats_m2.CLES_UTM == (
        "utm_source", "utm_medium", "utm_campaign", "utm_content")


def test_le_lead_d_essai_est_accepte_par_m2_sans_utm_et_avec_un_utm_conforme(declarer_services):
    declarer_services()
    sans_utm = {cle: valeur for cle, valeur in _lead(None).items() if cle != "utm"}
    assert contrats_m2.valider_structure(sans_utm) == (True, "")
    assert contrats_m2.valider_structure(_lead({"utm_source": "facebook"})) == (True, "")


def test_m1_et_m2_acceptent_et_refusent_les_memes_utm(declarer_services):
    declarer_services()
    total = accepte = 0
    for utm in _entrees():
        ok_m2, code_m2 = contrats_m2.valider_structure(_lead(utm))
        ok_m1 = contrats_m1.utm_invalide(utm) is None
        assert ok_m1 == ok_m2, f"M1 et M2 divergent sur {utm!r} : M1 {ok_m1}, M2 {ok_m2} ({code_m2})"
        if utm is not None:  # `None` veut dire « pas d'utm » pour l'appelant de M1 : rien à vérifier
            assert (contrats_m1.verifier_utm("formulaire", utm) is None) == ok_m2, utm
        total += 1
        accepte += ok_m2
    assert total > 400 and 0 < accepte < total, "l'essai couvre à la fois des refus et des acceptations"


@pytest.mark.parametrize("utm", [{"utm_source": "a" * 5000}, {"utm_content": " "}, {"utm_medium": "Été 2026 / CPC"}])
def test_ni_m1_ni_m2_ne_bornent_la_longueur_ni_l_alphabet(utm, declarer_services):
    """Décision reportée (T4.17-e3, GATE) : aucune borne de longueur ni d'alphabet, chez M2 comme chez M1."""
    declarer_services()
    assert contrats_m2.valider_structure(_lead(utm)) == (True, "")
    assert contrats_m1.utm_invalide(utm) is None


def test_le_lead_que_m1_valide_avec_son_utm_est_valide_pour_m2(declarer_services):
    declarer_services()
    services, _ = taxonomie.charger_services()
    for utm in ({"utm_source": "google"}, dict.fromkeys(contrats_m2.CLES_UTM, "valeur")):
        lead = _lead(utm)
        assert contrats_m1.valider_lead(lead, services=services)["code"] == "EVT-CONTRAT-VALIDE"
        assert contrats_m2.valider_structure(lead) == (True, "")
