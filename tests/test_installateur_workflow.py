"""Le workflow `installateur` (PLAN T0.11-d) : ce qu'on peut vérifier de lui avant de le lancer sur GitHub.

Un workflow ne s'exécute qu'en CI, et un YAML fautif ne se voit qu'au premier lancement (dix minutes de file, et un
runner macOS facturé dix fois). Ces tests lisent le fichier et vérifient ce que la tâche exige : trois jobs
d'installation
(Linux, macOS, Windows) qui ont les mêmes déclencheurs, un plafond de durée chacun, aucune étape qui tolère l'échec, un
diagnostic en cas d'échec qui ne montre aucun secret, des actions épinglées, et des scripts qui existent.

Ce qu'ils ne prouvent PAS : que GitHub accepte le fichier (syntaxe des expressions `${{ }}`, noms d'images), ni que les
scripts réussissent sur macOS et Windows. Cela, seul un lancement le prouve.
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


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _declencheurs(workflow: dict) -> dict:
    return workflow[True] if True in workflow else workflow["on"]  # YAML 1.1 lit `on` comme le booléen vrai


def _etapes(workflow: dict, job: str) -> list[dict]:
    return workflow["jobs"][job]["steps"]


def test_le_fichier_se_charge_et_porte_les_quatre_jobs(workflow):
    assert set(workflow["jobs"]) == {"analyse", *INSTALLATIONS}
    assert workflow["permissions"] == {"contents": "read"}


@pytest.mark.parametrize("job", sorted(INSTALLATIONS))
def test_chaque_installation_tourne_sur_son_systeme(workflow, job):
    assert workflow["jobs"][job]["runs-on"] == INSTALLATIONS[job]


def test_les_jobs_macos_et_windows_ont_les_declencheurs_du_job_linux(workflow):
    """Les déclencheurs sont ceux du workflow entier : aucun job n'a de condition propre qui les restreindrait."""
    declencheurs = _declencheurs(workflow)
    assert set(declencheurs) == {"workflow_dispatch", "push", "pull_request"}
    assert declencheurs["push"]["paths"] == declencheurs["pull_request"]["paths"]
    for chemin in ("install/**", "tests/installateur/**", ".github/workflows/installateur.yml", "src/opsys/instance.py",
                   "src/opsys/exportation.py"):
        assert chemin in declencheurs["pull_request"]["paths"]
    for job in INSTALLATIONS:
        assert "if" not in workflow["jobs"][job], f"{job} ne doit pas avoir de condition propre"
        assert "needs" not in workflow["jobs"][job], f"{job} ne dépend d'aucun autre job"
        assert "strategy" not in workflow["jobs"][job]


@pytest.mark.parametrize("job", sorted(INSTALLATIONS))
def test_chaque_installation_a_un_plafond_de_duree_raisonnable(workflow, job):
    delai = workflow["jobs"][job]["timeout-minutes"]

    # assez pour construire le core, pas assez pour brûler des minutes
    assert isinstance(delai, int) and 30 <= delai <= 150
    if job != "installation":
        assert delai >= workflow["jobs"]["installation"]["timeout-minutes"]  # ces systèmes construisent plus lentement


def test_aucune_etape_ne_tolere_l_echec(workflow):
    for job in INSTALLATIONS:
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


@pytest.mark.parametrize("job", ["installation-macos", "installation-windows"])
def test_le_service_est_requis_et_l_entree_sans_service_est_transmise(workflow, job):
    env = workflow["jobs"][job]["env"]

    assert env["OPSYS_SERVICE_REQUIS"] == "1"  # sans service utilisateur, le job échoue en le disant
    assert env["OPSYS_SANS_SERVICE"] == "${{ inputs.sans_service || '0' }}"


@pytest.mark.parametrize("job", ["installation", "installation-macos", "installation-windows"])
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
    marque = "bout_en_bout.ps1" if job == "installation-windows" else "bout_en_bout.sh"
    return next(e for e in _etapes(workflow, job) if marque in e.get("run", ""))


def test_macos_joue_le_script_de_preuve_bash_du_depot(workflow):
    etape = _etape_de_preuve(workflow, "installation-macos")

    assert etape["run"].strip() == "bash tests/installateur/bout_en_bout.sh"
    assert "shell" not in etape  # bash de macOS, comme le script l'annonce (bash 3.2 compris)


def test_windows_joue_le_script_de_preuve_powershell_avec_pwsh_et_propage_le_code_de_sortie(workflow):
    etape = _etape_de_preuve(workflow, "installation-windows")

    assert etape["shell"] == "pwsh"
    assert "& ./tests/installateur/bout_en_bout.ps1" in etape["run"]
    assert "exit $LASTEXITCODE" in etape["run"]


@pytest.mark.parametrize(("job", "commande"), [
    ("installation", "bash tests/installateur/diagnostic.sh"),
    ("installation-macos", "bash tests/installateur/diagnostic.sh"),
    ("installation-windows", "./tests/installateur/diagnostic.ps1"),
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


def test_macos_joue_d_abord_les_tests_des_scripts_contre_de_fausses_commandes_avant_de_construire_le_core(workflow):
    noms = [e.get("name", "") for e in _etapes(workflow, "installation-macos")]
    rapide = next(i for i, n in enumerate(noms) if "fausses commandes" in n)
    vrai = next(i for i, n in enumerate(noms) if "vrai core" in n)

    assert rapide < vrai
    corps = next(e["run"] for e in _etapes(workflow, "installation-macos") if "pytest" in e.get("run", ""))
    assert "tests/test_installateur_scripts.py" in corps
    # ces essais imitent macOS sur Linux : ils ne servent pas sur un Mac
    assert "test_installateur_bout_en_bout" not in corps


def test_windows_prepare_les_chemins_longs_avant_l_extraction_du_depot(workflow):
    noms = [e.get("name", e.get("uses", "")) for e in _etapes(workflow, "installation-windows")]
    longs = next(i for i, n in enumerate(noms) if "chemins longs" in n)
    extraction = next(i for i, n in enumerate(noms) if n.startswith("actions/checkout"))

    assert longs < extraction
    assert "core.longpaths true" in _etapes(workflow, "installation-windows")[longs]["run"]


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
