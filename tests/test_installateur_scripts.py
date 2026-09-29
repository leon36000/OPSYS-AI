"""Scripts `install/install.sh` et `install/uninstall.sh` (PLAN T0.11), joués contre de FAUSSES commandes.

Node, pnpm, uv et curl sont remplacés par de petits scripts qui journalisent leurs appels ; le moteur Python, lui,
est le vrai (l'interpréteur « de l'environnement » est l'interpréteur des tests), donc `opsys instance initialiser`,
les secrets, la configuration du core et l'export tournent pour de vrai dans un dossier temporaire.

Ce que ces tests prouvent : l'enchaînement des étapes et leur ordre, le fail-closed (prérequis, étape en échec,
fichier étranger, décision manquante), l'idempotence (secrets et configuration inchangés), qu'aucun secret n'est
affiché ni journalisé même quand une commande le crache, l'installation à distance depuis un dépôt git (y compris
par `bash < script`, comme `curl | bash`), et que la désinstallation retire le logiciel sans jamais toucher aux
données.

Ce qu'ils ne prouvent PAS, et que seul le job `installateur` de la CI prouve : que le vrai core se construit, accepte
la configuration (`openclaw config validate`), démarre par le service et lance le moteur.
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
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None,
                                reason="scripts bash : Linux et macOS (Windows : install.ps1)")

FICTIF = True  # aucune valeur ci-dessous n'est réelle (AGENTS.md)

RACINE = Path(__file__).resolve().parents[1]
INSTALL = RACINE / "install" / "install.sh"
UNINSTALL = RACINE / "install" / "uninstall.sh"
PNPM = "12.4.0"
EMBEDDINGS = {"OPSYS_EMBEDDINGS_URL": "http://127.0.0.1:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "bge-m3"}

FAUX_NODE = r"""#!/usr/bin/env bash
case "${1:-}" in
    -v) echo "v${FAUX_NODE_VERSION:-24.16.0}"; exit 0 ;;
    --input-type=module) [ "${FAUX_NODE_SUPPORTE:-1}" = "1" ]; exit $? ;;
esac
if [[ "${1:-}" == *openclaw.mjs ]]; then
    shift
    echo "openclaw $*" >>"$FAUX_JOURNAL"
    if [ "${FAUX_ECHEC:-}" = "openclaw $*" ]; then echo "echec simule de : $*" >&2; exit 1; fi
    if [ "$1 ${2:-}" = "gateway install" ]; then
        # Un core qui crache un secret : l'installateur ne doit ni l'afficher ni le journaliser.
        echo "service installe, jeton du moteur : $(sed -n 's/^OPSYS_MCP_JETON=//p' "$OPENCLAW_STATE_DIR/.env")"
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
    dossier="${*: -1}"
    mkdir -p "$dossier/bin"
    printf '#!/bin/sh\nexec %s "$@"\n' "$FAUX_PYTHON" >"$dossier/bin/python"
    chmod +x "$dossier/bin/python"
fi
exit 0
"""

FAUX_CURL = "#!/usr/bin/env bash\nexit 0\n"


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
        self.depot = tmp_path / "depot"
        self.hote.mkdir()
        self.faux.mkdir()
        for nom, corps in (("node", FAUX_NODE), ("pnpm", FAUX_PNPM), ("uv", FAUX_UV), ("curl", FAUX_CURL)):
            chemin = self.faux / nom
            chemin.write_text(corps, encoding="utf-8")
            chemin.chmod(0o755)
        self.journal.write_text("", encoding="utf-8")
        self.env_supplementaire: dict[str, str] = {}

    # -- le dépôt fictif : le strict nécessaire pour l'installateur, dans un vrai dépôt git ---------------------------
    def fabriquer_depot(self) -> Path:
        (self.depot / "core").mkdir(parents=True)
        (self.depot / "departments").mkdir()
        (self.depot / "core" / "openclaw.mjs").write_text("// faux core\n", encoding="utf-8")
        (self.depot / "core" / "node-version.mjs").write_text("// faux\n", encoding="utf-8")
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
            "FAUX_JOURNAL": str(self.journal), "FAUX_PNPM_VERSION": PNPM, "FAUX_PYTHON": sys.executable,
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

    def preparer_decisions(self) -> None:
        """Les décisions que l'installateur n'invente pas : un palier de modèles et le service d'embeddings."""
        self.home.mkdir(parents=True, mode=0o700, exist_ok=True)
        (self.home / "paliers.yaml").write_text(
            "paliers: {standard: {provider: anthropic, model: claude-sonnet-5}}\n", encoding="utf-8")
        self.env_supplementaire.update(EMBEDDINGS)

    def secrets(self) -> list[str]:
        env = (self.home / "core" / ".env").read_text(encoding="utf-8")
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


def test_un_node_non_supporte_par_le_fork_arrete_tout(bac):
    resultat = bac.installer(FAUX_NODE_SUPPORTE="0", FAUX_NODE_VERSION="22.1.0")

    assert resultat.returncode == 1
    assert "Node v22.1.0 n'est pas pris en charge" in resultat.stderr and "24.16" in resultat.stderr
    assert not any(a.startswith("pnpm") for a in bac.appels()) and not bac.bin.exists()


def test_une_option_inconnue_est_refusee(bac):
    resultat = bac.installer("--nimporte")

    assert resultat.returncode == 1 and "option inconnue" in resultat.stderr


# -- l'installation de bout en bout (fausses commandes) ------------------------------------------------------
def test_installation_complete_dans_l_ordre_avec_les_bons_arguments(bac):
    bac.preparer_decisions()

    resultat = bac.installer()

    assert resultat.returncode == 0, _sortie(resultat)
    assert "OPSYS est installé." in resultat.stdout
    appels = bac.appels()
    attendu = ["pnpm install --frozen-lockfile", "pnpm build", "openclaw --version"]
    assert [a for a in appels if a in attendu] == attendu
    ordre = [next(i for i, a in enumerate(appels) if a.startswith(debut)) for debut in (
        "pnpm install", "pnpm build", "uv venv", "uv pip install", "openclaw --version", "openclaw config validate",
        "openclaw gateway install")]
    assert ordre == sorted(ordre)
    assert f"uv venv --clear --python >=3.11 {bac.logiciel}/venv" in appels
    assert f"uv pip install --python {bac.logiciel}/venv/bin/python --editable {bac.depot}" in appels
    assert "openclaw gateway install --force --port 18789" in appels
    config = json.loads((bac.home / "core" / "openclaw.json").read_text(encoding="utf-8"))
    assert config["gateway"]["port"] == 18789
    metier = json.loads((bac.home / "core" / "opsys" / "metier.json").read_text(encoding="utf-8"))
    assert metier["actif"] is True and metier["dossier"] == str(bac.depot) and metier["port"] == 8765
    enregistrement = (bac.logiciel / "installation.env").read_text(encoding="utf-8")
    for ligne in (f"OPSYS_HOME={bac.home}", f"SOURCE={bac.depot}", "SOURCE_GEREE=0", "SERVICE=1", "PORT_GATEWAY=18789",
                  "PORT_MOTEUR=8765"):
        assert ligne in enregistrement.splitlines()


def test_les_ports_demandes_sont_ceux_du_service_et_du_moteur(bac):
    bac.preparer_decisions()

    resultat = bac.installer(OPSYS_PORT_GATEWAY="18790", OPSYS_PORT_MOTEUR="8766")

    assert resultat.returncode == 0, _sortie(resultat)
    assert "openclaw gateway install --force --port 18790" in bac.appels()
    metier = json.loads((bac.home / "core" / "opsys" / "metier.json").read_text(encoding="utf-8"))
    assert metier["port"] == 8766 and metier["commande"][-1] == "8766"
    relance = bac.installer()  # les ports sont ceux de la dernière installation, sans qu'on les redonne
    assert relance.returncode == 0 and "PORT_GATEWAY=18790" in (bac.logiciel / "installation.env").read_text()


def test_le_secret_est_prive_jamais_affiche_et_masque_meme_quand_une_commande_le_crache(bac):
    bac.preparer_decisions()

    resultat = bac.installer(OPSYS_VERBOSE="1")

    assert resultat.returncode == 0, _sortie(resultat)
    env = bac.home / "core" / ".env"
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
    avant_core = bac.empreinte_du_dossier(bac.home / "core")
    avant_paliers = (bac.home / "paliers.yaml").read_bytes()

    second = bac.installer()

    assert second.returncode == 0, _sortie(second)
    assert bac.empreinte_du_dossier(bac.home / "core") == avant_core  # .env, openclaw.json, fragments, metier.json
    assert (bac.home / "paliers.yaml").read_bytes() == avant_paliers
    assert bac.appels().count("openclaw gateway install --force --port 18789") == 2  # le Gateway est redémarré


def test_avec_l_option_sans_service_le_service_n_est_pas_installe(bac):
    bac.preparer_decisions()

    resultat = bac.installer("--sans-service")

    assert resultat.returncode == 0, _sortie(resultat)
    assert not [a for a in bac.appels() if a.startswith("openclaw gateway")]
    assert "openclaw config validate" in bac.appels()
    assert "SERVICE=0" in (bac.logiciel / "installation.env").read_text(encoding="utf-8").splitlines()
    assert "openclaw gateway run" in resultat.stdout


def test_les_commandes_installees_portent_l_instance_et_lisent_env_sans_l_evaluer(bac):
    bac.preparer_decisions()
    assert bac.installer("--sans-service").returncode == 0
    piege = bac.racine / "piege-execute"
    (bac.home / "core" / ".env").write_text(
        (bac.home / "core" / ".env").read_text(encoding="utf-8") + f"PIEGE=$(touch {piege})\n", encoding="utf-8")
    env = {k: v for k, v in bac.env().items() if k != "OPSYS_HOME"}  # la commande retrouve l'instance seule

    etat = subprocess.run([str(bac.bin / "opsys"), "base", "etat"], env=env, capture_output=True, text=True,
                          check=False)
    version = subprocess.run([str(bac.bin / "opsys"), "--version"], env=env, capture_output=True, text=True,
                             check=False)

    assert etat.returncode == 0, etat.stderr
    assert json.loads(etat.stdout)["base"].endswith(str(bac.home / "opsys.db"))
    assert version.stdout.startswith("opsys ")
    assert not piege.exists()  # la ligne du .env a été lue, jamais évaluée
    coeur = subprocess.run([str(bac.bin / "openclaw"), "config", "validate"], env=env, capture_output=True, text=True,
                           check=False)
    assert coeur.returncode == 0 and "openclaw config validate" in bac.appels()
    for commande in ("openclaw", "opsys"):
        assert os.access(bac.bin / commande, os.X_OK)


# -- fail-closed : décision manquante, étape en échec, fichier étranger --------------------------------------
def test_sans_paliers_ni_embeddings_l_installation_s_arrete_en_attente_avec_le_code_3(bac):
    resultat = bac.installer()

    assert resultat.returncode == 3, _sortie(resultat)
    assert "À FAIRE : paliers de modèles" in resultat.stderr and "À FAIRE : service d'embeddings" in resultat.stderr
    assert "Ce n'est pas une erreur d'installation" in resultat.stdout
    appels = bac.appels()
    assert "openclaw config validate" not in appels and not [a for a in appels if "gateway install" in a]
    assert (bac.bin / "openclaw").exists() and (bac.bin / "opsys").exists()  # de quoi fournir les décisions
    assert (bac.home / "core" / ".env").is_file() and not (bac.home / "core" / "openclaw.json").exists()

    bac.preparer_decisions()
    reprise = bac.installer()  # la même commande, décisions fournies : tout se termine
    assert reprise.returncode == 0, _sortie(reprise)
    assert "openclaw gateway install --force --port 18789" in bac.appels()


def test_une_etape_en_echec_arrete_tout_avec_la_fin_du_journal_et_quoi_faire(bac):
    bac.preparer_decisions()

    resultat = bac.installer(FAUX_ECHEC="pnpm build")

    assert resultat.returncode == 1
    assert "Construction du core (pnpm build, plusieurs minutes) : échec (code 1)" in resultat.stderr
    assert "echec simule de : pnpm build" in resultat.stderr  # fin du journal
    assert str(bac.logiciel / "journaux" / "installation.log") in resultat.stderr
    assert not [a for a in bac.appels() if a.startswith("uv")]  # rien n'a continué
    assert not bac.bin.exists() and not (bac.logiciel / "installation.env").exists()


def test_une_configuration_refusee_par_le_core_arrete_avant_le_service(bac):
    bac.preparer_decisions()

    resultat = bac.installer(FAUX_ECHEC="openclaw config validate")

    assert resultat.returncode == 1 and "Validation de la configuration par le core" in resultat.stderr
    assert not [a for a in bac.appels() if "gateway install" in a]


def test_un_service_impossible_dit_quoi_faire(bac):
    bac.preparer_decisions()

    resultat = bac.installer(FAUX_ECHEC="openclaw gateway install --force --port 18789")

    assert resultat.returncode == 1
    assert "--sans-service" in resultat.stderr and "openclaw gateway run" in resultat.stderr


def test_un_fichier_etranger_n_est_jamais_ecrase(bac):
    bac.preparer_decisions()
    bac.bin.mkdir()
    etranger = bac.bin / "openclaw"
    etranger.write_text("#!/bin/sh\necho openclaw d'origine\n", encoding="utf-8")

    resultat = bac.installer()

    assert resultat.returncode == 1 and "n'a pas été installé par OPSYS" in resultat.stderr
    assert etranger.read_text(encoding="utf-8") == "#!/bin/sh\necho openclaw d'origine\n"


def test_une_url_de_base_dans_l_environnement_est_refusee_avec_la_voie_docker(bac):
    bac.preparer_decisions()

    resultat = bac.installer(OPSYS_BASE_URL="postgresql+psycopg://u:mot-de-passe-pg-fictif@h/db")

    assert resultat.returncode == 1
    assert "Docker Compose" in _sortie(resultat) and "mot-de-passe-pg-fictif" not in _sortie(resultat)


def _unite_systemd(bac: Bac) -> Path:
    return bac.hote / ".config" / "systemd" / "user" / "openclaw-gateway.service"


@pytest.mark.skipif(sys.platform != "linux", reason="chemin de l'unité systemd (Linux)")
def test_le_service_d_une_autre_installation_n_est_jamais_remplace(bac):
    bac.preparer_decisions()
    unite = _unite_systemd(bac)
    unite.parent.mkdir(parents=True)
    etranger = "[Service]\nExecStart=/usr/bin/node /opt/openclaw/openclaw.mjs gateway --port 18789\n"
    unite.write_text(etranger, encoding="utf-8")

    resultat = bac.installer()

    assert resultat.returncode == 1
    assert "n'a pas été installé par cette installation d'OPSYS" in resultat.stderr and str(unite) in resultat.stderr
    assert not [a for a in bac.appels() if a.startswith("pnpm")]  # refus AVANT toute construction
    assert unite.read_text(encoding="utf-8") == etranger

    sans_service = bac.installer("--sans-service")  # l'option est l'issue documentée
    assert sans_service.returncode == 0, _sortie(sans_service)
    assert unite.read_text(encoding="utf-8") == etranger


@pytest.mark.skipif(sys.platform != "linux", reason="chemin de l'unité systemd (Linux)")
def test_un_service_qui_nomme_notre_instance_ou_note_dans_l_enregistrement_est_remplace(bac):
    bac.preparer_decisions()
    unite = _unite_systemd(bac)
    unite.parent.mkdir(parents=True)
    unite.write_text(f'[Service]\nEnvironment="OPENCLAW_STATE_DIR={bac.home}/core"\n', encoding="utf-8")

    premiere = bac.installer()  # première installation, définition qui nomme cette instance

    assert premiere.returncode == 0, _sortie(premiere)
    unite.write_text("[Service]\nExecStart=/ou/le/core/a/mis/son/chemin\n", encoding="utf-8")  # sans notre marque
    relance = bac.installer()  # l'enregistrement dit SERVICE=1 : le service est le nôtre
    assert relance.returncode == 0, _sortie(relance)
    assert bac.appels().count("openclaw gateway install --force --port 18789") == 2


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
    assert f"uv pip install --python {bac.logiciel}/venv/bin/python --editable {clone}" in bac.appels()

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
    secrets = bac.secrets()

    resultat = bac.lancer(dossier / "uninstall.sh")

    assert resultat.returncode == 0, _sortie(resultat)
    assert "openclaw gateway uninstall" in bac.appels()
    assert not (bac.bin / "openclaw").exists() and not (bac.bin / "opsys").exists()
    assert not bac.logiciel.exists()  # venv, clone géré, journal, enregistrement : tout est parti, dossier compris
    donnees_apres = bac.empreinte_du_dossier(bac.home)
    assert {nom: h for nom, h in donnees_apres.items() if not nom.startswith("opsys.db")} == \
           {nom: h for nom, h in donnees_avant.items() if not nom.startswith("opsys.db")}
    assert (bac.home / "opsys.db").is_file() and (bac.home / "core" / ".env").is_file()
    assert bac.secrets() == secrets  # les secrets sont ceux d'avant
    assert "Données conservées" in resultat.stdout and str(bac.home) in resultat.stdout

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

    resultat = bac.lancer(dossier / "uninstall.sh", FAUX_ECHEC="openclaw gateway uninstall")

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
    assert not (bac.bin / "openclaw").exists()


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


# -- les constantes que l'installateur recopie du fork -------------------------------------------------------
def test_les_versions_que_l_installateur_annonce_sont_celles_du_fork():
    plancher = re.findall(r"major: (\d+), minor: (\d+), patch: (\d+)",
                          (RACINE / "core/node-version.mjs").read_text(encoding="utf-8").split("const HIGHEST")[0])
    assert plancher == [("24", "16", "0"), ("26", "1", "0")]
    for script in (INSTALL, RACINE / "install" / "install.ps1"):
        texte = script.read_text(encoding="utf-8")
        assert "24.16" in texte and "26.1" in texte, script.name


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
    for script in (INSTALL, UNINSTALL, bout_en_bout):
        assert os.access(script, os.X_OK), f"{script.name} doit être exécutable"
        assert subprocess.run(["bash", "-n", str(script)], capture_output=True, check=False).returncode == 0
    shellcheck = shutil.which("shellcheck")
    if shellcheck:
        resultat = subprocess.run([shellcheck, "-s", "bash", str(INSTALL), str(UNINSTALL), str(bout_en_bout)],
                                  capture_output=True, text=True, check=False,
                                  env={**os.environ, "LC_ALL": "C.UTF-8"})
        assert resultat.returncode == 0, resultat.stdout
