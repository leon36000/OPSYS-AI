from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    argv: tuple[str, ...]
    expected_returncode: int
    actual_returncode: int | None
    status: str
    timed_out: bool
    error: str | None


@dataclass(frozen=True)
class GateResult:
    satisfied: bool
    status: str
    reasons: tuple[str, ...]
    checks: tuple[CheckResult, ...]


def evaluate_gate(phase: dict, state: dict, worktree: Path) -> GateResult:
    task_ids = phase.get("task_ids", [])
    tasks = state.get("tasks", {})
    unverified_task_ids = tuple(
        task_id
        for task_id in task_ids
        if tasks.get(task_id, {}).get("status") != "VERIFIED"
    )

    if unverified_task_ids:
        return GateResult(
            satisfied=False,
            status="TASKS_NOT_VERIFIED",
            reasons=unverified_task_ids,
            checks=(),
        )

    results: list[CheckResult] = []
    for check in phase.get("checks", []):
        argv = tuple(check["argv"])
        expected_returncode = check["expected_returncode"]
        try:
            completed_process = subprocess.run(
                list(check["argv"]),
                cwd=worktree,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=check["timeout_s"],
                shell=False,
            )
        except subprocess.TimeoutExpired:
            results.append(
                CheckResult(
                    check_id=check["check_id"],
                    argv=argv,
                    expected_returncode=expected_returncode,
                    actual_returncode=None,
                    status="ERROR",
                    timed_out=True,
                    error="TIMEOUT",
                )
            )
        except (FileNotFoundError, PermissionError) as exc:
            # Exactement les deux impossibilités de MESURER (jamais un échec
            # de contrôle) : outil absent (FileNotFoundError, ENOENT) et
            # outil présent mais non exécutable (PermissionError, EACCES) —
            # revue tour 1 (Gemini, élargi depuis FileNotFoundError seul).
            # PAS `except OSError` (revue tour 2, DeepSeek, mineure mesurée
            # vraie) : OSError engloberait aussi InterruptedError (EINTR,
            # interruption système TRANSITOIRE par signal) — un cas qui
            # n'est ni « outil absent » ni « outil inutilisable », et que
            # traiter comme ERROR masquerait une interruption qui devrait
            # normalement se résoudre par une ré-exécution, pas un verdict
            # définitif. Capturer exactement les deux exceptions nommées,
            # rien de plus large.
            results.append(
                CheckResult(
                    check_id=check["check_id"],
                    argv=argv,
                    expected_returncode=expected_returncode,
                    actual_returncode=None,
                    status="ERROR",
                    timed_out=False,
                    error=str(exc),
                )
            )
        else:
            actual_returncode = completed_process.returncode
            status = (
                "PASS"
                if actual_returncode == expected_returncode
                else "FAIL"
            )
            results.append(
                CheckResult(
                    check_id=check["check_id"],
                    argv=argv,
                    expected_returncode=expected_returncode,
                    actual_returncode=actual_returncode,
                    status=status,
                    timed_out=False,
                    error=None,
                )
            )

    checks = tuple(results)
    error_reasons = tuple(
        result.check_id for result in checks if result.status == "ERROR"
    )
    if error_reasons:
        # reasons agrège ERROR *et* FAIL (revue tour 1, Gemini) : un gate qui
        # a un check en ERROR ET un autre en FAIL simultanément ne doit pas
        # masquer le FAIL — status reste "ERROR" (priorité inchangée), mais
        # reasons expose TOUS les check_id en échec, pas seulement le sous-
        # ensemble ERROR, pour qu'un lecteur n'ait pas à consulter `checks`
        # en plus pour découvrir le FAIL après avoir corrigé l'ERROR.
        non_pass_reasons = tuple(
            result.check_id for result in checks if result.status != "PASS"
        )
        return GateResult(
            satisfied=False,
            status="ERROR",
            reasons=non_pass_reasons,
            checks=checks,
        )

    fail_reasons = tuple(
        result.check_id for result in checks if result.status == "FAIL"
    )
    if fail_reasons:
        return GateResult(
            satisfied=False,
            status="MEASURED_FAIL",
            reasons=fail_reasons,
            checks=checks,
        )

    return GateResult(
        satisfied=True,
        status="MEASURED_PASS",
        reasons=(),
        checks=checks,
    )
