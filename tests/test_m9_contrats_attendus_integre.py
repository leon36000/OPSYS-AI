"""Contrats attendus M9 face aux producteurs réels : catégories de M1 comparées, lectures absentes constatées."""

from __future__ import annotations

from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import contrats_attendus as ca

from opsys import lecteurs_m9, taxonomie

FICTIF = True


def test_les_categories_de_plainte_du_contrat_sont_celles_de_la_taxonomie_de_m1():
    assert frozenset(taxonomie.CATEGORIES_SIGNAL_PLAINTE) == ca.CATEGORIES_PLAINTE


def test_etat_des_contrats_attendus_suit_la_liste_blanche_du_port_prive():
    """Un contrat est PUBLIE si et seulement si son outil est dans la liste blanche du port privé ET au catalogue.

    L'égalité entre ce port et le catalogue de M9 est déjà prouvée par ``tests/test_lecteurs_m9.py``.
    """
    autorisees = {outil for outils in lecteurs_m9.LECTURES_AUTORISEES.values() for outil in outils}
    for domaine in ca.CONTRATS:
        branche = ca.CONTRATS[domaine]["outil_attendu"] in autorisees
        assert branche == (ca.CONTRATS[domaine]["lecture_id"] in cat.PAR_ID) == (ca.etat(domaine) == "PUBLIE"), domaine
    assert ca.etat("depenses_marketing") == "PUBLIE"
