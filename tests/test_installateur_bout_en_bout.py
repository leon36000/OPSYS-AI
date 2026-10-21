"""La preuve de bout en bout (`tests/installateur/bout_en_bout.sh`) jouée contre un FAUX core et faux Docker.

Le script de preuve n'a jamais tourné sur macOS. Le bac à sable ne construit pas le core et n'a pas macOS : on
essaie donc le script LUI-MÊME, avant la CI, contre `tests/installateur/faux_core.py` (le moteur Python est le vrai) et
contre des faux de `uname`, `stat`, `shasum` et `launchctl` qui se comportent comme ceux de macOS (BSD) : `stat -c` et
`sha256sum` y échouent, comme sur un Mac.

Ce que ces tests prouvent : la logique du script (branches macOS et Linux, ordre des étapes, groupes et annotations
GitHub, résumé), et que CHAQUE contrôle du service launchd attrape la faute qu'il prétend attraper (contrôles
négatifs : un plist qui porte un secret, un service arrêté, une mauvaise étiquette...). Un contrôle qui ne sait pas
échouer ne prouve rien.

Ce qu'ils ne prouvent PAS, et que seule la CI prouve : que le vrai core se construit, installe le LaunchAgent
`ai.openclaw.opsys` et le retire ; que `launchctl`, `stat -f`, `shasum` et bash 3.2 de macOS répondent comme leurs
faux ; que launchd du poste de CI a une session graphique.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not all(shutil.which(c) for c in ("bash", "curl", "git")),
    reason="ces essais IMITENT macOS sur Linux (stat, shasum, launchctl BSD) : un vrai Mac, c'est le job de la CI")

FICTIF = True  # aucune valeur ci-dessous n'est réelle (AGENTS.md)

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "tests" / "installateur"
SCRIPT = DOSSIER / "bout_en_bout.sh"
DIAGNOSTIC = DOSSIER / "diagnostic.sh"
FAUX_CORE = DOSSIER / "faux_core.py"
ETIQUETTE = "ai.openclaw.opsys"

FAUX_NODE = '#!/usr/bin/env bash\nexec "$FAUX_PYTHON" "$FAUX_CORE" "$@"\n'
FAUX_PNPM = '''#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then echo "$FAUX_PNPM_VERSION"; exit 0; fi
exit 0
'''
FAUX_UV = '''#!/usr/bin/env bash
if [ "$1 ${2:-}" = "venv --clear" ]; then
    for dossier; do :; done  # le dernier argument (portable : bash 3.2 de macOS compris)
    mkdir -p "$dossier/bin"
    printf '#!/bin/sh\\nexec %s "$@"\\n' "$FAUX_PYTHON" >"$dossier/bin/python"
    chmod +x "$dossier/bin/python"
fi
exit 0
'''
# -- les faux de macOS (BSD), sur une machine Linux -------------------------------------------------------------------
UNAME_DARWIN = '#!/usr/bin/env bash\nif [ "${1:-}" = "-s" ]; then echo Darwin; else exec /usr/bin/uname "$@"; fi\n'
STAT_BSD = '''#!/usr/bin/env bash
if [ "${1:-}" = "-f" ] && [ "${2:-}" = "%Lp" ] && [ "$#" -eq 3 ]; then exec /usr/bin/stat -c '%a' "$3"; fi
echo "stat: illegal option -- $*" >&2
exit 1
'''
SHASUM_BSD = '''#!/usr/bin/env bash
if [ "${1:-}" = "-a" ] && [ "${2:-}" = "256" ]; then shift 2; exec /usr/bin/sha256sum "$@"; fi
echo "shasum: seul -a 256 est émulé" >&2
exit 1
'''
ABSENT = '#!/usr/bin/env bash\necho "$0: command not found" >&2\nexit 127\n'  # ce que macOS n'a pas
FAUX_DOCKER = r'''#!/usr/bin/env bash
printf 'docker %s\n' "$*" >>"$FAUX_JOURNAL"
"$FAUX_PYTHON" -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >>"$FAUX_DOCKER_ARGV"
case "$*" in
    "info --format {{.OSType}}") echo linux ;;
    "image inspect openclaw-sandbox:bookworm-slim") exit 0 ;;
    *) echo "commande Docker inattendue dans la fixture : $*" >&2; exit 2 ;;
esac
'''
LAUNCHCTL = '''#!/usr/bin/env bash
[ "${1:-}" = "print" ] || { echo "faux launchctl : $*" >&2; exit 64; }
cible="${2:-}"
case "$cible" in
    gui/*/*)
        etiquette="${cible##*/}"
        pid="$(cat "$FAUX_LAUNCHD/$etiquette.pid" 2>/dev/null || true)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            printf '%s = {\\n\\tactive count = 1\\n\\tstate = running\\n\\n\\tpid = %s\\n}\\n' "$cible" "$pid"
            exit 0
        fi
        echo "Could not find service \\"$etiquette\\" in domain for user gui: ${cible#gui/}" >&2
        exit 113
        ;;
    gui/*)
        [ -z "${FAUX_DOMAINE_ABSENT:-}" ] || { echo "Bad request. Could not find domain for $cible" >&2; exit 113; }
        echo "$cible = { type = login }"
        exit 0
        ;;
    *) exit 64 ;;
esac
'''


def _port_libre() -> int:
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        return prise.getsockname()[1]


def _version_pnpm() -> str:
    texte = (RACINE / "core" / "package.json").read_text(encoding="utf-8")
    trouve = re.search(r'"packageManager"\s*:\s*"pnpm@([^"+]*)', texte)
    assert trouve, "core/package.json ne fixe pas pnpm"
    return trouve.group(1)


class Poste:
    """Un poste fictif : faux core, faux node/pnpm/uv/Docker et, pour macOS, fausses commandes BSD."""

    def __init__(self, tmp_path: Path, *, macos: bool) -> None:
        self.macos = macos
        racine = tmp_path / ("macos" if macos else "linux")  # deux postes dans un même test : deux dossiers
        self.logs_core = racine / "logs-core-fictifs"
        self.hote = racine / "hote"
        self.travail = racine / "travail"
        self.faux = racine / "faux"
        self.resume = racine / "resume.md"
        self.hote.mkdir(parents=True)
        self.faux.mkdir()
        self.port_gateway, self.port_moteur = _port_libre(), _port_libre()
        for nom, corps in (("node", FAUX_NODE), ("pnpm", FAUX_PNPM), ("uv", FAUX_UV), ("docker", FAUX_DOCKER)):
            self.ecrire(nom, corps)
        if macos:
            for nom, corps in (("uname", UNAME_DARWIN), ("stat", STAT_BSD), ("shasum", SHASUM_BSD),
                               ("launchctl", LAUNCHCTL), ("sha256sum", ABSENT), ("journalctl", ABSENT),
                               ("systemctl", ABSENT), ("loginctl", ABSENT), ("sudo", ABSENT)):
                self.ecrire(nom, corps)

    @property
    def etat_core(self) -> Path:
        return self.hote / ".opsys" / "core"

    @property
    def ancien_profil(self) -> Path:
        return self.hote / ".openclaw-opsys"  # où le profil rangeait son état avant T0.7 lot 3

    @property
    def plist(self) -> Path:
        return self.hote / "Library" / "LaunchAgents" / f"{ETIQUETTE}.plist"

    def ecrire(self, nom: str, corps: str) -> Path:
        chemin = self.faux / nom
        chemin.write_text(corps, encoding="utf-8")
        chemin.chmod(0o755)
        return chemin

    def env(self, **supplement: str) -> dict[str, str]:
        env = {cle: valeur for cle, valeur in os.environ.items()
               if not cle.startswith(("OPSYS_", "OPENCLAW_", "FAUX_", "GITHUB_"))}
        chemins_python = [str(RACINE / "src"), *sorted(str(p) for p in RACINE.glob("departments/*/src"))]
        env.update({
            "HOME": str(self.hote), "PATH": f"{self.faux}:{os.environ['PATH']}", "LANG": "C.UTF-8",
            "PYTHONPATH": os.pathsep.join(chemins_python), "OPSYS_TRAVAIL": str(self.travail),
            "OPSYS_PORT_GATEWAY": str(self.port_gateway), "OPSYS_PORT_MOTEUR": str(self.port_moteur),
            "FAUX_PYTHON": sys.executable, "FAUX_CORE": str(FAUX_CORE), "FAUX_PNPM_VERSION": _version_pnpm(),
            "FAUX_LAUNCHD": str(self.hote / ".faux-launchd"), "FAUX_JOURNAL": str(self.travail / "appels.log"),
            "FAUX_DOCKER_ARGV": str(self.travail / "docker-argv.jsonl"),
            "OPSYS_DIAGNOSTIC_CORE_LOG_DIR": str(self.logs_core),
        })
        env.update(supplement)
        return env

    def jouer(self, *, timeout: int = 420, **supplement: str) -> subprocess.CompletedProcess[str]:
        """Joue tout le script de preuve."""
        self.travail.mkdir(exist_ok=True)
        return subprocess.run(["bash", str(SCRIPT)], env=self.env(**supplement), cwd=RACINE, capture_output=True,
                              text=True, timeout=timeout, check=False)

    def arguments_docker(self) -> list[list[str]]:
        journal = self.travail / "docker-argv.jsonl"
        if not journal.exists():
            return []
        return [json.loads(ligne) for ligne in journal.read_text(encoding="utf-8").splitlines()]

    def verifier_docker_factice(self) -> None:
        commandes = self.arguments_docker()
        assert ["info", "--format", "{{.OSType}}"] in commandes
        assert ["image", "inspect", "openclaw-sandbox:bookworm-slim"] in commandes
        autorisees = (
            ["info", "--format", "{{.OSType}}"],
            ["image", "inspect", "openclaw-sandbox:bookworm-slim"],
        )
        assert all(commande in autorisees for commande in commandes)

    def secrets(self) -> list[str]:
        env = (self.etat_core / ".env").read_text(encoding="utf-8")
        return [v for k, v in re.findall(r"^([A-Z0-9_]+)=(.*)$", env, flags=re.MULTILINE)
                if re.search(r"JETON|TOKEN|CLE", k) and len(v) >= 12]


def _sortie(resultat: subprocess.CompletedProcess[str]) -> str:
    return resultat.stdout + resultat.stderr


def _sans_masque(texte: str) -> str:
    """Le texte sans les lignes `::add-mask::` : elles portent les secrets PAR CONCEPTION (GitHub les masque ainsi)."""
    return "\n".join(ligne for ligne in texte.splitlines() if not ligne.startswith("::add-mask::"))


@pytest.fixture
def macos(tmp_path: Path):
    poste = Poste(tmp_path, macos=True)
    yield poste
    _arreter_les_services(poste)


@pytest.fixture
def linux(tmp_path: Path):
    return Poste(tmp_path, macos=False)


def _arreter_les_services(poste: Poste) -> None:
    """Ce qu'un test interrompu laisserait : le faux service détaché."""
    dossier = poste.hote / ".faux-launchd"
    for fichier in dossier.glob("*.pid") if dossier.is_dir() else ():
        with contextlib.suppress(OSError, ValueError):
            os.kill(int(fichier.read_text(encoding="utf-8")), 15)


# -- la preuve entière ------------------------------------------------------------------------------------------------
def test_macos_la_preuve_entiere_passe_avec_le_service_launchd(macos):
    resultat = macos.jouer(GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(macos.resume), OPSYS_SERVICE_REQUIS="1")

    sortie = _sortie(resultat)
    assert resultat.returncode == 0, sortie
    macos.verifier_docker_factice()
    _verifier_fournisseurs(macos, mode="natif")
    installation = (macos.travail / "installation-1.log").read_text(encoding="utf-8")
    assert "natifs OpenClaw" in installation and "aucun service LiteLLM requis" in installation
    assert "== Tout est vrai" in resultat.stdout
    for etape in ("0. Poste", "1. Installation (sans service)", "1 quinquies. Installation d'avant le lot 3",
                  "2. Gateway au premier plan", "3. Relance", f"5. Service utilisateur ({ETIQUETTE})",
                  "5 bis. Service d'avant le lot 3", "6. Désinstallation"):
        assert f"::group::{etape}" in resultat.stdout, etape  # une étape = un groupe repliable
    assert resultat.stdout.count("::group::") == resultat.stdout.count("::endgroup::")
    assert "OK  poste neuf (Darwin)" in resultat.stdout
    assert f"OK  le service {ETIQUETTE} tourne dans launchd" in resultat.stdout
    # T0.7 lot 3 : l'état d'avant (~/.openclaw-opsys) est refusé, lu en place, puis déplacé par Doctor ; le service suit
    assert "OK  état d'avant le lot 3 : refusé par le moteur avec la marche à suivre" in resultat.stdout
    assert "OK  deux états : Doctor ne déplace, ne fusionne ni ne supprime rien" in resultat.stdout
    assert "OK  service d'avant le lot 3 : sa définition nomme" in resultat.stdout
    assert "OK  service d'avant le lot 3 : Doctor a déplacé l'état" in resultat.stdout
    assert "SHA-256 vérifié (shasum)" in resultat.stdout  # shasum de macOS, pas sha256sum
    resume = macos.resume.read_text(encoding="utf-8")
    assert "### Installateur avec le vrai core (Darwin)" in resume
    assert f"Service utilisateur ({ETIQUETTE}) prouvé : **oui**" in resume
    for secret in macos.secrets():
        assert secret not in _sans_masque(sortie), "un secret est imprimé en clair"
        assert secret not in resume
        assert f"::add-mask::{secret}" in resultat.stdout  # déclaré au masque de GitHub
    # la désinstallation a rangé le plist, comme le core (dans la corbeille) ; l'état du core est resté
    assert not macos.plist.exists() and (macos.hote / ".Trash" / f"{ETIQUETTE}.plist").is_file()
    assert (macos.etat_core / ".env").is_file()
    # le lien que Doctor a laissé à l'ancien chemin est intact
    assert macos.ancien_profil.is_symlink() and macos.ancien_profil.resolve() == macos.etat_core.resolve()
    assert not (macos.hote / ".openclaw-opsys.old").exists()  # le seul reste du script est retiré par lui
    assert not (macos.hote / "Library" / "LaunchAgents" / "ai.openclaw.gateway.plist").exists()


def test_linux_la_preuve_sans_service_passe_avec_les_commandes_gnu(linux):
    resultat = linux.jouer(OPSYS_SANS_SERVICE="1", GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(linux.resume),
                          OPSYS_MODE_FOURNISSEUR="litellm", OPSYS_PASSERELLE_URL="http://127.0.0.1:9/v1")

    sortie = _sortie(resultat)
    assert resultat.returncode == 0, sortie
    linux.verifier_docker_factice()
    _verifier_fournisseurs(linux, mode="litellm")
    assert "LiteLLM de compatibilité" in (linux.travail / "installation-1.log").read_text(encoding="utf-8")
    assert "== Tout est vrai" in resultat.stdout
    assert "OK  poste neuf (Linux)" in resultat.stdout
    # T0.7 lot 3 : la migration de l'état d'avant se prouve sans service ; l'étape du service d'avant saute avec lui
    assert "::group::1 quinquies. Installation d'avant le lot 3" in resultat.stdout
    assert "OK  état d'avant le lot 3 : refusé par le moteur avec la marche à suivre" in resultat.stdout
    assert "5 bis." not in resultat.stdout
    # la preuve du conflit a mis de côté, puis retiré, le faux ancien état qu'elle avait fabriqué : plus rien là
    assert not linux.ancien_profil.exists() and not linux.ancien_profil.is_symlink()
    assert not (linux.hote / ".openclaw-opsys.old").exists()
    # T0.7 lot 2 : `opsys` est le core, `opsys metier` le moteur par le core, l'ancienne forme dit la nouvelle
    assert "::group::1 bis bis. Une seule commande" in resultat.stdout
    assert "OK  opsys est le core (OPSYS <version>, alias openclaw identique) ; opsys metier lance le moteur" \
        in resultat.stdout
    assert "SHA-256 vérifié (sha256sum)" in resultat.stdout
    assert "::warning::phase du service sautée (OPSYS_SANS_SERVICE=1)" in resultat.stdout
    resume = linux.resume.read_text(encoding="utf-8")
    assert "### Installateur avec le vrai core (Linux)" in resume
    assert "prouvé : **non**" in resume  # jamais un faux vert : la phase sautée est dite
    for secret in linux.secrets():
        assert secret not in _sans_masque(sortie)


def _verifier_fournisseurs(poste: Poste, *, mode: str) -> None:
    """Le vrai moteur a produit un catalogue distinct pour chaque choix d'installation."""
    fournisseurs = json.loads((poste.etat_core / "opsys" / "models.json").read_text(encoding="utf-8"))["providers"]
    env = (poste.etat_core / ".env").read_text(encoding="utf-8")
    if mode == "natif":
        assert "anthropic" in fournisseurs
        assert fournisseurs["anthropic"]["apiKey"] == "${ANTHROPIC_API_KEY}"
        assert not any(nom.startswith("opsys-m") for nom in fournisseurs)
        assert "OPSYS_MODE_FOURNISSEUR=" not in env and "OPSYS_PASSERELLE_URL=" not in env
    else:
        assert "anthropic" not in fournisseurs
        assert fournisseurs["opsys-m1"]["baseUrl"] == "http://127.0.0.1:9/v1"
        assert "OPSYS_MODE_FOURNISSEUR=litellm\n" in env
        assert "OPSYS_PASSERELLE_URL=http://127.0.0.1:9/v1\n" in env


# -- les contrôles du service launchd, un à un (contrôles négatifs) --------------------------------------------------
JETON = "0123456789abcdef" * 4  # fictif
CLE = "sk-opsys-m01-fictive-0123456789ab"


def _attendre(url: str, delai: float = 20.0) -> None:
    import time
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if subprocess.run(["curl", "-s", "--noproxy", "*", "-o", "/dev/null", "-f", "--max-time", "2", url],
                          check=False).returncode == 0:
            return
        time.sleep(0.2)
    raise AssertionError(f"{url} ne répond pas")


def monde_launchd(poste: Poste, **fautes: str) -> dict[str, str]:
    """Le faux core installe son LaunchAgent (avec les fautes demandées) sur un état du core qui porte des secrets.

    Un seul port : le faux Gateway répond aussi à /sante (FAUX_SANTE), ce qui tient lieu de moteur.
    """
    poste.travail.mkdir(exist_ok=True)
    poste.etat_core.mkdir(mode=0o700, parents=True)
    (poste.etat_core / ".env").write_text(
        f"OPSYS_MCP_JETON={JETON}\nOPSYS_CLE_M01={CLE}\nOPSYS_EMBEDDINGS_MODELE=bge-m3\n", encoding="utf-8")
    (poste.etat_core / ".env").chmod(0o600)
    env = poste.env(FAUX_SANTE="1", OPSYS_PORT_MOTEUR=str(poste.port_gateway), **fautes)
    subprocess.run([sys.executable, str(FAUX_CORE), str(RACINE / "core" / "openclaw.mjs"), "--profile", "opsys",
                    "gateway", "install", "--force", "--port", str(poste.port_gateway)],
                   env=env, check=True, capture_output=True, text=True, timeout=60)
    if "FAUX_SERVICE_ARRETE" not in fautes:
        _attendre(f"http://127.0.0.1:{poste.port_gateway}/startupz")
    return env


def appeler(poste: Poste, env: dict[str, str], corps: str) -> subprocess.CompletedProcess[str]:
    """Charge les FONCTIONS du script de preuve (sans jouer la preuve) puis exécute `corps`."""
    commande = f'export OPSYS_BOUT_EN_BOUT_FONCTIONS_SEULEMENT=1; source "{SCRIPT}"; {corps}'
    return subprocess.run(["bash", "-c", commande], env=env, cwd=RACINE, capture_output=True, text=True,
                          timeout=60, check=False)


def test_le_service_launchd_conforme_passe_tous_les_controles(macos):
    env = monde_launchd(macos)

    resultat = appeler(macos, env, "verifier_service_launchd")

    assert resultat.returncode == 0, _sortie(resultat)
    assert f"OK  le service {ETIQUETTE} tourne dans launchd (pid = " in resultat.stdout
    assert JETON not in _sortie(resultat)


FAUTES = {
    "un plist qui porte le jeton du moteur": (
        {"FAUX_SECRET_DANS_PLIST": "1"}, "plist launchd : un secret de .env apparaît dans"),
    "un journal du service qui porte le jeton": (
        {"FAUX_SECRET_DANS_JOURNAL": "1"}, "journal du service : un secret de .env apparaît dans"),
    "un fichier d'environnement lisible par tous qui porte le jeton": (
        {"FAUX_ENV_LISIBLE": "1"}, "et son mode est 644 (0600 attendu)"),
    "l'étiquette du core d'origine": ({"FAUX_ETIQUETTE": "ai.openclaw.gateway"}, "n'existe pas après l'installation"),
    "un service installé mais arrêté": ({"FAUX_SERVICE_ARRETE": "1"}, "launchd ne connaît pas gui/"),
    "un plist sans RunAtLoad": ({"FAUX_PLIST_SANS_RUNATLOAD": "1"}, "RunAtLoad n'est pas vrai"),
    "un service sans le profil opsys": ({"FAUX_SANS_PROFIL": "1"}, "ne portent le profil opsys"),
    "un service sans journal": ({"FAUX_SANS_JOURNAL": "1"}, "n'existe pas : le service n'a rien écrit"),
}


@pytest.mark.parametrize("faute", sorted(FAUTES))
def test_chaque_controle_du_service_launchd_attrape_sa_faute(macos, faute):
    injection, message = FAUTES[faute]
    env = monde_launchd(macos, **injection)

    resultat = appeler(macos, env, "verifier_service_launchd")

    assert resultat.returncode == 1, f"la faute « {faute} » n'a pas été attrapée : {_sortie(resultat)}"
    assert message in resultat.stderr, resultat.stderr
    assert "ÉCHEC : " in resultat.stderr
    assert JETON not in _sans_masque(_sortie(resultat)) or "FAUX_SECRET" in str(injection)  # jamais imprimé en clair


def test_un_secret_n_est_jamais_imprime_meme_quand_le_controle_le_trouve(macos):
    env = monde_launchd(macos, FAUX_SECRET_DANS_PLIST="1")

    resultat = appeler(macos, env, "verifier_service_launchd")

    assert resultat.returncode == 1
    assert JETON not in _sans_masque(_sortie(resultat))
    assert CLE not in _sans_masque(_sortie(resultat))
    assert f"::add-mask::{JETON}" in resultat.stdout  # l'échec déclare d'abord les secrets au masque de GitHub


# -- les contrôles de la migration de l'état d'avant le lot 3, un à un (contrôles négatifs) ----------------------------
FAUTES_DE_MIGRATION = {
    "un core qui ne replie pas sur l'ancien dossier tant qu'il est seul à porter un état": (
        {"FAUX_SANS_REPLI": "1"}, "l'état resté à l'ancien emplacement n'est pas signalé"),
    "un Doctor qui ne fait rien": ({"FAUX_DOCTOR_INACTIF": "1"}, "Doctor n'a pas déplacé l'état de"),
    "un Doctor qui copie au lieu de déplacer": ({"FAUX_DOCTOR_COPIE": "1"}, "Doctor n'a pas déplacé l'état de"),
    "un Doctor qui ne laisse pas de lien": ({"FAUX_DOCTOR_SANS_LIEN": "1"}, "en laissant un lien à l'ancien chemin"),
    "un Doctor qui perd un fichier": ({"FAUX_DOCTOR_PERD_UN_FICHIER": "1"}, "Doctor a perdu ./opsys/tools.json"),
    "un Doctor qui modifie un secret": (
        {"FAUX_DOCTOR_ALTERE_UN_SECRET": "1"}, "les secrets ou les fragments ont changé pendant le déplacement"),
    "un Doctor qui renomme la configuration": (  # un renommage est une perte de l'ancien nom : le nom est vérifié
        {"FAUX_DOCTOR_RENOMME_LA_CONFIG": "1"}, "Doctor a perdu ./openclaw.json"),
    "un Doctor qui fusionne deux états": (
        {"FAUX_DOCTOR_FUSIONNE": "1"}, "Doctor a touché à l'ancien état malgré le conflit"),
}


@pytest.mark.parametrize("faute", sorted(FAUTES_DE_MIGRATION))
def test_chaque_controle_de_la_migration_attrape_sa_faute(linux, faute):
    injection, message = FAUTES_DE_MIGRATION[faute]

    resultat = linux.jouer(OPSYS_SANS_SERVICE="1", **injection)

    assert resultat.returncode == 1, f"la faute « {faute} » n'a pas été attrapée : {_sortie(resultat)}"
    assert message in resultat.stderr, resultat.stderr
    assert "== Tout est vrai" not in resultat.stdout
    assert "== 1 quinquies." in resultat.stdout  # arrêté à l'étape de la migration, pas avant ni après
    assert "== 2. Gateway au premier plan" not in resultat.stdout


FAUTES_DU_SERVICE_D_AVANT = {
    "un service dont la définition nomme toujours l'ancien dossier": (
        {"FAUX_SERVICE_GARDE_L": "1"}, "le service désigne l'ancien dossier du profil"),
    "un service qui ne suit pas l'état lu à l'ancien emplacement": (
        {"FAUX_SERVICE_NOMME_LE_NOUVEAU": "1"}, "ne nomme pas"),
}


@pytest.mark.parametrize("faute", sorted(FAUTES_DU_SERVICE_D_AVANT))
def test_chaque_controle_du_service_d_avant_le_lot_3_attrape_sa_faute(macos, faute):
    injection, message = FAUTES_DU_SERVICE_D_AVANT[faute]

    resultat = macos.jouer(OPSYS_SERVICE_REQUIS="1", **injection)

    assert resultat.returncode == 1, f"la faute « {faute} » n'a pas été attrapée : {_sortie(resultat)}"
    assert message in resultat.stderr, resultat.stderr
    assert "== Tout est vrai" not in resultat.stdout


def test_un_ancien_dossier_du_profil_deja_la_arrete_la_preuve_avant_de_toucher_a_quoi_que_ce_soit(linux):
    linux.ancien_profil.mkdir(parents=True)
    (linux.ancien_profil / ".env").write_text("MARQUEUR=poste-reel-fictif\n", encoding="utf-8")

    resultat = linux.jouer(OPSYS_SANS_SERVICE="1")

    assert resultat.returncode == 1 and f"{linux.ancien_profil} existe déjà" in resultat.stderr
    assert (linux.ancien_profil / ".env").read_text(encoding="utf-8") == "MARQUEUR=poste-reel-fictif\n"
    assert not linux.etat_core.exists()


# -- les aides du script ---------------------------------------------------------------------------------------------
def _serveur_200(port: int):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Repond(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_: object) -> None:
            return

    serveur = HTTPServer(("127.0.0.1", port), Repond)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    return serveur


def test_mode_de_lit_le_mode_par_stat_bsd_sur_macos_et_gnu_sur_linux(macos, linux):
    fichier = macos.hote / "f"
    fichier.write_text("x", encoding="utf-8")
    fichier.chmod(0o640)

    sur_macos = appeler(macos, macos.env(), f'mode_de "{fichier}"')
    sur_linux = appeler(linux, linux.env(), f'mode_de "{fichier}"')

    assert sur_macos.stdout.strip() == "640", _sortie(sur_macos)  # le faux stat n'accepte que la syntaxe BSD
    assert sur_linux.stdout.strip() == "640", _sortie(sur_linux)


def test_empreinte_utilise_shasum_sur_macos_et_sha256sum_sur_linux(macos, linux):
    fichier = macos.hote / "f"
    fichier.write_text("bonjour\n", encoding="utf-8")
    attendu = subprocess.run(["sha256sum", str(fichier)], capture_output=True, text=True, check=True).stdout.split()[0]

    sur_macos = appeler(macos, macos.env(), f'empreinte "{fichier}"')
    sur_linux = appeler(linux, linux.env(), f'empreinte "{fichier}"')

    assert sur_macos.stdout.strip() == attendu and sur_linux.stdout.strip() == attendu, _sortie(sur_macos)


def test_un_systeme_inconnu_est_refuse_avant_toute_chose(tmp_path):
    poste = Poste(tmp_path, macos=False)
    poste.ecrire("uname", '#!/usr/bin/env bash\necho FreeBSD\n')

    resultat = poste.jouer()

    assert resultat.returncode == 1 and "système non pris en charge (FreeBSD)" in resultat.stderr
    assert not poste.etat_core.exists()


def test_code_http_rend_000_quand_rien_ne_repond_et_le_code_sinon(macos):
    libre = _port_libre()
    serveur = _serveur_200(_port_libre())
    try:
        rien = appeler(macos, macos.env(), f'printf "[%s]" "$(code_http http://127.0.0.1:{libre}/x)"')
        repond = appeler(macos, macos.env(), f'printf "[%s]" "$(code_http http://127.0.0.1:{serveur.server_port}/x)"')
    finally:
        serveur.shutdown()

    assert rien.stdout == "[000]" and repond.stdout == "[200]"


def test_attendre_arret_echoue_tant_que_l_adresse_repond_et_passe_quand_elle_se_tait(macos):
    serveur = _serveur_200(_port_libre())
    url = f"http://127.0.0.1:{serveur.server_port}/x"
    try:
        encore = appeler(macos, macos.env(), f'attendre_arret "{url}" 2 "le service"')
    finally:
        serveur.shutdown()
        serveur.server_close()
    fini = appeler(macos, macos.env(), f'attendre_arret "{url}" 2 "le service" && echo arrete')

    assert encore.returncode == 1 and "le service : " in encore.stderr
    assert "répond encore 2 s après l'arrêt" in encore.stderr
    assert fini.returncode == 0 and "arrete" in fini.stdout


def test_un_echec_sous_github_ferme_le_groupe_pose_l_annotation_et_le_resume(macos):
    macos.travail.mkdir(exist_ok=True)
    env = macos.env(GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(macos.resume))

    resultat = appeler(macos, env, 'etape "5. Service utilisateur"; echec "cause avec 100% de\nsauts de ligne"')

    assert resultat.returncode == 1
    lignes = resultat.stdout.splitlines()
    assert lignes.index("::group::5. Service utilisateur") < lignes.index("::endgroup::")  # fermé AVANT la cause
    assert "::error title=Installateur Darwin - étape 5::cause avec 100%25 de%0Asauts de ligne" in lignes
    assert "ÉCHEC : cause avec 100% de\nsauts de ligne" in resultat.stderr
    resume = macos.resume.read_text(encoding="utf-8")
    assert "ÉCHEC à l'étape « 5. Service utilisateur »" in resume and "sauts de ligne" in resume


def test_hors_github_aucun_marqueur_de_groupe_n_est_imprime(macos):
    macos.travail.mkdir(exist_ok=True)

    resultat = appeler(macos, macos.env(), 'etape "1. Installation"; constat "fait"')

    assert "::group::" not in resultat.stdout
    assert "== 1. Installation" in resultat.stdout and "OK  fait" in resultat.stdout


def test_un_fichier_qui_porte_un_secret_doit_etre_prive(macos):
    monde = macos.etat_core
    monde.mkdir(mode=0o700, parents=True)
    (monde / ".env").write_text(f"OPSYS_MCP_JETON={JETON}\n", encoding="utf-8")
    dossier = macos.hote / "Library" / "LaunchAgents"
    dossier.mkdir(parents=True)
    fichier = dossier / "x.env"
    fichier.write_text(f"export OPSYS_MCP_JETON={JETON}\n", encoding="utf-8")
    macos.travail.mkdir(exist_ok=True)

    fichier.chmod(0o600)
    prive = appeler(macos, macos.env(), f'exiger_secrets_prives_au_repos "{dossier}"')
    fichier.chmod(0o640)
    lisible = appeler(macos, macos.env(), f'exiger_secrets_prives_au_repos "{dossier}"')

    assert prive.returncode == 0, _sortie(prive)
    assert lisible.returncode == 1 and "son mode est 640 (0600 attendu)" in lisible.stderr


# -- le service demandé mais absent, et une désinstallation incomplète (preuve entière) ------------------------------
def test_macos_service_requis_et_domaine_launchd_absent_est_un_echec_qui_dit_quoi_faire(macos):
    resultat = macos.jouer(GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(macos.resume), FAUX_DOMAINE_ABSENT="1",
                           OPSYS_SERVICE_REQUIS="1")

    assert resultat.returncode == 1, _sortie(resultat)
    assert "OPSYS_SERVICE_REQUIS=1" in resultat.stderr and "sans_service=1" in resultat.stderr
    assert "::error title=Installateur Darwin - étape 5::" in resultat.stdout
    assert "== Tout est vrai" not in resultat.stdout
    assert "ÉCHEC à l'étape « 5. Service utilisateur" in macos.resume.read_text(encoding="utf-8")


def test_macos_service_non_requis_et_absent_est_dit_en_clair_jamais_un_faux_vert(macos):
    resultat = macos.jouer(GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(macos.resume), FAUX_DOMAINE_ABSENT="1")

    assert resultat.returncode == 0, _sortie(resultat)
    assert f"::warning::launchd (gui/{os.getuid()}) est indisponible sur ce poste" in resultat.stdout
    assert "service launchd NON prouvé" in resultat.stdout
    assert "prouvé : **non**" in macos.resume.read_text(encoding="utf-8")


def test_macos_une_desinstallation_qui_laisse_le_plist_est_un_echec(macos):
    resultat = macos.jouer(FAUX_DESINSTALLATION_INCOMPLETE="1")

    assert resultat.returncode == 1, _sortie(resultat)
    assert f"le plist {macos.plist} est encore installé après la désinstallation" in resultat.stderr


# -- diagnostic.sh ---------------------------------------------------------------------------------------------------
def _monde_du_diagnostic(poste: Poste) -> None:
    poste.etat_core.mkdir(mode=0o700, parents=True)
    (poste.etat_core / ".env").write_text(
        f"OPSYS_MCP_JETON={JETON}\nOPSYS_CLE_M01={CLE}\nRIEN=ceci\n", encoding="utf-8")
    (poste.etat_core / "openclaw.json").write_text("{}", encoding="utf-8")
    poste.travail.mkdir()
    (poste.travail / "installation-1.log").write_text(
        f"debut\nle moteur dit {JETON} et {CLE}\nfin de l'installation\n", encoding="utf-8")
    journaux = poste.hote / "Library" / "Logs" / "openclaw"
    journaux.mkdir(parents=True)
    (journaux / "gateway-opsys.log").write_text(f"ligne du service\njeton={JETON}\n", encoding="utf-8")
    poste.logs_core.mkdir()
    (poste.logs_core / "legacy-fictif.log").write_text(
        f"le core temporaire dit {JETON} et {CLE}\n", encoding="utf-8")


@pytest.mark.parametrize("systeme", ["macos", "linux"])
def test_le_diagnostic_imprime_les_journaux_sans_jamais_un_secret_ni_le_contenu_de_env(tmp_path, systeme):
    poste = Poste(tmp_path, macos=systeme == "macos")
    _monde_du_diagnostic(poste)

    resultat = subprocess.run(["bash", str(DIAGNOSTIC)], env=poste.env(GITHUB_ACTIONS="true"), cwd=RACINE,
                              capture_output=True, text=True, timeout=120, check=False)

    sortie = _sortie(resultat)
    assert resultat.returncode == 0, sortie
    assert f"::add-mask::{JETON}" in resultat.stdout and f"::add-mask::{CLE}" in resultat.stdout
    imprime = _sans_masque(sortie)
    assert JETON not in imprime and CLE not in imprime, "un secret est imprimé en clair"
    assert "le moteur dit *** et ***" in imprime  # la fin du journal de l'installateur, secrets remplacés
    if systeme == "macos":
        # Un booléen garde le rouge lisible sans imprimer les journaux globaux du poste hôte.
        legacy_fictif_lu = "le core temporaire dit *** et ***" in imprime
        assert legacy_fictif_lu
        assert str(poste.logs_core / "legacy-fictif.log") in imprime
        assert "/tmp/openclaw/" not in imprime
    assert "RIEN=ceci" not in imprime and "OPSYS_MCP_JETON" not in imprime  # jamais le contenu de .env
    assert "::group::" in resultat.stdout
    assert resultat.stdout.count("::group::") == resultat.stdout.count("::endgroup::")
    assert ".opsys/core/.env" in imprime  # le NOM du fichier et son mode, oui
    if systeme == "macos":
        assert "ligne du service" in imprime and "jeton=***" in imprime  # le journal du service, filtré


def test_le_diagnostic_ne_s_arrete_pas_sur_un_poste_vide(tmp_path):
    poste = Poste(tmp_path, macos=False)

    resultat = subprocess.run(["bash", str(DIAGNOSTIC)], env=poste.env(), cwd=RACINE, capture_output=True, text=True,
                              timeout=120, check=False)

    assert resultat.returncode == 0, _sortie(resultat)
    assert "== santé du Gateway et du moteur" in resultat.stdout
