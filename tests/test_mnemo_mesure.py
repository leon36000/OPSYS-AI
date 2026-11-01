"""Harnais de mesure de Mnémo : le corpus livré, ses métriques et ses limites.

Le corpus (`departments/m10-memoire/evals/soi-graphe.v1.yaml`) est rédigé à la main avant exécution. Les tests
vérifient les
métriques (exactitude, rappel, précision, abstentions), la concordance des deux moteurs, le témoin « un saut » et le
rejet
des corpus mal formés. Aucun modèle : les chiffres valident le moteur, pas un agent.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path

import pytest
from m10_memoire.registre import Registre

from opsys.mnemo import codes, mesure
from opsys.mnemo.codes import ErreurMnemo
from opsys.mnemo.graphe import GrapheMemoire, GrapheSql

FICTIF = True
CORPUS = Path(__file__).resolve().parents[1] / "departments" / "m10-memoire" / "evals" / "soi-graphe.v1.yaml"


def garde_vide(cible, texte):
    return {"departement": cible, "regressions": [], "bloquants_nouveaux": []}


@pytest.fixture(scope="module")
def corpus():
    return mesure.charger_corpus(CORPUS.read_text(encoding="utf-8"))


@pytest.fixture
def rapport(session, corpus):
    with session() as cnx:
        return mesure.executer(corpus, GrapheSql(cnx), garde=garde_vide, registre_factory=Registre)


def test_le_corpus_est_fictif_borne_et_couvre_toutes_les_categories(corpus):
    assert corpus["fictif"] is True and len(corpus["questions"]) >= 30
    categories = {q["categorie"] for q in corpus["questions"]}
    assert categories == set(mesure.CATEGORIES)
    assert sum(1 for q in corpus["questions"] if q["categorie"] == "negatif") >= 6
    assert len({q["id"] for q in corpus["questions"]}) == len(corpus["questions"])
    brut = CORPUS.read_text(encoding="utf-8")
    assert "@" not in brut.replace("bus:", "")  # aucune adresse courriel, aucune coordonnée


def test_le_moteur_sql_repond_exactement_a_toutes_les_questions(rapport):
    g = rapport["graphe"]["modes"]["graphe"]["global"]
    assert g["exactitude"] == "1.0000" and g["exactes"] == g["questions"], rapport["graphe"]["modes"]["graphe"][
        "echecs"
    ]
    assert g["rappel_moyen"] == "1.0000" and g["precision_moyenne"] == "1.0000"
    assert g["abstentions_correctes"] == g["abstentions_attendues"] == 2 and g["reponses_inventees"] == 0
    assert rapport["graphe"]["moteurs_concordent"] is True and rapport["modele_reel"] is False


def test_le_temoin_un_saut_montre_ce_que_le_multi_sauts_apporte(rapport):
    graphe = rapport["graphe"]["modes"]["graphe"]
    un_saut = rapport["graphe"]["modes"]["un_saut"]
    assert Decimal(un_saut["global"]["exactitude"]) < Decimal(graphe["global"]["exactitude"])
    assert un_saut["par_categorie"]["multi_sauts"]["exactitude"] == "0.0000" or Decimal(
        un_saut["par_categorie"]["multi_sauts"]["exactitude"]
    ) < Decimal("0.3")
    assert Decimal(un_saut["par_categorie"]["un_saut"]["exactitude"]) > Decimal(
        "0.5"
    )  # là où un saut suffit, il suffit
    assert graphe["par_categorie"]["multi_sauts"]["exactitude"] == "1.0000"


def test_les_cas_de_garde_des_lecons_sont_tous_conformes(rapport):
    lc = rapport["lecons"]
    assert lc["conformes"] == lc["cas"] >= 7, [r for r in lc["resultats"] if not r["conforme"]]


def test_le_banc_attrape_un_moteur_defectueux(corpus):
    """Un moteur qui ignore la validité dans le temps ou qui compte les brouillons doit échouer au banc (pas de banc
    complaisant)."""

    class SansValidite(GrapheMemoire):
        def _incidentes(self, ids, date, inclure_brouillons):
            return super()._incidentes(ids, "9999-12-31", inclure_brouillons)

    class AvecBrouillons(GrapheMemoire):
        def _incidentes(self, ids, date, inclure_brouillons):
            return super()._incidentes(ids, date, True)

    for classe, categories in ((SansValidite, {"temporel"}), (AvecBrouillons, {"negatif"})):
        r = mesure.mesurer_graphe(corpus, classe(), modes=("graphe",))["modes"]["graphe"]
        echoues = {e["id"] for e in r["echecs"]}
        assert echoues and any(q["id"] in echoues and q["categorie"] in categories for q in corpus["questions"]), classe


def test_les_metriques_precision_et_rappel_se_calculent_sur_les_ensembles():
    note = mesure._noter({"entites": ["a", "b", "c", "d"]}, {"entites": ["a", "b", "x"]})
    assert (
        note["rappel"] == Decimal(2) / Decimal(4) and note["precision"] == Decimal(2) / Decimal(3) and not note["exact"]
    )
    assert mesure._noter({"entites": []}, {"entites": []})["exact"] is True
    inv = mesure._noter({"abstention": True}, {"entites": ["a"]})
    assert inv["reponse_inventee"] and not inv["exact"]
    assert mesure._noter({"entites": ["a"]}, {"abstention": True})["abstention_a_tort"]


@pytest.mark.parametrize(
    "modif",
    [
        lambda c: c.update(schema="autre"),
        lambda c: c.update(fictif=False),
        lambda c: c["questions"].append(c["questions"][0]),
        lambda c: c["graphe"]["aretes"].append(c["graphe"]["aretes"][0]),
        lambda c: c["graphe"]["aretes"][0].update(vers="propriete:inconnue"),
        lambda c: c["graphe"]["aretes"][0].update(etat="fermee"),
        lambda c: c["questions"][0]["plan"].update(operation="sql_libre"),
        lambda c: c["questions"][0].update(categorie="autre"),
        lambda c: c["questions"][0]["plan"]["etapes"][0].update(arete="inventee"),
        lambda c: c["questions"][0]["plan"].update(depart="client:fantome"),
    ],
)
def test_un_corpus_mal_forme_est_refuse(corpus, modif):
    mauvais = copy.deepcopy(corpus)
    modif(mauvais)
    with pytest.raises(ErreurMnemo, match=codes.ENTREE_INVALIDE):
        mesure.charger_corpus(mauvais)


def test_le_rapport_markdown_dit_ses_limites(rapport):
    texte = mesure.markdown(rapport)
    assert "Aucun modèle de langage" in texte and "concordants : **oui**" in texte and "un_saut" in texte
    assert "| graphe |" in texte
