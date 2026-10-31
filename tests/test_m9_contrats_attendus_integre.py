"""Contrats attendus M9 face aux producteurs réels : catégories de M1 comparées, lectures absentes constatées."""

from __future__ import annotations

from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import contrats_attendus as ca

from opsys import lecteurs_m9, taxonomie

FICTIF = True


def test_les_categories_de_plainte_du_contrat_sont_celles_de_la_taxonomie_de_m1():
    assert frozenset(taxonomie.CATEGORIES_SIGNAL_PLAINTE) == ca.CATEGORIES_PLAINTE


def test_aucun_lecteur_prive_ne_publie_encore_capacite_depenses_ni_plaintes_structurees():
    """Le port privé de M9 (liste blanche) ne contient aucun outil attendu : l'absence est constatée, non déclarée.

    L'égalité entre ce port et le catalogue de M9 est déjà prouvée par ``tests/test_lecteurs_m9.py``.
    """
    autorisees = {outil for outils in lecteurs_m9.LECTURES_AUTORISEES.values() for outil in outils}
    for domaine in ("capacite_equipe", "depenses_marketing", "plaintes_structurees"):
        assert ca.CONTRATS[domaine]["outil_attendu"] not in autorisees, domaine
        assert ca.CONTRATS[domaine]["lecture_id"] not in cat.PAR_ID, domaine
