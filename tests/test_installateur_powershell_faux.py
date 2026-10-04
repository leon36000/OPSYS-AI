"""`install.ps1` et `uninstall.ps1` EXÉCUTÉS (PowerShell 7 sous Linux) contre de fausses commandes et un faux core.

`test_installateur_powershell.py` ne lit que le texte des scripts ; `test_installateur_windows.py` en exécute les
fonctions. Ici, les DEUX scripts tournent en entier, comme `test_installateur_scripts.py` le fait pour `install.sh` :
Node, pnpm, uv, curl et Docker sont de faux programmes (le moteur Python est le vrai), le core
est `tests/installateur/faux_core.py`,
qui émule la tâche planifiée (`FAUX_PLATEFORME=windows`). PowerShell sous Linux convertit les `\\` des chemins de
`Join-Path` : `Scripts\\python.exe` devient `Scripts/python.exe`, ce qui permet de jouer le script sans Windows.

Ce que ces tests prouvent : l'enchaînement des étapes de `install.ps1` et de `uninstall.ps1` sous un vrai PowerShell
(paramètres, `Invoke-Capture`, masque des secrets, codes de sortie 0, 1 et 3, journal, enveloppes `.cmd`,
enregistrement de l'installation), l'environnement de l'appelant rendu intact, l'idempotence, et que la désinstallation
ne touche à aucune donnée.

Ce qu'ils ne prouvent PAS, et que seul le job `installation-windows` de la CI prouve : tout ce qui est propre à Windows
(chemins avec lettre de lecteur, `.cmd`, `curl.exe`, `icacls`, tâche planifiée réelle, Windows PowerShell 5.1) et le
vrai core.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

FICTIF = True  # aucune valeur ci-dessous n'est réelle (AGENTS.md)

RACINE = Path(__file__).resolve().parents[1]
INSTALL_PS1 = RACINE / "install" / "install.ps1"
UNINSTALL_PS1 = RACINE / "install" / "uninstall.ps1"
FAUX_CORE = RACINE / "tests" / "installateur" / "faux_core.py"
PREUVE_PS1 = RACINE / "tests" / "installateur" / "bout_en_bout.ps1"
PWSH = shutil.which("pwsh")
PNPM = "12.4.0"
EMBEDDINGS = {"OPSYS_EMBEDDINGS_URL": "http://127.0.0.1:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "bge-m3"}

pytestmark = pytest.mark.skipif(
    PWSH is None or os.name == "nt" or shutil.which("curl") is None or shutil.which("git") is None,
    reason="pwsh, curl et git sous Linux ou macOS : les scripts s'exécutent sous Windows en CI")

FAUX_NODE = '#!/usr/bin/env bash\necho "node $*" >>"$FAUX_JOURNAL"\nexec "$FAUX_PYTHON" "$FAUX_CORE" "$@"\n'
FAUX_PNPM = '''#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then echo "$FAUX_PNPM_VERSION"; exit 0; fi
echo "pnpm $*" >>"$FAUX_JOURNAL"
if [ "${FAUX_ECHEC:-}" = "pnpm $*" ]; then
    echo "echec simule de : pnpm $* jeton=$(sed -n 's/^OPSYS_MCP_JETON=//p' "$FAUX_ETAT/.env" 2>/dev/null)" >&2
    exit 1
fi
exit 0
'''
FAUX_UV = '''#!/usr/bin/env bash
echo "uv $*" >>"$FAUX_JOURNAL"
if [ "$1 ${2:-}" = "venv --clear" ]; then
    for dossier; do :; done  # le dernier argument (portable : bash 3.2 de macOS compris)
    mkdir -p "$dossier/Scripts"
    printf '#!/bin/sh\\nexec %s "$@"\\n' "$FAUX_PYTHON" >"$dossier/Scripts/python.exe"
    chmod +x "$dossier/Scripts/python.exe"
fi
exit 0
'''
# `-o NUL` (Windows) devient `-o /dev/null` : le reste est le vrai curl
FAUX_CURL_EXE = '''#!/usr/bin/env bash
args=()
while [ $# -gt 0 ]; do
    if [ "$1" = "-o" ] && [ "${2:-}" = "NUL" ]; then args+=(-o /dev/null); shift 2; else args+=("$1"); shift; fi
done
exec curl "${args[@]}"
'''
FAUX_DOCKER = r'''#!/usr/bin/env bash
printf 'docker %s\n' "$*" >>"$FAUX_JOURNAL"
"$FAUX_PYTHON" -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >>"$FAUX_DOCKER_ARGV"
case "${1:-}" in
    info)
        if [ "${FAUX_DOCKER_DAEMON:-ready}" != "ready" ]; then
            echo 'Cannot connect to Docker daemon' >&2
            exit 1
        fi
        echo "${FAUX_DOCKER_OS:-linux}"
        ;;
    image)
        if [ "${2:-}" = "inspect" ] && {
            [ "${FAUX_DOCKER_IMAGE:-present}" = "present" ] || [ -f "$FAUX_DOCKER_IMAGE_STATE" ]
        }; then
            exit 0
        fi
        exit 1
        ;;
    build)
        if [ "${FAUX_DOCKER_BUILD:-success}" = "fail" ]; then echo 'network unavailable' >&2; exit 1; fi
        : >"$FAUX_DOCKER_IMAGE_STATE"
        exit 0
        ;;
    *) echo "unexpected docker arguments: $*" >&2; exit 2 ;;
esac
'''


def _port_libre() -> int:
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        return prise.getsockname()[1]


class Poste:
    """Un poste Windows fictif, joué par PowerShell sous Linux."""

    def __init__(self, tmp_path: Path) -> None:
        self.racine = tmp_path
        self.hote = tmp_path / "hote"
        self.home = tmp_path / "instance"
        self.logiciel = tmp_path / "logiciel"
        self.bin = tmp_path / "commandes"
        self.faux = tmp_path / "faux"
        self.depot = tmp_path / "depot"
        self.journal = tmp_path / "appels.log"
        self.journal_docker_argv = tmp_path / "docker-argv.jsonl"
        self.export = tmp_path / "export"
        self.port_gateway, self.port_moteur = _port_libre(), _port_libre()
        for dossier in (self.hote, self.faux, self.export):
            dossier.mkdir()
        for nom, corps in (("node", FAUX_NODE), ("pnpm", FAUX_PNPM), ("uv", FAUX_UV),
                           ("curl.exe", FAUX_CURL_EXE), ("docker", FAUX_DOCKER)):
            chemin = self.faux / nom
            chemin.write_text(corps, encoding="utf-8")
            chemin.chmod(0o755)
        self.journal.write_text("", encoding="utf-8")
        self.env_supplementaire: dict[str, str] = {}
        self._fabriquer_depot()

    @property
    def etat_core(self) -> Path:
        return self.hote / ".opsys" / "core"  # le dossier canonique du profil `opsys` (T0.7 lot 3)

    @property
    def ancien_profil(self) -> Path:
        return self.hote / ".openclaw-opsys"  # où le profil rangeait son état avant le lot 3

    def _fabriquer_depot(self) -> None:
        (self.depot / "core").mkdir(parents=True)
        (self.depot / "departments").mkdir()
        (self.depot / "core" / "openclaw.mjs").write_text("// faux core\n", encoding="utf-8")
        (self.depot / "core" / "node-version.mjs").write_text("// faux\n", encoding="utf-8")
        (self.depot / "core" / "package.json").write_text(
            json.dumps({"packageManager": f"pnpm@{PNPM}+sha512.0123456789abcdef"}), encoding="utf-8")
        shutil.copytree(RACINE / "core" / "scripts", self.depot / "core" / "scripts")
        (self.depot / "pyproject.toml").write_text('[project]\nname = "faux-opsys"\n', encoding="utf-8")
        (self.depot / "departments" / "LISEZMOI").write_text("faux\n", encoding="utf-8")
        git = ["git", "-C", str(self.depot)]
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}
        for commande in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "premier"]):
            subprocess.run([*git, *commande], env=env, check=True, capture_output=True)

    def preparer_decisions(self) -> None:
        """Les décisions que l'installateur n'invente pas : un palier de modèles et le service d'embeddings."""
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "paliers.yaml").write_text(
            "paliers: {standard: {provider: anthropic, model: claude-sonnet-5}}\n", encoding="utf-8")
        self.env_supplementaire.update(EMBEDDINGS)

    def env(self, **supplement: str) -> dict[str, str]:
        env = {cle: valeur for cle, valeur in os.environ.items()
               if not cle.startswith(("OPSYS_", "OPENCLAW_", "FAUX_", "GITHUB_", "CI"))}
        chemins_python = [str(RACINE / "src"), *sorted(str(p) for p in RACINE.glob("departments/*/src"))]
        env.update({
            "HOME": str(self.hote), "USERPROFILE": str(self.hote), "LOCALAPPDATA": str(self.hote / "AppData" / "Local"),
            "APPDATA": str(self.hote / "AppData" / "Roaming"), "PATH": f"{self.faux}:/usr/bin:/bin",
            "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT": "1", "NO_COLOR": "1",
            "PYTHONPATH": os.pathsep.join(chemins_python),
            "OPSYS_HOME": str(self.home), "OPSYS_LOGICIEL": str(self.logiciel), "OPSYS_BIN": str(self.bin),
            "OPSYS_PORT_GATEWAY": str(self.port_gateway), "OPSYS_PORT_MOTEUR": str(self.port_moteur),
            "FAUX_PYTHON": sys.executable, "FAUX_CORE": str(FAUX_CORE), "FAUX_JOURNAL": str(self.journal),
            "FAUX_PNPM_VERSION": PNPM, "FAUX_PLATEFORME": "windows", "FAUX_ETAT": str(self.etat_core),
            "FAUX_TACHES": str(self.hote / ".faux-taches"),
            "FAUX_DOCKER_IMAGE_STATE": str(self.racine / "docker-image"),
            "FAUX_DOCKER_ARGV": str(self.journal_docker_argv),
        })
        env.update(self.env_supplementaire)
        env.update(supplement)
        return env

    def pwsh(self, script: Path, *arguments: str, commande: str | None = None, timeout: int = 300,
             **env: str) -> subprocess.CompletedProcess[str]:
        assert PWSH is not None
        if commande is None:
            appel = [PWSH, "-NoProfile", "-NonInteractive", "-File", str(script), *arguments]
        else:
            appel = [PWSH, "-NoProfile", "-NonInteractive", "-Command", commande]
        return subprocess.run(appel, env=self.env(**env), capture_output=True, text=True, timeout=timeout, check=False,
                              cwd=self.racine)

    def installer(self, *options: str, **env: str) -> subprocess.CompletedProcess[str]:
        return self.pwsh(INSTALL_PS1, "-Source", str(self.depot), *options, **env)

    def desinstaller(self, *options: str, **env: str) -> subprocess.CompletedProcess[str]:
        return self.pwsh(UNINSTALL_PS1, *options, **env)

    def appels(self) -> list[str]:
        return self.journal.read_text(encoding="utf-8").splitlines()

    def arguments_docker(self) -> list[list[str]]:
        if not self.journal_docker_argv.exists():
            return []
        return [json.loads(ligne) for ligne in self.journal_docker_argv.read_text(encoding="utf-8").splitlines()]

    def secrets(self) -> list[str]:
        env = (self.etat_core / ".env").read_text(encoding="utf-8")
        return [v for k, v in re.findall(r"^([A-Z0-9_]+)=(.*)$", env, flags=re.MULTILINE)
                if re.search(r"JETON|TOKEN|CLE", k) and len(v) >= 12]

    def enregistrement(self) -> dict[str, str]:
        lignes = (self.logiciel / "installation.env").read_text(encoding="utf-8").splitlines()
        return dict(ligne.split("=", 1) for ligne in lignes if "=" in ligne)

    def empreintes(self, dossier: Path) -> dict[str, str]:
        return {str(p.relative_to(dossier)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(dossier.rglob("*")) if p.is_file()}

    def arreter_les_services(self) -> None:
        taches = self.hote / ".faux-taches"
        for fichier in taches.glob("*.pid") if taches.is_dir() else ():
            with contextlib.suppress(OSError, ValueError):
                os.kill(int(fichier.read_text(encoding="utf-8")), 15)


def _sortie(resultat: subprocess.CompletedProcess[str]) -> str:
    return resultat.stdout + resultat.stderr


@pytest.fixture
def poste(tmp_path: Path):
    poste = Poste(tmp_path)
    yield poste
    poste.arreter_les_services()


@pytest.fixture
def pret(poste: Poste) -> Poste:
    poste.preparer_decisions()
    return poste


# -- install.ps1 -------------------------------------------------------------------------------------------------------
def test_installation_sans_service_dans_l_ordre_avec_les_bons_arguments(pret):
    resultat = pret.installer("-SansService")

    assert resultat.returncode == 0, _sortie(resultat)
    assert "OPSYS est installe." in resultat.stdout
    appels = pret.appels()
    attendu = ["pnpm install --frozen-lockfile", "pnpm build"]
    assert [a for a in appels if a in attendu] == attendu
    assert f"uv venv --clear --python >=3.11 {pret.logiciel / 'venv'}" in appels
    python = pret.logiciel / "venv" / "Scripts" / "python.exe"
    sync = (f"uv sync --locked --project {pret.depot} --python {python} "
            "--group build --no-dev --extra tournees --extra soumission --no-build-isolation")
    assert sync + " --no-install-project" in appels
    assert sync in appels
    config = json.loads((pret.etat_core / "opsys.json").read_text(encoding="utf-8"))
    assert config["gateway"]["port"] == pret.port_gateway or config["gateway"]["port"] == 18789
    assert not (pret.etat_core / "openclaw.json").exists()  # l'instance neuve n'a que le nom canonique
    metier = json.loads((pret.etat_core / "opsys" / "metier.json").read_text(encoding="utf-8"))
    assert metier["actif"] is True and metier["dossier"] == str(pret.depot) and metier["port"] == pret.port_moteur
    enregistrement = pret.enregistrement()
    assert enregistrement["SERVICE"] == "0" and enregistrement["PROFIL_CORE"] == "opsys"
    assert enregistrement["DOSSIER_CORE"] == str(pret.etat_core) and enregistrement["SOURCE_GEREE"] == "0"
    assert enregistrement["PORT_GATEWAY"] == str(pret.port_gateway)
    assert enregistrement["PORT_MOTEUR"] == str(pret.port_moteur)
    assert re.fullmatch(r"[0-9a-f]{40}", enregistrement["SOURCE_COMMIT"])


def test_daemon_docker_linux_absent_arrete_avant_le_build_et_le_gateway(poste):
    resultat = poste.installer("-SansService", FAUX_DOCKER_DAEMON="absent")
    appels = poste.appels()

    assert resultat.returncode == 1 and "daemon Docker inaccessible" in _sortie(resultat)
    assert not any(a.startswith(("pnpm", "uv", "openclaw")) for a in appels)
    assert not any("gateway install" in a for a in appels)


def test_absence_cli_docker_windows_arrete_avant_tout_travail(poste):
    (poste.faux / "docker").unlink()
    resultat = poste.installer("-SansService")

    assert resultat.returncode == 1 and "Docker CLI" in _sortie(resultat)
    assert not any(a.startswith(("pnpm", "uv", "openclaw")) for a in poste.appels())
    assert not any("gateway install" in a for a in poste.appels())


def test_daemon_docker_non_linux_arrete_avant_tout_travail(poste):
    resultat = poste.installer("-SansService", FAUX_DOCKER_OS="windows")
    appels = poste.appels()

    assert resultat.returncode == 1 and "conteneurs Linux" in _sortie(resultat)
    assert not any(a.startswith(("pnpm", "uv", "openclaw")) for a in appels)
    assert not any("gateway install" in a for a in appels)


def test_image_docker_existante_est_reutilisee_sans_build_ni_pull(pret):
    resultat = pret.installer("-SansService", FAUX_DOCKER_IMAGE="present")
    appels = pret.appels()

    assert resultat.returncode == 0, _sortie(resultat)
    assert "docker image inspect openclaw-sandbox:bookworm-slim" in appels
    assert not any(a.startswith(("docker build", "docker pull")) for a in appels)


def test_image_docker_absente_est_construite_avec_le_dockerfile_du_core_avant_le_gateway(pret):
    pret.depot.rename(pret.depot.with_name("depot avec espaces"))
    pret.depot = pret.depot.with_name("depot avec espaces")
    resultat = pret.installer(FAUX_DOCKER_IMAGE="absent")
    appels = pret.appels()

    assert resultat.returncode == 0, _sortie(resultat)
    build = next(i for i, a in enumerate(appels) if a.startswith("docker build -t openclaw-sandbox:bookworm-slim"))
    gateway = next(i for i, a in enumerate(appels) if "gateway install" in a)
    assert build < gateway
    assert "scripts/docker/sandbox/Dockerfile" in appels[build]
    attendu = ["build", "-t", "openclaw-sandbox:bookworm-slim", "-f",
               str(pret.depot / "core" / "scripts" / "docker" / "sandbox" / "Dockerfile"), str(pret.depot / "core")]
    assert attendu in pret.arguments_docker()


def test_echec_build_docker_empeche_l_installation_du_gateway(pret):
    resultat = pret.installer(FAUX_DOCKER_IMAGE="absent", FAUX_DOCKER_BUILD="fail")

    assert resultat.returncode == 1
    assert "Construction de l'image sandbox" in _sortie(resultat)
    assert "reseau Docker" in _sortie(resultat)
    assert not any("gateway install" in a for a in pret.appels())


def test_les_commandes_installees_sont_des_enveloppes_cmd_qui_ecartent_l_environnement_du_core(pret):
    resultat = pret.installer("-SansService")

    assert resultat.returncode == 0, _sortie(resultat)
    core = (pret.bin / "opsys.cmd").read_bytes().decode("ascii")
    alias = (pret.bin / "openclaw.cmd").read_bytes().decode("ascii")
    moteur = (pret.bin / "opsys-metier.cmd").read_bytes().decode("ascii")
    assert alias == core  # T0.7 lot 2 : `opsys` est le core, `openclaw` son alias (le même contenu)
    assert "-m opsys.cli" not in core  # `opsys` n'est plus l'enveloppe du moteur
    assert "\r\n" in core and "\r\n" in moteur  # fins de ligne de cmd.exe
    assert "--profile opsys %*" in core and "setlocal" in core
    ecartees = ("OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH", "OPENCLAW_HOME", "OPENCLAW_PROFILE",
                "OPENCLAW_LAUNCHD_LABEL", "OPENCLAW_SYSTEMD_UNIT", "OPENCLAW_WINDOWS_TASK_NAME")
    for nom in ecartees:
        assert f'set "{nom}="' in core  # écartées : le core viserait sinon un autre dossier
    assert "OPSYS-INSTALLATEUR" in core and "OPSYS-INSTALLATEUR" in moteur
    # `setlocal` : les secrets de .env que la commande lit ne restent pas dans le cmd.exe de l'appelant
    assert "setlocal" in moteur and moteur.index("setlocal") < moteur.index("DOSSIER_CORE")
    assert 'set "PYTHONUTF8=1"' in moteur and "-m opsys.cli %*" in moteur
    assert moteur.index("PYTHONUTF8") < moteur.index("-m opsys.cli")
    assert str(pret.etat_core) in moteur  # le .env que la commande lit vit dans l'état du core


def _ancienne_enveloppe_du_moteur() -> str:
    """Le `opsys.cmd` que l'installateur écrivait avant le lot 2 : l'enveloppe du moteur, sous la même marque."""
    marque = re.search(r"^\$script:Marque = '(.*)'$", INSTALL_PS1.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert marque is not None
    return f'@echo off\r\nrem {marque.group(1)}\r\nsetlocal\r\n"C:\\ancien\\python.exe" -m opsys.cli %*\r\n'


def test_une_installation_d_avant_le_lot_2_est_mise_a_jour_sans_perte_et_le_dit(pret):
    """`opsys.cmd` était le moteur : la relance le remplace par le core, rend le moteur à `opsys-metier.cmd`."""
    assert pret.installer("-SansService").returncode == 0
    (pret.bin / "opsys.cmd").write_bytes(_ancienne_enveloppe_du_moteur().encode("ascii"))  # l'état d'avant le lot 2
    (pret.bin / "opsys-metier.cmd").unlink()
    donnees_avant = {k: v for k, v in pret.empreintes(pret.home).items() if k != "opsys.db"}

    mise_a_jour = pret.installer("-SansService")

    assert mise_a_jour.returncode == 0, _sortie(mise_a_jour)
    assert "l'ancienne commande du moteur est remplacee" in mise_a_jour.stdout
    assert "opsys metier <commande>" in mise_a_jour.stdout and "opsys-metier <commande>" in mise_a_jour.stdout
    assert "-m opsys.cli" not in (pret.bin / "opsys.cmd").read_bytes().decode("ascii")  # le core, plus le moteur
    assert "-m opsys.cli" in (pret.bin / "opsys-metier.cmd").read_bytes().decode("ascii")
    assert {k: v for k, v in pret.empreintes(pret.home).items() if k != "opsys.db"} == donnees_avant
    encore = pret.installer("-SansService")
    assert encore.returncode == 0 and "l'ancienne commande du moteur est remplacee" not in encore.stdout


def test_un_fichier_etranger_opsys_metier_arrete_avant_toute_ecriture(pret):
    pret.bin.mkdir()
    etranger = pret.bin / "opsys-metier.cmd"
    etranger.write_bytes(b"@echo moteur d'un autre\r\n")

    resultat = pret.installer("-SansService")

    assert resultat.returncode == 1, _sortie(resultat)
    assert "n'a pas ete installe par OPSYS" in _sortie(resultat) and "opsys-metier.cmd" in _sortie(resultat)
    assert etranger.read_bytes() == b"@echo moteur d'un autre\r\n"  # en octets : la lecture texte avale le \r
    assert [f.name for f in pret.bin.iterdir()] == ["opsys-metier.cmd"]  # ni opsys.cmd ni openclaw.cmd n'ont été écrits


def test_l_installateur_rend_a_l_appelant_l_environnement_qu_il_a_pose_ou_retire(pret):
    """Lancé depuis une session (`.\\install.ps1`), le script n'y laisse ni CI=true, ni PYTHONUTF8, ni PATH allongé."""
    commande = (
        "$env:CI = $null; $env:PYTHONUTF8 = $null; $env:OPENCLAW_STATE_DIR = 'etat-de-l-appelant'; "
        "$env:Path = 'chemin-de-l-appelant'; $avant = $env:Path; "
        f"& '{INSTALL_PS1}' -SansService -Source '{pret.depot}'; "
        "\"code=$LASTEXITCODE\"; \"CI=[$($env:CI)]\"; \"PYTHONUTF8=[$($env:PYTHONUTF8)]\"; "
        "\"COREPACK=[$($env:COREPACK_ENABLE_DOWNLOAD_PROMPT)]\"; \"ETAT=[$($env:OPENCLAW_STATE_DIR)]\"; "
        f"\"OPSYS_HOME=[$($env:OPSYS_HOME)]\"; \"CHEMIN=[$($env:Path)]\"")

    resultat = pret.pwsh(INSTALL_PS1, commande=commande)

    lignes = resultat.stdout.splitlines()
    assert resultat.returncode == 0, _sortie(resultat)
    assert "code=0" in lignes and "CI=[]" in lignes and "COREPACK=[]" in lignes
    assert "ETAT=[etat-de-l-appelant]" in lignes  # retiré pour le core, rendu ensuite
    assert f"OPSYS_HOME=[{pret.home}]" in lignes and "PYTHONUTF8=[]" in lignes
    # le PATH de pnpm n'y est plus ; seul y reste le dossier des commandes, ajouté pour qu'on s'en serve tout de suite
    assert f"CHEMIN=[chemin-de-l-appelant;{pret.bin}]" in lignes


def test_les_secrets_sont_prives_jamais_affiches_et_masques_meme_quand_une_commande_les_crache(pret):
    pret.env_supplementaire["FAUX_CRACHE_LE_JETON"] = "1"

    resultat = pret.installer(OPSYS_VERBOSE="1")

    assert resultat.returncode == 0, _sortie(resultat)
    secrets = pret.secrets()
    assert len(secrets) >= 12
    journal = (pret.logiciel / "journaux" / "installation.log").read_text(encoding="utf-8")
    for secret in secrets:
        assert secret not in _sortie(resultat), "un secret est affiché"
        assert secret not in journal, "un secret est journalisé"
    assert "jeton du moteur : ***" in journal  # le faux core l'a craché, le masque l'a couvert


def test_une_relance_ne_change_ni_secret_ni_configuration_ni_donnee(pret):
    premiere = pret.installer("-SansService")
    avant = pret.empreintes(pret.etat_core)
    donnees_avant = pret.empreintes(pret.home)

    seconde = pret.installer("-SansService")

    assert premiere.returncode == 0 and seconde.returncode == 0, _sortie(seconde)
    assert pret.empreintes(pret.etat_core) == avant, "la relance a modifié l'état du core (secrets, configuration)"
    assert {k: v for k, v in pret.empreintes(pret.home).items() if k != "opsys.db"} == \
        {k: v for k, v in donnees_avant.items() if k != "opsys.db"}


def test_les_ports_de_la_derniere_installation_sont_repris_sans_qu_on_les_redonne(pret):
    pret.installer("-SansService")

    relance = pret.pwsh(INSTALL_PS1, "-Source", str(pret.depot), "-SansService",
                        OPSYS_PORT_GATEWAY="", OPSYS_PORT_MOTEUR="")

    assert relance.returncode == 0, _sortie(relance)
    assert pret.enregistrement()["PORT_GATEWAY"] == str(pret.port_gateway)
    assert pret.enregistrement()["PORT_MOTEUR"] == str(pret.port_moteur)


def test_sans_decision_l_installateur_sort_en_3_et_dit_quoi_fournir(poste):
    resultat = poste.installer("-SansService")  # ni paliers.yaml ni service d'embeddings

    assert resultat.returncode == 3, _sortie(resultat)
    assert "il manque les decisions listees ci-dessus" in resultat.stdout
    assert not (poste.etat_core / "opsys.json").exists()  # fail-closed : rien d'autre n'est écrit
    assert (poste.etat_core / ".env").is_file()  # mais les secrets existent, pour la relance


def test_un_echec_d_etape_arrete_tout_dit_ou_regarder_et_ne_montre_aucun_secret(pret):
    pret.installer("-SansService")  # pour que .env existe : le faux pnpm en crache le premier secret
    resultat = pret.installer("-SansService", FAUX_ECHEC="pnpm build")

    assert resultat.returncode == 1, _sortie(resultat)
    assert "Construction du core (pnpm build, plusieurs minutes) : echec (code 1)" in resultat.stdout
    assert "Journal complet :" in resultat.stdout and "Le journal donne la cause" in resultat.stdout
    for secret in pret.secrets():
        assert secret not in _sortie(resultat)
    assert "OPSYS est installe." not in resultat.stdout


def test_l_ancienne_disposition_est_refusee_avec_la_marche_a_suivre_sans_rien_modifier(pret):
    (pret.home / "core").mkdir(parents=True)
    (pret.home / "core" / ".env").write_text("MARQUEUR=ancien-etat-fictif\n", encoding="utf-8")
    avant = pret.empreintes(pret.home / "core")

    resultat = pret.installer("-SansService")

    assert resultat.returncode == 1, _sortie(resultat)
    assert "ancienne disposition d" in _sortie(resultat) and str(pret.home / "core") in _sortie(resultat)
    assert pret.empreintes(pret.home / "core") == avant and not (pret.etat_core / "opsys.json").exists()


def _etat_d_une_installation_d_avant_le_lot_3(pret: Poste, *options: str) -> Path:
    """Ce qu'une installation faite depuis T0.11-b laisse : l'état dans `%USERPROFILE%\\.openclaw-opsys` (configuration
    `openclaw.json`). On installe, puis on défait ce que le lot 3 a changé."""
    assert pret.installer(*options).returncode == 0
    shutil.move(str(pret.etat_core), str(pret.ancien_profil))
    (pret.ancien_profil / "opsys.json").rename(pret.ancien_profil / "openclaw.json")
    (pret.hote / ".opsys").rmdir()  # le dossier d'instance n'existait pas encore (OPSYS_HOME est ailleurs, ici)
    return pret.ancien_profil


def _secrets_de(dossier: Path) -> list[str]:
    env = (dossier / ".env").read_text(encoding="utf-8")
    return [v for k, v in re.findall(r"^([A-Z0-9_]+)=(.*)$", env, flags=re.MULTILINE)
            if re.search(r"JETON|TOKEN|CLE", k) and len(v) >= 12]


def test_un_etat_reste_dans_l_ancien_dossier_du_profil_arrete_l_installation_avec_la_marche_a_suivre(pret):
    ancien = _etat_d_une_installation_d_avant_le_lot_3(pret, "-SansService")
    secrets = _secrets_de(ancien)
    avant = pret.empreintes(ancien)

    resultat = pret.installer("-SansService")

    assert resultat.returncode == 1, _sortie(resultat)
    assert "ancien emplacement d" in _sortie(resultat) and str(ancien) in _sortie(resultat)
    assert str(pret.etat_core) in _sortie(resultat) and "opsys doctor --non-interactive" in _sortie(resultat)
    assert pret.empreintes(ancien) == avant and not pret.etat_core.exists()  # rien n'a bougé, rien n'est copié
    assert not any(secret in _sortie(resultat) for secret in secrets)  # jamais un secret dans un message


def test_apres_le_deplacement_par_doctor_la_relance_garde_les_secrets_et_repointe_le_service(pret):
    ancien = _etat_d_une_installation_d_avant_le_lot_3(pret)  # avec le service (tâche planifiée émulée)
    script_ancien = ancien / "gateway.cmd"
    script_ancien.write_text(script_ancien.read_text(encoding="utf-8").replace(str(pret.etat_core), str(ancien)),
                             encoding="utf-8")
    secrets = _secrets_de(ancien)
    assert pret.installer().returncode == 1  # le refus, puis la marche à suivre : arrêter le service, lancer Doctor

    # le faux core joue Doctor : un renommage, puis un lien à l'ancien chemin
    doctor = subprocess.run(
        [sys.executable, str(FAUX_CORE), str(pret.depot / "core" / "openclaw.mjs"), "--profile", "opsys", "doctor",
         "--non-interactive"], env=pret.env(), capture_output=True, text=True, check=False)
    assert doctor.returncode == 0, _sortie(doctor)
    assert ancien.is_symlink() and ancien.resolve() == pret.etat_core.resolve()
    reprise = pret.installer()

    assert reprise.returncode == 0, _sortie(reprise)
    assert "Gateway et moteur repondent." in reprise.stdout
    assert _secrets_de(pret.etat_core) == secrets  # les secrets sont ceux d'avant : rien n'a été régénéré
    assert (pret.etat_core / "openclaw.json").is_file() and not (pret.etat_core / "opsys.json").exists()
    script = (pret.etat_core / "gateway.cmd").read_text(encoding="utf-8")
    assert f'OPENCLAW_STATE_DIR={pret.etat_core}"' in script and str(ancien) not in script  # le service suit l'état
    assert pret.enregistrement()["DOSSIER_CORE"] == str(pret.etat_core)


# -- la preuve de la migration de bout_en_bout.ps1, rejouée contre le faux core -------------------------------------
# Le script de preuve ne s'exécute en entier que sous Windows (CI). Ses deux fonctions de la migration, elles,
# sont chargées depuis l'arbre syntaxique et jouées ici, sous PowerShell 7, avec les commandes du poste remplacées
# par le faux core : ni .cmd, ni ACL, ni Planificateur de tâches sous Linux. Les FAUTES du faux core (Doctor qui
# copie, qui perd un fichier, qui fusionne ; core sans repli ; service qui nomme le mauvais dossier) prouvent que
# chaque contrôle sait échouer.
PRELUDE_PREUVE = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$global:LASTEXITCODE = 0
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:PREUVE_PS1, [ref]$null, [ref]$null)
$genre = [System.Management.Automation.Language.FunctionDefinitionAst]
foreach ($definition in $ast.FindAll({ param($n) $n -is $genre }, $false)) {
    . ([scriptblock]::Create($definition.Extent.Text))
}
Add-Type -AssemblyName System.Net.Http
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:Latin1 = [System.Text.Encoding]::GetEncoding('iso-8859-1')
$script:EAigu = [string][char]0x00E9
$script:Secrets = @()
$script:GroupeOuvert = $false
$script:GatewayProc = $null
$script:EnActions = $false
$script:EchecPrevu = $false
$script:EtapeCourante = 'essai'
$script:Constats = New-Object System.Collections.Generic.List[string]
$script:Personnel = $env:HOME
$script:DossierInstance = Join-Path $script:Personnel '.opsys'
$script:EtatCore = Join-Path $script:DossierInstance 'core'
$script:AncienProfil = Join-Path $script:Personnel '.openclaw-opsys'
$script:InstanceExistait = $false
$script:OpsysHome = $env:OPSYS_HOME
$script:Racine = $env:RACINE_ESSAI
$script:Travail = $env:TRAVAIL_ESSAI
$script:Logiciel = $env:OPSYS_LOGICIEL
$script:Bin = $env:OPSYS_BIN
$script:PortGateway = [int]$env:OPSYS_PORT_GATEWAY
$script:PortMoteur = [int]$env:OPSYS_PORT_MOTEUR
$script:HotePrincipal = $env:PWSH_ESSAI
$script:ModeService = 'aucun'
$script:ServiceProuve = 'non'
# Les commandes du poste, jouees par le faux core (le moteur seul est le vrai).
function Invoke-Opsys {
    param([string[]]$Arguments)
    return Invoke-Natif { & $env:PYTHON_ESSAI $env:FAUX_CORE $env:ENTREE_ESSAI '--profile' 'opsys' @Arguments }
}
function Invoke-OpsysMetier {
    param([string[]]$Arguments)
    return Invoke-Opsys (@('metier') + $Arguments)
}
function Invoke-Moteur {
    param([string[]]$Arguments)
    return Invoke-Natif { & $env:PYTHON_ESSAI -m opsys.cli @Arguments }
}
function Assert-AclPrivee {
    param([string]$Chemin, [string]$Libelle, [switch]$SansHeritage)
}
function Confirm-ServiceWindows { }
# (`--source` : le depot de l'installation ; sans lui, `initialiser` prendrait celui du paquet)
$ports = @('--port-gateway', [string]$script:PortGateway, '--port-moteur', [string]$script:PortMoteur,
    '--source', $env:OPSYS_SOURCE)
try {
"""
FIN_PREUVE = r"""
}
catch {
    [Console]::Error.WriteLine("ECHEC : " + $_.Exception.Message)
    exit 1
}
"""


def _jouer_la_preuve(pret: Poste, corps: str, **env: str) -> subprocess.CompletedProcess[str]:
    assert PWSH is not None
    environnement = pret.env(
        PREUVE_PS1=str(PREUVE_PS1), RACINE_ESSAI=str(RACINE), TRAVAIL_ESSAI=str(pret.racine), PWSH_ESSAI=PWSH,
        PYTHON_ESSAI=sys.executable, ENTREE_ESSAI=str(pret.depot / "core" / "openclaw.mjs"),
        OPSYS_SOURCE=str(pret.depot), **env)
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", PRELUDE_PREUVE + corps + FIN_PREUVE],
                          env=environnement, capture_output=True, text=True, timeout=600, check=False, cwd=RACINE)


def test_la_preuve_de_la_migration_joue_ses_quatre_temps_contre_le_faux_core(pret):
    assert pret.installer("-SansService").returncode == 0
    secrets = _secrets_de(pret.etat_core)

    resultat = _jouer_la_preuve(pret, "Invoke-PreuveDeLaMigration $ports")

    assert resultat.returncode == 0, _sortie(resultat)
    assert "OK  etat d'avant le lot 3 : refuse par le moteur avec la marche a suivre" in resultat.stdout
    assert "OK  deux etats : Doctor ne deplace, ne fusionne ni ne supprime rien" in resultat.stdout
    assert _secrets_de(pret.etat_core) == secrets  # les secrets sont ceux d'avant
    assert (pret.etat_core / "openclaw.json").is_file() and not (pret.etat_core / "opsys.json").exists()
    assert not pret.ancien_profil.exists() and (pret.hote / ".openclaw-opsys.old").is_dir()  # mis de côté, pas supprimé
    assert not any(secret in _sortie(resultat) for secret in secrets)


FAUTES_DE_MIGRATION_PS = {
    "un core sans repli sur l'ancien dossier": (
        {"FAUX_SANS_REPLI": "1"}, "l'etat reste a l'ancien emplacement n'est pas signale"),
    "un Doctor qui ne fait rien": ({"FAUX_DOCTOR_INACTIF": "1"}, "Doctor n'a pas deplace l'etat de"),
    "un Doctor qui copie au lieu de deplacer": ({"FAUX_DOCTOR_COPIE": "1"}, "Doctor n'a pas deplace l'etat de"),
    "un Doctor qui ne laisse pas de lien": ({"FAUX_DOCTOR_SANS_LIEN": "1"}, "en laissant un lien a l'ancien chemin"),
    "un Doctor qui perd un fichier": ({"FAUX_DOCTOR_PERD_UN_FICHIER": "1"}, "Doctor a perdu opsys"),
    "un Doctor qui modifie un secret": (
        {"FAUX_DOCTOR_ALTERE_UN_SECRET": "1"}, "les secrets ou les fragments ont change pendant le deplacement"),
    "un Doctor qui renomme la configuration": ({"FAUX_DOCTOR_RENOMME_LA_CONFIG": "1"}, "Doctor a perdu openclaw.json"),
    "un Doctor qui fusionne deux etats": (
        {"FAUX_DOCTOR_FUSIONNE": "1"}, "Doctor a touche a l'ancien etat malgre le conflit"),
}


@pytest.mark.parametrize("faute", sorted(FAUTES_DE_MIGRATION_PS))
def test_chaque_controle_de_la_migration_powershell_attrape_sa_faute(pret, faute):
    injection, message = FAUTES_DE_MIGRATION_PS[faute]
    assert pret.installer("-SansService").returncode == 0

    resultat = _jouer_la_preuve(pret, "Invoke-PreuveDeLaMigration $ports", **injection)

    assert resultat.returncode == 1, f"la faute « {faute} » n'a pas été attrapée : {_sortie(resultat)}"
    assert message in resultat.stderr, resultat.stderr


def test_la_preuve_du_service_d_avant_le_lot_3_suit_la_marche_a_suivre_contre_le_faux_core(pret):
    assert pret.installer().returncode == 0  # avec le service (tâche planifiée émulée)
    secrets = _secrets_de(pret.etat_core)

    resultat = _jouer_la_preuve(pret, "Invoke-ServiceDAvantLeLot3")

    assert resultat.returncode == 0, _sortie(resultat)
    assert "OK  service d'avant le lot 3 : sa definition nomme" in resultat.stdout
    assert "OK  service d'avant le lot 3 : Doctor a deplace l'etat" in resultat.stdout
    assert _secrets_de(pret.etat_core) == secrets and pret.ancien_profil.is_symlink()
    script = (pret.etat_core / "gateway.cmd").read_text(encoding="utf-8")
    assert f'OPENCLAW_STATE_DIR={pret.etat_core}"' in script and str(pret.ancien_profil) not in script


FAUTES_DU_SERVICE_PS = {
    "un service dont la definition nomme toujours l'ancien dossier": (
        {"FAUX_SERVICE_GARDE_L": "1"}, "apres la relance de l'installateur, la definition du service ne nomme pas"),
    "un service qui ne suit pas l'etat lu a l'ancien emplacement": (
        {"FAUX_SERVICE_NOMME_LE_NOUVEAU": "1"}, "la definition du service ne nomme pas"),
}


@pytest.mark.parametrize("faute", sorted(FAUTES_DU_SERVICE_PS))
def test_chaque_controle_du_service_d_avant_le_lot_3_powershell_attrape_sa_faute(pret, faute):
    injection, message = FAUTES_DU_SERVICE_PS[faute]
    assert pret.installer().returncode == 0

    resultat = _jouer_la_preuve(pret, "Invoke-ServiceDAvantLeLot3", **injection)

    assert resultat.returncode == 1, f"la faute « {faute} » n'a pas été attrapée : {_sortie(resultat)}"
    assert message in resultat.stderr, resultat.stderr


def test_une_option_ou_un_prerequis_manquant_est_refuse_avant_toute_ecriture(pret):
    (pret.faux / "uv").unlink()

    sans_uv = pret.installer("-SansService")
    inconnue = pret.pwsh(INSTALL_PS1, "-Source", str(pret.depot), "-Nimporte")

    assert sans_uv.returncode == 1 and "uv est introuvable" in sans_uv.stdout and "astral.sh/uv" in sans_uv.stdout
    assert inconnue.returncode != 0
    assert not pret.etat_core.exists() and not pret.bin.exists()


def test_aide_ne_fait_rien(pret):
    resultat = pret.pwsh(INSTALL_PS1, "-Aide")

    assert resultat.returncode == 0 and "install.ps1 : installe OPSYS" in resultat.stdout
    assert not pret.logiciel.exists() and not pret.etat_core.exists()


# -- le service (tâche planifiée émulée) et uninstall.ps1 ------------------------------------------------------------
def test_le_service_est_installe_par_le_profil_opsys_sans_secret_puis_retire_par_uninstall(pret):
    installation = pret.installer()

    assert installation.returncode == 0, _sortie(installation)
    assert "Gateway et moteur repondent." in installation.stdout
    assert pret.enregistrement()["SERVICE"] == "1"
    script = (pret.etat_core / "gateway.cmd").read_text(encoding="utf-8")
    assert 'set "OPENCLAW_PROFILE=opsys"' in script and str(pret.etat_core) in script
    for secret in pret.secrets():
        assert secret not in script and secret not in _sortie(installation)
    tache = pret.hote / ".faux-taches" / "OpenClaw Gateway (opsys).tache"
    assert tache.is_file()
    donnees = pret.empreintes(pret.etat_core)
    donnees.pop("gateway.cmd", None)

    retrait = pret.desinstaller("-ExporterAvant", str(pret.export / "avant.tar.gz"))

    assert retrait.returncode == 0, _sortie(retrait)
    assert not tache.exists() and not (pret.etat_core / "gateway.cmd").exists()  # le service et son script sont retirés
    assert (pret.export / "avant.tar.gz").is_file() and (pret.export / "avant.tar.gz.sha256").is_file()
    apres = {k: v for k, v in pret.empreintes(pret.etat_core).items() if not k.startswith("logs")}
    assert {k: v for k, v in donnees.items() if not k.startswith("logs")} == apres  # l'état du core est intact
    assert not pret.logiciel.exists() and not pret.bin.exists()  # le logiciel et les commandes sont partis
    assert (pret.home / "opsys.db").is_file() and (pret.home / "paliers.yaml").is_file()
    assert "Etat du core conserve" in retrait.stdout and str(pret.etat_core) in retrait.stdout


def test_la_desinstallation_est_relancable_et_ne_touche_pas_au_depot(pret):
    pret.installer("-SansService")

    premiere = pret.desinstaller()
    seconde = pret.desinstaller()

    assert premiere.returncode == 0 and seconde.returncode == 0, _sortie(seconde)
    assert (pret.depot / "core" / "openclaw.mjs").is_file()  # un dépôt à soi n'est jamais touché
    assert "le depot" in premiere.stdout and "n'est pas gere par l'installateur" in premiere.stdout


def test_la_simulation_ne_retire_rien(pret):
    pret.installer("-SansService")
    avant = pret.empreintes(pret.logiciel / "venv") if (pret.logiciel / "venv").is_dir() else {}

    resultat = pret.desinstaller("-Simuler")

    assert resultat.returncode == 0 and "[simulation]" in resultat.stdout, _sortie(resultat)
    for commande in ("opsys.cmd", "openclaw.cmd", "opsys-metier.cmd"):
        assert (pret.bin / commande).is_file(), commande
    assert pret.empreintes(pret.logiciel / "venv") == avant


def test_un_export_qui_echoue_empeche_tout_retrait(pret):
    pret.installer("-SansService")
    (pret.export / "existe.tar.gz").write_text("deja la", encoding="utf-8")  # un export n'écrase jamais un fichier

    resultat = pret.desinstaller("-ExporterAvant", str(pret.export / "existe.tar.gz"))

    assert resultat.returncode == 1, _sortie(resultat)
    assert "RIEN n'a ete retire" in _sortie(resultat)
    assert (pret.bin / "opsys.cmd").is_file() and (pret.logiciel / "venv").is_dir()


def test_la_desinstallation_refuse_de_supprimer_un_dossier_qui_contient_les_donnees(pret):
    pret.installer("-SansService")
    piege = pret.racine / "gros-dossier"
    piege.mkdir()
    shutil.move(str(pret.logiciel / "venv"), str(piege / "venv"))
    shutil.move(str(pret.logiciel / "installation.env"), str(piege / "installation.env"))
    instance_dedans = piege / "venv" / "instance"
    shutil.move(str(pret.home), str(instance_dedans))

    resultat = pret.desinstaller(OPSYS_LOGICIEL=str(piege), OPSYS_HOME=str(instance_dedans))

    assert resultat.returncode == 1, _sortie(resultat)
    assert "il contient les donnees de l'instance" in _sortie(resultat) and "Rien n'a ete retire" in _sortie(resultat)
    # le refus vient AVANT tout retrait
    assert (instance_dedans / "opsys.db").is_file() and (pret.bin / "opsys.cmd").is_file()


def test_la_desinstallation_refuse_de_supprimer_un_dossier_qui_contient_l_etat_du_core(pret):
    pret.installer("-SansService")
    dedans = pret.logiciel / "venv" / "etat-du-core"  # un état du core rangé DANS un dossier que le script supprime
    shutil.move(str(pret.etat_core), str(dedans))
    enregistrement = pret.logiciel / "installation.env"
    enregistrement.write_text(enregistrement.read_text(encoding="utf-8").replace(
        f"DOSSIER_CORE={pret.etat_core}", f"DOSSIER_CORE={dedans}"), encoding="utf-8")

    resultat = pret.desinstaller()

    assert resultat.returncode == 1, _sortie(resultat)
    assert "c'est l'etat du core ou il le contient" in _sortie(resultat)
    assert (dedans / ".env").is_file() and (pret.bin / "opsys.cmd").is_file()  # le refus vient AVANT tout retrait


def test_la_desinstallation_protege_l_etat_du_core_la_ou_il_est_meme_si_l_enregistrement_nomme_l_ancien_chemin(pret):
    """Une installation d'avant le lot 3 a noté `.openclaw-opsys` ; l'état est maintenant dans `.opsys/core`."""
    pret.installer("-SansService")
    enregistrement = pret.logiciel / "installation.env"
    enregistrement.write_text(enregistrement.read_text(encoding="utf-8").replace(
        f"DOSSIER_CORE={pret.etat_core}", f"DOSSIER_CORE={pret.ancien_profil}"), encoding="utf-8")
    poste = pret.logiciel / "venv" / "poste"  # un dossier personnel rangé DANS un dossier que le script supprime
    etat = poste / ".opsys" / "core"
    etat.mkdir(parents=True)
    (etat / ".env").write_text("OPSYS_MCP_JETON=jeton-fictif-0123456789abcdef\n", encoding="utf-8")

    resultat = pret.desinstaller(USERPROFILE=str(poste), HOME=str(poste))

    assert resultat.returncode == 1, _sortie(resultat)
    assert "c'est l'etat du core ou il le contient" in _sortie(resultat)
    assert (etat / ".env").is_file() and (pret.bin / "opsys.cmd").is_file()  # le refus vient AVANT tout retrait


def test_uninstall_ps1_rend_l_environnement_de_l_appelant(pret):
    pret.installer("-SansService")
    commande = (
        "$env:PYTHONUTF8 = $null; $env:OPENCLAW_PROFILE = 'autre'; $env:OPENCLAW_STATE_DIR = 'etat-de-l-appelant'; "
        f"& '{UNINSTALL_PS1}'; \"code=$LASTEXITCODE\"; \"PYTHONUTF8=[$($env:PYTHONUTF8)]\"; "
        "\"PROFIL=[$($env:OPENCLAW_PROFILE)]\"; \"ETAT=[$($env:OPENCLAW_STATE_DIR)]\"")

    resultat = pret.pwsh(UNINSTALL_PS1, commande=commande)

    lignes = resultat.stdout.splitlines()
    assert resultat.returncode == 0, _sortie(resultat)
    assert "code=0" in lignes and "PYTHONUTF8=[]" in lignes  # posé par le script pour l'export, rendu ensuite
    assert "PROFIL=[autre]" in lignes and "ETAT=[etat-de-l-appelant]" in lignes  # retirés pour le core, rendus ensuite
