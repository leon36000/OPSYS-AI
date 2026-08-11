from dataclasses import dataclass


@dataclass
class PolicyResult:
    satisfied: bool
    status: str
    reasons: tuple[str, ...]


def _open_critical_objection_codes(reviews: list[dict]) -> tuple[str, ...]:
    codes = []
    for review in reviews:
        for objection in review.get("objections", []):
            if (
                objection.get("severity") == "CRITICAL"
                and objection.get("status") == "OPEN"
            ):
                codes.append(objection.get("code"))
    return tuple(codes)


def evaluate_policy(
    policy: str, reviews: list[dict], ratifications: list[dict]
) -> PolicyResult:
    """Évalue UNE politique nommée contre reviews et/ou ratifications."""
    if policy == "NONE":
        return PolicyResult(True, "SATISFIED", ())

    if policy == "INDEPENDENT_REVIEW":
        objection_codes = _open_critical_objection_codes(reviews)
        if objection_codes:
            return PolicyResult(
                False, "CRITICAL_OBJECTION_OPEN", objection_codes
            )

        reviewer_ids = {
            review["reviewer_id"]
            for review in reviews
            if review["verdict"] == "APPROVE"
        }
        if len(reviewer_ids) < 1:
            return PolicyResult(
                False, "AWAITING_REVIEW", ("one distinct APPROVE required",)
            )
        return PolicyResult(True, "SATISFIED", ())

    if policy == "TRIAD_CONSENSUS":
        objection_codes = _open_critical_objection_codes(reviews)
        if objection_codes:
            return PolicyResult(
                False, "CRITICAL_OBJECTION_OPEN", objection_codes
            )

        if len(reviews) < 3:
            return PolicyResult(
                False, "AWAITING_TRIAD", (f"{len(reviews)}/3 reviews",)
            )

        vendors = {
            review["vendor"]
            for review in reviews
            if review["vendor"] is not None
        }
        domains = {
            review["failure_domain"]
            for review in reviews
            if review["failure_domain"] is not None
        }
        if len(vendors) < 3 or len(domains) < 3:
            return PolicyResult(
                False,
                "DIVERSITY_NOT_PROVED",
                (f"vendors={len(vendors)}", f"failure_domains={len(domains)}"),
            )

        approved = [
            review for review in reviews if review["verdict"] == "APPROVE"
        ]
        if len(approved) < 2:
            return PolicyResult(
                False, "CONSENSUS_REJECTED", (f"approve={len(approved)}",)
            )

        approving_vendors = {
            review["vendor"]
            for review in approved
            if review["vendor"] is not None
        }
        approving_domains = {
            review["failure_domain"]
            for review in approved
            if review["failure_domain"] is not None
        }
        if len(approving_vendors) < 2 or len(approving_domains) < 2:
            return PolicyResult(
                False,
                "APPROVALS_NOT_INDEPENDENT",
                (
                    f"approve_vendors={len(approving_vendors)}",
                    f"approve_failure_domains={len(approving_domains)}",
                ),
            )

        return PolicyResult(True, "SATISFIED", ())

    if policy == "NATHAN_RATIFICATION":
        for ratification in ratifications:
            if (
                ratification.get("decision") == "APPROVE"
                and ratification.get("role") == "NATHAN"
                and ratification.get("generated_by_agent") is not True
            ):
                return PolicyResult(True, "SATISFIED", ())
        return PolicyResult(False, "AWAITING_NATHAN", ())

    if policy == "PROFESSIONAL_GATE":
        professional_roles = {"CPA", "FISCALISTE", "AVOCAT", "NOTAIRE"}
        for ratification in ratifications:
            if (
                ratification.get("decision") == "APPROVE"
                and ratification.get("role") in professional_roles
                and ratification.get("generated_by_agent") is not True
            ):
                return PolicyResult(True, "SATISFIED", ())
        return PolicyResult(False, "AWAITING_PROFESSIONAL", ())

    return PolicyResult(False, "UNKNOWN_POLICY", (policy,))
