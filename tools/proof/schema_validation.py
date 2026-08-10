from __future__ import annotations

import re


class SchemaValidationError(ValueError):
    """Levée par les validateurs sur toute violation de schéma."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_TASK_STATUSES = {
    "READY",
    "BLOCKED",
    "IN_PROGRESS",
    "EVIDENCE_SUBMITTED",
    "VERIFIED",
    "SUPERSEDED",
}
_TASK_RISKS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_REVIEW_POLICIES = {"NONE", "INDEPENDENT_REVIEW", "TRIAD_CONSENSUS"}
_REVIEW_VERDICTS = {"APPROVE", "REJECT", "CONTESTED"}
_GATE_STATUSES = {"MEASURED_PASS", "MEASURED_FAIL"}

_EVIDENCE_KEYS = {
    "schema_version",
    "task_id",
    "implementer_id",
    "commit",
    "tree",
    "inputs_manifest",
    "outputs_manifest",
    "commands",
}
_REVIEW_KEYS = {
    "schema_version",
    "subject_type",
    "subject_id",
    "reviewer_id",
    "vendor",
    "verdict",
    "objections",
    "evidence_sha256",
}
_OBJECTION_KEYS = {"code", "severity", "text", "status"}
_OBJECTION_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_OBJECTION_STATUSES = {"OPEN", "RESOLVED", "WITHDRAWN"}


def _fail(message: str) -> None:
    raise SchemaValidationError(message)


def _object(obj: object, name: str) -> dict:
    if not isinstance(obj, dict):
        _fail(f"{name} must be an object")
    return obj


def _required(obj: dict, keys: set[str], name: str) -> None:
    missing = keys.difference(obj)
    if missing:
        _fail(f"{name} missing required field(s): {', '.join(sorted(missing))}")


def _string(value: object, field: str, non_empty: bool = True) -> None:
    if not isinstance(value, str) or (non_empty and not value):
        _fail(f"{field} must be a non-empty string")


def _enum(value: object, field: str, values: set[str]) -> None:
    if not isinstance(value, str) or value not in values:
        _fail(f"{field} has an invalid value")


def _string_list(value: object, field: str, non_empty: bool = False) -> None:
    if not isinstance(value, list) or (non_empty and not value):
        _fail(f"{field} must be a list" + (" and non-empty" if non_empty else ""))
    for index, item in enumerate(value):
        _string(item, f"{field}[{index}]")


def _sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field} must be a lowercase hexadecimal SHA-256 hash")


def _integer(value: object, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(f"{field} must be an integer")


def _manifest(value: object, field: str) -> None:
    if not isinstance(value, list) or not value:
        _fail(f"{field} must be a non-empty list")
    for index, entry in enumerate(value):
        entry_name = f"{field}[{index}]"
        if not isinstance(entry, dict):
            _fail(f"{entry_name} must be an object")
        _required(entry, {"path", "sha256", "size"}, entry_name)
        _string(entry["path"], f"{entry_name}.path")
        _sha256(entry["sha256"], f"{entry_name}.sha256")
        _integer(entry["size"], f"{entry_name}.size")
        if entry["size"] < 0:
            _fail(f"{entry_name}.size must not be negative")


def _evidence_command(value: object, index: int) -> None:
    name = f"commands[{index}]"
    if not isinstance(value, dict):
        _fail(f"{name} must be an object")
    required = {
        "argv",
        "expected_returncode",
        "actual_returncode",
        "stdout_sha256",
        "stderr_sha256",
    }
    _required(value, required, name)
    _string_list(value["argv"], f"{name}.argv", non_empty=True)
    _integer(value["expected_returncode"], f"{name}.expected_returncode")
    _integer(value["actual_returncode"], f"{name}.actual_returncode")
    _sha256(value["stdout_sha256"], f"{name}.stdout_sha256")
    _sha256(value["stderr_sha256"], f"{name}.stderr_sha256")


def _objection(value: object, index: int) -> None:
    # Revue scellée C01-002 (Gemini-3.1-Pro, MAJEURE, confirmée) : le
    # champ `objections` n'était contrôlé que comme liste, jamais dans la
    # structure de ses éléments — contredit l'objectif même de la tâche
    # (schémas STRICTS). Chaque objection est maintenant un objet fermé
    # avec sévérité/statut en énumération fermée, comme les autres champs
    # d'énumération de ce module.
    name = f"objections[{index}]"
    if not isinstance(value, dict):
        _fail(f"{name} must be an object")
    _required(value, _OBJECTION_KEYS, name)
    unexpected = set(value).difference(_OBJECTION_KEYS)
    if unexpected:
        _fail(f"{name} contains additional field(s): {', '.join(sorted(unexpected))}")
    _string(value["code"], f"{name}.code")
    _enum(value["severity"], f"{name}.severity", _OBJECTION_SEVERITIES)
    _string(value["text"], f"{name}.text")
    _enum(value["status"], f"{name}.status", _OBJECTION_STATUSES)


def _gate_check(value: object, index: int) -> None:
    name = f"checks[{index}]"
    if not isinstance(value, dict):
        _fail(f"{name} must be an object")
    required = {"check_id", "argv", "expected_returncode", "actual_returncode"}
    _required(value, required, name)
    _string(value["check_id"], f"{name}.check_id")
    _string_list(value["argv"], f"{name}.argv", non_empty=True)
    _integer(value["expected_returncode"], f"{name}.expected_returncode")
    _integer(value["actual_returncode"], f"{name}.actual_returncode")


def validate_task(obj: dict) -> None:
    """Validate a task object."""
    value = _object(obj, "task")
    required = {
        "schema_version",
        "task_id",
        "title",
        "status",
        "risk",
        "review_policy",
        "dependencies",
        "outputs",
    }
    _required(value, required, "task")
    _string(value["schema_version"], "task.schema_version")
    _string(value["task_id"], "task.task_id")
    _string(value["title"], "task.title")
    _enum(value["status"], "task.status", _TASK_STATUSES)
    _enum(value["risk"], "task.risk", _TASK_RISKS)
    _enum(value["review_policy"], "task.review_policy", _REVIEW_POLICIES)
    _string_list(value["dependencies"], "task.dependencies")
    _string_list(value["outputs"], "task.outputs", non_empty=True)


def validate_evidence(obj: dict) -> None:
    """Validate an evidence object."""
    value = _object(obj, "evidence")
    _required(value, _EVIDENCE_KEYS, "evidence")
    unexpected = set(value).difference(_EVIDENCE_KEYS)
    if unexpected:
        _fail(f"evidence contains additional field(s): {', '.join(sorted(unexpected))}")
    _string(value["schema_version"], "evidence.schema_version")
    _string(value["task_id"], "evidence.task_id")
    _string(value["implementer_id"], "evidence.implementer_id")
    _sha256(value["commit"], "evidence.commit")
    _sha256(value["tree"], "evidence.tree")
    _manifest(value["inputs_manifest"], "inputs_manifest")
    _manifest(value["outputs_manifest"], "outputs_manifest")
    if not isinstance(value["commands"], list):
        _fail("evidence.commands must be a list")
    for index, command in enumerate(value["commands"]):
        _evidence_command(command, index)


def validate_review(obj: dict) -> None:
    """Validate a review object."""
    value = _object(obj, "review")
    _required(value, _REVIEW_KEYS, "review")
    unexpected = set(value).difference(_REVIEW_KEYS)
    if unexpected:
        _fail(f"review contains additional field(s): {', '.join(sorted(unexpected))}")
    _string(value["schema_version"], "review.schema_version")
    _string(value["subject_type"], "review.subject_type")
    _string(value["subject_id"], "review.subject_id")
    _string(value["reviewer_id"], "review.reviewer_id")
    _string(value["vendor"], "review.vendor")
    _enum(value["verdict"], "review.verdict", _REVIEW_VERDICTS)
    if not isinstance(value["objections"], list):
        _fail("review.objections must be a list")
    for index, objection in enumerate(value["objections"]):
        _objection(objection, index)
    _sha256(value["evidence_sha256"], "review.evidence_sha256")


def validate_gate(obj: dict) -> None:
    """Validate a gate object."""
    value = _object(obj, "gate")
    required = {
        "schema_version",
        "phase",
        "run_id",
        "commit",
        "tree",
        "status",
        "checks",
    }
    _required(value, required, "gate")
    _string(value["schema_version"], "gate.schema_version")
    _string(value["phase"], "gate.phase")
    _string(value["run_id"], "gate.run_id")
    _sha256(value["commit"], "gate.commit")
    _sha256(value["tree"], "gate.tree")
    _enum(value["status"], "gate.status", _GATE_STATUSES)
    if not isinstance(value["checks"], list):
        _fail("gate.checks must be a list")
    for index, check in enumerate(value["checks"]):
        _gate_check(check, index)
