from dataclasses import dataclass
import hashlib
import json
import re


@dataclass
class ReviewVerdict:
    ok: bool
    errors: list[str]


def verify_review(review: dict, evidence: dict, raw_response: bytes) -> ReviewVerdict:
    """Vérifie qu'une revue scellée est liée à l'evidence et à sa réponse brute."""
    if not isinstance(review, dict):
        raise TypeError("review doit être un dict")
    if not isinstance(raw_response, bytes):
        raise TypeError("raw_response doit être des bytes")

    errors: list[str] = []
    required_fields = (
        "reviewer_id",
        "vendor",
        "request_id",
        "commit",
        "tree",
        "evidence_sha256",
        "prompt_sha256",
        "raw_response_sha256",
    )

    for field in required_fields:
        if field not in review:
            errors.append(f"champ requis absent : {field}")

    if "vendor" in review:
        if not isinstance(review["vendor"], str) or not review["vendor"]:
            errors.append("vendor doit être une chaîne non vide")

    if "request_id" in review:
        if not isinstance(review["request_id"], str) or not review["request_id"]:
            errors.append("request_id doit être une chaîne non vide")

    if (
        "commit" in review
        and isinstance(evidence, dict)
        and "commit" in evidence
        and review["commit"] != evidence["commit"]
    ):
        errors.append("commit de la review différent de celui de l'evidence")

    if (
        "tree" in review
        and isinstance(evidence, dict)
        and "tree" in evidence
        and review["tree"] != evidence["tree"]
    ):
        errors.append("tree de la review différent de celui de l'evidence")

    if "evidence_sha256" in review:
        try:
            canonical_evidence = json.dumps(
                evidence,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            expected_evidence_hash = hashlib.sha256(
                canonical_evidence.encode("utf-8")
            ).hexdigest()
            if review["evidence_sha256"] != expected_evidence_hash:
                errors.append("evidence_sha256 ne correspond pas à l'evidence")
        except (TypeError, ValueError, OverflowError):
            errors.append("evidence_sha256 ne peut pas être recalculé pour l'evidence")

    if "prompt_sha256" in review:
        prompt_hash = review["prompt_sha256"]
        if not isinstance(prompt_hash, str) or re.fullmatch(r"[0-9a-f]{64}", prompt_hash) is None:
            errors.append("prompt_sha256 doit être un hash SHA-256 hexadécimal valide")

    if "raw_response_sha256" in review:
        expected_raw_response_hash = hashlib.sha256(raw_response).hexdigest()
        if review["raw_response_sha256"] != expected_raw_response_hash:
            errors.append("raw_response_sha256 ne correspond pas à raw_response")

    if (
        "reviewer_id" in review
        and isinstance(evidence, dict)
        and "implementer_id" in evidence
        and review["reviewer_id"] == evidence["implementer_id"]
    ):
        errors.append("reviewer_id identique à implementer_id : auto-revue interdite")

    return ReviewVerdict(ok=not errors, errors=errors)
