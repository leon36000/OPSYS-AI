"""Scripts `install/install.sh` et `install/uninstall.sh` (PLAN T0.11), joués contre de FAUSSES commandes.

Node, pnpm, uv, curl et Docker sont remplacés par de petits scripts qui journalisent leurs appels ; le moteur Python,
lui, est le vrai (l'interpréteur « de l'environnement » est celui des tests), donc
`opsys-metier instance initialiser`, les secrets, la configuration du core et l'export tournent pour de vrai
dans un dossier temporaire.

Le faux `node` joue le rôle du core sur ce qui a fait échouer la première exécution de la CI (PLAN T0.11-b) : il
applique la règle du fork. `--profile <p>` est une option racine qui projette l'état canonique du profil
(`applyCliProfileEnv`) : `~/.opsys/core` et `opsys.json` pour le profil `opsys` (T0.7 lot 3 : un `openclaw.json` qui
existe reste lu, et l'ancien `~/.openclaw-opsys` sert tant qu'il est seul à porter un état), `~/.openclaw-<p>` pour
les autres ; `gateway install|uninstall` est refusé si l'état n'est pas ce dossier canonique ou si OPENCLAW_HOME est
défini (`isDefaultInstallIdentity`, chemins réels comparés) ; le nom du service vient du profil (`constants.ts`). Un
installateur qui pose OPENCLAW_STATE_DIR à la main est donc refusé ici comme il l'est par le vrai core.

Ce que ces tests prouvent : l'enchaînement des étapes et leur ordre, le fail-closed (prérequis, étape en échec,
fichier étranger, décision manquante, ancienne disposition, état resté dans `~/.openclaw-opsys` puis repris après
Doctor : secrets gardés, service réécrit vers `~/.opsys/core`), l'idempotence (secrets et configuration inchangés),
qu'aucun secret n'est affiché ni journalisé même quand une commande le crache, l'installation à distance depuis un
dépôt git (y compris par `bash < script`, comme `curl | bash`), que le core tourne toujours sous le profil `opsys`
quel que soit l'environnement de l'appelant, que le service du core d'origine n'est jamais touché, et que la
désinstallation retire le logiciel sans jamais toucher aux données ni à l'état du core.

Ce qu'ils ne prouvent PAS, et que seul le job `installateur` de la CI prouve : que le vrai core se construit, accepte
la configuration (`opsys config validate`), applique bien la règle qu'on lui prête (`opsys config file`,
`gateway install`), démarre par le service et lance le moteur.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from opsys import instance

pytestmark = pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None,
                                reason="scripts bash : Linux et macOS (Windows : install.ps1)")

FICTIF = True  # aucune valeur ci-dessous n'est réelle (AGENTS.md)

RACINE = Path(__file__).resolve().parents[1]
INSTALL = RACINE / "install" / "install.sh"
UNINSTALL = RACINE / "install" / "uninstall.sh"
PNPM = "12.4.0"
PROFIL = "--profile opsys"  # l'option racine par laquelle le core projette son état canonique
EMBEDDINGS = {"OPSYS_EMBEDDINGS_URL": "http://127.0.0.1:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "bge-m3"}

FAUX_NODE = r"""#!/usr/bin/env bash
case "${1:-}" in
    -v) echo "v${FAUX_NODE_VERSION:-24.16.0}"; exit 0 ;;
    --input-type=module) [ "${FAUX_NODE_SUPPORTE:-1}" = "1" ]; exit $? ;;
esac
if [[ "${1:-}" == *openclaw.mjs ]]; then
    shift
    appel="openclaw $*"
    # Option racine `--profile` : le core pose l'état et la configuration canoniques du profil, sauf si un état est
    # déjà posé dans l'environnement (core/src/cli/profile.ts, applyCliProfileEnv).
    plein() { [ -n "$(ls -A "$1" 2>/dev/null)" ]; }
    if [ "${1:-}" = "--profile" ]; then
        export OPENCLAW_PROFILE="$2"
        shift 2
        # core/src/config/opsys-instance.ts : l'état du profil `opsys` est ~/.opsys/core ; tant que seul l'ancien
        # ~/.openclaw-opsys porte un état, le core l'utilise en place (Doctor le déplace ensuite).
        if [ "$OPENCLAW_PROFILE" = "opsys" ]; then
            defaut="$HOME/.opsys/core"
            if ! plein "$defaut" && plein "$HOME/.openclaw-opsys"; then defaut="$HOME/.openclaw-opsys"; fi
        else
            defaut="$HOME/.openclaw-$OPENCLAW_PROFILE"
        fi
        export OPENCLAW_STATE_DIR="${OPENCLAW_STATE_DIR:-$defaut}"
        if [ -z "${OPENCLAW_CONFIG_PATH:-}" ]; then
            config="$OPENCLAW_STATE_DIR/openclaw.json"
            # profil `opsys` : opsys.json, sauf si seul un openclaw.json existe (lu en place, jamais renommé)
            if [ "$OPENCLAW_PROFILE" = "opsys" ]; then
                if [ -e "$OPENCLAW_STATE_DIR/opsys.json" ] || [ ! -e "$config" ]; then
                    config="$OPENCLAW_STATE_DIR/opsys.json"
                fi
            fi
            export OPENCLAW_CONFIG_PATH="$config"
        fi
    fi
    echo "$appel" >>"$FAUX_JOURNAL"
    echo "etat=${OPENCLAW_STATE_DIR:-} profil=${OPENCLAW_PROFILE:-} home=${OPENCLAW_HOME:-}" \
        "config=${OPENCLAW_CONFIG_PATH:-}" >>"$FAUX_ETATS"
    if [ "${FAUX_ECHEC:-}" = "$appel" ]; then echo "echec simule de : $*" >&2; exit 1; fi
    if [ "$1" = "config" ] && [ "${2:-}" = "file" ]; then
        if [ -n "${FAUX_CONFIG_AILLEURS:-}" ]; then echo "$FAUX_CONFIG_AILLEURS"; exit 0; fi
        echo "${OPENCLAW_CONFIG_PATH:-$HOME/.openclaw/openclaw.json}"
        exit 0
    fi
    if [ "$1" = "gateway" ] && { [ "${2:-}" = "install" ] || [ "${2:-}" = "uninstall" ]; }; then
        # core/src/config/paths.ts, isDefaultInstallIdentity : l'état doit être le dossier canonique du profil (chemin
        # réel : un lien laissé par Doctor à l'ancien chemin désigne le même dossier), la configuration un de ses noms.
        reel() { (cd "$1" 2>/dev/null && pwd -P) || printf '%s' "$1"; }
        if [ "${OPENCLAW_PROFILE:-}" = "opsys" ]; then
            canonique="$HOME/.opsys/core"
            if ! plein "$canonique" && plein "$HOME/.openclaw-opsys"; then canonique="$HOME/.openclaw-opsys"; fi
            noms="opsys.json openclaw.json"
        else
            canonique="$HOME/.openclaw${OPENCLAW_PROFILE:+-$OPENCLAW_PROFILE}"
            noms="openclaw.json"
        fi
        config_canonique=0
        if [ -z "${OPENCLAW_CONFIG_PATH:-}" ]; then config_canonique=1; fi
        canonique_reel="$(reel "$canonique")"
        for nom in $noms; do
            if [ -n "${OPENCLAW_CONFIG_PATH:-}" ]; then
                actif="$(reel "$(dirname "$OPENCLAW_CONFIG_PATH")")/$(basename "$OPENCLAW_CONFIG_PATH")"
                if [ "$actif" = "$canonique_reel/$nom" ]; then config_canonique=1; fi
            fi
        done
        etat_reel="$(reel "${OPENCLAW_STATE_DIR:-$HOME/.openclaw}")"
        if [ -n "${OPENCLAW_HOME:-}" ] || [ "$etat_reel" != "$canonique_reel" ] || [ "$config_canonique" -ne 1 ]; then
            echo "Gateway $2 blocked: Error: service management skipped: non-default state dir or config path." >&2
            exit 1
        fi
        # core/src/daemon/constants.ts : le nom du service vient du profil.
        unite="$HOME/.config/systemd/user/openclaw-gateway${OPENCLAW_PROFILE:+-$OPENCLAW_PROFILE}.service"
        if [ "$2" = "install" ]; then
            mkdir -p "$(dirname "$unite")"
            printf '[Service]\nEnvironment="OPENCLAW_STATE_DIR=%s"\n' "$OPENCLAW_STATE_DIR" >"$unite"
            # Un core qui crache un secret : l'installateur ne doit ni l'afficher ni le journaliser.
            echo "service installe, jeton du moteur : $(sed -n 's/^OPSYS_MCP_JETON=//p' "$OPENCLAW_STATE_DIR/.env")"
        else
            rm -f "$unite"
        fi
    fi
    exit 0
fi
echo "faux node : appel inattendu : $*" >&2
exit 99
"""

FAUX_PNPM = r"""#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then echo "$FAUX_PNPM_VERSION"; exit 0; fi
echo "pnpm $*" >>"$FAUX_JOURNAL"
if [ "${FAUX_ECHEC:-}" = "pnpm $*" ]; then echo "echec simule de : pnpm $*" >&2; exit 1; fi
exit 0
"""

FAUX_UV = r"""#!/usr/bin/env bash
echo "uv $*" >>"$FAUX_JOURNAL"
if [ "$1 ${2:-}" = "venv --clear" ]; then
    for dossier; do :; done  # le dernier argument (portable : bash 3.2 de macOS compris)
    mkdir -p "$dossier/bin"
    printf '#!/bin/sh\nexec %s "$@"\n' "$FAUX_PYTHON" >"$dossier/bin/python"
    chmod +x "$dossier/bin/python"
fi
exit 0
"""

FAUX_CURL = "#!/usr/bin/env bash\nexit 0\n"
FAUX_DOCKER = r'''#!/usr/bin/env bash
printf 'docker %s\n' "$*" >>"$FAUX_JOURNAL"
"$FAUX_PYTHON" -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >>"$FAUX_DOCKER_ARGV"
case "${1:-}" in
    info)
        if [ "${FAUX_DOCKER_DAEMON:-ready}" != "ready" ]; then
            echo 'Cannot connect to the Docker daemon' >&2
            exit 1
        fi
        [ "${FAUX_DOCKER_OS:-linux}" = "linux" ] || {
            echo "${FAUX_DOCKER_OS}"
            exit 0
        }
        echo linux
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
        if [ "${FAUX_DOCKER_BUILD:-success}" = "fail" ]; then
            echo 'network unavailable while fetching pinned base image' >&2
            exit 1
        fi
        : >"$FAUX_DOCKER_IMAGE_STATE"
        exit 0
        ;;
    *) echo "unexpected docker arguments: $*" >&2; exit 2 ;;
esac
'''


class Bac:
    """Un poste fictif : HOME, instance, logiciel, commandes, fausses commandes et journal des appels."""

    def __init__(self, tmp_path: Path) -> None:
        self.racine = tmp_path
        self.hote = tmp_path / "hote"
        self.home = tmp_path / "instance"
        self.logiciel = tmp_path / "logiciel"
        self.bin = tmp_path / "commandes"
        self.faux = tmp_path / "faux"
        self.journal = tmp_path / "appels.log"
        self.etats = tmp_path / "etats.log"
        self.depot = tmp_path / "depot"
        self.etat_core = self.hote / ".opsys" / "core"  # le dossier canonique du profil `opsys`, sous HOME
        self.ancien_profil = self.hote / ".openclaw-opsys"  # où le profil rangeait son état avant T0.7 lot 3
        self.hote.mkdir()
        self.faux.mkdir()
        for nom, corps in (("node", FAUX_NODE), ("pnpm", FAUX_PNPM), ("uv", FAUX_UV), ("curl", FAUX_CURL),
                           ("docker", FAUX_DOCKER)):
            chemin = self.faux / nom
            chemin.write_text(corps, encoding="utf-8")
            chemin.chmod(0o755)
        self.journal.write_text("", encoding="utf-8")
        self.etats.write_text("", encoding="utf-8")
        self.env_supplementaire: dict[str, str] = {}

    # -- le dépôt fictif : le strict nécessaire pour l'installateur, dans un vrai dépôt git ---------------------------
    def fabriquer_depot(self) -> Path:
        (self.depot / "core").mkdir(parents=True)
        (self.depot / "departments").mkdir()
        (self.depot / "core" / "openclaw.mjs").write_text("// faux core\n", encoding="utf-8")
        (self.depot / "core" / "node-version.mjs").write_text("// faux\n", encoding="utf-8")
        shutil.copytree(RACINE / "core" / "scripts", self.depot / "core" / "scripts")
        (self.depot / "core" / "package.json").write_text(
            json.dumps({"name": "openclaw", "packageManager": f"pnpm@{PNPM}+sha512.0123456789abcdef"}, indent=2) + "\n",
            encoding="utf-8")
        (self.depot / "pyproject.toml").write_text('[project]\nname = "faux-opsys"\n', encoding="utf-8")
        (self.depot / "departments" / "LISEZMOI").write_text("faux\n", encoding="utf-8")
        for commande in (["init", "-q", "-b", "main"], ["add", "-A"]):
            self.git(*commande)
        self.commit("premier")
        self.git("tag", "v0")
        return self.depot

    def git(self, *args: str) -> str:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}
        return subprocess.run(["git", "-C", str(self.depot), *args], env=env, check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, message: str) -> str:
        (self.depot / "core" / "CHANGEMENT").write_text(message + "\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    # -- exécution -------------------------------------------------------------------------------------------
    def env(self, chemin_path: str | None = None) -> dict[str, str]:
        chemins_python = [str(RACINE / "src"), *sorted(str(p) for p in RACINE.glob("departments/*/src"))]
        env = {
            "HOME": str(self.hote), "PATH": chemin_path or f"{self.faux}:/usr/bin:/bin",
            "OPSYS_HOME": str(self.home), "OPSYS_LOGICIEL": str(self.logiciel), "OPSYS_BIN": str(self.bin),
            "PYTHONPATH": os.pathsep.join(chemins_python), "LANG": "C.UTF-8",
            "FAUX_JOURNAL": str(self.journal), "FAUX_ETATS": str(self.etats), "FAUX_PNPM_VERSION": PNPM,
            "FAUX_PYTHON": sys.executable, "FAUX_DOCKER_IMAGE_STATE": str(self.racine / "docker-image"),
            "FAUX_DOCKER_ARGV": str(self.racine / "docker-argv.jsonl"),
        }
        env.update(self.env_supplementaire)
        return env


    def lancer(self, script: Path, *args: str, chemin_path: str | None = None, entree: str | None = None,
               cwd: Path | None = None, **env: str) -> subprocess.CompletedProcess[str]:
        commande = ["bash", "-s", "--", *args] if entree is not None else ["bash", str(script), *args]
        return subprocess.run(commande, env={**self.env(chemin_path), **env}, input=entree, capture_output=True,
                              text=True, timeout=300, check=False, cwd=cwd or self.racine)

    def installer(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return self.lancer(INSTALL, *args, OPSYS_SOURCE=str(self.depot), **env)

    def appels(self) -> list[str]:
        return self.journal.read_text(encoding="utf-8").splitlines()

    def arguments_docker(self) -> list[list[str]]:
        journal = self.racine / "docker-argv.jsonl"
        if not journal.exists():
            return []
        return [json.loads(ligne) for ligne in journal.read_text(encoding="utf-8").splitlines()]

    def etats_du_core(self) -> list[dict[str, str]]:
        """Ce que le faux core a reçu à chaque appel : état, profil, OPENCLAW_HOME, configuration."""
        lignes = self.etats.read_text(encoding="utf-8").splitlines()
        return [dict(champ.split("=", 1) for champ in ligne.split() if "=" in champ) | {"ligne": ligne}
                for ligne in lignes]

    def etats_vus_par_le_core(self) -> set[str]:
        """Les dossiers d'état que le faux core a reçus, un par appel."""
        return {appel["etat"] for appel in self.etats_du_core()}

    def preparer_decisions(self) -> None:
        """Les décisions que l'installateur n'invente pas : un palier de modèles et le service d'embeddings."""
        self.home.mkdir(parents=True, mode=0o700, exist_ok=True)
        (self.home / "paliers.yaml").write_text(
            "paliers: {standard: {provider: anthropic, model: claude-sonnet-5}}\n", encoding="utf-8")
        self.env_supplementaire.update(EMBEDDINGS)

    def secrets(self, dossier: Path | None = None) -> list[str]:
        env = ((dossier or self.etat_core) / ".env").read_text(encoding="utf-8")
        return [v for k, v in re.findall(r"^([A-Z0-9_]+)=(.*)$", env, flags=re.MULTILINE)
                if re.search(r"JETON|TOKEN|CLE", k) and len(v) >= 12]

    def empreinte_du_dossier(self, dossier: Path) -> dict[str, str]:
        return {str(p.relative_to(dossier)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(dossier.rglob("*")) if p.is_file()}


@pytest.fixture
def bac(tmp_path: Path) -> Bac:
    bac = Bac(tmp_path)
    bac.fabriquer_depot()
    return bac


def _sortie(resultat: subprocess.CompletedProcess[str]) -> str:
    return resultat.stdout + resultat.stderr


# -- fail-closed : prérequis ---------------------------------------------------------------------------------
def test_sans_node_ou_sans_uv_rien_n_est_fait_et_le_message_dit_quoi_installer(bac):
    (bac.faux / "node").unlink()
    sans_node = bac.installer(chemin_path=f"{bac.faux}:/usr/bin:/bin")
    (bac.faux / "node").write_text(FAUX_NODE, encoding="utf-8")
    (bac.faux / "node").chmod(0o755)
    (bac.faux / "uv").unlink()
    sans_uv = bac.installer(chemin_path=f"{bac.faux}:/usr/bin:/bin")

    assert sans_node.returncode == 1 and "Node.js est introuvable" in sans_node.stderr
    assert "24.16" in sans_node.stderr and "26.1" in sans_node.stderr
    assert sans_uv.returncode == 1 and "uv est introuvable" in sans_uv.stderr
    assert "astral.sh/uv" in sans_uv.stderr
    assert not bac.home.exists() and not bac.logiciel.exists() and not bac.bin.exists()  # rien n'a été créé


@pytest.mark.parametrize(
    ("reglages", "message"),
    [
        ({"OPSYS_MODE_FOURNISSEUR": "autre"}, "doit valoir natif ou litellm"),
        ({"OPSYS_MODE_FOURNISSEUR": "litellm"}, "exige OPSYS_PASSERELLE_URL"),
        ({"OPSYS_PASSERELLE_URL": "http://127.0.0.1:4000/v1"}, "seul n'active pas LiteLLM"),
    ],
)
def test_le_mode_fournisseur_est_valide_avant_tout_travail_installateur(bac, reglages, message):
    resultat = bac.installer(**reglages)

    assert resultat.returncode == 1 and message in resultat.stderr
    assert not any(appel.startswith(("pnpm", "uv")) for appel in bac.appels())
    assert not bac.home.exists() and not bac.logiciel.exists() and not bac.bin.exists()


def test_un_node_non_supporte_par_le_fork_arrete_tout(bac):
    resultat = bac.installer(FAUX_NODE_SUPPORTE="0", FAUX_NODE_VERSION="22.1.0")

    assert resultat.returncode == 1
    assert "Node v22.1.0 n'est pas pris en charge" in resultat.stderr and "24.16" in resultat.stderr
    assert not any(a.startswith("pnpm") for a in bac.appels()) and not bac.bin.exists()


def test_sans_cli_docker_l_installation_est_refusee_avant_tout_travail(bac):
    (bac.faux / "docker").unlink()

    resultat = bac.installer()

    assert resultat.returncode == 1 and "Docker CLI" in resultat.stderr
    assert not any(a.startswith(("pnpm", "uv", "openclaw")) for a in bac.appels())
    assert not bac.home.exists() and not bac.logiciel.exists() and not bac.bin.exists()


def test_sans_daemon_docker_linux_accessible_aucune_installation_ne_demarre(bac):
    resultat = bac.installer(FAUX_DOCKER_DAEMON="absent")

    assert resultat.returncode == 1 and "daemon Docker" in resultat.stderr
    assert "docker info" in "\n".join(bac.appels())
    assert not any(a.startswith(("pnpm", "uv", "openclaw")) for a in bac.appels())
    assert not any("gateway install" in a for a in bac.appels())


def test_daemon_docker_windows_est_refuse_avant_tout_travail(bac):
    resultat = bac.installer(FAUX_DOCKER_OS="windows")

    assert resultat.returncode == 1 and "conteneurs Linux" in resultat.stderr
    assert not any(a.startswith(("pnpm", "uv", "openclaw")) for a in bac.appels())
    assert not any("gateway install" in a for a in bac.appels())


def test_image_sandbox_existante_est_reutilisee_sans_rebuild_ni_pull(bac):
    bac.preparer_decisions()

    resultat = bac.installer(FAUX_DOCKER_IMAGE="present")

    appels = bac.appels()
    assert resultat.returncode == 0, _sortie(resultat)
    assert "docker image inspect openclaw-sandbox:bookworm-slim" in appels
    assert not any(a.startswith("docker build") for a in appels)
    assert not any(a.startswith("docker pull") for a in appels)
    assert appels.index("docker image inspect openclaw-sandbox:bookworm-slim") < next(
        i for i, a in enumerate(appels) if "gateway install" in a
    )


def test_image_sandbox_absente_est_construite_avant_demarrage_du_gateway(bac):
    bac.preparer_decisions()
    bac.depot.rename(bac.depot.with_name("depot avec espaces"))
    bac.depot = bac.depot.with_name("depot avec espaces")

    resultat = bac.installer(FAUX_DOCKER_IMAGE="absent")

    assert resultat.returncode == 0, _sortie(resultat)
    appels = bac.appels()
    construction = next(i for i, a in enumerate(appels) if a.startswith("docker build "))
    demarrage = next(i for i, a in enumerate(appels) if "gateway install" in a)
    assert construction < demarrage
    assert "openclaw-sandbox:bookworm-slim" in appels[construction]
    assert "scripts/docker/sandbox/Dockerfile" in appels[construction]
    assert not any(a.startswith("docker pull") for a in appels)
    attendu = ["build", "-t", "openclaw-sandbox:bookworm-slim", "-f",
               str(bac.depot / "core/scripts/docker/sandbox/Dockerfile"), str(bac.depot / "core")]
    assert attendu in bac.arguments_docker()


def test_echec_build_sandbox_arrete_l_installation_avec_conseil_reseau(bac):
    resultat = bac.installer(FAUX_DOCKER_IMAGE="absent", FAUX_DOCKER_BUILD="fail")

    assert resultat.returncode == 1
    assert "image sandbox" in resultat.stderr.lower()
    assert "reseau" in resultat.stderr.lower() or "réseau" in resultat.stderr.lower()
    assert not any("gateway install" in a for a in bac.appels())
    assert any(a.startswith("docker build") for a in bac.appels())


def test_une_option_inconnue_est_refusee(bac):
    resultat = bac.installer("--nimporte")

    assert resultat.returncode == 1 and "option inconnue" in resultat.stderr


# -- l'installation de bout en bout (fausses commandes) ------------------------------------------------------
def test_installation_complete_dans_l_ordre_avec_les_bons_arguments(bac):
    bac.preparer_decisions()

    resultat = bac.installer()

    assert resultat.returncode == 0, _sortie(resultat)
    assert "OPSYS est installé." in resultat.stdout
    assert "natifs OpenClaw" in resultat.stdout and "aucun service LiteLLM requis" in resultat.stdout
    appels = bac.appels()
    attendu = ["pnpm install --frozen-lockfile", "pnpm build", f"openclaw {PROFIL} --version"]
    assert [a for a in appels if a in attendu] == attendu
    ordre = [next(i for i, a in enumerate(appels) if a.startswith(debut)) for debut in (
        "pnpm install", "pnpm build", "uv venv", "uv sync", f"openclaw {PROFIL} --version",
        f"openclaw {PROFIL} config file", f"openclaw {PROFIL} config validate", f"openclaw {PROFIL} gateway install")]
    assert ordre == sorted(ordre)
    assert f"uv venv --clear --python >=3.11 {bac.logiciel}/venv" in appels
    sync = (f"uv sync --locked --project {bac.depot} --python {bac.logiciel}/venv/bin/python "
            "--group build --no-dev --extra tournees --extra soumission --no-build-isolation")
    assert sync + " --no-install-project" in appels
    assert sync in appels
    assert f"openclaw {PROFIL} gateway install --force --port 18789" in appels
    assert all(a.startswith(f"openclaw {PROFIL} ") for a in appels if a.startswith("openclaw "))  # jamais sans profil
    config = json.loads((bac.etat_core / "opsys.json").read_text(encoding="utf-8"))
    assert config["gateway"]["port"] == 18789
    assert not (bac.etat_core / "openclaw.json").exists()  # l'instance neuve n'a que le nom canonique
    metier = json.loads((bac.etat_core / "opsys" / "metier.json").read_text(encoding="utf-8"))
    assert metier["actif"] is True and metier["dossier"] == str(bac.depot) and metier["port"] == 8765
    enregistrement = (bac.logiciel / "installation.env").read_text(encoding="utf-8")
    for ligne in (f"OPSYS_HOME={bac.home}", f"SOURCE={bac.depot}", "SOURCE_GEREE=0", "SERVICE=1", "PORT_GATEWAY=18789",
                  "PORT_MOTEUR=8765", "PROFIL_CORE=opsys", f"DOSSIER_CORE={bac.etat_core}"):
        assert ligne in enregistrement.splitlines()


def test_les_ports_demandes_sont_ceux_du_service_et_du_moteur(bac):
    bac.preparer_decisions()

    resultat = bac.installer(OPSYS_PORT_GATEWAY="18790", OPSYS_PORT_MOTEUR="8766")

    assert resultat.returncode == 0, _sortie(resultat)
    assert f"openclaw {PROFIL} gateway install --force --port 18790" in bac.appels()
    metier = json.loads((bac.etat_core / "opsys" / "metier.json").read_text(encoding="utf-8"))
    assert metier["port"] == 8766 and metier["commande"][-1] == "8766"
    relance = bac.installer()  # les ports sont ceux de la dernière installation, sans qu'on les redonne
    assert relance.returncode == 0 and "PORT_GATEWAY=18790" in (bac.logiciel / "installation.env").read_text()


def test_le_secret_est_prive_jamais_affiche_et_masque_meme_quand_une_commande_le_crache(bac):
    bac.preparer_decisions()

    resultat = bac.installer(OPSYS_VERBOSE="1")

    assert resultat.returncode == 0, _sortie(resultat)
    env = bac.etat_core / ".env"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    secrets = bac.secrets()
    assert len(secrets) >= 12
    journal = (bac.logiciel / "journaux" / "installation.log").read_text(encoding="utf-8")
    for secret in secrets:
        assert secret not in _sortie(resultat), "un secret est affiché"
        assert secret not in journal, "un secret est journalisé"
    assert "service installe, jeton du moteur : ***" in journal  # le faux core l'a craché, le masque l'a couvert
    assert "service installe, jeton du moteur : ***" in resultat.stdout  # (OPSYS_VERBOSE=1 : à l'écran aussi)


def test_relancer_l_installateur_ne_change_ni_secret_ni_configuration_ni_donnee(bac):
    bac.preparer_decisions()
    premier = bac.installer()
    assert premier.returncode == 0, _sortie(premier)
    avant_core = bac.empreinte_du_dossier(bac.etat_core)
    avant_paliers = (bac.home / "paliers.yaml").read_bytes()

    second = bac.installer()

    assert second.returncode == 0, _sortie(second)
    assert bac.empreinte_du_dossier(bac.etat_core) == avant_core  # .env, opsys.json, fragments, metier.json
    assert (bac.home / "paliers.yaml").read_bytes() == avant_paliers
    installation_du_service = f"openclaw {PROFIL} gateway install --force --port 18789"
    assert bac.appels().count(installation_du_service) == 2  # le Gateway est redémarré


def test_avec_l_option_sans_service_le_service_n_est_pas_installe(bac):
    bac.preparer_decisions()

    resultat = bac.installer("--sans-service")

    assert resultat.returncode == 0, _sortie(resultat)
    assert not [a for a in bac.appels() if " gateway " in a]
    assert f"openclaw {PROFIL} config validate" in bac.appels()
    assert "SERVICE=0" in (bac.logiciel / "installation.env").read_text(encoding="utf-8").splitlines()
    assert "opsys gateway run" in resultat.stdout


def test_les_commandes_installees_portent_l_instance_et_lisent_env_sans_l_evaluer(bac):
    bac.preparer_decisions()
    assert bac.installer("--sans-service").returncode == 0
    piege = bac.racine / "piege-execute"
    (bac.etat_core / ".env").write_text(
        (bac.etat_core / ".env").read_text(encoding="utf-8") + f"PIEGE=$(touch {piege})\n", encoding="utf-8")
    env = {k: v for k, v in bac.env().items() if k != "OPSYS_HOME"}  # la commande retrouve l'instance seule

    # `opsys-metier` : le moteur seul (T0.7 lot 2), l'ancienne commande `opsys` renommée
    etat = subprocess.run([str(bac.bin / "opsys-metier"), "base", "etat"], env=env, capture_output=True, text=True,
                          check=False)
    version = subprocess.run([str(bac.bin / "opsys-metier"), "--version"], env=env, capture_output=True, text=True,
                             check=False)

    assert etat.returncode == 0, etat.stderr
    assert json.loads(etat.stdout)["base"].endswith(str(bac.home / "opsys.db"))
    assert version.stdout.startswith("opsys-metier ")
    assert not piege.exists()  # la ligne du .env a été lue, jamais évaluée
    # `opsys` est le core, et `openclaw` son alias : les deux passent par le core, sous le profil `opsys`
    validation = f"openclaw {PROFIL} config validate"
    deja = bac.appels().count(validation)  # l'installateur l'a lancée lui-même une fois
    for commande in ("opsys", "openclaw"):
        coeur = subprocess.run([str(bac.bin / commande), "config", "validate"], env=env, capture_output=True,
                               text=True, check=False)
        assert coeur.returncode == 0, (commande, coeur.stderr)
    assert bac.appels().count(validation) == deja + 2
    for commande in ("opsys", "openclaw", "opsys-metier"):
        assert os.access(bac.bin / commande, os.X_OK)
    enveloppe_core = (bac.bin / "opsys").read_text(encoding="utf-8")
    assert (bac.bin / "openclaw").read_text(encoding="utf-8") == enveloppe_core  # l'alias est le même core
    assert f"--profile {instance.PROFIL_CORE} " in enveloppe_core  # le core d'OPSYS tourne sous son profil
    assert "export OPENCLAW_STATE_DIR" not in enveloppe_core  # jamais un état posé à la main
    assert f"unset {' '.join(instance.VARIABLES_ECARTEES)}" in enveloppe_core
    assert "-m opsys.cli" not in enveloppe_core  # `opsys` n'est plus l'enveloppe du moteur
    enveloppe_moteur = (bac.bin / "opsys-metier").read_text(encoding="utf-8")
    assert f"DOSSIER_CORE={bac.etat_core}" in enveloppe_moteur and "-m opsys.cli" in enveloppe_moteur
    powershell = (RACINE / "install" / "install.ps1").read_text(encoding="utf-8")
    assert "natifs OpenClaw" in powershell and "aucun service LiteLLM requis" in powershell


# -- fail-closed : décision manquante, étape en échec, fichier étranger --------------------------------------
def test_sans_paliers_ni_embeddings_l_installation_s_arrete_en_attente_avec_le_code_3(bac):
    resultat = bac.installer()

    assert resultat.returncode == 3, _sortie(resultat)
    assert "À FAIRE : paliers de modèles" in resultat.stderr and "À FAIRE : service d'embeddings" in resultat.stderr
    assert "Ce n'est pas une erreur d'installation" in resultat.stdout
    appels = bac.appels()
    assert f"openclaw {PROFIL} config validate" not in appels and not [a for a in appels if "gateway install" in a]
    assert f"openclaw {PROFIL} config file" in appels  # la vérification du dossier d'état a lieu même en attente
    for commande in ("opsys", "openclaw", "opsys-metier"):  # de quoi fournir les décisions
        assert (bac.bin / commande).exists(), commande
    assert (bac.etat_core / ".env").is_file() and not (bac.etat_core / "opsys.json").exists()

    bac.preparer_decisions()
    reprise = bac.installer()  # la même commande, décisions fournies : tout se termine
    assert reprise.returncode == 0, _sortie(reprise)
    assert f"openclaw {PROFIL} gateway install --force --port 18789" in bac.appels()


def test_une_etape_en_echec_arrete_tout_avec_la_fin_du_journal_et_quoi_faire(bac):
    bac.preparer_decisions()

    resultat = bac.installer(FAUX_ECHEC="pnpm build")

    assert resultat.returncode == 1
    assert "Construction du core (pnpm build, plusieurs minutes) : échec (code 1)" in resultat.stderr
    assert "echec simule de : pnpm build" in resultat.stderr  # fin du journal
    assert str(bac.logiciel / "journaux" / "installation.log") in resultat.stderr
    assert not [a for a in bac.appels() if a.startswith("uv")]  # rien n'a continué
    assert not bac.bin.exists() and not (bac.logiciel / "installation.env").exists()


def test_le_bout_en_bout_sonde_de_vrais_endpoints_http_de_readiness(bac):
    requetes: list[str] = []

    class Gestionnaire(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requetes.append(self.path)
            self.send_response(200 if self.path in {"/startupz", "/sante"} else 404)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
    fil = threading.Thread(target=serveur.serve_forever, daemon=True)
    fil.start()
    try:
        bac.preparer_decisions()
        curl = shutil.which("curl", path="/usr/bin:/bin")
        assert curl
        (bac.faux / "curl").write_text(f'#!/usr/bin/env bash\nexec {curl} "$@"\n', encoding="utf-8")
        (bac.faux / "curl").chmod(0o755)

        resultat = bac.installer(
            OPSYS_PORT_GATEWAY=str(serveur.server_port), OPSYS_PORT_MOTEUR=str(serveur.server_port)
        )

        assert resultat.returncode == 0, _sortie(resultat)
        assert "/startupz" in requetes and "/sante" in requetes
    finally:
        serveur.shutdown()
        serveur.server_close()
        fil.join(timeout=2)


def test_une_configuration_refusee_par_le_core_arrete_avant_le_service(bac):
    bac.preparer_decisions()

    resultat = bac.installer(FAUX_ECHEC=f"openclaw {PROFIL} config validate")

    assert resultat.returncode == 1 and "Validation de la configuration par le core" in resultat.stderr
    assert not [a for a in bac.appels() if "gateway install" in a]


def test_un_service_impossible_dit_quoi_faire(bac):
    bac.preparer_decisions()

    resultat = bac.installer(FAUX_ECHEC=f"openclaw {PROFIL} gateway install --force --port 18789")

    assert resultat.returncode == 1
    assert "--sans-service" in resultat.stderr and "opsys gateway run" in resultat.stderr


def test_un_fichier_etranger_n_est_jamais_ecrase(bac):
    bac.preparer_decisions()
    bac.bin.mkdir()
    etranger = bac.bin / "openclaw"
    etranger.write_text("#!/bin/sh\necho openclaw d'origine\n", encoding="utf-8")

    resultat = bac.installer()

    assert resultat.returncode == 1 and "n'a pas été installé par OPSYS" in resultat.stderr
    assert etranger.read_text(encoding="utf-8") == "#!/bin/sh\necho openclaw d'origine\n"


def test_un_fichier_etranger_opsys_ou_opsys_metier_arrete_avant_toute_ecriture(bac):
    """Les trois commandes sont vérifiées avant la première écriture : aucun jeu n'est laissé à moitié remplacé."""
    bac.preparer_decisions()
    bac.bin.mkdir()
    for nom in ("opsys", "opsys-metier"):
        etranger = bac.bin / nom
        etranger.write_text(f"#!/bin/sh\necho {nom} d'un autre\n", encoding="utf-8")

        resultat = bac.installer()

        assert resultat.returncode == 1, (nom, _sortie(resultat))
        assert "n'a pas été installé par OPSYS" in resultat.stderr and str(etranger) in resultat.stderr
        assert etranger.read_text(encoding="utf-8") == f"#!/bin/sh\necho {nom} d'un autre\n"
        assert [f.name for f in bac.bin.iterdir()] == [nom]  # ni l'alias ni l'autre commande n'ont été écrits
        etranger.unlink()


def _ancienne_enveloppe_du_moteur() -> str:
    """Le fichier `opsys` que l'installateur écrivait avant le lot 2 : l'enveloppe du moteur, sous la même marque."""
    marque = re.search(r"^MARQUE='(.*)'$", INSTALL.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert marque is not None
    return f'#!/usr/bin/env bash\n{marque.group(1)}\nPY=/ancien/venv/bin/python\nexec "$PY" -m opsys.cli "$@"\n'


def test_une_installation_d_avant_le_lot_2_est_mise_a_jour_sans_perte_et_le_dit(bac):
    """`opsys` était le moteur : la relance le remplace par le core, rend le moteur à `opsys-metier`, et le dit."""
    bac.preparer_decisions()
    assert bac.installer().returncode == 0
    (bac.bin / "opsys").write_text(_ancienne_enveloppe_du_moteur(), encoding="utf-8")  # l'état d'avant le lot 2
    (bac.bin / "opsys-metier").unlink()
    chemin_metier = bac.etat_core / "opsys" / "metier.json"
    ancien_metier = json.loads(chemin_metier.read_text(encoding="utf-8"))
    ancien_metier.pop("commande_cli")
    chemin_metier.write_text(json.dumps(ancien_metier), encoding="utf-8")
    donnees_avant = bac.empreinte_du_dossier(bac.home)

    mise_a_jour = bac.installer()

    assert mise_a_jour.returncode == 0, _sortie(mise_a_jour)
    assert "l'ancienne commande du moteur est remplacée" in mise_a_jour.stdout
    assert "opsys metier <commande>" in mise_a_jour.stdout and "opsys-metier <commande>" in mise_a_jour.stdout
    remplace = (bac.bin / "opsys").read_text(encoding="utf-8")
    assert "openclaw.mjs" in remplace and "-m opsys.cli" not in remplace  # le core, plus l'enveloppe du moteur
    assert "-m opsys.cli" in (bac.bin / "opsys-metier").read_text(encoding="utf-8")
    metier = json.loads(chemin_metier.read_text(encoding="utf-8"))
    # la clé que `opsys metier` lit est revenue : le même interpréteur que le serveur que le Gateway supervise
    assert metier["commande_cli"] == [metier["commande"][0], "-m", "opsys.cli"]
    assert {n: h for n, h in bac.empreinte_du_dossier(bac.home).items() if not n.startswith("opsys.db")} == \
           {n: h for n, h in donnees_avant.items() if not n.startswith("opsys.db")}  # les données sont celles d'avant
    encore = bac.installer()
    assert encore.returncode == 0 and "l'ancienne commande du moteur est remplacée" not in encore.stdout


def test_un_autre_opsys_dans_le_path_est_signale_sans_etre_lance(bac):
    """Typiquement l'ancien moteur Python (pip, pipx, uv tool) : `opsys metier` n'atteindrait pas le core."""
    bac.preparer_decisions()
    marqueur = bac.racine / "autre-opsys-execute"
    autre = bac.faux / "opsys"
    autre.write_text(f"#!/bin/sh\ntouch {marqueur}\n", encoding="utf-8")
    autre.chmod(0o755)

    masque = bac.installer("--sans-service", chemin_path=f"{bac.faux}:{bac.bin}:/usr/bin:/bin")

    assert masque.returncode == 0, _sortie(masque)  # un avertissement, jamais un échec
    assert "AVERTISSEMENT : la commande « opsys » de votre PATH est " + str(autre) in masque.stderr
    assert f"pas celle qu'OPSYS vient d'installer ({bac.bin}/opsys)" in masque.stderr
    assert "pip uninstall opsys-ai" in masque.stderr and "uv tool uninstall opsys-ai" in masque.stderr
    assert not marqueur.exists()  # le chemin est dit, la commande n'est jamais lancée
    autre.unlink()

    propre = bac.installer("--sans-service", chemin_path=f"{bac.bin}:{bac.faux}:/usr/bin:/bin")

    assert propre.returncode == 0, _sortie(propre)
    assert "de votre PATH est" not in propre.stderr  # `opsys` d'OPSYS passe en premier : rien à dire


def test_une_url_de_base_dans_l_environnement_est_refusee_avec_la_voie_docker(bac):
    bac.preparer_decisions()

    resultat = bac.installer(OPSYS_BASE_URL="postgresql+psycopg://u:mot-de-passe-pg-fictif@h/db")

    assert resultat.returncode == 1
    assert "Docker Compose" in _sortie(resultat) and "mot-de-passe-pg-fictif" not in _sortie(resultat)


def _unite_du_core(bac: Bac, *, profil: str | None = "opsys") -> Path:
    """L'unité systemd que le faux core pose : son nom vient du profil (`constants.ts`)."""
    nom = f"openclaw-gateway-{profil}.service" if profil else "openclaw-gateway.service"
    return bac.hote / ".config" / "systemd" / "user" / nom


# -- le core tourne sous son profil : l'échec de la première exécution de la CI, reproduit puis évité -----------------
def test_le_faux_core_refuse_comme_le_vrai_un_etat_qui_n_est_pas_le_dossier_canonique_du_profil(bac):
    """Garde de l'outil de test : sans elle, les tests ci-dessous ne prouveraient rien."""
    bac.preparer_decisions()
    # ce que posait l'ancien installateur : un état à lui, sous OPSYS_HOME
    env = {**bac.env(), "OPENCLAW_STATE_DIR": str(bac.home / "core"), "OPENCLAW_PROFILE": "opsys"}

    refus = subprocess.run([str(bac.faux / "node"), "core/openclaw.mjs", "gateway", "install"], env=env,
                           capture_output=True, text=True, check=False)

    assert refus.returncode == 1 and "non-default state dir or config path" in refus.stderr
    sans_profil = subprocess.run(  # la variable OPENCLAW_PROFILE seule ne projette rien : l'état reste ~/.openclaw
        [str(bac.faux / "node"), "core/openclaw.mjs", "gateway", "install"],
        env={**bac.env(), "OPENCLAW_PROFILE": "opsys"}, capture_output=True, text=True, check=False)
    assert sans_profil.returncode == 1 and "non-default state dir" in sans_profil.stderr
    avec_home = subprocess.run(
        [str(bac.faux / "node"), "core/openclaw.mjs", "--profile", "opsys", "gateway", "install"],
        env={**bac.env(), "OPENCLAW_HOME": "/ailleurs"}, capture_output=True, text=True, check=False)
    assert avec_home.returncode == 1 and "non-default state dir" in avec_home.stderr


def test_le_core_recoit_toujours_le_profil_opsys_et_son_etat_est_le_dossier_canonique(bac):
    bac.preparer_decisions()

    resultat = bac.installer()

    assert resultat.returncode == 0, _sortie(resultat)
    assert bac.etats_vus_par_le_core() == {str(bac.etat_core)}  # chaque appel du core : le même dossier d'état
    appels_du_core = bac.etats_du_core()
    assert len(appels_du_core) >= 4  # --version, config file, config validate, gateway install
    assert {a["profil"] for a in appels_du_core} == {"opsys"} and {a.get("home", "") for a in appels_du_core} == {""}
    assert {a["config"] for a in appels_du_core} == {str(bac.etat_core / "opsys.json")}
    assert (bac.etat_core / ".env").is_file() and (bac.etat_core / "opsys.json").is_file()
    assert (bac.etat_core / "opsys" / "metier.json").is_file()
    assert not (bac.home / "core").exists()  # rien de l'état du core sous OPSYS_HOME
    assert stat.S_IMODE(bac.etat_core.stat().st_mode) == 0o700
    assert _unite_du_core(bac).is_file()  # le service du profil
    assert f"OPENCLAW_STATE_DIR={bac.etat_core}" in _unite_du_core(bac).read_text(encoding="utf-8")
    donnees = {p.name for p in bac.home.iterdir()}
    assert {"opsys.db", "paliers.yaml"} <= donnees and "core" not in donnees  # les données restent dans OPSYS_HOME


def test_un_environnement_qui_sortirait_l_etat_du_dossier_canonique_est_ecarte(bac):
    bac.preparer_decisions()
    pollue = {"OPENCLAW_STATE_DIR": str(bac.racine / "ailleurs"), "OPENCLAW_CONFIG_PATH": str(bac.racine / "c.json"),
              "OPENCLAW_HOME": str(bac.racine / "home-du-core"), "OPENCLAW_PROFILE": "autre",
              "OPENCLAW_SYSTEMD_UNIT": "autre.service", "OPENCLAW_LAUNCHD_LABEL": "autre",
              "OPENCLAW_WINDOWS_TASK_NAME": "autre"}

    resultat = bac.installer(**pollue)

    assert resultat.returncode == 0, _sortie(resultat)
    assert bac.etats_vus_par_le_core() == {str(bac.etat_core)}
    assert not (bac.racine / "ailleurs").exists() and not (bac.racine / "home-du-core").exists()
    assert any("OPENCLAW_STATE_DIR" in ligne and "ignoré" in ligne for ligne in _sortie(resultat).splitlines())
    # la commande `openclaw` installée écarte elle aussi l'environnement de l'appelant
    bac.etats.write_text("", encoding="utf-8")
    env = {k: v for k, v in bac.env().items() if k != "OPSYS_HOME"} | pollue
    coeur = subprocess.run([str(bac.bin / "openclaw"), "config", "file"], env=env, capture_output=True, text=True,
                           check=False)
    assert coeur.returncode == 0 and coeur.stdout.strip() == str(bac.etat_core / "opsys.json")
    assert bac.etats_vus_par_le_core() == {str(bac.etat_core)}
    assert {a["profil"] for a in bac.etats_du_core()} == {"opsys"}
    assert {a.get("home", "") for a in bac.etats_du_core()} == {""}


def test_le_core_qui_cherche_sa_configuration_ailleurs_arrete_tout_avant_le_service(bac):
    """Si la règle de profil du fork change, l'installateur s'arrête : pas de Gateway sans la configuration générée."""
    bac.preparer_decisions()

    resultat = bac.installer(FAUX_CONFIG_AILLEURS="/ailleurs/opsys.json")

    assert resultat.returncode == 1
    assert "/ailleurs/opsys.json" in resultat.stderr and f"{bac.etat_core}/opsys.json" in resultat.stderr
    assert "core/src/config/opsys-instance.ts" in resultat.stderr and "rien n'est démarré" in resultat.stderr
    assert not [a for a in bac.appels() if "gateway install" in a or "config validate" in a]
    assert not (bac.bin / "openclaw").exists()  # arrêt avant l'installation des commandes


def test_le_service_du_core_d_origine_n_est_jamais_touche_et_aucune_garde_ne_bloque(bac):
    """Le profil donne un nom de service distinct : plus de garde « service d'une autre installation »."""
    bac.preparer_decisions()
    origine = _unite_du_core(bac, profil=None)
    origine.parent.mkdir(parents=True)
    contenu = "[Service]\nExecStart=/usr/bin/node /opt/openclaw/openclaw.mjs gateway --port 18789\n"
    origine.write_text(contenu, encoding="utf-8")

    resultat = bac.installer()

    assert resultat.returncode == 0, _sortie(resultat)
    assert origine.read_text(encoding="utf-8") == contenu  # le service du core d'origine est intact
    assert _unite_du_core(bac).is_file() and _unite_du_core(bac) != origine
    relance = bac.installer()  # « gateway install --force » remplace le service du profil, pas celui d'origine
    assert relance.returncode == 0, _sortie(relance)
    assert origine.read_text(encoding="utf-8") == contenu
    dossier = _telecharger(bac)
    retrait = bac.lancer(dossier / "uninstall.sh")
    assert retrait.returncode == 0, _sortie(retrait)
    assert not _unite_du_core(bac).exists() and origine.read_text(encoding="utf-8") == contenu


# -- l'ancienne disposition ($OPSYS_HOME/core) : signalée avec la marche à suivre, jamais migrée en silence ----------
def test_une_installation_a_l_ancienne_disposition_est_signalee_et_rien_n_est_migre(bac):
    bac.preparer_decisions()
    ancien = bac.home / "core"
    (ancien / "opsys").mkdir(parents=True)
    (ancien / ".env").write_text("OPSYS_MCP_JETON=ancien-jeton-fictif-0123456789abcdef\n", encoding="utf-8")
    avant = bac.empreinte_du_dossier(ancien)

    resultat = bac.installer()

    assert resultat.returncode == 1
    assert "ancienne disposition détectée" in resultat.stderr and str(ancien) in resultat.stderr
    assert str(bac.etat_core) in resultat.stderr and "Rien n'est migré en silence" in resultat.stderr
    assert f"{ancien}.ancien" in resultat.stderr and "mv" in resultat.stderr
    assert "ancien-jeton-fictif" not in _sortie(resultat)  # jamais un secret dans un message
    assert bac.empreinte_du_dossier(ancien) == avant and not bac.etat_core.exists()
    assert not [a for a in bac.appels() if "gateway" in a]  # aucun service, aucun redémarrage
    assert not (bac.bin / "openclaw").exists() and not (bac.logiciel / "installation.env").exists()

    ancien.rename(bac.home / "core.ancien")  # la marche à suivre (2) : repartir à neuf
    apres = bac.installer()
    assert apres.returncode == 0, _sortie(apres)
    assert bac.empreinte_du_dossier(bac.home / "core.ancien") == avant and (bac.etat_core / ".env").is_file()


# -- l'état d'avant le lot 3 (~/.openclaw-opsys) : refusé tant que Doctor ne l'a pas déplacé ------------------------
def _etat_d_une_installation_d_avant_le_lot_3(bac: Bac) -> Path:
    """Ce qu'une installation faite depuis T0.11-b laisse : l'état dans ~/.openclaw-opsys (configuration
    `openclaw.json`), un service qui nomme ce dossier, et un enregistrement qui le note. On installe, puis on défait
    ce que le lot 3 a changé."""
    bac.preparer_decisions()
    assert bac.installer().returncode == 0
    shutil.move(str(bac.etat_core), str(bac.ancien_profil))
    (bac.ancien_profil / "opsys.json").rename(bac.ancien_profil / "openclaw.json")
    (bac.hote / ".opsys").rmdir()  # le dossier d'instance n'existait pas encore (OPSYS_HOME est ailleurs, ici)
    for fichier in (_unite_du_core(bac), bac.logiciel / "installation.env"):
        fichier.write_text(fichier.read_text(encoding="utf-8").replace(str(bac.etat_core), str(bac.ancien_profil)),
                           encoding="utf-8")
    return bac.ancien_profil


def _deplacer_comme_doctor(bac: Bac) -> None:
    """Ce que fait Doctor (`core/src/infra/state-migrations.opsys-instance.ts`) : un renommage, puis un lien."""
    bac.etat_core.parent.mkdir(parents=True, exist_ok=True)
    bac.ancien_profil.rename(bac.etat_core)
    bac.ancien_profil.symlink_to(bac.etat_core, target_is_directory=True)


def test_le_faux_core_applique_la_resolution_du_lot_3_pour_le_profil_opsys(bac):
    """Garde de l'outil de test : la règle qu'il prête au core est celle de `core/src/config/opsys-instance.ts`
    (que vitest et le job `installateur` prouvent pour de vrai)."""
    def config_du_core(profil: str = "opsys") -> str:
        sortie = subprocess.run([str(bac.faux / "node"), "core/openclaw.mjs", "--profile", profil, "config", "file"],
                                env=bac.env(), capture_output=True, text=True, check=True).stdout
        return sortie.strip()

    assert config_du_core() == str(bac.etat_core / "opsys.json")  # poste neuf
    assert config_du_core("autre") == str(bac.hote / ".openclaw-autre" / "openclaw.json")  # autres profils : inchangés

    (bac.ancien_profil).mkdir()
    (bac.ancien_profil / "openclaw.json").write_text("{}\n", encoding="utf-8")
    assert config_du_core() == str(bac.ancien_profil / "openclaw.json")  # seul l'ancien porte un état : lu en place

    bac.etat_core.mkdir(parents=True)
    (bac.etat_core / "openclaw.json").write_text("{}\n", encoding="utf-8")
    assert config_du_core() == str(bac.etat_core / "openclaw.json")  # le canonique gagne dès qu'il porte un état
    (bac.etat_core / "opsys.json").write_text("{}\n", encoding="utf-8")
    assert config_du_core() == str(bac.etat_core / "opsys.json")  # et opsys.json l'emporte sur openclaw.json

    shutil.rmtree(bac.ancien_profil)
    bac.ancien_profil.symlink_to(bac.etat_core, target_is_directory=True)  # le lien de Doctor
    (bac.etat_core / ".env").write_text("OPSYS_MCP_JETON=fictif-0123456789abcdef\n", encoding="utf-8")
    via_le_lien = subprocess.run(  # un service qui nomme encore l'ancien chemin reste géré : mêmes chemins réels
        [str(bac.faux / "node"), "core/openclaw.mjs", "gateway", "install"],
        env={**bac.env(), "OPENCLAW_PROFILE": "opsys", "OPENCLAW_STATE_DIR": str(bac.ancien_profil),
             "OPENCLAW_CONFIG_PATH": str(bac.ancien_profil / "opsys.json")},
        capture_output=True, text=True, check=False)
    assert via_le_lien.returncode == 0, via_le_lien.stderr


def test_un_etat_reste_dans_l_ancien_dossier_du_profil_arrete_l_installation_avec_la_marche_a_suivre(bac):
    ancien = _etat_d_une_installation_d_avant_le_lot_3(bac)
    secrets = bac.secrets(ancien)
    avant = bac.empreinte_du_dossier(ancien)
    appels_avant = len(bac.appels())

    resultat = bac.installer()

    assert resultat.returncode == 1
    assert "ancien emplacement détecté" in resultat.stderr and str(ancien) in resultat.stderr
    assert str(bac.etat_core) in resultat.stderr and "Rien n'a été modifié" in resultat.stderr
    assert "opsys gateway stop" in resultat.stderr and "opsys doctor --non-interactive" in resultat.stderr
    assert bac.empreinte_du_dossier(ancien) == avant and not bac.etat_core.exists()  # rien n'a bougé, rien n'est copié
    assert not ancien.is_symlink()
    assert not [a for a in bac.appels()[appels_avant:] if " gateway " in a or "config validate" in a]
    assert not any(secret in _sortie(resultat) for secret in secrets)  # jamais un secret dans un message


def test_apres_le_deplacement_par_doctor_la_relance_garde_les_secrets_et_repointe_le_service(bac):
    ancien = _etat_d_une_installation_d_avant_le_lot_3(bac)
    secrets = bac.secrets(ancien)
    assert bac.installer().returncode == 1  # le refus, puis la marche à suivre
    assert f"OPENCLAW_STATE_DIR={ancien}" in _unite_du_core(bac).read_text(encoding="utf-8")

    _deplacer_comme_doctor(bac)
    reprise = bac.installer()

    assert reprise.returncode == 0, _sortie(reprise)
    assert bac.secrets() == secrets  # les secrets sont ceux d'avant : rien n'a été régénéré
    assert (bac.etat_core / "openclaw.json").is_file() and not (bac.etat_core / "opsys.json").exists()
    assert ancien.is_symlink()  # le lien de Doctor n'est pas touché
    unite = _unite_du_core(bac).read_text(encoding="utf-8")
    assert f"OPENCLAW_STATE_DIR={bac.etat_core}" in unite and str(ancien) not in unite  # le service suit le nouvel état
    assert bac.etats_du_core()[-1]["config"] == str(bac.etat_core / "openclaw.json")  # la configuration d'avant, lue
    enregistrement = (bac.logiciel / "installation.env").read_text(encoding="utf-8").splitlines()
    assert f"DOSSIER_CORE={bac.etat_core}" in enregistrement
    avant = bac.empreinte_du_dossier(bac.etat_core)
    assert bac.installer().returncode == 0 and bac.empreinte_du_dossier(bac.etat_core) == avant  # relançable


def test_deux_etats_l_ancien_et_le_nouveau_arretent_l_installation_sans_rien_fusionner(bac):
    bac.preparer_decisions()
    assert bac.installer().returncode == 0
    (bac.ancien_profil / "opsys").mkdir(parents=True)
    (bac.ancien_profil / ".env").write_text("OPSYS_MCP_JETON=jeton-de-l-ancien-etat-fictif-0123456789\n",
                                            encoding="utf-8")
    avant_ancien, avant_neuf = bac.empreinte_du_dossier(bac.ancien_profil), bac.empreinte_du_dossier(bac.etat_core)

    resultat = bac.installer()

    assert resultat.returncode == 1 and "ancien emplacement en conflit" in resultat.stderr
    assert f"{bac.ancien_profil}.old" in resultat.stderr and f"{bac.etat_core}.old" in resultat.stderr
    assert "décision humaine" in resultat.stderr and "jeton-de-l-ancien-etat-fictif" not in _sortie(resultat)
    assert bac.empreinte_du_dossier(bac.ancien_profil) == avant_ancien
    assert bac.empreinte_du_dossier(bac.etat_core) == avant_neuf
    assert bac.appels().count(f"openclaw {PROFIL} gateway install --force --port 18789") == 1  # celui de la 1re fois


# -- installation à distance : clone d'un dépôt git, y compris `bash < script` (comme `curl | bash`) ---------
def _telecharger(bac: Bac) -> Path:
    """Le script tel qu'un utilisateur le télécharge : ailleurs que dans un dépôt."""
    dossier = bac.racine / "telecharge"
    dossier.mkdir()
    shutil.copy(INSTALL, dossier / "install.sh")
    shutil.copy(UNINSTALL, dossier / "uninstall.sh")
    return dossier


def _a_distance(bac: Bac, **env: str) -> dict[str, str]:
    return {"OPSYS_REPO_URL": f"file://{bac.depot}", **env}


def test_installation_a_distance_par_curl_pipe_bash_puis_mise_a_jour_par_relance(bac):
    bac.preparer_decisions()
    script = INSTALL.read_text(encoding="utf-8")

    premiere = bac.lancer(INSTALL, "--ref", "v0", entree=script, **_a_distance(bac))

    assert premiere.returncode == 0, _sortie(premiere)
    clone = bac.logiciel / "source"
    assert (clone / ".git").is_dir() and bac.git("rev-parse", "v0") == subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    enregistrement = (bac.logiciel / "installation.env").read_text(encoding="utf-8").splitlines()
    assert f"SOURCE={clone}" in enregistrement and "SOURCE_GEREE=1" in enregistrement
    sync = (f"uv sync --locked --project {clone} --python {bac.logiciel}/venv/bin/python "
            "--group build --no-dev --extra tournees --extra soumission --no-build-isolation")
    assert sync + " --no-install-project" in bac.appels()
    assert sync in bac.appels()

    nouveau = bac.commit("deuxième")
    seconde = bac.lancer(INSTALL, entree=script, **_a_distance(bac))  # main : la mise à jour
    assert seconde.returncode == 0, _sortie(seconde)
    assert subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip() == nouveau


def test_un_clone_gere_avec_des_modifications_locales_n_est_pas_mis_a_jour(bac):
    bac.preparer_decisions()
    dossier = _telecharger(bac)
    assert bac.lancer(dossier / "install.sh", **_a_distance(bac)).returncode == 0
    (bac.logiciel / "source" / "core" / "CHANGEMENT").write_text("modif locale\n", encoding="utf-8")
    bac.commit("troisième")

    resultat = bac.lancer(dossier / "install.sh", **_a_distance(bac))

    assert resultat.returncode == 1 and "modifications locales" in resultat.stderr
    assert (bac.logiciel / "source" / "core" / "CHANGEMENT").read_text(encoding="utf-8") == "modif locale\n"


def test_une_reference_introuvable_est_refusee_avec_le_depot_nomme(bac):
    dossier = _telecharger(bac)

    resultat = bac.lancer(dossier / "install.sh", "--ref", "n-existe-pas", **_a_distance(bac))

    assert resultat.returncode == 1 and "'n-existe-pas' est introuvable" in resultat.stderr


def test_un_depot_voisin_est_utilise_tel_quel_sans_clone(bac):
    bac.preparer_decisions()
    (bac.depot / "install").mkdir()
    shutil.copy(INSTALL, bac.depot / "install" / "install.sh")

    resultat = bac.lancer(bac.depot / "install" / "install.sh")  # ni OPSYS_SOURCE ni OPSYS_REPO_URL

    assert resultat.returncode == 0, _sortie(resultat)
    assert f"dépôt détecté : {bac.depot}" in resultat.stdout
    assert not (bac.logiciel / "source").exists()
    assert "SOURCE_GEREE=0" in (bac.logiciel / "installation.env").read_text(encoding="utf-8").splitlines()


# -- la désinstallation : le logiciel part, les données restent ----------------------------------------------
def _installer_a_distance(bac: Bac) -> Path:
    bac.preparer_decisions()
    dossier = _telecharger(bac)
    resultat = bac.lancer(dossier / "install.sh", **_a_distance(bac))
    assert resultat.returncode == 0, _sortie(resultat)
    with_data = bac.home / "opsys.db"
    assert with_data.is_file()
    return dossier


def test_la_desinstallation_retire_le_logiciel_et_ne_touche_jamais_aux_donnees(bac):
    dossier = _installer_a_distance(bac)
    donnees_avant = bac.empreinte_du_dossier(bac.home)
    etat_avant = bac.empreinte_du_dossier(bac.etat_core)
    secrets = bac.secrets()
    assert _unite_du_core(bac).is_file()

    # même avec un environnement qui sortirait l'état du dossier canonique : le service du profil est retiré
    resultat = bac.lancer(dossier / "uninstall.sh", OPENCLAW_STATE_DIR=str(bac.racine / "ailleurs"),
                          OPENCLAW_HOME=str(bac.racine / "home-du-core"))

    assert resultat.returncode == 0, _sortie(resultat)
    assert f"openclaw {PROFIL} gateway uninstall" in bac.appels()
    assert not _unite_du_core(bac).exists()  # le service du profil est parti
    assert bac.empreinte_du_dossier(bac.etat_core) == etat_avant  # l'état du core (secrets, Gateway) : jamais touché
    for commande in ("opsys", "openclaw", "opsys-metier"):
        assert not (bac.bin / commande).exists(), commande
    assert not bac.logiciel.exists()  # venv, clone géré, journal, enregistrement : tout est parti, dossier compris
    donnees_apres = bac.empreinte_du_dossier(bac.home)
    assert {nom: h for nom, h in donnees_apres.items() if not nom.startswith("opsys.db")} == \
           {nom: h for nom, h in donnees_avant.items() if not nom.startswith("opsys.db")}
    assert (bac.home / "opsys.db").is_file() and (bac.etat_core / ".env").is_file()
    assert bac.secrets() == secrets  # les secrets sont ceux d'avant
    assert "Données conservées" in resultat.stdout and str(bac.home) in resultat.stdout
    assert "État du core conservé" in resultat.stdout and str(bac.etat_core) in resultat.stdout

    encore = bac.lancer(dossier / "uninstall.sh")  # relançable
    assert encore.returncode == 0, _sortie(encore)


def test_la_desinstallation_avec_export_ecrit_l_archive_et_son_empreinte_d_abord(bac):
    dossier = _installer_a_distance(bac)
    archive = bac.racine / "sauvegarde" / "avant-desinstallation.tar.gz"

    resultat = bac.lancer(dossier / "uninstall.sh", "--exporter-avant", str(archive))

    assert resultat.returncode == 0, _sortie(resultat)
    assert archive.is_file() and archive.with_name(archive.name + ".sha256").is_file()
    somme = archive.with_name(archive.name + ".sha256").read_text(encoding="utf-8").split()[0]
    assert somme == hashlib.sha256(archive.read_bytes()).hexdigest()
    with tarfile.open(archive, "r:gz") as tar:
        contenus = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}  # type: ignore[union-attr]
    assert sorted(contenus) == ["opsys-export/manifeste.json", "opsys-export/opsys.db", "opsys-export/paliers.yaml"]
    assert not [s for s in bac.secrets() for c in contenus.values() if s.encode() in c]  # aucun secret de .env
    assert not bac.logiciel.exists() and (bac.home / "opsys.db").is_file()


def test_un_export_en_echec_n_est_suivi_d_aucun_retrait(bac):
    dossier = _installer_a_distance(bac)
    archive = bac.racine / "existe-deja.tar.gz"
    archive.write_bytes(b"deja la")  # un export n'écrase jamais : il échoue

    resultat = bac.lancer(dossier / "uninstall.sh", "--exporter-avant", str(archive))

    assert resultat.returncode == 1 and "RIEN n'a été retiré" in resultat.stderr
    assert (bac.logiciel / "venv").is_dir() and (bac.bin / "openclaw").exists()
    assert not [a for a in bac.appels() if "gateway uninstall" in a]
    assert archive.read_bytes() == b"deja la"


def test_un_service_qui_ne_se_retire_pas_arrete_la_desinstallation_avant_le_reste(bac):
    dossier = _installer_a_distance(bac)

    resultat = bac.lancer(dossier / "uninstall.sh", FAUX_ECHEC=f"openclaw {PROFIL} gateway uninstall")

    assert resultat.returncode == 1 and "Rien d'autre n'a été retiré" in resultat.stderr
    assert (bac.logiciel / "venv").is_dir() and (bac.bin / "opsys").exists()


def test_la_simulation_ne_retire_rien(bac):
    dossier = _installer_a_distance(bac)
    avant = bac.empreinte_du_dossier(bac.logiciel / "source" / "core")

    resultat = bac.lancer(dossier / "uninstall.sh", "--simuler")

    assert resultat.returncode == 0, _sortie(resultat)
    assert "[simulation] suppression de" in resultat.stdout
    assert (bac.logiciel / "venv").is_dir() and (bac.bin / "openclaw").exists()
    assert bac.empreinte_du_dossier(bac.logiciel / "source" / "core") == avant
    assert not [a for a in bac.appels() if "gateway uninstall" in a]


def test_un_depot_a_soi_et_les_commandes_etrangeres_ne_sont_jamais_retires(bac):
    bac.preparer_decisions()
    assert bac.installer().returncode == 0  # dépôt à soi (OPSYS_SOURCE) : SOURCE_GEREE=0
    (bac.bin / "opsys").write_text("#!/bin/sh\necho autre outil\n", encoding="utf-8")  # remplacé par autre chose

    resultat = bac.lancer(UNINSTALL)

    assert resultat.returncode == 0, _sortie(resultat)
    assert bac.depot.is_dir() and (bac.depot / "core" / "openclaw.mjs").is_file()
    assert (bac.bin / "opsys").read_text(encoding="utf-8") == "#!/bin/sh\necho autre outil\n"
    assert "n'a pas été installé par OPSYS : laissé en place" in resultat.stderr
    assert not (bac.bin / "openclaw").exists() and not (bac.bin / "opsys-metier").exists()


def test_la_desinstallation_retire_aussi_l_ancienne_enveloppe_du_moteur_et_laisse_un_opsys_metier_etranger(bac):
    bac.preparer_decisions()
    assert bac.installer("--sans-service").returncode == 0
    (bac.bin / "opsys").write_text(_ancienne_enveloppe_du_moteur(), encoding="utf-8")  # installation d'avant le lot 2
    (bac.bin / "opsys-metier").write_text("#!/bin/sh\necho moteur d'un autre\n", encoding="utf-8")

    resultat = bac.lancer(UNINSTALL)

    assert resultat.returncode == 0, _sortie(resultat)
    assert not (bac.bin / "opsys").exists() and not (bac.bin / "openclaw").exists()  # la marque les reconnaît
    assert (bac.bin / "opsys-metier").read_text(encoding="utf-8") == "#!/bin/sh\necho moteur d'un autre\n"
    assert f"{bac.bin}/opsys-metier n'a pas été installé par OPSYS : laissé en place" in resultat.stderr


def test_la_desinstallation_refuse_de_supprimer_un_dossier_qui_contient_les_donnees(bac):
    bac.preparer_decisions()
    assert bac.installer("--sans-service").returncode == 0
    logiciel_piege = bac.racine / "gros-dossier"
    logiciel_piege.mkdir()
    shutil.move(str(bac.logiciel / "venv"), str(logiciel_piege / "venv"))
    shutil.move(str(bac.logiciel / "installation.env"), str(logiciel_piege / "installation.env"))
    instance_dedans = logiciel_piege / "venv" / "instance"
    shutil.move(str(bac.home), str(instance_dedans))

    resultat = bac.lancer(UNINSTALL, OPSYS_LOGICIEL=str(logiciel_piege), OPSYS_HOME=str(instance_dedans))

    assert resultat.returncode == 1 and "contient les données de l'instance" in resultat.stderr
    assert (instance_dedans / "opsys.db").is_file()
    assert (bac.bin / "opsys").exists()  # le refus vient AVANT tout retrait


@pytest.mark.parametrize("alias", ["dotdot", "symlink"])
def test_la_garde_resout_les_alias_physiques_vers_les_donnees(bac, alias):
    bac.preparer_decisions()
    assert bac.installer("--sans-service").returncode == 0
    logiciel = bac.racine / "software"
    (logiciel / "venv").mkdir(parents=True)
    instance_dedans = logiciel / "venv" / "instance"
    instance_dedans.mkdir()
    (instance_dedans / "opsys.db").write_text("base-fictive\n", encoding="utf-8")

    if alias == "dotdot":
        (bac.racine / "sous-dossier").mkdir()
        chemin = bac.racine / "alias-parent"
        chemin.symlink_to(bac.racine / "sous-dossier", target_is_directory=True)
        logiciel_alias = chemin / ".." / "software"
    else:
        logiciel_alias = bac.racine / "lien-logiciel"
        logiciel_alias.symlink_to(logiciel, target_is_directory=True)

    resultat = bac.lancer(UNINSTALL, "--simuler", OPSYS_LOGICIEL=str(logiciel_alias),
                          OPSYS_HOME=str(instance_dedans))

    assert resultat.returncode == 1 and "données de l'instance" in resultat.stderr
    assert (instance_dedans / "opsys.db").is_file()
    assert not [appel for appel in bac.appels() if appel.startswith("node ") and "gateway uninstall" in appel]


def test_la_garde_refuse_un_lien_de_suppression_vers_un_descendant_des_donnees(bac):
    bac.preparer_decisions()
    assert bac.installer("--sans-service").returncode == 0
    instance = bac.racine / "instance-fictive"
    dossier_a_conserver = instance / "archives"
    dossier_a_conserver.mkdir(parents=True)
    (dossier_a_conserver / "preuve.txt").write_text("conserver\n", encoding="utf-8")
    logiciel = bac.racine / "logiciel-fictif"
    (logiciel / "venv").mkdir(parents=True)
    (logiciel / "journaux").symlink_to(dossier_a_conserver, target_is_directory=True)

    resultat = bac.lancer(UNINSTALL, "--simuler", OPSYS_LOGICIEL=str(logiciel), OPSYS_HOME=str(instance))

    assert resultat.returncode == 1 and "sous-dossier des données" in resultat.stderr
    assert (dossier_a_conserver / "preuve.txt").read_text(encoding="utf-8") == "conserver\n"


def test_la_garde_refuse_une_cible_physique_egale_aux_donnees(bac):
    bac.preparer_decisions()
    assert bac.installer("--sans-service").returncode == 0
    logiciel = bac.racine / "logiciel-egal"
    (logiciel / "venv").mkdir(parents=True)
    (logiciel / "venv" / "opsys.db").write_text("base-fictive\n", encoding="utf-8")

    resultat = bac.lancer(UNINSTALL, "--simuler", OPSYS_LOGICIEL=str(logiciel),
                          OPSYS_HOME=str(logiciel / "venv"))

    assert resultat.returncode == 1 and "contient les données de l'instance" in resultat.stderr
    assert (logiciel / "venv" / "opsys.db").is_file()


def test_la_desinstallation_refuse_une_archive_placee_dans_un_dossier_a_supprimer(bac):
    bac.preparer_decisions()
    assert bac.installer("--sans-service").returncode == 0
    archive = bac.logiciel / "venv" / "sauvegarde.tar.gz"

    resultat = bac.lancer(UNINSTALL, "--simuler", "--exporter-avant", str(archive))

    assert resultat.returncode == 1 and "contient la sauvegarde demandée" in resultat.stderr
    assert "[simulation] export" not in resultat.stdout
    assert (bac.logiciel / "venv").is_dir()


def test_la_desinstallation_refuse_de_supprimer_un_dossier_qui_contient_l_etat_du_core(bac):
    bac.preparer_decisions()
    assert bac.installer("--sans-service").returncode == 0
    dedans = bac.logiciel / "venv" / "etat-du-core"  # un état du core rangé DANS un dossier que le script supprime
    shutil.move(str(bac.etat_core), str(dedans))
    enregistrement = bac.logiciel / "installation.env"
    enregistrement.write_text(enregistrement.read_text(encoding="utf-8").replace(
        f"DOSSIER_CORE={bac.etat_core}", f"DOSSIER_CORE={dedans}"), encoding="utf-8")

    resultat = bac.lancer(UNINSTALL)

    assert resultat.returncode == 1 and "contient l'état du core" in resultat.stderr
    assert (dedans / ".env").is_file() and (bac.bin / "opsys").exists()  # le refus vient AVANT tout retrait


def test_la_desinstallation_protege_l_etat_du_core_la_ou_il_est_meme_si_l_enregistrement_nomme_l_ancien_chemin(bac):
    """Une installation d'avant le lot 3 a noté `~/.openclaw-opsys` ; l'état est maintenant dans `~/.opsys/core`."""
    bac.preparer_decisions()
    assert bac.installer("--sans-service").returncode == 0
    enregistrement = bac.logiciel / "installation.env"
    enregistrement.write_text(enregistrement.read_text(encoding="utf-8").replace(
        f"DOSSIER_CORE={bac.etat_core}", f"DOSSIER_CORE={bac.ancien_profil}"), encoding="utf-8")
    poste = bac.logiciel / "venv" / "poste"  # un dossier personnel rangé DANS un dossier que le script supprime
    etat = poste / ".opsys" / "core"
    etat.mkdir(parents=True)
    (etat / ".env").write_text("OPSYS_MCP_JETON=jeton-fictif-0123456789abcdef\n", encoding="utf-8")

    resultat = bac.lancer(UNINSTALL, HOME=str(poste))

    assert resultat.returncode == 1 and "contient l'état du core" in resultat.stderr and str(etat) in resultat.stderr
    assert (etat / ".env").is_file() and (bac.bin / "opsys").exists()  # le refus vient AVANT tout retrait


def test_la_desinstallation_laisse_l_etat_et_le_lien_de_doctor_intacts(bac):
    ancien = _etat_d_une_installation_d_avant_le_lot_3(bac)
    _deplacer_comme_doctor(bac)
    assert bac.installer().returncode == 0
    etat_avant = bac.empreinte_du_dossier(bac.etat_core)

    resultat = bac.lancer(UNINSTALL)

    assert resultat.returncode == 0, _sortie(resultat)
    assert bac.empreinte_du_dossier(bac.etat_core) == etat_avant
    assert ancien.is_symlink() and ancien.resolve() == bac.etat_core.resolve()
    assert not _unite_du_core(bac).exists() and not bac.logiciel.exists()  # le service et le logiciel sont partis
    assert "État du core conservé" in resultat.stdout and str(bac.etat_core) in resultat.stdout


# -- les constantes que l'installateur recopie du fork -------------------------------------------------------
def test_les_versions_que_l_installateur_annonce_sont_celles_du_fork():
    plancher = re.findall(r"major: (\d+), minor: (\d+), patch: (\d+)",
                          (RACINE / "core/node-version.mjs").read_text(encoding="utf-8").split("const HIGHEST")[0])
    assert plancher == [("24", "16", "0"), ("26", "1", "0")]
    for script in (INSTALL, RACINE / "install" / "install.ps1"):
        texte = script.read_text(encoding="utf-8")
        assert "24.16" in texte and "26.1" in texte, script.name


def test_les_installateurs_native_n_exigent_litellm_que_sur_choix_explicite():
    bash = INSTALL.read_text(encoding="utf-8")
    powershell = (RACINE / "install" / "install.ps1").read_text(encoding="utf-8")
    for script in (bash, powershell):
        assert "OPSYS_MODE_FOURNISSEUR" in script
        assert "OPSYS_PASSERELLE_URL seul n" in script
        assert "natifs OpenClaw" in script
        assert "aucun service LiteLLM requis" in script
    assert 'local mode="${OPSYS_MODE_FOURNISSEUR:-natif}"' in bash
    assert "function Test-ModeFournisseur" in powershell


def test_le_profil_les_variables_ecartees_et_les_noms_de_service_des_scripts_sont_ceux_du_moteur_et_du_fork():
    constantes = (RACINE / "core/src/daemon/constants.ts").read_text(encoding="utf-8")
    for script in (INSTALL, UNINSTALL):
        texte = script.read_text(encoding="utf-8")
        assert f'PROFIL_CORE="{instance.PROFIL_CORE}"' in texte, script.name
        ecartees = re.search(r"^VARIABLES_ECARTEES=\((.*?)\)$", texte, flags=re.MULTILINE | re.DOTALL)
        assert ecartees and ecartees.group(1).split() == list(instance.VARIABLES_ECARTEES), script.name
        assert "OPENCLAW_STATE_DIR=" not in re.sub(r"#.*", "", texte), f"{script.name} ne doit rien poser à la main"
    # noms de service que les messages des scripts donnent, dérivés comme le fait le fork
    assert "`openclaw-gateway${suffix}`" in constantes and "`ai.openclaw.${normalized}`" in constantes
    assert "openclaw-gateway-$PROFIL_CORE" in INSTALL.read_text(encoding="utf-8")  # Linux : journalctl du service
    assert "openclaw-gateway-$PROFIL_CORE" in UNINSTALL.read_text(encoding="utf-8")  # Linux : retrait à la main
    assert "ai.openclaw.$PROFIL_CORE" in UNINSTALL.read_text(encoding="utf-8")  # macOS : retrait à la main


def test_l_indice_d_ou_regarder_quand_le_gateway_ne_repond_pas_est_celui_du_systeme():
    """Linux : journalctl ; macOS : le journal du LaunchAgent et `launchctl print` (chemins lus dans le fork)."""
    source = INSTALL.read_text(encoding="utf-8")
    fonction = re.search(r"^indice_journaux\(\) \{\n(.*?)\n\}$", source, flags=re.MULTILINE | re.DOTALL)
    assert fonction is not None

    def indice(systeme: str) -> str:
        programme = f'uname() {{ echo {systeme}; }}; PROFIL_CORE=opsys; {fonction.group(0)}\nindice_journaux'
        return subprocess.run(["bash", "-c", programme], capture_output=True, text=True, check=True).stdout

    assert "journalctl --user -u openclaw-gateway-opsys" in indice("Linux")
    macos = indice("Darwin")
    assert "~/Library/Logs/openclaw/gateway-opsys.log" in macos and "launchctl print gui/" in macos
    assert "/ai.openclaw.opsys" in macos and "journalctl" not in macos
    # ces chemins sont ceux du fork : journal des LaunchAgents et étiquette du profil
    restart_logs = (RACINE / "core/src/daemon/restart-logs.ts").read_text(encoding="utf-8")
    assert 'path.posix.join(home, "Library", "Logs", "openclaw")' in restart_logs
    assert "`gateway${resolveGatewayProfileSuffix(env.OPENCLAW_PROFILE)}`" in restart_logs
    assert indice("FreeBSD").strip() == "opsys gateway status --deep ; opsys logs"


def test_l_installateur_lit_la_version_de_pnpm_dans_le_package_json_reel_du_core():
    source = INSTALL.read_text(encoding="utf-8")
    fonction = re.search(r"^version_pnpm_du_core\(\) \{\n(.*?)\n\}$", source, flags=re.MULTILINE | re.DOTALL)
    assert fonction is not None
    reel = json.loads((RACINE / "core/package.json").read_text(encoding="utf-8"))["packageManager"]

    lu = subprocess.run(["bash", "-c", fonction.group(1)], env={"SOURCE": str(RACINE), "PATH": "/usr/bin:/bin"},
                        capture_output=True, text=True, check=True).stdout.strip()

    assert reel.startswith(f"pnpm@{lu}") and re.fullmatch(r"\d+\.\d+\.\d+", lu)


def test_les_scripts_sont_executables_et_sans_faute_de_syntaxe():
    bout_en_bout = RACINE / "tests" / "installateur" / "bout_en_bout.sh"  # joué par la CI avec le vrai core
    diagnostic = RACINE / "tests" / "installateur" / "diagnostic.sh"  # joué par la CI après un échec
    for script in (INSTALL, UNINSTALL, bout_en_bout, diagnostic):
        assert os.access(script, os.X_OK), f"{script.name} doit être exécutable"
        assert subprocess.run(["bash", "-n", str(script)], capture_output=True, check=False).returncode == 0
    shellcheck = shutil.which("shellcheck")
    if shellcheck:
        resultat = subprocess.run([shellcheck, "-s", "bash", str(INSTALL), str(UNINSTALL), str(bout_en_bout),
                                   str(diagnostic)],
                                  capture_output=True, text=True, check=False,
                                  env={**os.environ, "LC_ALL": "C.UTF-8"})
        assert resultat.returncode == 0, resultat.stdout


# Les extras qui ne servent qu'à Docker Compose (`postgres`, `console`) ou aux contributeurs (`dev`) ; tout autre extra
# de pyproject.toml est une dépendance d'exécution du moteur que les deux installateurs doivent poser (T0.11-c).
# Ingestion et embeddings locaux sont des capacités optionnelles, activées séparément.
EXTRAS_HORS_INSTALLATEUR = {"postgres", "console", "dev", "ingestion", "ingestion-pdf", "embeddings-local"}


def test_les_installateurs_posent_tous_les_extras_d_execution_du_moteur() -> None:
    import tomllib

    projet = tomllib.loads((RACINE / "pyproject.toml").read_text(encoding="utf-8"))
    attendus = set(projet["project"]["optional-dependencies"]) - EXTRAS_HORS_INSTALLATEUR
    assert attendus >= {"tournees", "soumission"}
    sh = re.search(r'^EXTRAS_MOTEUR="([a-z,_-]+)"$', INSTALL.read_text(encoding="utf-8"), re.MULTILINE)
    ps1 = re.search(r"^\$script:ExtrasMoteur = '([a-z,_-]+)'$",
                    (RACINE / "install" / "install.ps1").read_text(encoding="utf-8"), re.MULTILINE)
    assert sh is not None and ps1 is not None
    assert set(sh.group(1).split(",")) == attendus
    assert set(ps1.group(1).split(",")) == attendus
