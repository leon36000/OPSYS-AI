"""Priorisation et allocation M9.11 : rangs refaisables à la main, capacité citée, aucun arbitrage (fictif)."""

from __future__ import annotations

import copy

import pytest
from m9_strategic_intelligence import priorisation

FICTIF = True


def cand(id_, impact, urgence, confiance, effort=None, **extra):
    base = {"id": id_, "libelle": f"Piste fictive {id_}", "origine": "DECLAREE_PAR_LA_PERSONNE",
            "impact": impact, "urgence": urgence, "confiance": confiance}  # fmt: skip
    if effort is not None:
        base["effort_jours_personnes"] = effort
    return {**base, **extra}


def test_score_refait_a_la_main_et_ordre():
    # A : 3*5 + 2*1 + 1*1 = 18 ; B : 3*4 + 2*5 + 1*3 = 25 ; C : 3*2 + 2*2 + 1*5 = 15
    classes = priorisation.classer([cand("A", 5, 1, 1), cand("B", 4, 5, 3), cand("C", 2, 2, 5)])
    assert [(c["id"], c["score"], c["rang"]) for c in classes] == [("B", 25, 1), ("A", 18, 2), ("C", 15, 3)]
    assert classes[0]["contributions"] == {"impact": 12, "urgence": 10, "confiance": 3}


def test_egalite_departagee_par_effort_puis_identifiant():
    classes = priorisation.classer(
        [cand("Z", 3, 3, 3, "2"), cand("Y", 3, 3, 3, "5"), cand("X", 3, 3, 3, "2"), cand("W", 3, 3, 3)]
    )
    assert [c["id"] for c in classes] == ["X", "Z", "Y", "W"]  # effort inconnu en dernier


def test_sans_capacite_aucune_allocation_mais_classement_rendu():
    res = priorisation.allouer([cand("A", 5, 5, 5, "3")], capacite=None)
    assert res["allocation"]["statut"] == "CAPACITE_INCONNUE"
    assert res["retenus"] == [] and res["non_retenus"] == [{"id": "A", "raison": "CAPACITE_INCONNUE"}]
    assert res["classement"][0]["rang"] == 1 and "personnes_affectees" not in res["allocation"]


def test_allocation_gloutonne_et_raisons_de_non_retenue():
    res = priorisation.allouer(
        [cand("A", 5, 5, 5, "4"), cand("B", 4, 4, 4, "5"), cand("C", 3, 3, 3, "1"), cand("D", 2, 2, 2)],
        capacite="6", source_capacite="m4.cedule_semaine#0:p0.x",
    )  # fmt: skip
    assert [r["id"] for r in res["retenus"]] == ["A", "C"]
    assert {n["id"]: n["raison"] for n in res["non_retenus"]} == {"B": "CAPACITE_INSUFFISANTE", "D": "EFFORT_INCONNU"}
    alloc = res["allocation"]
    assert (alloc["capacite"], alloc["utilisee"], alloc["restante"]) == ("6", "5", "1")
    assert alloc["personnes_affectees"] == [] and alloc["source_capacite"] == "m4.cedule_semaine#0:p0.x"
    assert res["alternatives"] == []  # B (5) ne tient pas même en retirant C (1) : 1 + 1 < 5


def test_alternative_seulement_si_elle_tient():
    res = priorisation.allouer(
        [cand("A", 5, 5, 5, "3"), cand("B", 4, 4, 4, "4"), cand("C", 1, 1, 1, "3.5"), cand("D", 1, 1, 1, "5")],
        capacite="7",
    )
    assert [r["id"] for r in res["retenus"]] == ["A", "B"]
    # C (3.5) tient si B (4) est retiré ; D (5) ne tient pas : aucune alternative inventée pour lui.
    assert res["alternatives"] == [{"retirer": "B", "ajouter": "C", "capacite_restante_apres": "0.5"}]


def test_dependance_retenue_d_abord_puis_dependant_revu():
    res = priorisation.allouer([cand("A", 5, 5, 5, "2", depend_de=["B"]), cand("B", 4, 4, 4, "2")], capacite="10")
    assert [r["id"] for r in res["retenus"]] == ["B", "A"] and res["non_retenus"] == []


def test_dependance_jamais_satisfaite_si_la_capacite_manque():
    res = priorisation.allouer([cand("A", 5, 5, 5, "2", depend_de=["B"]), cand("B", 4, 4, 4, "9")], capacite="3")
    assert res["retenus"] == []
    assert {n["id"]: n["raison"] for n in res["non_retenus"]} == {
        "A": "DEPENDANCE_NON_SATISFAITE",
        "B": "CAPACITE_INSUFFISANTE",
    }


def test_conflit_nomme_jamais_arbitre_par_le_code_des_deux_voies():
    res = priorisation.allouer(
        [cand("A", 5, 5, 5, "1", incompatible_avec=["B"]), cand("B", 4, 4, 4, "1")], capacite="10"
    )
    assert res["conflits"] == [{"entre": ["A", "B"], "meilleur_rang": 1, "arbitrage": "HUMAIN_REQUIS",
                                "voies": ["retenir A sans B", "retenir B sans A"]}]  # fmt: skip
    # Le meilleur rang est retenu à titre PROPOSÉ ; l'autre est exclu sans être décidé : le conflit reste ouvert.
    assert [n["raison"] for n in res["non_retenus"]] == ["EXCLU_PAR_CONFLIT"]


def test_validation_humaine_conservee_meme_retenue():
    res = priorisation.allouer([cand("A", 5, 5, 5, "1", validation="depense_reelle")], capacite="3")
    assert res["retenus"] == [{"id": "A", "validation": "depense_reelle", "mandataire": "Nathan",
                              "statut": "VALIDATION_HUMAINE_REQUISE"}]  # fmt: skip


@pytest.mark.parametrize("capacite", ["0", "0.00", "-1", "abc", "1e3", "1,5", " 3"])
def test_capacite_invalide_ou_nulle_refusee(capacite):
    with pytest.raises(ValueError, match="REJ-PRIORITE"):
        priorisation.allouer([cand("A", 1, 1, 1, "1")], capacite=capacite)


@pytest.mark.parametrize("defaut", [
    {"impact": 0}, {"impact": 6}, {"urgence": True}, {"confiance": "3"}, {"confiance": 2.5},
    {"origine": "MODELE"}, {"effort_jours_personnes": "-2"}, {"effort_jours_personnes": 3}, {"id": "a b"},
    {"libelle": " "}, {"validation": "inconnue"}, {"depend_de": "B"}, {"refs": ["x y"]},
])  # fmt: skip
def test_candidat_hors_bornes_refuse(defaut):
    with pytest.raises(ValueError, match="REJ-PRIORITE"):
        priorisation.classer([{**cand("A", 3, 3, 3, "1"), **defaut}])


def test_champ_inconnu_doublon_reference_inconnue_ou_circulaire():
    for mauvais in (
        [{**cand("A", 3, 3, 3), "cout": "5"}],
        [cand("A", 3, 3, 3), cand("A", 2, 2, 2)],
        [cand("A", 3, 3, 3, depend_de=["Z"])],
        [cand("A", 3, 3, 3, depend_de=["A"])],
        [],
        "A",
    ):
        with pytest.raises(ValueError, match="REJ-PRIORITE-CANDIDAT"):
            priorisation.classer(mauvais)
    with pytest.raises(ValueError, match="REJ-PRIORITE-CANDIDAT"):
        priorisation.classer([cand(f"c{i}", 1, 1, 1) for i in range(priorisation.MAX_CANDIDATS + 1)])


def test_deterministe_non_mutant_et_identifiant_lie_au_contenu():
    entrees = [cand("A", 5, 1, 1, "2"), cand("B", 4, 5, 3, "1")]
    avant = copy.deepcopy(entrees)
    un = priorisation.allouer(entrees, capacite="3")
    deux = priorisation.allouer(list(reversed(entrees)), capacite="3")
    assert entrees == avant
    assert un == deux and len(un["priorisation_id"]) == 64
    autre = priorisation.allouer(entrees, capacite="2")
    assert autre["priorisation_id"] != un["priorisation_id"]
    assert un["politique"]["version"] == priorisation.VERSION
