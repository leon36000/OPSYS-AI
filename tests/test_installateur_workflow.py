"""Contrat des checks installateur hosted et des E2E poste Docker auto-hébergés.

Les tests scripts/fakes tournent sur les runners hosted. Les E2E macOS/Windows exigent un runner du propriétaire avec
daemon Linux et s'activent seulement par workflow_dispatch explicite. Ces tests vérifient la séparation, les prévols,
les diagnostics qui masquent les secrets, les actions épinglées et les scripts.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[1]
WORKFLOW = RACINE / ".github" / "workflows" / "installateur.yml"
INSTALLATIONS = {
    "installation": "ubuntu-24.04", "installation-macos": "macos-latest", "installation-windows": "windows-latest"}
INSTALLATIONS_DOCKER = {
    "installation-macos-docker": ["self-hosted", "macOS", "opsys-docker-linux"],
    "installation-windows-docker": ["self-hosted", "Windows", "opsys-docker-linux"],
}
TOUS_LES_JOBS_INSTALLATION = (*INSTALLATIONS, *INSTALLATIONS_DOCKER)
JOBS_E2E_REEL = ("installation", *INSTALLATIONS_DOCKER)


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _declencheurs(workflow: dict) -> dict:
    return workflow[True] if True in workflow else workflow["on"]  # YAML 1.1 lit `on` comme le booléen vrai


def _etapes(workflow: dict, job: str) -> list[dict]:
    return workflow["jobs"][job]["steps"]


def test_le_fichier_se_charge_et_porte_les_six_jobs(workflow):
    assert set(workflow["jobs"]) == {"analyse", *INSTALLATIONS, *INSTALLATIONS_DOCKER}
    assert workflow["permissions"] == {"contents": "read"}


@pytest.mark.parametrize("job", sorted(INSTALLATIONS))
def test_chaque_installation_tourne_sur_son_systeme(workflow, job):
    assert workflow["jobs"][job]["runs-on"] == INSTALLATIONS[job]


@pytest.mark.parametrize("job", sorted(INSTALLATIONS_DOCKER))
def test_les_e2e_poste_docker_utilisent_les_labels_self_hosted(workflow, job):
    assert workflow["jobs"][job]["runs-on"] == INSTALLATIONS_DOCKER[job]
    condition = "${{ github.event_name == 'workflow_dispatch' && inputs.preuve_poste_docker }}"
    assert workflow["jobs"][job]["if"] == condition


def test_les_checks_hosted_conservent_les_declencheurs_automatiques_du_job_linux(workflow):
    """Les tests/faux restent automatiques; seuls les vrais E2E poste Docker sont opt-in."""
    declencheurs = _declencheurs(workflow)
    assert set(declencheurs) == {"workflow_dispatch", "push", "pull_request"}
    assert declencheurs["push"]["paths"] == declencheurs["pull_request"]["paths"]
    for chemin in ("install/**", "tests/installateur/**", "tests/test_installateur_*.py",
                   ".github/workflows/installateur.yml", "src/opsys/instance.py",
                   "src/opsys/exportation.py", "src/opsys/openclaw.py", "uv.lock", "requirements-runtime.lock.txt"):
        assert chemin in declencheurs["pull_request"]["paths"]
    # T0.7 lot 3 : ce qui décide où le core range son état, et la migration de Doctor, relancent la preuve
    for chemin in ("core/src/config/opsys-instance.ts", "core/src/config/paths.ts", "core/src/cli/profile.ts",
                   "core/src/cli/profile-utils.ts", "core/src/daemon/paths.ts",
                   "core/src/infra/state-migrations.opsys-instance.ts", "core/src/infra/state-migrations.state-dir.ts",
                   "core/openclaw.mjs"):
        assert chemin in declencheurs["pull_request"]["paths"], chemin
    for job in INSTALLATIONS:
        assert "if" not in workflow["jobs"][job], f"{job} ne doit pas avoir de condition propre"
        assert "needs" not in workflow["jobs"][job], f"{job} ne dépend d'aucun autre job"
        assert "strategy" not in workflow["jobs"][job]
    entree = declencheurs["workflow_dispatch"]["inputs"]["preuve_poste_docker"]
    assert entree["type"] == "boolean" and entree["default"] is False
    for job in INSTALLATIONS_DOCKER:
        assert "needs" not in workflow["jobs"][job]
        assert "strategy" not in workflow["jobs"][job]


@pytest.mark.parametrize("job", sorted(TOUS_LES_JOBS_INSTALLATION))
def test_chaque_installation_a_un_plafond_de_duree_raisonnable(workflow, job):
    delai = workflow["jobs"][job]["timeout-minutes"]

    # assez pour construire le core, pas assez pour brûler des minutes
    assert isinstance(delai, int) and 30 <= delai <= 150
    if job in INSTALLATIONS_DOCKER:
        assert delai >= workflow["jobs"]["installation"]["timeout-minutes"]  # ces systèmes construisent plus lentement


def test_aucune_etape_ne_tolere_l_echec(workflow):
    for job in TOUS_LES_JOBS_INSTALLATION:
        for etape in _etapes(workflow, job):
            nom = etape.get("name", etape.get("uses", "?"))
            assert "continue-on-error" not in etape, f"{job} / {nom}"
            corps = etape.get("run", "")
            assert "|| true" not in corps and "set +e" not in corps, f"{job} / {nom}"
            assert "-ErrorAction SilentlyContinue" not in corps, f"{job} / {nom}"
            assert "$ErrorActionPreference = 'SilentlyContinue'" not in corps, f"{job} / {nom}"
    assert "continue-on-error" not in WORKFLOW.read_text(encoding="utf-8")


def test_chaque_etape_a_un_nom_ou_une_action_et_les_actions_sont_epinglees_par_empreinte(workflow):
    for job in workflow["jobs"]:
        for etape in _etapes(workflow, job):
            assert etape.get("name") or etape.get("uses"), f"{job} : étape sans nom"
            if "uses" in etape:
                epinglee = re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", etape["uses"])
                assert epinglee, f"{job} : {etape['uses']} n'est pas épinglée"


@pytest.mark.parametrize("job", ["installation-macos-docker", "installation-windows-docker"])
def test_le_service_est_requis_et_l_entree_sans_service_est_transmise(workflow, job):
    env = workflow["jobs"][job]["env"]

    assert env["OPSYS_SERVICE_REQUIS"] == "1"  # sans service utilisateur, le job échoue en le disant
    assert env["OPSYS_SANS_SERVICE"] == "${{ inputs.sans_service || '0' }}"


@pytest.mark.parametrize("job", JOBS_E2E_REEL)
def test_le_dossier_de_travail_est_pose_par_etape_car_le_contexte_runner_n_existe_pas_au_niveau_du_job(workflow, job):
    """GitHub refuse `${{ runner.temp }}` dans le `env` d'un job (actionlint l'a montré) : il vit dans les étapes."""
    assert "runner." not in str(workflow["jobs"][job].get("env", {}))
    motif = r"(bash tests/installateur/|\./tests/installateur/)(bout_en_bout|diagnostic)\.(sh|ps1)"
    scripts = [e for e in _etapes(workflow, job) if re.search(motif, e.get("run", ""))]
    assert len(scripts) == 2, "la preuve et son diagnostic"
    for etape in scripts:
        travail = etape["env"]["OPSYS_TRAVAIL"]
        assert travail.startswith("${{ runner.temp }}") and travail.endswith("installateur"), etape["name"]


def test_l_entree_sans_service_du_job_linux_est_inchangee(workflow):
    etape = next(e for e in _etapes(workflow, "installation") if "bout_en_bout.sh" in e.get("run", ""))

    assert etape["env"]["OPSYS_SANS_SERVICE"] == "${{ inputs.sans_service || '0' }}"
    assert "OPSYS_SERVICE_REQUIS" not in etape["env"]  # Linux : l'absence de systemd --user reste dite, pas refusée
    entree = _declencheurs(workflow)["workflow_dispatch"]["inputs"]["sans_service"]
    assert entree["options"] == ["0", "1"] and entree["default"] == "0"


def _etape_de_preuve(workflow, job: str) -> dict:
    marque = "bout_en_bout.ps1" if job == "installation-windows-docker" else "bout_en_bout.sh"
    return next(e for e in _etapes(workflow, job) if marque in e.get("run", ""))


def test_macos_joue_le_script_de_preuve_bash_du_depot(workflow):
    etape = _etape_de_preuve(workflow, "installation-macos-docker")

    assert etape["run"].strip() == "bash tests/installateur/bout_en_bout.sh"
    assert "shell" not in etape  # bash de macOS, comme le script l'annonce (bash 3.2 compris)
    assert workflow["jobs"]["installation-macos-docker"]["runs-on"] == ["self-hosted", "macOS", "opsys-docker-linux"]


def test_windows_joue_le_script_de_preuve_powershell_avec_pwsh_et_propage_le_code_de_sortie(workflow):
    etape = _etape_de_preuve(workflow, "installation-windows-docker")

    assert etape["shell"] == "pwsh"
    assert "& ./tests/installateur/bout_en_bout.ps1" in etape["run"]
    assert "exit $LASTEXITCODE" in etape["run"]
    assert workflow["jobs"]["installation-windows-docker"]["runs-on"] == [
        "self-hosted", "Windows", "opsys-docker-linux"]


@pytest.mark.parametrize(("job", "commande"), [
    ("installation", "bash tests/installateur/diagnostic.sh"),
    ("installation-macos-docker", "bash tests/installateur/diagnostic.sh"),
    ("installation-windows-docker", "./tests/installateur/diagnostic.ps1"),
])
def test_un_echec_est_suivi_d_un_diagnostic_qui_ne_montre_aucun_secret(workflow, job, commande):
    dernieres = _etapes(workflow, job)[-1]

    assert dernieres["if"] == "failure()"
    assert dernieres["run"].strip() == commande  # un script lu, testé, qui masque les secrets (pas un tail en ligne)
    for etape in _etapes(workflow, job)[:-1]:
        assert etape.get("if") != "failure()"  # une seule étape de diagnostic, la dernière


def test_les_scripts_que_le_workflow_appelle_existent(workflow):
    for job in workflow["jobs"]:
        for etape in _etapes(workflow, job):
            for chemin in re.findall(r"(?:tests/installateur|install)/[A-Za-z_./-]+\.(?:sh|ps1)", etape.get("run", "")):
                assert (RACINE / chemin).is_file(), f"{job} appelle {chemin}, qui n'existe pas"


def test_les_tests_python_du_job_linux_comprennent_les_nouveaux_fichiers(workflow):
    corps = next(e["run"] for e in _etapes(workflow, "installation") if "pytest" in e.get("run", ""))

    for fichier in ("test_installateur_scripts.py", "test_installateur_windows.py",
                    "test_installateur_powershell_faux.py", "test_installateur_bout_en_bout.py",
                    "test_installateur_workflow.py", "test_instance.py", "test_exportation.py"):
        assert f"tests/{fichier}" in corps
        assert (RACINE / "tests" / fichier).is_file()


def test_macos_hosted_joue_les_fakes_sans_promettre_le_docker_linux_ni_le_vrai_core(workflow):
    noms = [e.get("name", "") for e in _etapes(workflow, "installation-macos")]
    corps = next(e["run"] for e in _etapes(workflow, "installation-macos") if "pytest" in e.get("run", ""))
    assert "tests/test_installateur_scripts.py" in corps
    assert "test_installateur_bout_en_bout" not in corps
    assert not any("bout_en_bout.sh" in e.get("run", "") for e in _etapes(workflow, "installation-macos"))
    assert not any("vrai core" in n.lower() for n in noms)
    assert not any("Docker : CLI et daemon Linux" in n for n in noms)


def test_windows_hosted_joue_les_fakes_sans_vrai_e2e(workflow):
    corps = next(e["run"] for e in _etapes(workflow, "installation-windows") if "pytest" in e.get("run", ""))
    assert "test_installateur_powershell_faux.py" in corps
    assert "test_installateur_windows.py" in corps
    assert "bout_en_bout.ps1" not in corps
    assert not any("bout_en_bout.ps1" in e.get("run", "") for e in _etapes(workflow, "installation-windows"))
    assert not any("Docker : CLI et daemon Linux" in e.get("name", "")
                   for e in _etapes(workflow, "installation-windows"))
@pytest.mark.parametrize("job", ["installation", *INSTALLATIONS_DOCKER])
def test_le_prevol_docker_linux_precede_le_script_de_preuve(workflow, job):
    etapes = _etapes(workflow, job)
    prevol = next(i for i, e in enumerate(etapes) if "Docker : CLI et daemon Linux" in e.get("name", ""))
    marque = "bout_en_bout.ps1" if job == "installation-windows-docker" else "bout_en_bout.sh"
    preuve = next(i for i, e in enumerate(etapes) if marque in e.get("run", ""))
    corps = etapes[prevol]["run"]
    assert prevol < preuve
    assert "docker --version" in corps
    assert "docker info --format '{{.OSType}}'" in corps
    assert "linux" in corps.lower()


@pytest.mark.parametrize("job", ["installation-windows", "installation-windows-docker"])
def test_windows_prepare_les_chemins_longs_avant_l_extraction_du_depot(workflow, job):
    noms = [e.get("name", e.get("uses", "")) for e in _etapes(workflow, job)]
    longs = next(i for i, n in enumerate(noms) if "chemins longs" in n)
    extraction = next(i for i, n in enumerate(noms) if n.startswith("actions/checkout"))

    assert longs < extraction
    assert "core.longpaths true" in _etapes(workflow, job)[longs]["run"]


def test_le_workflow_n_emploie_aucun_secret_du_depot():
    assert "secrets." not in WORKFLOW.read_text(encoding="utf-8")


def test_le_workflow_est_sans_bom_et_en_lf():
    octets = WORKFLOW.read_bytes()

    assert not octets.startswith(b"\xef\xbb\xbf") and b"\r" not in octets


def test_les_scripts_du_depot_gardent_les_fins_de_ligne_lf_sur_tous_les_systemes():
    """`.gitattributes` : Git pour Windows convertirait les scripts en CRLF ; un script bash CRLF ne s'exécute plus."""
    sortie = subprocess.run(
        ["git", "check-attr", "eol", "--", "install/install.sh", "install/uninstall.sh", "install/install.ps1",
         "install/uninstall.ps1", "tests/installateur/bout_en_bout.sh", "tests/installateur/bout_en_bout.ps1"],
        cwd=RACINE, capture_output=True, text=True, check=True).stdout.splitlines()

    assert len(sortie) == 6 and all(ligne.endswith("eol: lf") for ligne in sortie), sortie


@pytest.mark.skipif(shutil.which("actionlint") is None, reason="actionlint absent : le job `analyse` de la CI le joue")
def test_actionlint_accepte_le_workflow():
    resultat = subprocess.run(["actionlint", str(WORKFLOW)], cwd=RACINE, capture_output=True, text=True, check=False)

    assert resultat.returncode == 0, resultat.stdout + resultat.stderr


def test_le_job_d_analyse_joue_actionlint_a_version_et_empreinte_epinglees(workflow):
    corps = next(e["run"] for e in _etapes(workflow, "analyse") if "actionlint" in e.get("run", ""))

    assert "download/v1.7.7/actionlint_1.7.7_linux_amd64.tar.gz" in corps
    # vérifié avant d'être décompressé
    assert re.search(r'echo "[0-9a-f]{64}  actionlint.tar.gz" \| sha256sum -c -', corps)
    assert corps.index("sha256sum -c -") < corps.index("tar -xzf")
