import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "run-e2e.sh"
_BASH = shutil.which("bash") or "/usr/bin/bash"


def _recording_python(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "python-argv.log"
    wrapper = tmp_path / "python-wrapper"
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "import sys\n"
        f"with open({str(log)!r}, 'a', encoding='utf-8') as stream:\n"
        "    stream.write(' '.join(sys.argv[1:]) + '\\n')\n"
        "arguments = sys.argv[1:]\n"
        "single_test = os.environ.get('E2E_PROBE_SINGLE_TEST')\n"
        "if arguments[:2] == ['-m', 'pytest'] and single_test:\n"
        "    arguments = ['-m', 'pytest', single_test, '-q']\n"
        "os.execv(sys.executable, [sys.executable, *arguments])\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper, log


def test_run_e2e_refuse_un_interpreteur_implicite():
    if os.environ.get("E2E_PROBE_NESTED") == "1":
        pytest.skip("évite de relancer le test de contrat depuis le harnais")

    env = {**os.environ, "E2E_PROBE_NESTED": "1"}
    env.pop("PYTHON_BIN", None)

    completed = subprocess.run(
        [_BASH, str(SCRIPT), "e2e"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )

    assert completed.returncode == 10
    assert "PYTHON_BIN" in completed.stderr


def test_run_e2e_utilise_l_interpreteur_declare(tmp_path):
    if os.environ.get("E2E_PROBE_NESTED") == "1":
        pytest.skip("évite de relancer le test de contrat depuis le harnais")

    wrapper, log = _recording_python(tmp_path)
    env = {
        **os.environ,
        "PYTHON_BIN": str(wrapper),
        "E2E_PROBE_NESTED": "1",
        "E2E_PROBE_SINGLE_TEST": str(REPO_ROOT / "tests/e2e/test_e2e_brand.py"),
    }

    completed = subprocess.run(
        [_BASH, str(SCRIPT), "e2e"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )

    assert completed.returncode == 0, (
        f"L'E2E doit utiliser l'interpréteur déclaré.\n"
        f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
    )
    assert "-m pytest" in log.read_text(encoding="utf-8")


def test_ci_e2e_installe_le_lock_et_declare_son_interpreteur():
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert workflow.count("PYTHON_BIN: python3") == 2
    assert workflow.count(
        "python3 -m pip install --quiet --require-hashes -r tests/e2e/requirements.lock"
    ) == 2
