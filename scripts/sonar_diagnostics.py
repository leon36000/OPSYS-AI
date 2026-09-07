#!/usr/bin/env python3
"""Export Sonar en lecture seule pour #182 ; jamais une qualification globale.

Projet/hôte/branche fixes. PAT dans SONAR_TOKEN uniquement. Aucun message
source, identité utilisateur, corps d'erreur HTTP ou jeton n'est exporté.
Les tests utilisent des réponses fictives ; un accès réel reste nécessaire.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import contextmanager
import errno
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import secrets
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

PROJECT = "leon36000_OPSYS-AI"
BRANCH = "main"
HOST = "https://sonarcloud.io/"
_REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_ITEMS = 10_000
MAX_RESPONSE = 8 * 1024 * 1024
METRICS = (
    "security_rating", "reliability_rating", "sqale_rating", "coverage",
    "duplicated_lines_density", "security_hotspots_reviewed",
    "new_security_rating", "new_reliability_rating", "new_maintainability_rating",
    "new_coverage", "new_duplicated_lines_density", "new_security_hotspots_reviewed",
)
ENDPOINTS = frozenset({
    "api/users/current", "api/components/show", "api/project_analyses/search",
    "api/qualitygates/project_status", "api/measures/component", "api/issues/search",
    "api/hotspots/search", "api/measures/component_tree", "api/duplications/show",
})
JsonGet = Callable[[str, dict[str, Any]], dict[str, Any]]


class ExportError(RuntimeError):
    """Erreur nommée sans corps de réponse ni valeur de credential."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Ne jamais transférer le header Authorization à une autre destination.
        fp.close()
        raise ExportError(f"HTTP_{code}_REDIRECT_REFUSED")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON number")


class SonarClient:
    """Client GET HTTPS, sans redirection, proxy d'environnement ni retry caché."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ExportError("TOKEN_REQUIRED")
        if not token.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token):
            raise ExportError("TOKEN_INVALID")
        self._token = token
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if path not in ENDPOINTS:
            raise ExportError("ENDPOINT_REFUSED")
        suffix = "?" + urlencode(params) if params else ""
        request = Request(HOST + path + suffix, headers={
            "Authorization": "Bearer " + self._token, "Accept": "application/json",
        }, method="GET")
        try:
            with self.opener.open(request, timeout=15) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except HTTPError as exc:
            exc.close()
            raise ExportError(f"HTTP_{exc.code}") from None
        except OSError:
            raise ExportError("TRANSPORT_UNAVAILABLE") from None
        if len(raw) > MAX_RESPONSE:
            raise ExportError("RESPONSE_LIMIT")
        try:
            data = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant,
                              object_pairs_hook=_unique_object)
        except (ValueError, RecursionError):
            raise ExportError("JSON_INVALID") from None
        if not isinstance(data, dict):
            raise ExportError("JSON_INVALID")
        return data


def _object(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExportError(code)
    return value


def _rows(value: Any, code: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        raise ExportError(code)
    return value


def _text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExportError(code)
    return value


def _project(value: Any) -> dict[str, Any]:
    obj = _object(value, "PROJECT_MISMATCH")
    if obj.get("key") != PROJECT or obj.get("qualifier") != "TRK":
        raise ExportError("PROJECT_MISMATCH")
    return obj


def _pick(obj: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    # Projection volontaire : pas de message, commentaire, auteur ou extrait source.
    return {key: obj[key] for key in fields if key in obj}


def _latest(get: JsonGet, revision: str) -> dict[str, Any]:
    data = get("api/project_analyses/search", {"project": PROJECT, "branch": BRANCH, "p": 1, "ps": 1})
    analyses = _rows(data.get("analyses"), "ANALYSIS_MISSING")
    if len(analyses) != 1:
        raise ExportError("ANALYSIS_MISSING")
    analysis = analyses[0]
    if analysis.get("revision") != revision:
        raise ExportError("REVISION_MISMATCH")
    for field in ("key", "date"):
        _text(analysis.get(field), "ANALYSIS_MISSING")
    try:
        parsed_date = datetime.fromisoformat(analysis["date"])
    except ValueError:
        raise ExportError("ANALYSIS_DATE_INVALID") from None
    if parsed_date.tzinfo is None:
        raise ExportError("ANALYSIS_DATE_INVALID")
    return _pick(analysis, ("key", "date", "revision"))


def _page_shape(data: dict[str, Any], page: int, expected: tuple[int, int] | None) -> tuple[int, int]:
    paging = _object(data.get("paging"), "PAGINATION_INVALID")
    index, size, total = (paging.get(k) for k in ("pageIndex", "pageSize", "total"))
    if any(type(x) is not int for x in (index, size, total)):
        raise ExportError("PAGINATION_INVALID")
    if index != page or not 1 <= size <= 500 or total < 0:
        raise ExportError("PAGINATION_INVALID")
    if total > MAX_ITEMS:
        raise ExportError("PAGINATION_LIMIT")
    if expected is not None and expected != (size, total):
        raise ExportError("PAGINATION_CHANGED")
    return size, total


def _add_unique(result: list[dict[str, Any]], seen: set[str], rows: list[dict[str, Any]]) -> None:
    for row in rows:
        identity = _text(row.get("key"), "PAGINATION_INVALID")
        if identity in seen:
            raise ExportError("DUPLICATE_ITEM")
        seen.add(identity)
        result.append(row)


def _pages(get: JsonGet, path: str, key: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    expected = None
    for page in range(1, MAX_ITEMS + 2):
        data = get(path, dict(params, branch=BRANCH, p=page, ps=100))
        size, total = _page_shape(data, page, expected)
        expected = (size, total)
        rows = _rows(data.get(key), "PAGINATION_INVALID")
        if len(rows) != min(size, total - len(result)):
            raise ExportError("PAGINATION_INCOMPLETE")
        if key == "components":
            _project(data.get("baseComponent"))
        _add_unique(result, seen, rows)
        if len(result) == total:
            return result
    raise ExportError("PAGINATION_LIMIT")


def _measure_period(value: Any, field: str) -> Any:
    fields = ("index", "value")
    if field == "period":
        return _pick(_object(value, "METRICS_INVALID"), fields)
    return [_pick(p, fields) for p in _rows(value, "METRICS_INVALID")]


def _measures(obj: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for measure in _rows(obj.get("measures"), "METRICS_INVALID"):
        name = _text(measure.get("metric"), "METRICS_INVALID")
        if name in seen:
            raise ExportError("METRICS_DUPLICATE")
        seen.add(name)
        clean = _pick(measure, ("metric", "value"))
        for field in ("period", "periods"):
            if field in measure:
                clean[field] = _measure_period(measure[field], field)
        result.append(clean)
    return result


def _measured(measure: dict[str, Any]) -> bool:
    candidates = [measure]
    if "period" in measure:
        candidates.append(measure["period"])
    candidates.extend(measure.get("periods", []))
    for candidate in candidates:
        value = candidate.get("value")
        if isinstance(value, str) and value:
            try:
                if Decimal(value).is_finite():
                    return True
            except InvalidOperation:
                continue
    return False


def _inside_project(component: Any, *, allow_root: bool = False) -> str:
    key = _text(component, "COMPONENT_OUTSIDE_PROJECT")
    if not (key.startswith(PROJECT + ":") or (allow_root and key == PROJECT)):
        raise ExportError("COMPONENT_OUTSIDE_PROJECT")
    return key


def _findings(rows: list[dict[str, Any]], rule: str) -> list[dict[str, Any]]:
    fields = ("key", "component", "project", rule, "severity", "type", "status",
              "issueStatus", "resolution", "line", "textRange", "securityCategory",
              "vulnerabilityProbability", "impacts", "creationDate", "updateDate")
    result = []
    for row in rows:
        if row.get("project") != PROJECT:
            raise ExportError("FINDING_PROJECT_MISMATCH")
        _inside_project(row.get("component"), allow_root=True)
        _text(row.get(rule), "FINDING_INVALID")
        clean = _pick(row, fields)
        if "textRange" in row:
            clean["textRange"] = _pick(_object(row["textRange"], "FINDING_INVALID"),
                                       ("startLine", "endLine", "startOffset", "endOffset"))
        if "impacts" in row:
            clean["impacts"] = [_pick(i, ("softwareQuality", "severity"))
                                for i in _rows(row["impacts"], "FINDING_INVALID")]
        result.append(clean)
    return result


def _duplication_count(file: dict[str, Any]) -> int:
    _inside_project(file.get("key"))
    if file.get("qualifier") not in {"FIL", "UTS"}:
        raise ExportError("DUPLICATION_INVALID")
    values = [m.get("value") for m in _measures(file) if m["metric"] == "duplicated_blocks"]
    if len(values) != 1 or not isinstance(values[0], str) or not re.fullmatch(r"\d+", values[0], flags=re.ASCII):
        raise ExportError("DUPLICATION_METRIC_MISSING")
    return int(values[0])


def _duplication_group(group: dict[str, Any], refs: dict[str, Any]) -> dict[str, Any]:
    blocks = _rows(group.get("blocks"), "DUPLICATION_INVALID")
    if not blocks:
        raise ExportError("DUPLICATION_INVALID")
    result = []
    for block in blocks:
        ref = block.get("_ref")
        if not isinstance(ref, str) or ref not in refs:
            raise ExportError("DUPLICATION_INVALID")
        if any(type(block.get(k)) is not int or block[k] < 1 for k in ("from", "size")):
            raise ExportError("DUPLICATION_INVALID")
        target = _object(refs[ref], "DUPLICATION_INVALID")
        result.append({"from": block["from"], "size": block["size"],
                       "component": _text(target.get("key"), "DUPLICATION_INVALID")})
    return {"blocks": result}


def _duplications(get: JsonGet, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for file in files:
        if _duplication_count(file) == 0:
            continue
        data = get("api/duplications/show", {"key": file["key"], "branch": BRANCH})
        groups = _rows(data.get("duplications"), "DUPLICATION_INVALID")
        refs = _object(data.get("files"), "DUPLICATION_INVALID")
        if not groups:
            raise ExportError("DUPLICATION_DETAILS_MISSING")
        result.append({"component": file["key"], "path": file.get("path"),
                       "groups": [_duplication_group(group, refs) for group in groups]})
    return result


def collect(get: JsonGet, revision: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or revision == "0" * 40:
        raise ExportError("EXPECTED_REVISION_INVALID")
    # authentication/validate seul ne suffit pas : il accepte aussi l'anonyme.
    if get("api/users/current", {}).get("isLoggedIn") is not True:
        raise ExportError("AUTH_REQUIRED")
    _project(get("api/components/show", {"component": PROJECT, "branch": BRANCH}).get("component"))
    analysis = _latest(get, revision)
    gate = _object(get("api/qualitygates/project_status", {"analysisId": analysis["key"]}).get("projectStatus"), "GATE_INVALID")
    if gate.get("status") not in ("OK", "ERROR", "NONE"):
        raise ExportError("GATE_INVALID")
    conditions = _rows(gate.get("conditions"), "GATE_INVALID")
    for condition in conditions:
        _text(condition.get("metricKey"), "GATE_INVALID")
        if condition.get("status") not in ("OK", "ERROR", "NO_VALUE"):
            raise ExportError("GATE_INVALID")
    component = _project(get("api/measures/component", {
        "component": PROJECT, "branch": BRANCH, "metricKeys": ",".join(METRICS),
    }).get("component"))
    measures = _measures(component)
    measured = {m["metric"] for m in measures if _measured(m)}
    issues = _pages(get, "api/issues/search", "issues", {"componentKeys": PROJECT, "resolved": "false"})
    hotspots = _pages(get, "api/hotspots/search", "hotspots", {"projectKey": PROJECT})
    files = _pages(get, "api/measures/component_tree", "components", {
        "component": PROJECT, "metricKeys": "duplicated_blocks", "qualifiers": "FIL,UTS", "strategy": "leaves",
    })
    duplicates = _duplications(get, files)
    if _latest(get, revision) != analysis:
        raise ExportError("ANALYSIS_CHANGED")
    return {
        "schema_version": 1, "project": PROJECT, "branch": BRANCH, "analysis": analysis,
        "collected_at": datetime.now(timezone.utc).isoformat(), "collection_status": "COMPLETE",
        "quality_verified": False,
        "quality_gate": {"status": gate["status"], "ignoredConditions": gate.get("ignoredConditions"),
                         "conditions": [_pick(c, ("metricKey", "status", "actualValue", "errorThreshold", "comparator", "periodIndex")) for c in conditions]},
        "measures": measures, "missing_metrics": sorted(set(METRICS) - measured),
        "issues": _findings(issues, "rule"), "hotspots": _findings(hotspots, "ruleKey"),
        "duplications": duplicates,
        "limits": ["Messages, auteurs, identités et extraits source non exportés.",
                   "Analyse identique avant/après ; pas de transaction serveur sur les statuts d'issues.",
                   "Ce diagnostic ne qualifie ni tout le dépôt ni la sécurité de production."],
    }


def diagnostic_exit_code(report: dict[str, Any]) -> int:
    gate = report["quality_gate"]
    if gate["status"] == "ERROR" or any(c["status"] == "ERROR" for c in gate["conditions"]):
        return 1
    if (gate["status"] != "OK" or report["missing_metrics"] or gate["ignoredConditions"] is not False
            or not gate["conditions"] or any(c["status"] != "OK" for c in gate["conditions"])):
        return 3
    return 0


def canonical(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _output_name(path: Path) -> str:
    """Confine l'entrée CLI à un fichier JSON de la racine fixe du dépôt."""
    root = _REPO_ROOT / ".opsys" / "diagnostics"
    candidate = path if path.is_absolute() else root / path
    if candidate.parent != root or not re.fullmatch(r"\w[\w.-]{0,119}\.json", candidate.name, flags=re.ASCII):
        raise ExportError("OUTPUT_PATH_REFUSED")
    return candidate.name


@contextmanager
def _export_directory():
    """Ancre les opérations à un descripteur, sans suivre les symlinks."""
    if (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
            or not {os.open, os.link, os.unlink}.issubset(os.supports_dir_fd)):
        raise ExportError("OUTPUT_PLATFORM_UNSUPPORTED")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        fd = os.open(_REPO_ROOT, flags)
        try:
            for part in (".opsys", "diagnostics"):
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd
        finally:
            os.close(fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ExportError("OUTPUT_ROOT_UNSAFE") from None
        raise


def write_export(path: Path, report: dict[str, Any], token: str) -> None:
    name = _output_name(path)
    payload = canonical({"report": report, "sha256": hashlib.sha256(canonical(report)).hexdigest()}) + b"\n"
    if token and token.encode("utf-8") in payload:
        raise ExportError("TOKEN_IN_OUTPUT")
    with _export_directory() as directory:
        # Nom généré, relatif au même descripteur pour écrire, publier et nettoyer.
        temporary = ".sonar-export-" + secrets.token_hex(16)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory,
                        follow_symlinks=False)
            except FileExistsError:
                raise ExportError("OUTPUT_EXISTS") from None
        finally:
            os.unlink(temporary, dir_fd=directory)


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse peut répéter un argument erroné contenant accidentellement un secret.
        self.exit(2, "SONAR_EXPORT_BLOCKED: ARGUMENTS_INVALID; utiliser --help\n")


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Commit Git exact attendu, 40 hex minuscules")
    parser.add_argument("--output", type=Path, required=True, help="Nom JSON dans .opsys/diagnostics du dépôt ; répertoire existant")
    args = parser.parse_args(argv)
    try:
        _output_name(args.output)
        token = os.environ.get("SONAR_TOKEN", "")
        report = collect(SonarClient(token).get, args.revision)
        write_export(args.output, report, token)
    except ExportError as exc:
        print(f"SONAR_EXPORT_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("SONAR_EXPORT_BLOCKED: OUTPUT_IO_ERROR", file=sys.stderr)
        return 2
    code = diagnostic_exit_code(report)
    print(f"SONAR_DIAGNOSTIC_EXPORTED: gate={report['quality_gate']['status']} rc={code}; quality_verified=false")
    return code


if __name__ == "__main__":
    sys.exit(main())
