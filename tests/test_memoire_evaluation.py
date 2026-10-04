import hashlib
import json
import math
from pathlib import Path

import pytest

from opsys.memoire.evaluation import EvaluationInvalide, evaluer

ROOT = Path(__file__).parent
JEU_PATH = ROOT / "fixtures/memoire/evaluation-v1.json"
CORPUS_PATH = ROOT / "fixtures/memoire/jeu_or_fr.json"


def _charger_jeu():
    return json.loads(JEU_PATH.read_text(encoding="utf-8"))


def _mini_jeu():
    return {
        "fictif": True,
        "jeu_id": "oracle-manuel",
        "version": 1,
        "proprietaire": "jeu synthétique de test",
        "autorisation": "créé pour tests seulement",
        "corpus": {"chemin": "synthetique", "sha256": "a" * 64},
        "sources": ["A", "B", "C", "F", "X"],
        "questions": [
            {
                "qid": "q1",
                "famille": "fam-a",
                "split": "development",
                "question": "question synthétique A",
                "pertinents": [{"source_id": "A", "grade": 2}, {"source_id": "B", "grade": 1}],
                "interdits": ["F"],
            },
            {
                "qid": "q2",
                "famille": "fam-b",
                "split": "holdout",
                "question": "question synthétique B",
                "pertinents": [{"source_id": "C", "grade": 2}],
                "interdits": [],
            },
        ],
    }


def test_fixture_est_fictif_hash_corpus_et_splits_sans_fuite_de_famille():
    jeu = _charger_jeu()
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    hash_corpus = hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest()

    assert jeu["fictif"] is True
    assert jeu["corpus"]["sha256"] == hash_corpus
    assert jeu["sources"] == sorted(fragment["cle"] for fragment in corpus["fragments"])
    assert {q["split"] for q in jeu["questions"]} == {"development", "holdout"}
    assert len(jeu["questions"]) == len(corpus["questions"])
    assert all(q["pertinents"] and q["interdits"] for q in jeu["questions"])

    splits_par_famille = {}
    for question in jeu["questions"]:
        splits_par_famille.setdefault(question["famille"], set()).add(question["split"])
        ids_pertinents = {r["source_id"] for r in question["pertinents"]}
        ids_interdits = set(question["interdits"])
        assert ids_pertinents | ids_interdits <= set(jeu["sources"])
        assert not ids_pertinents.intersection(ids_interdits)
    assert all(len(splits) == 1 for splits in splits_par_famille.values())
    rapport = evaluer(jeu, {q["qid"]: [] for q in jeu["questions"]}, mode="double")
    assert rapport["question_count"] == 9
    assert rapport["metrics"]["holdout"]["recall_at_5"] == 0.0


def test_oracle_manuel_moyennes_et_deduplication_par_source():
    jeu = _mini_jeu()
    resultats = {"q1": ["X", "A", "A", "B", "F"], "q2": ["C"]}

    rapport = evaluer(jeu, resultats, mode="lexical")
    attendu_ndcg_q1 = (3 / math.log2(3) + 1 / 2) / (3 + 1 / math.log2(3))
    assert rapport["mode"] == "lexical"
    assert rapport["metrics"]["all"] == pytest.approx(
        {
            "recall_at_5": 1.0,
            "precision_at_5": 0.3,
            "mrr_at_10": 0.75,
            "ndcg_at_10": (attendu_ndcg_q1 + 1.0) / 2,
            "forbidden_hit_rate_at_10": 0.5,
        }
    )
    assert rapport["metrics"]["development"]["precision_at_5"] == pytest.approx(0.4)
    assert rapport["metrics"]["holdout"]["mrr_at_10"] == pytest.approx(1.0)


def test_forbidden_hit_est_signale_et_mode_double_ne_qualifie_pas_un_modele():
    jeu = _mini_jeu()
    rapport = evaluer(jeu, {"q1": ["F", "A"], "q2": []}, mode="double")

    assert rapport["mode"] == "double"
    assert rapport["metrics"]["all"]["forbidden_hit_rate_at_10"] == pytest.approx(0.5)
    assert rapport["forbidden_hits_by_qid"] == {"q1": True, "q2": False}
    assert "model" not in rapport and "semantic" not in rapport
    assert "ne prouve pas une autorisation d'accès à un sujet" in rapport["interpretation"]


def test_empreintes_identifient_corpus_qrels_et_classements_ordonnes():
    jeu = _mini_jeu()
    resultats = {"q1": ["X", "A", "B"], "q2": ["C"]}
    original = evaluer(jeu, resultats, mode="lexical")
    identique = evaluer(_mini_jeu(), {"q1": ["X", "A", "B"], "q2": ["C"]}, mode="lexical")
    assert original["corpus_sha256"] == "a" * 64
    assert original["qrels_sha256"] == identique["qrels_sha256"]
    assert original["classements_sha256"] == identique["classements_sha256"]

    qrels_changes = _mini_jeu()
    qrels_changes["questions"][0]["pertinents"][1]["grade"] = 2
    qrels_modifies = evaluer(qrels_changes, resultats, mode="lexical")
    assert qrels_modifies["qrels_sha256"] != original["qrels_sha256"]
    assert qrels_modifies["classements_sha256"] == original["classements_sha256"]

    rang_changes = {"q1": ["A", "X", "B"], "q2": ["C"]}
    rang_modifie = evaluer(jeu, rang_changes, mode="lexical")
    assert rang_modifie["qrels_sha256"] == original["qrels_sha256"]
    assert rang_modifie["classements_sha256"] != original["classements_sha256"]


@pytest.mark.parametrize("grade", [True, False, 0, -1, 3, float("nan"), float("inf"), "2"])
def test_grade_invalide_est_refuse(grade):
    jeu = _mini_jeu()
    jeu["questions"][0]["pertinents"][0]["grade"] = grade

    with pytest.raises(EvaluationInvalide):
        evaluer(jeu, {"q1": [], "q2": []}, mode="lexical")


def test_ids_invalides_qrels_rejeu_et_mode_inconnu_sont_refuses():
    jeu = _mini_jeu()
    jeu["questions"][0]["pertinents"][0]["source_id"] = "bad id"
    with pytest.raises(EvaluationInvalide):
        evaluer(jeu, {"q1": [], "q2": []}, mode="lexical")

    jeu = _mini_jeu()
    with pytest.raises(EvaluationInvalide):
        evaluer(jeu, {"q1": ["not-in-corpus"], "q2": []}, mode="lexical")
    with pytest.raises(EvaluationInvalide):
        evaluer(jeu, {"q1": [], "q2": []}, mode="semantic")
    with pytest.raises(EvaluationInvalide):
        evaluer(jeu, {"q1": [], "q2": []}, mode=[])
    with pytest.raises(EvaluationInvalide):
        evaluer(jeu, {"q1": []}, mode="lexical")


def test_qrels_incoherents_et_famille_partagee_entre_splits_sont_refuses():
    jeu = _mini_jeu()
    jeu["questions"][1]["famille"] = "fam-a"
    with pytest.raises(EvaluationInvalide):
        evaluer(jeu, {"q1": [], "q2": []}, mode="lexical")

    jeu = _mini_jeu()
    jeu["version"] = True
    with pytest.raises(EvaluationInvalide):
        evaluer(jeu, {"q1": [], "q2": []}, mode="lexical")

    jeu = _mini_jeu()
    jeu["version"] = 1_000_001
    with pytest.raises(EvaluationInvalide):
        evaluer(jeu, {"q1": [], "q2": []}, mode="lexical")

    jeu = _mini_jeu()
    jeu["questions"][0]["interdits"] = ["A"]
    with pytest.raises(EvaluationInvalide):
        evaluer(jeu, {"q1": [], "q2": []}, mode="lexical")


def test_entrees_et_volumes_sont_bornes():
    jeu = _mini_jeu()
    with pytest.raises(EvaluationInvalide):
        evaluer(jeu, {"q1": ["A"] * 51, "q2": []}, mode="lexical")

    jeu["questions"] *= 101
    with pytest.raises(EvaluationInvalide):
        evaluer(jeu, {"q1": [], "q2": []}, mode="lexical")
