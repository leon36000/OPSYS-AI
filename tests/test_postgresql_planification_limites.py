"""Planificateur durable : les LIMITES DE TAILLE des colonnes, sur SQLite ET sur PostgreSQL 17 réel.

SQLite n'impose aucune longueur à `VARCHAR(n)` ; PostgreSQL la refuse (`value too long for type character varying`). Un
code de refus rendu par un outil de département peut dépasser la colonne `dernier_code` (64) : sur PostgreSQL,
l'écriture
de fin de passage levait, le tour entier s'interrompait et les exécuteurs suivants ne passaient pas. Le code est
maintenant
tronqué à la taille de la colonne, comme l'est déjà son jumeau du journal. Données fictives.
"""

from __future__ import annotations

import planif_qa as pq
import pytest
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)

from opsys import stockage
from opsys.connecteurs_planification import journal
from opsys.connecteurs_planification.planificateur import RefusExecuteur

FICTIF = True
CODE_LONG = "REJ-PLAN-" + "-".join(["LONG"] * 30)  # 9 + 30*4 + 29 = 158 caractères


class _Bavard:
    """Exécuteur de test : rend un code de 158 caractères, comme un outil au verdict démesuré."""

    nom = "m8.entrepot"

    def ressources(self, ctx):
        return ["r"]

    def cle_bail(self, ressource):
        return "essai.limites:" + ressource

    def constater(self, ressource, ctx):
        return {}

    def traiter(self, ressource, ctx, bail):
        return {"traites": 1, "code": CODE_LONG}


class _Refuse(_Bavard):
    nom = "peremptions.balayage"

    def traiter(self, ressource, ctx, bail):
        raise RefusExecuteur(CODE_LONG)


class _Suivant(_Bavard):
    nom = "m10.mnemo"

    def traiter(self, ressource, ctx, bail):
        return {"traites": 1}


@pytest.fixture
def p(url_base, tmp_path, monkeypatch):  # noqa: F811
    mon = pq.monter(tmp_path, monkeypatch, (), url=url_base)
    yield mon
    stockage.liberer()


@pytest.mark.parametrize("executeur", [_Bavard, _Refuse])
def test_un_code_de_refus_demesure_est_tronque_et_le_tour_continue(p, executeur):
    for nom in (executeur.nom, _Suivant.nom):
        p.activer(nom, intervalle_s=30)
    resume = p.tour(avance=1, executeurs=[executeur(), _Suivant()])
    assert resume["executeurs"][_Suivant.nom]["statut"] == "ok", resume  # le suivant n'est pas empêché de passer
    ligne = p.ligne(executeur.nom)
    assert ligne["dernier_code"] == CODE_LONG[:64] and len(ligne["dernier_code"]) == 64
    with stockage.transaction() as cnx:
        passages = [j for j in journal.lire(cnx, executeur.nom) if j["evenement"] == "passage"]
    assert passages and passages[0]["code"] == CODE_LONG[:64]
