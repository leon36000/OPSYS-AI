"""Métriques déterministes pour un banc de retrieval synthétique et borné."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any


class EvaluationInvalide(ValueError):
    """Le jeu de qrels ou le classement soumis ne respecte pas son contrat."""


_MAX_QUESTIONS = 200
_MAX_SOURCES = 500
_MAX_RESULTATS_PAR_QUESTION = 50
_MAX_QRELS_PAR_QUESTION = 100
_MAX_VERSION = 1_000_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_MODES = frozenset({"lexical", "double"})
_SPLITS = frozenset({"development", "holdout"})


def evaluer(jeu: Mapping[str, Any], resultats: Mapping[str, Sequence[str]], *, mode: str) -> dict[str, Any]:
    """Calcule Recall@5, P@5, MRR@10, nDCG@10 et forbidden-hit@10.

    ``resultats`` mappe chaque qid à une liste ordonnée d'identifiants de source.
    Les doublons sont supprimés en conservant leur premier rang. ``mode`` est
    une étiquette fournie explicitement par le banc appelant: lexical ou double.
    Cette mesure ne qualifie ni un modèle ni la fidélité d'une réponse.
    """
    questions, sources = _valider_jeu(jeu)
    if not isinstance(mode, str) or mode not in _MODES:
        raise EvaluationInvalide("mode doit être explicitement 'lexical' ou 'double'")
    if not isinstance(resultats, Mapping):
        raise EvaluationInvalide("resultats doit être une correspondance qid → classement")

    qids = {question["qid"] for question in questions}
    if set(resultats) != qids:
        raise EvaluationInvalide("les résultats doivent contenir exactement les qid du jeu")

    scores: dict[str, list[dict[str, float]]] = {"all": [], "development": [], "holdout": []}
    classements_ordonnes: dict[str, list[str]] = {}
    forbidden_par_qid: dict[str, bool] = {}
    for question in questions:
        qid = question["qid"]
        classement = resultats[qid]
        if isinstance(classement, (str, bytes)) or not isinstance(classement, Sequence):
            raise EvaluationInvalide(f"classement invalide pour {qid}")
        if len(classement) > _MAX_RESULTATS_PAR_QUESTION:
            raise EvaluationInvalide(f"classement trop long pour {qid}")

        uniques: list[str] = []
        vus: set[str] = set()
        for source_id in classement:
            _valider_id(source_id, "source de résultat")
            if source_id not in sources:
                raise EvaluationInvalide(f"source de résultat inconnue pour {qid}")
            if source_id not in vus:
                uniques.append(source_id)
                vus.add(source_id)
        classements_ordonnes[qid] = list(classement)

        grades = {item["source_id"]: item["grade"] for item in question["pertinents"]}
        pertinents = set(grades)
        top5 = uniques[:5]
        top10 = uniques[:10]
        rangs_pertinents = [
            (rang, grades[source_id])
            for rang, source_id in enumerate(top10, start=1)
            if source_id in pertinents
        ]
        recall = len(pertinents.intersection(top5)) / len(pertinents)
        precision = len(pertinents.intersection(top5)) / 5
        mrr = 1 / rangs_pertinents[0][0] if rangs_pertinents else 0.0
        dcg = sum((2**grade - 1) / math.log2(rang + 1) for rang, grade in rangs_pertinents)
        grades_ideaux = sorted(grades.values(), reverse=True)[:10]
        idcg = sum((2**grade - 1) / math.log2(rang + 1) for rang, grade in enumerate(grades_ideaux, start=1))
        ndcg = dcg / idcg if idcg else 0.0
        forbidden_par_qid[qid] = bool(set(top10).intersection(question["interdits"]))
        forbidden_hit = float(forbidden_par_qid[qid])
        score = {
            "recall_at_5": recall,
            "precision_at_5": precision,
            "mrr_at_10": mrr,
            "ndcg_at_10": ndcg,
            "forbidden_hit_rate_at_10": forbidden_hit,
        }
        scores["all"].append(score)
        scores[question["split"]].append(score)

    return {
        "jeu_id": jeu["jeu_id"],
        "version": jeu["version"],
        "corpus_sha256": jeu["corpus"]["sha256"],
        "qrels_sha256": _sha256_canonique(questions),
        "classements_sha256": _sha256_canonique(
            {qid: classements_ordonnes[qid] for qid in sorted(classements_ordonnes)}
        ),
        "mode": mode,
        "question_count": len(questions),
        "forbidden_hits_by_qid": forbidden_par_qid,
        "interpretation": (
            "mesure de ranking du banc; ne qualifie ni modèle ni fidélité des réponses "
            "et ne prouve pas une autorisation d'accès à un sujet"
        ),
        "metrics": {split: _moyennes(values) for split, values in scores.items()},
    }


def _valider_jeu(jeu: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], set[str]]:
    if not isinstance(jeu, Mapping) or jeu.get("fictif") is not True:
        raise EvaluationInvalide("le jeu doit déclarer fictif=true")
    if set(jeu) - {"fictif", "jeu_id", "version", "proprietaire", "autorisation", "corpus", "sources", "questions"}:
        raise EvaluationInvalide("champ inconnu dans le manifeste du jeu")
    if not _texte_borne(jeu.get("jeu_id"), 96):
        raise EvaluationInvalide("jeu_id invalide")
    if not _texte_borne(jeu.get("proprietaire"), 160) or not _texte_borne(jeu.get("autorisation"), 512):
        raise EvaluationInvalide("propriétaire ou autorisation du jeu invalide")
    version = jeu.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= _MAX_VERSION:
        raise EvaluationInvalide("version invalide")
    corpus = jeu.get("corpus")
    if (
        not isinstance(corpus, Mapping)
        or not isinstance(corpus.get("sha256"), str)
        or not _SHA256.fullmatch(corpus["sha256"])
    ):
        raise EvaluationInvalide("empreinte SHA-256 du corpus invalide")
    if set(corpus) - {"chemin", "sha256"} or not _texte_borne(corpus.get("chemin"), 256):
        raise EvaluationInvalide("référence du corpus invalide")

    sources_liste = jeu.get("sources")
    if not isinstance(sources_liste, list) or not 1 <= len(sources_liste) <= _MAX_SOURCES:
        raise EvaluationInvalide("nombre de sources hors limites")
    sources: set[str] = set()
    for source_id in sources_liste:
        _valider_id(source_id, "source du jeu")
        if source_id in sources:
            raise EvaluationInvalide("source dupliquée dans le jeu")
        sources.add(source_id)

    questions = jeu.get("questions")
    if not isinstance(questions, list) or not 1 <= len(questions) <= _MAX_QUESTIONS:
        raise EvaluationInvalide("nombre de questions hors limites")
    qids: set[str] = set()
    splits_par_famille: dict[str, str] = {}
    for question in questions:
        if not isinstance(question, Mapping):
            raise EvaluationInvalide("entrée de question invalide")
        if set(question) - {"qid", "famille", "split", "question", "pertinents", "interdits"}:
            raise EvaluationInvalide("champ inconnu dans les qrels")
        qid = question.get("qid")
        famille = question.get("famille")
        split = question.get("split")
        _valider_id(qid, "qid")
        _valider_id(famille, "famille")
        if qid in qids:
            raise EvaluationInvalide("qid dupliqué")
        qids.add(qid)
        if not isinstance(split, str) or split not in _SPLITS:
            raise EvaluationInvalide("split inconnu")
        split_precedent = splits_par_famille.setdefault(famille, split)
        if split_precedent != split:
            raise EvaluationInvalide("une famille de questions traverse plusieurs splits")
        texte = question.get("question")
        if not _texte_borne(texte, 1000):
            raise EvaluationInvalide(f"texte de question invalide pour {qid}")

        pertinents = question.get("pertinents")
        interdits = question.get("interdits")
        if not isinstance(pertinents, list) or not 1 <= len(pertinents) <= _MAX_QRELS_PAR_QUESTION:
            raise EvaluationInvalide(f"qrels pertinents invalides pour {qid}")
        if not isinstance(interdits, list) or len(interdits) > _MAX_QRELS_PAR_QUESTION:
            raise EvaluationInvalide(f"qrels interdits invalides pour {qid}")
        ids_pertinents: set[str] = set()
        for item in pertinents:
            if not isinstance(item, Mapping):
                raise EvaluationInvalide(f"grade invalide pour {qid}")
            if set(item) != {"source_id", "grade"}:
                raise EvaluationInvalide(f"forme de grade invalide pour {qid}")
            source_id = item.get("source_id")
            grade = item.get("grade")
            _valider_id(source_id, "source pertinente")
            if source_id not in sources or source_id in ids_pertinents:
                raise EvaluationInvalide(f"source pertinente inconnue ou dupliquée pour {qid}")
            if isinstance(grade, bool) or not isinstance(grade, int) or grade not in (1, 2):
                raise EvaluationInvalide(f"grade doit être 1 ou 2 pour {qid}")
            ids_pertinents.add(source_id)
        ids_interdits: set[str] = set()
        for source_id in interdits:
            _valider_id(source_id, "source interdite")
            if source_id not in sources or source_id in ids_interdits:
                raise EvaluationInvalide(f"source interdite inconnue ou dupliquée pour {qid}")
            ids_interdits.add(source_id)
        if ids_pertinents.intersection(ids_interdits):
            raise EvaluationInvalide(f"source à la fois pertinente et interdite pour {qid}")
    return questions, sources


def _valider_id(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise EvaluationInvalide(f"{label} invalide")


def _texte_borne(value: Any, maximum: int) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= maximum and value.strip() == value


def _moyennes(scores: list[dict[str, float]]) -> dict[str, float]:
    if not scores:
        return {key: 0.0 for key in _METRIC_KEYS}
    return {key: sum(score[key] for score in scores) / len(scores) for key in _METRIC_KEYS}


def _sha256_canonique(value: Any) -> str:
    contenu = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(contenu).hexdigest()


_METRIC_KEYS = (
    "recall_at_5",
    "precision_at_5",
    "mrr_at_10",
    "ndcg_at_10",
    "forbidden_hit_rate_at_10",
)
