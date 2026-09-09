"""Integrity of execution receipts; no LLM vote and no implied reexecution.

Scoped policy for SONAR-DIAGNOSTICS-182 following Nathan's no-trio direction.
CI still executes the exporter and bootstrap suites in their existing jobs.
These unsigned receipts protect against accidental drift, not a malicious
writer able to replace both code and evidence. Never execute receipt argv.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import zlib
from typing import Any

POLICY = 'EXECUTION_RECEIPTS_V1'
TASK = 'SONAR-DIAGNOSTICS-182'
SUBJECT_FILES = (
    'scripts/sonar_diagnostics.py', 'scripts/tests/test_sonar_diagnostics.py',
    'core/scripts/verify_proof_sealed.py', 'core/scripts/proof_execution_receipts.py',
    'core/tests/bootstrap/test_proof_execution_receipts.py',
    'core/tests/bootstrap/test_proof_sealed.py',
)
SUITES = {'exporter': (SUBJECT_FILES[1], 112), 'policy': (SUBJECT_FILES[4], 58),
          'legacy': (SUBJECT_FILES[5], 28)}
ARTIFACTS = {label + suffix for label in SUITES
             for suffix in ('.json.zlib', '.stdout.txt', '.stderr.txt')}
LIMIT = 2 * 1024 * 1024


class ReceiptInvalid(ValueError):
    """Fixed failure code, without raw evidence or credential values."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ReceiptInvalid(code)


def _read(root: Path, relative: str) -> bytes:
    path = root
    for part in Path(relative).parts:
        path = path / part
        _require(not path.is_symlink(), 'SYMLINK_REFUSED')
    with path.open('rb') as stream:
        data = stream.read(LIMIT + 1)
    _require(len(data) <= LIMIT, 'SIZE_LIMIT')
    return data


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, 'DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _keys(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ReceiptInvalid(code)
    return value


def _events(events: Any, target: str, minimum: int) -> int:
    _require(isinstance(events, list) and bool(events), 'TESTS_MISSING')
    stages: dict[str, set[str]] = {}
    for event in events:
        _keys(event, {'nodeid', 'when', 'outcome'}, 'TEST_EVENT_INVALID')
        node = event['nodeid']
        _require(isinstance(node, str) and node.startswith(target + '::'), 'WRONG_TEST_TARGET')
        _require(event['outcome'] == 'passed', 'TEST_NOT_PASSED')
        stage = event['when']
        _require(stage in ('setup', 'call', 'teardown'), 'TEST_STAGE_INVALID')
        seen = stages.setdefault(node, set())
        _require(stage not in seen, 'DUPLICATE_TEST_STAGE')
        seen.add(stage)
    _require(len(stages) >= minimum, 'TEST_COUNT_BELOW_BASELINE')
    _require(all(s == {'setup', 'call', 'teardown'} for s in stages.values()), 'TEST_INCOMPLETE')
    return len(stages)


def _receipt(raw: bytes, target: str, minimum: int, inputs: dict[str, str], diff: str) -> int:
    decoder = zlib.decompressobj()
    decoded = decoder.decompress(raw, LIMIT + 1)
    _require(decoder.eof and not decoder.unused_data and len(decoded) <= LIMIT, 'COMPRESSED_RECEIPT_INVALID')
    data = json.loads(decoded, object_pairs_hook=_pairs)
    _keys(data, {'schema_version', 'code_diff_sha256', 'input_files', 'argv', 'returncode',
                 'collection_errors', 'deselected', 'environment', 'events'}, 'RECEIPT_SCHEMA')
    _require(type(data['schema_version']) is int and data['schema_version'] == 1, 'RECEIPT_VERSION')
    _require(data['code_diff_sha256'] == diff and data['input_files'] == inputs, 'STALE_RECEIPT')
    _require(data['argv'] == ['-q', '-p', 'no:cacheprovider', target], 'COMMAND_MISMATCH')
    for field in ('returncode', 'collection_errors', 'deselected'):
        _require(type(data[field]) is int and data[field] == 0, 'EXECUTION_FAILED_OR_PARTIAL')
    _keys(data['environment'], {'python', 'pytest'}, 'ENVIRONMENT_MISSING')
    _require(all(isinstance(v, str) and v for v in data['environment'].values()), 'ENVIRONMENT_MISSING')
    return _events(data['events'], target, minimum)


def _artifacts(root: Path, task_dir: Path, declared: Any) -> dict[str, bytes]:
    _keys(declared, ARTIFACTS, 'ARTIFACT_MANIFEST_INCOMPLETE')
    directory = task_dir / 'execution'
    _require(not directory.is_symlink(), 'SYMLINK_REFUSED')
    _require({p.name for p in directory.iterdir()} == ARTIFACTS, 'ARTIFACT_INVENTORY_MISMATCH')
    data = {}
    for name in sorted(ARTIFACTS):
        raw = _read(root, f'evidence/tasks/{TASK}/execution/{name}')
        _require(_hash(raw) == declared[name], 'ARTIFACT_HASH_MISMATCH')
        data[name] = raw
    return data


def verify_execution(task_id: str, root: Path, task_dir: Path, manifest: dict,
                     expected_diff: str, changed_paths: set[str]) -> tuple[bool, str]:
    """Verify fixed suites, inputs and raw logs; legacy review policy unchanged."""
    try:
        _require(task_id == TASK and manifest.get('task_id') == TASK, 'TASK_NOT_AUTHORIZED')
        _require(manifest.get('proof_policy') == POLICY, 'POLICY_NOT_AUTHORIZED')
        _require(task_dir == root / 'evidence' / 'tasks' / TASK, 'TASK_PATH_MISMATCH')
        _require(manifest.get('reviews') == {} and not (task_dir / 'reviews').exists(), 'REVIEWS_NOT_OMITTABLE')
        _require(bool(changed_paths) and changed_paths <= set(SUBJECT_FILES), 'CODE_SCOPE_MISMATCH')
        _require(bool(re.fullmatch(r'[0-9a-f]{64}', expected_diff)), 'DIFF_INVALID')
        _require(manifest.get('code_diff_sha256') == expected_diff, 'DIFF_MISMATCH')
        execution = _keys(manifest.get('execution'), {'input_files', 'artifacts'},
                          'EXECUTION_MANIFEST_MISSING')
        inputs = execution['input_files']
        _keys(inputs, set(SUBJECT_FILES), 'INPUT_MANIFEST_INCOMPLETE')
        measured = {path: _hash(_read(root, path)) for path in SUBJECT_FILES}
        _require(inputs == measured, 'INPUT_HASH_MISMATCH')
        artifacts = _artifacts(root, task_dir, execution['artifacts'])
        counts = {name: _receipt(artifacts[name + '.json.zlib'], target, minimum, measured, expected_diff)
                  for name, (target, minimum) in SUITES.items()}
    except ReceiptInvalid as exc:
        return False, f'EXECUTION_RECEIPTS: REFUSED — {exc}'
    except (OSError, ValueError, TypeError, KeyError, RecursionError, zlib.error):
        return False, 'EXECUTION_RECEIPTS: REFUSED — invalid, stale or incomplete evidence'
    return True, f'EXECUTION_RECEIPTS: integrity verified {counts}; review=NOT_PERFORMED; reexecution=SEPARATE_CI_JOBS'
