"""Tests de la liaison revue↔code↔prompt↔preuves (C01-004).

Contrat exact (task spec `tasks/C01-004.md`) :
- `verify_review(review: dict, evidence: dict, raw_response: bytes) ->
  ReviewVerdict` : vérifie qu'une revue scellée est RÉELLEMENT liée à
  l'evidence qu'elle prétend avoir examinée et à sa propre réponse brute
  — jamais une confiance aveugle au contenu déclaré par le reviewer.

Contrat de vérification (design de ce module, documenté ici) :
1. `review["commit"] == evidence["commit"]` et
   `review["tree"] == evidence["tree"]` (le reviewer a examiné le BON
   commit/tree, pas un autre).
2. `review["evidence_sha256"]` == hash canonique RECALCULÉ de `evidence`
   (le dict PASSÉ EN PARAMÈTRE, jamais une valeur déclarée non
   vérifiée) — canonique = `json.dumps(evidence, ensure_ascii=False,
   sort_keys=True, separators=(",", ":"))` encodé UTF-8, sha256 hex.
3. `review["prompt_sha256"]` est un SHA-256 hex64 bien formé (aucune
   source de prompt externe dans la signature — seule la FORME est
   vérifiable ici, jamais une valeur inventée qui ressemble à un hash
   sans en être un).
4. `review["raw_response_sha256"] == sha256(raw_response)` (le hash
   déclaré correspond aux OCTETS BRUTS réellement fournis, jamais une
   valeur non vérifiée).
5. `review["reviewer_id"] != evidence["implementer_id"]` (jamais
   d'auto-revue — un reviewer qui EST l'implémenteur de la tâche est
   structurellement invalide, indépendamment de tout hash).
6. `review["vendor"]` et `review["request_id"]` sont des chaînes NON
   VIDES (une revue sans identité de vendor ou sans identifiant de
   requête ne peut pas être tracée jusqu'à son appel réel).

`ReviewVerdict` : dataclass `{ok: bool, errors: list[str]}` — même forme
que `ReplayResult` (C01-003), convention établie de ce paquet.

Écrit par l'Orchestrateur AVANT toute implémentation (RED d'abord, TDD) —
le crew implémente `tools/proof/review_verifier.py` CONTRE ce fichier.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from tools.proof.review_verifier import ReviewVerdict, verify_review

HEX64_COMMIT = "1" * 64
HEX64_TREE = "2" * 64
HEX64_PROMPT = "3" * 64


def _canonique(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_texte(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def _evidence_valide() -> dict:
    return {
        "schema_version": "1.0",
        "task_id": "C01-004",
        "implementer_id": "claude-code-orchestrateur",
        "commit": HEX64_COMMIT,
        "tree": HEX64_TREE,
        "inputs_manifest": [{"path": "inputs/spec.md", "sha256": "a" * 64, "size": 10}],
        "outputs_manifest": [{"path": "outputs/module.py", "sha256": "b" * 64, "size": 20}],
        "commands": [],
    }


def _review_valide(evidence: dict, raw_response: bytes) -> dict:
    return {
        "reviewer_id": "DeepSeek-V4-Pro",
        "vendor": "deepseek",
        "request_id": "req-abc123",
        "commit": evidence["commit"],
        "tree": evidence["tree"],
        "evidence_sha256": _sha256_texte(_canonique(evidence)),
        "prompt_sha256": HEX64_PROMPT,
        "raw_response_sha256": hashlib.sha256(raw_response).hexdigest(),
        "verdict": "APPROVE",
    }


def test_lier_les_revues_au_code_au_prompt_et_aux_preuves_1():
    """Cas RED obligatoire : rejeter commit/tree/evidence/prompt hash
    divergent — chacune des 4 vérifications, altérée isolément, doit
    faire échouer verify_review (ok=False, erreur nommée)."""
    evidence = _evidence_valide()
    raw_response = b'{"verdict": "APPROVE"}'
    review_reference = _review_valide(evidence, raw_response)

    # Référence : tout intact -> ok.
    resultat = verify_review(review_reference, evidence, raw_response)
    assert resultat.ok, resultat.errors

    # Sous-cas COMMIT divergent.
    review = dict(review_reference)
    review["commit"] = "9" * 64
    resultat = verify_review(review, evidence, raw_response)
    assert not resultat.ok
    assert resultat.errors

    # Sous-cas TREE divergent.
    review = dict(review_reference)
    review["tree"] = "9" * 64
    resultat = verify_review(review, evidence, raw_response)
    assert not resultat.ok

    # Sous-cas EVIDENCE_SHA256 divergent (evidence dict modifié après
    # que la revue ait déclaré son hash -> le reviewer n'a PAS examiné
    # CE evidence exact).
    evidence_modifie = dict(evidence)
    evidence_modifie["task_id"] = "C01-999-substitue"
    resultat = verify_review(review_reference, evidence_modifie, raw_response)
    assert not resultat.ok

    # Sous-cas PROMPT_SHA256 mal formé (pas 64 hex).
    review = dict(review_reference)
    review["prompt_sha256"] = "pas-un-hash"
    resultat = verify_review(review, evidence, raw_response)
    assert not resultat.ok


def test_lier_les_revues_au_code_au_prompt_et_aux_preuves_2():
    """Cas RED obligatoire : rejeter reviewer identique à l'implémenteur
    — jamais d'auto-revue, indépendamment de la validité de tous les
    autres champs."""
    evidence = _evidence_valide()
    raw_response = b'{"verdict": "APPROVE"}'
    review = _review_valide(evidence, raw_response)
    review["reviewer_id"] = evidence["implementer_id"]  # auto-revue

    resultat = verify_review(review, evidence, raw_response)
    assert not resultat.ok
    assert resultat.errors


def test_lier_les_revues_au_code_au_prompt_et_aux_preuves_3():
    """Cas RED obligatoire : rejeter raw_response hash divergent — le
    hash déclaré doit correspondre aux OCTETS BRUTS réellement fournis à
    verify_review, pas à une valeur arbitraire."""
    evidence = _evidence_valide()
    raw_response = b'{"verdict": "APPROVE"}'
    review = _review_valide(evidence, raw_response)

    autre_raw_response = b'{"verdict": "REJECT", "objections": []}'
    resultat = verify_review(review, evidence, autre_raw_response)
    assert not resultat.ok
    assert resultat.errors


def test_lier_les_revues_au_code_au_prompt_et_aux_preuves_4():
    """Cas RED obligatoire : rejeter vendor ou request_id manquant —
    une revue sans identité de vendor ou sans identifiant de requête ne
    peut pas être tracée jusqu'à son appel réel."""
    evidence = _evidence_valide()
    raw_response = b'{"verdict": "APPROVE"}'

    review = _review_valide(evidence, raw_response)
    del review["vendor"]
    resultat = verify_review(review, evidence, raw_response)
    assert not resultat.ok

    review = _review_valide(evidence, raw_response)
    review["vendor"] = ""
    resultat = verify_review(review, evidence, raw_response)
    assert not resultat.ok

    review = _review_valide(evidence, raw_response)
    del review["request_id"]
    resultat = verify_review(review, evidence, raw_response)
    assert not resultat.ok

    review = _review_valide(evidence, raw_response)
    review["request_id"] = ""
    resultat = verify_review(review, evidence, raw_response)
    assert not resultat.ok


# ---------------------------------------------------------------------------
# Robustesse additionnelle.
# ---------------------------------------------------------------------------


def test_verify_review_verdict_est_un_objet_structure():
    """ReviewVerdict est une dataclass {ok: bool, errors: list[str]} —
    jamais un booléen nu (perdrait la raison de l'échec) ni une
    exception pour un échec de VÉRIFICATION (verify_review ne lève que
    sur une entrée structurellement invalide, ex. review pas un dict)."""
    evidence = _evidence_valide()
    raw_response = b"x"
    review = _review_valide(evidence, raw_response)
    resultat = verify_review(review, evidence, raw_response)
    assert isinstance(resultat, ReviewVerdict)
    assert isinstance(resultat.ok, bool)
    assert isinstance(resultat.errors, list)


def test_verify_review_entree_structurellement_invalide_leve():
    """Une entrée qui n'est même pas un dict/bytes (pas seulement un
    échec de vérification sémantique) lève, ne retourne pas
    silencieusement ok=False."""
    evidence = _evidence_valide()
    with pytest.raises((TypeError, ValueError)):
        verify_review("pas-un-dict", evidence, b"x")


def test_verify_review_champs_requis_de_review_absents_rejetes():
    """Une revue à laquelle il manque un champ structurel de base
    (reviewer_id, commit, tree, evidence_sha256, prompt_sha256,
    raw_response_sha256) est rejetée nommément, pas seulement les 2
    champs (vendor/request_id) explicitement cités par la spec."""
    evidence = _evidence_valide()
    raw_response = b'{"verdict": "APPROVE"}'
    for champ in ("reviewer_id", "commit", "tree", "evidence_sha256", "prompt_sha256", "raw_response_sha256"):
        review = _review_valide(evidence, raw_response)
        del review[champ]
        resultat = verify_review(review, evidence, raw_response)
        assert not resultat.ok, f"champ manquant non détecté : {champ}"
