from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from tools.proof.schema_validation import validate_evidence

try:
    from tools.proof.replay import generate_replay_script
except ModuleNotFoundError:

    def generate_replay_script(evidence: dict) -> str:
        return '''from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    bundle = Path(__file__).resolve().parent
    evidence_path = bundle / "evidence.json"
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"cannot read evidence.json: {error}", file=sys.stderr)
        return 1

    errors: list[str] = []
    for manifest_name in ("inputs_manifest", "outputs_manifest"):
        entries = evidence.get(manifest_name)
        if not isinstance(entries, list):
            print(f"invalid {manifest_name}", file=sys.stderr)
            return 1
        for entry in entries:
            if not isinstance(entry, dict):
                print(f"invalid entry in {manifest_name}", file=sys.stderr)
                return 1
            path_value = entry.get("path")
            expected_hash = entry.get("sha256")
            if not isinstance(path_value, str) or not isinstance(expected_hash, str):
                print(f"invalid entry in {manifest_name}", file=sys.stderr)
                return 1
            artifact = bundle / path_value
            if not artifact.is_file():
                errors.append(f"{path_value}: file is missing")
                continue
            actual_hash = _sha256(artifact)
            if actual_hash != expected_hash:
                errors.append(f"{path_value}: sha256 mismatch")

    for error in errors:
        print(error, file=sys.stderr)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


_BUNDLE_MANIFEST_KEYS = {
    "task_id",
    "implementer_id",
    "commit",
    "tree",
    "environment",
    "inputs",
    "outputs",
    "commands",
    "tests",
    "limitations",
    "rollback",
}
_RECEIPT_KEYS = {
    "argv",
    "expected_returncode",
    "actual_returncode",
    "stdout_sha256",
    "stderr_sha256",
}
_COMMAND_KEYS = {"kind", "receipt_dir"}
_ROLLBACK_KEYS = {"procedure", "tested", "receipt_refs"}
_ONE_MIB = 1_048_576


@dataclass
class ReplayResult:
    ok: bool
    errors: list[str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _value_error(message: str) -> None:
    raise ValueError(message)


def _read_json(path: Path, description: str) -> object:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        _value_error(f"{description} is absent or malformed: {error}")


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        _value_error(f"{field} must be a non-empty string")
    return value


def _relative_path(value: object, field: str) -> Path:
    text = _non_empty_string(value, field)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        _value_error(f"{field} must be relative and must not contain '..'")
    return path


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        _value_error(f"{field} must be a list")
    return [_non_empty_string(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _validate_source_manifest(value: object, task_id: str) -> dict:
    if not isinstance(value, dict):
        _value_error("manifest.json must contain an object")

    missing = _BUNDLE_MANIFEST_KEYS.difference(value)
    additional = set(value).difference(_BUNDLE_MANIFEST_KEYS)
    if missing:
        _value_error(f"manifest.json missing field(s): {', '.join(sorted(missing))}")
    if additional:
        _value_error(f"manifest.json contains additional field(s): {', '.join(sorted(additional))}")

    manifest_task_id = _non_empty_string(value["task_id"], "manifest.task_id")
    if manifest_task_id != task_id:
        _value_error("manifest.task_id does not match task_id")

    _non_empty_string(value["implementer_id"], "manifest.implementer_id")
    _non_empty_string(value["commit"], "manifest.commit")
    _non_empty_string(value["tree"], "manifest.tree")

    if not isinstance(value["environment"], dict):
        _value_error("manifest.environment must be an object")
    _string_list(value["inputs"], "manifest.inputs")
    _string_list(value["outputs"], "manifest.outputs")

    if not isinstance(value["commands"], list):
        _value_error("manifest.commands must be a list")
    for index, command in enumerate(value["commands"]):
        name = f"manifest.commands[{index}]"
        if not isinstance(command, dict):
            _value_error(f"{name} must be an object")
        if set(command) != _COMMAND_KEYS:
            _value_error(f"{name} must contain exactly kind and receipt_dir")
        _non_empty_string(command["kind"], f"{name}.kind")
        _relative_path(command["receipt_dir"], f"{name}.receipt_dir")

    if not isinstance(value["tests"], list):
        _value_error("manifest.tests must be a list")
    if not isinstance(value["limitations"], list):
        _value_error("manifest.limitations must be a list")

    rollback = value["rollback"]
    if not isinstance(rollback, dict) or set(rollback) != _ROLLBACK_KEYS:
        _value_error("manifest.rollback must contain exactly procedure, tested and receipt_refs")
    _non_empty_string(rollback["procedure"], "manifest.rollback.procedure")
    if not isinstance(rollback["tested"], bool):
        _value_error("manifest.rollback.tested must be a boolean")
    _string_list(rollback["receipt_refs"], "manifest.rollback.receipt_refs")

    return value


def _receipt_command(receipt_dir: Path, command_index: int) -> dict:
    receipt_path = receipt_dir / "receipt.json"
    receipt = _read_json(receipt_path, f"receipt for command {command_index}")
    if not isinstance(receipt, dict):
        _value_error(f"receipt for command {command_index} must contain an object")
    if set(receipt) != _RECEIPT_KEYS:
        _value_error(f"receipt for command {command_index} has invalid fields")
    return receipt


def _artifact_entries(source_dir: Path, paths: list[str], field: str) -> tuple[list[dict], list[tuple[Path, Path, str]]]:
    entries: list[dict] = []
    copies: list[tuple[Path, Path, str]] = []

    for index, raw_path in enumerate(paths):
        relative = _relative_path(raw_path, f"manifest.{field}[{index}]")
        source_path = source_dir / relative
        if not source_path.is_file():
            _value_error(f"manifest.{field}[{index}] does not name an existing file")

        size = source_path.stat().st_size
        digest = _sha256(source_path)
        stored_relative = Path("cas") / digest if size > _ONE_MIB else relative
        entries.append(
            {
                "path": stored_relative.as_posix(),
                "sha256": digest,
                "size": size,
            }
        )
        copies.append((source_path, stored_relative, digest))

    return entries, copies


def _copy_artifacts(bundle: Path, artifacts: list[tuple[Path, Path, str]]) -> None:
    copied_cas: set[str] = set()
    for source_path, stored_relative, digest in artifacts:
        if stored_relative.parts[0] == "cas":
            if digest in copied_cas:
                continue
            copied_cas.add(digest)
        destination = bundle / stored_relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def build_bundle(task_id: str, source_dir: Path, out_dir: Path) -> Path:
    _non_empty_string(task_id, "task_id")
    source_dir = Path(source_dir)
    out_dir = Path(out_dir)

    manifest = _validate_source_manifest(
        _read_json(source_dir / "manifest.json", "manifest.json"),
        task_id,
    )

    inputs_manifest, input_artifacts = _artifact_entries(
        source_dir, manifest["inputs"], "inputs"
    )
    outputs_manifest, output_artifacts = _artifact_entries(
        source_dir, manifest["outputs"], "outputs"
    )

    evidence_commands: list[dict] = []
    receipt_directories: list[tuple[Path, Path]] = []
    for index, command in enumerate(manifest["commands"]):
        receipt_relative = _relative_path(
            command["receipt_dir"], f"manifest.commands[{index}].receipt_dir"
        )
        receipt_source = source_dir / receipt_relative
        if not receipt_source.is_dir():
            _value_error(f"manifest.commands[{index}].receipt_dir does not name a directory")
        for required_name in ("receipt.json", "stdout.bin", "stderr.bin"):
            if not (receipt_source / required_name).is_file():
                _value_error(
                    f"manifest.commands[{index}].receipt_dir is missing {required_name}"
                )
        evidence_commands.append(_receipt_command(receipt_source, index))
        receipt_directories.append((receipt_source, receipt_relative))

    evidence = {
        "schema_version": "1",
        "task_id": manifest["task_id"],
        "implementer_id": manifest["implementer_id"],
        "commit": manifest["commit"],
        "tree": manifest["tree"],
        "inputs_manifest": inputs_manifest,
        "outputs_manifest": outputs_manifest,
        "commands": evidence_commands,
    }
    try:
        validate_evidence(evidence)
    except Exception as error:
        _value_error(f"generated evidence is invalid: {error}")

    bundle = out_dir / task_id
    bundle.mkdir(parents=True, exist_ok=True)

    _copy_artifacts(bundle, input_artifacts + output_artifacts)

    copied_receipts: set[Path] = set()
    for receipt_source, receipt_relative in receipt_directories:
        if receipt_relative in copied_receipts:
            continue
        copied_receipts.add(receipt_relative)
        shutil.copytree(receipt_source, bundle / receipt_relative, dirs_exist_ok=True)

    (bundle / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle / "replay.py").write_text(
        generate_replay_script(evidence),
        encoding="utf-8",
    )

    return bundle


def replay_bundle(bundle: Path) -> ReplayResult:
    bundle = Path(bundle)
    evidence_path = bundle / "evidence.json"
    evidence = _read_json(evidence_path, "evidence.json")
    try:
        validate_evidence(evidence)
    except Exception as error:
        _value_error(f"evidence.json is structurally invalid: {error}")

    errors: list[str] = []
    for manifest_name in ("inputs_manifest", "outputs_manifest"):
        for entry in evidence[manifest_name]:
            path_text = entry["path"]
            artifact = bundle / path_text
            if not artifact.is_file():
                errors.append(f"{path_text}: file is missing")
                continue
            actual_hash = _sha256(artifact)
            if actual_hash != entry["sha256"]:
                errors.append(f"{path_text}: sha256 mismatch")

    return ReplayResult(ok=not errors, errors=errors)
