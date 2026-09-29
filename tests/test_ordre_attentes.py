"""Ordre des attentes du propriétaire (console, briefing, « À voir ») : le niveau le plus élevé d'abord.

Constat de l'E2E contre le vrai core (T1.5-f) : triées par ancienneté seule, une revue N4 avec écart critique
passait derrière des rappels plus anciens (« seuil à configurer ») et tombait hors de la première page.
"""

from __future__ import annotations

from opsys.approbations import ordre_attente


def _attente(niveau, depuis, ident="a", departement="m04-field-ops", type_="t"):
    return {"niveau": niveau, "depuis": depuis, "id": ident, "departement": departement, "type": type_}


def test_le_niveau_le_plus_eleve_passe_devant_le_plus_ancien():
    rappel_ancien = _attente("N3", "2026-09-01T08:00:00-04:00", "rappel")
    revue_recente = _attente("N4", "2026-09-29T11:00:00-04:00", "revue")
    assert sorted([rappel_ancien, revue_recente], key=ordre_attente) == [revue_recente, rappel_ancien]


def test_a_niveau_egal_la_plus_ancienne_d_abord():
    vieille = _attente("N4", "2026-09-01T08:00:00-04:00", "b")
    recente = _attente("N4", "2026-09-29T08:00:00-04:00", "a")
    assert sorted([recente, vieille], key=ordre_attente) == [vieille, recente]


def test_un_niveau_illisible_n_est_jamais_enterre():
    illisible = _attente("??", "2026-09-29T08:00:00-04:00", "x")
    absent = {"depuis": "2026-09-29T09:00:00-04:00", "id": "y", "departement": "m05-financecore", "type": "t"}
    n5 = _attente("N5", "2026-09-01T08:00:00-04:00", "z")
    ordre = sorted([n5, absent, illisible], key=ordre_attente)
    assert ordre[:2] == [illisible, absent]
    assert ordre[2] == n5
