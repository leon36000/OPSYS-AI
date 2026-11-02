"""Console d'administration du planificateur : deux admins qui fixent le mode d'un exécuteur AU MÊME INSTANT, en vrais
processus, sur SQLite ET sur PostgreSQL 17 réel.

Sous SQLite, `BEGIN IMMEDIATE` sérialise les écrivains : le second admin lit l'état laissé par le premier. Sous
PostgreSQL (READ COMMITTED), deux admins lisaient la MÊME révision : (1) à la première activation, les deux insèrent la
ligne et le perdant reçoit une erreur d'intégrité brute ; (2) ensuite, le `UPDATE … WHERE revision = ?` du perdant
ne touche
aucune ligne SANS qu'on le voie, et le journal append-only raconte tout de même un changement de mode qui n'a pas eu
lieu.
Le geste prend maintenant le verrou d'écriture de la console (comme tout écrivain humain de la console) et refuse
typiquement (`REVISION_PERIMEE`) si la ligne a changé sous lui. Données fictives.
"""

from __future__ import annotations

import planif_qa as pq
import pytest
from pg_concurrence import lancer
from pg_constats import activer_executeur
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)

from opsys import stockage
from opsys.connecteurs_planification import etat, journal

FICTIF = True
EXECUTEUR = "m8.entrepot"


@pytest.fixture
def p(url_base, tmp_path, monkeypatch):  # noqa: F811
    mon = pq.monter(tmp_path, monkeypatch, (), url=url_base)
    yield mon
    stockage.liberer()


def _modes() -> list[dict]:
    with stockage.transaction() as cnx:
        return [j for j in journal.lire(cnx, EXECUTEUR, limite=100) if j["evenement"] == "mode"]


def test_deux_admins_qui_activent_la_premiere_fois_en_meme_temps_un_seul_cree_la_ligne_l_autre_la_modifie(p):
    issues = lancer(activer_executeur, [(EXECUTEUR, "ombre", 60, "nathan"), (EXECUTEUR, "actif", 120, "nathan")],
                    delai_s=300)
    assert [i for i in issues if i[0] == "PANNE"] == [], issues  # jamais une erreur d'intégrité brute
    assert all(i[0] == "ok" for i in issues), issues
    assert sorted(i[2] for i in issues) == [1, 2]  # deux révisions distinctes, dans l'ordre de passage
    with stockage.transaction() as cnx:
        ligne = etat.ligne(cnx, EXECUTEUR)
    assert ligne["revision"] == 2
    modes = _modes()
    assert len(modes) == 2 and modes[0]["details"]["revision"] == 2  # le journal raconte exactement ce qui est arrivé
    assert modes[0]["mode"] == ligne["mode"] and modes[0]["details"]["intervalle_s"] == ligne["intervalle_s"]


def test_n_admins_qui_changent_le_mode_en_meme_temps_chaque_changement_est_une_revision_et_le_journal_dit_vrai(p):
    p.activer(EXECUTEUR, "ombre", intervalle_s=60)
    gestes = [(EXECUTEUR, mode, 60 + 30 * i, "nathan") for i, mode in enumerate(("actif", "ombre", "actif", "ombre"))]
    issues = lancer(activer_executeur, gestes, delai_s=300)
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    assert all(i[0] == "ok" for i in issues), issues
    assert sorted(i[2] for i in issues) == [2, 3, 4, 5]  # quatre révisions, aucune perdue en silence
    with stockage.transaction() as cnx:
        ligne = etat.ligne(cnx, EXECUTEUR)
    assert ligne["revision"] == 5
    derniere = _modes()[0]
    assert derniere["details"]["revision"] == 5
    assert (derniere["mode"], derniere["details"]["intervalle_s"]) == (ligne["mode"], ligne["intervalle_s"])
