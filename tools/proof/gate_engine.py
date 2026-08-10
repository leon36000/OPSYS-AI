from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile

# Plafond de sécurité par flux (revue tours 6-7, CRITIQUE confirmée) : un
# check qui produit une quantité massive de logs AVANT l'expiration de son
# timeout ne doit jamais pouvoir faire exploser la mémoire du process
# Python hôte. stdout/stderr sont redirigés vers des fichiers temporaires
# (jamais subprocess.PIPE) — le système de fichiers absorbe une sortie de
# taille arbitraire SANS toucher la mémoire Python pendant l'exécution ;
# seule la relecture explicite après coup, plafonnée à cette taille, entre
# en mémoire.
_MAX_OUTPUT_BYTES = 1_048_576  # 1 MiB par flux


def _lire_sortie_bornee(fichier) -> str:
    """Relit un fichier de sortie de sous-processus, plafonné en taille.
    Le fichier lui-même peut avoir grossi sans limite pendant l'exécution
    (écrit directement par l'enfant via son descripteur, jamais bufferisé
    par Python) — seule CETTE lecture entre en mémoire, et elle est bornée."""
    fichier.seek(0, 2)  # fin de fichier, pour connaître la taille réelle
    taille_totale = fichier.tell()
    fichier.seek(0)
    donnees = fichier.read(_MAX_OUTPUT_BYTES)
    texte = donnees.decode("utf-8", errors="replace")
    if taille_totale > _MAX_OUTPUT_BYTES:
        texte += (
            f"\n...[TRONQUÉ — {taille_totale} octets au total, "
            f"{_MAX_OUTPUT_BYTES} conservés]..."
        )
    return texte


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    argv: tuple[str, ...]
    expected_returncode: int
    actual_returncode: int | None
    status: str
    timed_out: bool
    error: str | None
    stdout: str
    stderr: str


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
        with tempfile.TemporaryFile() as stdout_fichier, tempfile.TemporaryFile() as stderr_fichier:
            try:
                completed_process = subprocess.run(
                    list(check["argv"]),
                    cwd=worktree,
                    stdout=stdout_fichier,
                    stderr=stderr_fichier,
                    timeout=check["timeout_s"],
                    shell=False,
                )
            except subprocess.TimeoutExpired:
                # revue tour 5 (Gemini, MAJEURE, mesurée vraie) : stdout/stderr
                # étaient capturés puis totalement ignorés — un check en
                # échec devenait indébogable. Relus depuis LES FICHIERS
                # temporaires (jamais depuis exc.stdout/.stderr — inexistants
                # avec une redirection fichier, jamais PIPE) : tout ce que
                # l'enfant a écrit avant le kill reste lisible, plafonné.
                results.append(
                    CheckResult(
                        check_id=check["check_id"],
                        argv=argv,
                        expected_returncode=expected_returncode,
                        actual_returncode=None,
                        status="ERROR",
                        timed_out=True,
                        error="TIMEOUT",
                        stdout=_lire_sortie_bornee(stdout_fichier),
                        stderr=_lire_sortie_bornee(stderr_fichier),
                    )
                )
            except OSError as exc:
                # Historique complet (4 tours de revue, chaque étape mesurée
                # avant application, jamais acceptée sur la seule autorité
                # d'un modèle) :
                #   Tour 1 (Gemini) : FileNotFoundError seul -> élargi à
                #     (FileNotFoundError, PermissionError).
                #   Tour 2 (DeepSeek) : OSError large -> rétréci, car
                #     engloberait InterruptedError (EINTR, transitoire).
                #   Tour 3 (Qwen) : + NotADirectoryError (confirmé
                #     empiriquement, 2 scénarios réels) ; IsADirectoryError
                #     REJETÉE (justification du tour 3 vérifiée FAUSSE — un
                #     répertoire exécuté lève PermissionError sur cette
                #     plateforme, PAS IsADirectoryError, y compris avec le
                #     bit +x explicitement posé, re-vérifié au tour 4).
                #   Tour 4 (DeepSeek) : signale ENOEXEC (« Exec format
                #     error » — un fichier +x au format binaire/script
                #     invalide) — CONFIRMÉ empiriquement : c'est un OSError
                #     GÉNÉRIQUE (errno=8), qui n'a PAS de sous-classe nommée
                #     dans la hiérarchie Python (contrairement à
                #     ENOENT/EACCES/ENOTDIR/EISDIR/EINTR qui, eux, en ont
                #     une). Conséquence structurelle : énumérer des sous-
                #     classes nommées ne peut JAMAIS être complet — il
                #     existe des errno « outil inutilisable » sans sous-
                #     classe dédiée. Seul `OSError` (le parent commun)
                #     couvre TOUS les cas actuels ET futurs.
                #
                #   Le retour à `OSError` large est donc correct — la
                #   réintroduction du risque InterruptedError (tour 2) est
                #   réexaminée, pas ignorée : ce dépôt tourne sur Python
                #   3.12.3 (vérifié : `sys.version_info`), où la PEP 475
                #   (Python 3.5+) fait déjà réessayer automatiquement, AU
                #   NIVEAU C, tout appel système interrompu par EINTR
                #   utilisé en interne par `subprocess.Popen`/
                #   `subprocess.run` — InterruptedError ne remonte donc, en
                #   pratique, JAMAIS jusqu'à ce niveau Python sur cette
                #   plateforme. Et même dans un résidu improbable où elle
                #   remonterait : produire un CheckResult ERROR (rejouable
                #   par l'appelant) est un dégradé plus sûr qu'une
                #   exception non capturée qui ferait planter TOUT
                #   evaluate_gate — y compris les checks suivants de la
                #   même liste — pour un seul signal transitoire sur un
                #   seul check.
                results.append(
                    CheckResult(
                        check_id=check["check_id"],
                        argv=argv,
                        expected_returncode=expected_returncode,
                        actual_returncode=None,
                        status="ERROR",
                        timed_out=False,
                        error=str(exc),
                        stdout="",  # aucun sous-processus n'a jamais démarré
                        stderr="",
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
                        stdout=_lire_sortie_bornee(stdout_fichier),
                        stderr=_lire_sortie_bornee(stderr_fichier),
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
