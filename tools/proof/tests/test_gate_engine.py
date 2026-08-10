"""Tests pour tools/proof/gate_engine.py (C01-006).

Couvre les 4 cas RED obligatoires de tasks/C01-006.md :
  1. ne pas promouvoir NOT_EVALUATED
  2. exécuter chaque argv sans shell
  3. timeout ou outil absent = ERROR
  4. un fichier présent ne satisfait pas un contrôle sémantique

Corrige directement AOA-002 (ANALYSE-FORENSIQUE-COMPLETE.md) : « phase_cli.py
convertit NOT_EVALUATED en SATISFIED et vérifie surtout l'existence nominale
de livrables ». Ce moteur ne doit reproduire ni l'un ni l'autre défaut.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gate_engine import CheckResult, GateResult, evaluate_gate  # noqa: E402


def _phase(checks: list[dict], task_ids: list[str] | None = None) -> dict:
    return {
        "phase": "C01",
        "task_ids": task_ids if task_ids is not None else ["C01-001"],
        "checks": checks,
        "closure_rule": "All tasks VERIFIED, all executable checks return the expected code.",
    }


def _state(statuses: dict[str, str]) -> dict:
    return {"tasks": {tid: {"status": s} for tid, s in statuses.items()}}


# ---------------------------------------------------------------------------
# Cas RED 1 — ne pas promouvoir NOT_EVALUATED
# ---------------------------------------------------------------------------


def test_impl_menter_les_gates_s_mantiques_ex_cutables_1(tmp_path):
    """Une tâche déclarée NOT_EVALUATED ne doit jamais produire un gate satisfied,
    même si tous les checks déclarés réussiraient réellement."""
    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-01",
                "argv": [sys.executable, "-c", "import sys; sys.exit(0)"],
                "expected_returncode": 0,
                "timeout_s": 5,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "NOT_EVALUATED"})
    result = evaluate_gate(phase, state, tmp_path)
    assert isinstance(result, GateResult)
    assert result.satisfied is False
    assert result.status == "TASKS_NOT_VERIFIED"
    assert "C01-001" in result.reasons
    # Aucun check ne doit avoir été exécuté : la précondition tâches échoue
    # avant toute mesure — c'est la garde anti-AOA-002 (jamais mesurer un
    # gate sur un travail non vérifié).
    assert result.checks == ()


def test_tache_absente_de_state_traitee_comme_non_verifiee(tmp_path):
    """Une tâche listée dans phase['task_ids'] mais absente de state['tasks']
    (jamais journalisée) doit bloquer exactement comme NOT_EVALUATED — une
    absence n'est pas une preuve de succès."""
    phase = _phase(checks=[], task_ids=["C01-999"])
    state = _state({})
    result = evaluate_gate(phase, state, tmp_path)
    assert result.satisfied is False
    assert result.status == "TASKS_NOT_VERIFIED"
    assert "C01-999" in result.reasons


def test_toutes_taches_verified_et_checks_vides_est_satisfied(tmp_path):
    """Cas trivial mais nécessaire pour isoler le cas 1 : si tout est VERIFIED
    et qu'il n'y a aucun check déclaré, le gate est satisfied (vacuously)."""
    phase = _phase(checks=[], task_ids=["C01-001", "C01-002"])
    state = _state({"C01-001": "VERIFIED", "C01-002": "VERIFIED"})
    result = evaluate_gate(phase, state, tmp_path)
    assert result.satisfied is True
    assert result.status == "MEASURED_PASS"


# ---------------------------------------------------------------------------
# Cas RED 2 — exécuter chaque argv sans shell
# ---------------------------------------------------------------------------


def test_impl_menter_les_gates_s_mantiques_ex_cutables_2(tmp_path):
    """Un argv contenant des métacaractères shell (';', '&&', '$(...)') ne doit
    JAMAIS être interprété par un shell — la preuve est un effet de bord
    shell absent (aucun fichier créé par l'injection)."""
    piege = tmp_path / "injection_reussie.txt"
    argv_avec_injection = [
        sys.executable,
        "-c",
        "import sys; print(sys.argv[1])",
        f"; touch {piege} #",
    ]
    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-SHELL",
                "argv": argv_avec_injection,
                "expected_returncode": 0,
                "timeout_s": 5,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    result = evaluate_gate(phase, state, tmp_path)
    # Le check réussit (python affiche l'argument littéral et sort 0) mais
    # SURTOUT le fichier-piège ne doit jamais exister : si un shell avait
    # interprété la chaîne, `touch` aurait couru en dehors de l'argv.
    assert not piege.exists(), "métacaractères shell interprétés — argv non isolé"
    assert result.status == "MEASURED_PASS"
    assert result.checks[0].actual_returncode == 0


def test_argv_est_une_liste_jamais_une_chaine_concatenee(tmp_path):
    """L'argument contenant des espaces doit être transmis comme UN SEUL
    argv[1] au sous-processus (preuve indirecte que shell=False : sous un
    shell sans guillemets, la chaîne aurait été redécoupée par IFS)."""
    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-ARGC",
                "argv": [
                    sys.executable,
                    "-c",
                    "import sys; sys.exit(0 if len(sys.argv) == 2 else 1)",
                    "un seul argument avec espaces",
                ],
                "expected_returncode": 0,
                "timeout_s": 5,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    result = evaluate_gate(phase, state, tmp_path)
    assert result.status == "MEASURED_PASS"


# ---------------------------------------------------------------------------
# Cas RED 3 — timeout ou outil absent = ERROR
# ---------------------------------------------------------------------------


def test_impl_menter_les_gates_s_mantiques_ex_cutables_3(tmp_path):
    """Un outil absent (FileNotFoundError) produit un statut ERROR distinct de
    MEASURED_FAIL — ce n'est pas un échec de contrôle, c'est une impossibilité
    de mesurer."""
    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-ABSENT",
                "argv": ["ce-binaire-n-existe-certainement-pas-xyz-123"],
                "expected_returncode": 0,
                "timeout_s": 5,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    result = evaluate_gate(phase, state, tmp_path)
    assert result.satisfied is False
    assert result.status == "ERROR"
    assert result.checks[0].status == "ERROR"
    assert result.checks[0].actual_returncode is None
    assert result.checks[0].timed_out is False


def test_timeout_produit_error_distinct_de_measured_fail(tmp_path):
    """Un check qui dépasse son timeout_s produit ERROR (timed_out=True), pas
    MEASURED_FAIL — une bascule silencieuse vers FAIL masquerait un outil qui
    ne répond plus, un cas opérationnel distinct d'un contrôle qui échoue."""
    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-TIMEOUT",
                "argv": [sys.executable, "-c", "import time; time.sleep(5)"],
                "expected_returncode": 0,
                "timeout_s": 0.2,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    result = evaluate_gate(phase, state, tmp_path)
    assert result.satisfied is False
    assert result.status == "ERROR"
    assert result.checks[0].status == "ERROR"
    assert result.checks[0].timed_out is True


# ---------------------------------------------------------------------------
# Cas RED 4 — un fichier présent ne satisfait pas un contrôle sémantique
# ---------------------------------------------------------------------------


def test_impl_menter_les_gates_s_mantiques_ex_cutables_4(tmp_path):
    """AOA-002 direct : un fichier de sortie présent dans le worktree ne doit
    JAMAIS, à lui seul, satisfaire un check. Seul le code retour réel du
    sous-processus déclaré (argv) fait foi — jamais une inspection de
    présence de fichier en substitut."""
    # Le fichier que produirait normalement une vraie tâche existe déjà,
    # intact et non vide.
    livrable = tmp_path / "livrable_pretendument_complet.py"
    livrable.write_text("def fonction_reelle(): return 42\n", encoding="utf-8")
    assert livrable.exists() and livrable.stat().st_size > 0

    # Mais le check sémantique déclaré (qui mesure un VRAI comportement, pas
    # la présence du fichier) échoue réellement.
    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-SEMANTIQUE",
                "argv": [
                    sys.executable,
                    "-c",
                    "import sys; sys.exit(1)",  # échec réel et volontaire
                ],
                "expected_returncode": 0,
                "timeout_s": 5,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    result = evaluate_gate(phase, state, tmp_path)
    # La présence du livrable ne doit avoir AUCUNE influence : le gate mord.
    assert result.satisfied is False
    assert result.status == "MEASURED_FAIL"
    assert result.checks[0].actual_returncode == 1
    assert livrable.exists()  # toujours là — le moteur ne l'a ni lu ni jugé


def test_gate_engine_n_inspecte_jamais_le_systeme_de_fichiers_du_worktree(tmp_path, monkeypatch):
    """Garde structurelle : evaluate_gate ne doit appeler AUCUNE primitive de
    présence de fichier sur le worktree reçu — seule l'exécution du check
    fait foi. Empêche une régression future qui réintroduirait un raccourci
    « fichier présent = check satisfait » (AOA-002).

    Élargi suite à la revue tour 1 (Gemini, MAJEURE) : espionner UNIQUEMENT
    Path.exists laissait passer sans détection un contournement futur via
    Path.is_file/is_dir ou os.path.exists/isfile/os.stat — toutes les
    primitives de présence de fichier plausibles sont maintenant surveillées,
    pas une seule."""
    import os as os_module

    import gate_engine

    appels: list[Path] = []

    def _fait_espion(nom_attribut, original, extracteur_chemin):
        def _espion(*args, **kwargs):
            chemin = extracteur_chemin(*args, **kwargs)
            if chemin is not None:
                appels.append(Path(chemin))
            return original(*args, **kwargs)

        return _espion

    original_path_exists = Path.exists
    original_path_is_file = Path.is_file
    original_path_is_dir = Path.is_dir
    original_os_path_exists = os_module.path.exists
    original_os_path_isfile = os_module.path.isfile
    original_os_stat = os_module.stat

    monkeypatch.setattr(
        Path, "exists", _fait_espion("Path.exists", original_path_exists, lambda self: self)
    )
    monkeypatch.setattr(
        Path, "is_file", _fait_espion("Path.is_file", original_path_is_file, lambda self: self)
    )
    monkeypatch.setattr(
        Path, "is_dir", _fait_espion("Path.is_dir", original_path_is_dir, lambda self: self)
    )
    monkeypatch.setattr(
        os_module.path,
        "exists",
        _fait_espion("os.path.exists", original_os_path_exists, lambda p: p),
    )
    monkeypatch.setattr(
        os_module.path,
        "isfile",
        _fait_espion("os.path.isfile", original_os_path_isfile, lambda p: p),
    )
    monkeypatch.setattr(
        os_module, "stat", _fait_espion("os.stat", original_os_stat, lambda p, **kw: p)
    )

    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-01",
                "argv": [sys.executable, "-c", "import sys; sys.exit(0)"],
                "expected_returncode": 0,
                "timeout_s": 5,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    gate_engine.evaluate_gate(phase, state, tmp_path)
    chemins_worktree = [p for p in appels if tmp_path in p.parents or p == tmp_path]
    assert chemins_worktree == []


# ---------------------------------------------------------------------------
# Robustesse structurelle de GateResult / CheckResult
# ---------------------------------------------------------------------------


def test_gate_result_et_check_result_sont_geles(tmp_path):
    """GateResult/CheckResult sont des structures immuables (frozen) — un
    résultat de mesure ne doit pas pouvoir être réécrit après coup pour
    fabriquer un faux verdict."""
    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-01",
                "argv": [sys.executable, "-c", "import sys; sys.exit(0)"],
                "expected_returncode": 0,
                "timeout_s": 5,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    result = evaluate_gate(phase, state, tmp_path)
    with pytest.raises(Exception):
        result.satisfied = False
    with pytest.raises(Exception):
        result.checks[0].actual_returncode = 999


def test_plusieurs_checks_measured_fail_liste_tous_les_check_id_en_echec(tmp_path):
    """Avec plusieurs checks déclarés, un seul en échec doit suffire à faire
    échouer le gate, et les reasons doivent identifier PRÉCISÉMENT lequel —
    jamais un verdict agrégé muet."""
    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-OK",
                "argv": [sys.executable, "-c", "import sys; sys.exit(0)"],
                "expected_returncode": 0,
                "timeout_s": 5,
            },
            {
                "check_id": "C01-CHK-KO",
                "argv": [sys.executable, "-c", "import sys; sys.exit(1)"],
                "expected_returncode": 0,
                "timeout_s": 5,
            },
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    result = evaluate_gate(phase, state, tmp_path)
    assert result.satisfied is False
    assert result.status == "MEASURED_FAIL"
    assert result.reasons == ("C01-CHK-KO",)
    assert len(result.checks) == 2


# ---------------------------------------------------------------------------
# Corrections revue tour 1 (Gemini-3.1-Pro, INDEPENDENT_REVIEW)
# ---------------------------------------------------------------------------


def test_reasons_agrege_error_et_fail_quand_les_deux_coexistent(tmp_path):
    """MAJEURE->mineure (revue tour 1) : quand un check est en ERROR et un
    AUTRE en FAIL dans le même gate, `reasons` ne doit PAS se limiter au(x)
    check_id en ERROR — le FAIL doit rester visible dans reasons, même si
    `status` global reste "ERROR" (priorité de statut inchangée). Un lecteur
    de `reasons` seul ne doit jamais perdre l'information qu'un check a
    RÉELLEMENT échoué, pas seulement qu'un autre n'a pas pu être mesuré."""
    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-ABSENT",
                "argv": ["ce-binaire-n-existe-certainement-pas-xyz-123"],
                "expected_returncode": 0,
                "timeout_s": 5,
            },
            {
                "check_id": "C01-CHK-ECHOUE",
                "argv": [sys.executable, "-c", "import sys; sys.exit(1)"],
                "expected_returncode": 0,
                "timeout_s": 5,
            },
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    result = evaluate_gate(phase, state, tmp_path)
    assert result.satisfied is False
    assert result.status == "ERROR"  # priorité ERROR sur FAIL inchangée
    assert set(result.reasons) == {"C01-CHK-ABSENT", "C01-CHK-ECHOUE"}, (
        "reasons doit contenir le check en FAIL en plus du check en ERROR, "
        f"reçu {result.reasons}"
    )


def test_permission_error_produit_error_jamais_de_crash(tmp_path):
    """mineure (revue tour 1) : un outil PRÉSENT mais SANS droit d'exécution
    (PermissionError, EACCES) doit produire un CheckResult status=ERROR
    propre, exactement comme un outil ABSENT — jamais laisser l'exception
    remonter et faire planter evaluate_gate. Reproduit une panne opérationnelle
    réaliste (script qui a perdu son bit +x), distincte de FileNotFoundError."""
    binaire_non_executable = tmp_path / "script_sans_droit_exec.sh"
    binaire_non_executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binaire_non_executable.chmod(0o644)  # explicitement PAS exécutable
    assert not (binaire_non_executable.stat().st_mode & 0o111)

    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-SANS-DROIT",
                "argv": [str(binaire_non_executable)],
                "expected_returncode": 0,
                "timeout_s": 5,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    # Ne doit lever AUCUNE exception : evaluate_gate doit capturer
    # PermissionError et produire un GateResult, jamais crasher.
    result = evaluate_gate(phase, state, tmp_path)
    assert result.satisfied is False
    assert result.status == "ERROR"
    assert result.checks[0].status == "ERROR"
    assert result.checks[0].actual_returncode is None
    assert result.checks[0].timed_out is False
    assert result.checks[0].error is not None


def test_not_a_directory_error_composant_chemin_argv_produit_error(tmp_path):
    """mineure (revue tour 3, Qwen — vérifiée vraie empiriquement) : un argv[0]
    dont un COMPOSANT du chemin traite un fichier comme un répertoire (ex.
    <fichier>/<suite>) lève NotADirectoryError, jamais capturé auparavant —
    doit produire ERROR proprement, pas planter evaluate_gate. Scénario réel
    reproduit directement (pas un mock), confirmé par exécution empirique
    avant d'écrire ce test."""
    un_fichier = tmp_path / "pas_un_dossier.txt"
    un_fichier.write_text("contenu", encoding="utf-8")
    chemin_invalide = un_fichier / "composant_apres_un_fichier"

    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-COMPOSANT-INVALIDE",
                "argv": [str(chemin_invalide)],
                "expected_returncode": 0,
                "timeout_s": 5,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    result = evaluate_gate(phase, state, tmp_path)
    assert result.satisfied is False
    assert result.status == "ERROR"
    assert result.checks[0].status == "ERROR"
    assert result.checks[0].actual_returncode is None


def test_not_a_directory_error_worktree_est_un_fichier_produit_error(tmp_path):
    """mineure (revue tour 3, Qwen — vérifiée vraie empiriquement, second
    chemin distinct) : `worktree` lui-même (passé en `cwd` à subprocess.run)
    peut être un FICHIER plutôt qu'un répertoire — evaluate_gate ne valide
    jamais son 3e paramètre. Doit produire ERROR proprement, pas planter."""
    worktree_invalide = tmp_path / "worktree_est_un_fichier.txt"
    worktree_invalide.write_text("contenu", encoding="utf-8")

    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-CWD-INVALIDE",
                "argv": [sys.executable, "-c", "import sys; sys.exit(0)"],
                "expected_returncode": 0,
                "timeout_s": 5,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    result = evaluate_gate(phase, state, worktree_invalide)
    assert result.satisfied is False
    assert result.status == "ERROR"
    assert result.checks[0].status == "ERROR"
    assert result.checks[0].actual_returncode is None


def test_exec_format_error_fichier_invalide_produit_error_jamais_de_crash(tmp_path):
    """mineure (revue tour 4, DeepSeek — vérifiée vraie empiriquement) : un
    fichier marqué exécutable (+x) mais de format binaire/script invalide
    (ENOEXEC, « Exec format error ») lève un OSError GÉNÉRIQUE — sans
    sous-classe nommée dans la hiérarchie Python (contrairement à
    FileNotFoundError/PermissionError/NotADirectoryError, qui EN ont une).
    Preuve que « énumérer les sous-classes nommées » ne peut jamais être
    complet — seul `except OSError` capture ce cas. Scénario réel reproduit
    directement (pas un mock), confirmé par exécution empirique avant
    d'écrire ce test."""
    script_invalide = tmp_path / "script_format_invalide"
    script_invalide.write_text("ceci n'est pas un script valide, aucun shebang\n", encoding="utf-8")
    script_invalide.chmod(0o755)

    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-FORMAT-INVALIDE",
                "argv": [str(script_invalide)],
                "expected_returncode": 0,
                "timeout_s": 5,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    result = evaluate_gate(phase, state, tmp_path)
    assert result.satisfied is False
    assert result.status == "ERROR"
    assert result.checks[0].status == "ERROR"
    assert result.checks[0].actual_returncode is None


# ---------------------------------------------------------------------------
# Correction revue tour 5 (Gemini-3.1-Pro, MAJEURE)
# ---------------------------------------------------------------------------


def test_stdout_stderr_sont_captures_et_exposes_sur_check_fail(tmp_path):
    """MAJEURE (revue tour 5, Gemini — mesurée vraie) : stdout/stderr étaient
    capturés (subprocess.PIPE) puis totalement ignorés — un check en échec
    devenait indébogable pour un humain/orchestrateur qui lit le GateResult
    (aucune trace de ce que l'outil a réellement affiché). Un check qui écrit
    des messages DISTINCTS et identifiables sur stdout et stderr avant
    d'échouer doit voir ces DEUX flux exposés, texte par texte, sur le
    CheckResult correspondant."""
    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-SORTIE",
                "argv": [
                    sys.executable,
                    "-c",
                    "import sys; print('MARQUEUR-STDOUT-UNIQUE'); "
                    "print('MARQUEUR-STDERR-UNIQUE', file=sys.stderr); sys.exit(1)",
                ],
                "expected_returncode": 0,
                "timeout_s": 5,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    result = evaluate_gate(phase, state, tmp_path)
    assert result.status == "MEASURED_FAIL"
    assert "MARQUEUR-STDOUT-UNIQUE" in result.checks[0].stdout
    assert "MARQUEUR-STDERR-UNIQUE" in result.checks[0].stderr


def test_stdout_stderr_sont_captures_sur_check_pass(tmp_path):
    """Même garantie sur un check qui RÉUSSIT : la sortie n'est pas
    seulement conservée pour les échecs, elle est toujours exposée — un
    orchestrateur peut vouloir inspecter la sortie d'un check qui passe
    (ex. un résumé de couverture)."""
    phase = _phase(
        checks=[
            {
                "check_id": "C01-CHK-SORTIE-OK",
                "argv": [sys.executable, "-c", "print('SORTIE-SUR-SUCCES'); import sys; sys.exit(0)"],
                "expected_returncode": 0,
                "timeout_s": 5,
            }
        ],
        task_ids=["C01-001"],
    )
    state = _state({"C01-001": "VERIFIED"})
    result = evaluate_gate(phase, state, tmp_path)
    assert result.status == "MEASURED_PASS"
    assert "SORTIE-SUR-SUCCES" in result.checks[0].stdout
