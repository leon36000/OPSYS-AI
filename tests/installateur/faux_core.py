"""Faux core d'OPSYS : remplace `node core/openclaw.mjs` pour éprouver `bout_en_bout.sh` hors de la CI.

Le bac à sable de développement ne construit ni n'exécute le core (TypeScript). Ce script joue le core sur ce que
`bout_en_bout.sh` lui demande, d'après le code du fork lu, pour que le script de preuve lui-même soit essayé avant la
CI (`tests/test_installateur_bout_en_bout.py`). Le MOTEUR est le vrai : le faux Gateway lance `opsys/metier.json`
comme le superviseur du core (T0.10), avec le jeton de `.env`.

Ce que ce faux core NE prouve PAS : que le vrai core se construit, qu'il applique ces règles, qu'il installe un
LaunchAgent ou une tâche planifiée. Cela, seule la CI le prouve. Ici, on éprouve la logique du script de preuve : ses
attentes, ses branches macOS et Linux, ses échecs (chaque contrôle est essayé avec une faute injectée).

Appel : `node faux_core.py <arguments de node>` (le faux `node` du test l'exécute). Arguments compris : `-v`,
`--input-type=module`, le fichier `opsys-node-<guid>.mjs` du contrôle de version de install.ps1, et
`<...>/openclaw.mjs [--profile <p>] <commande>` pour `--version`, `config file`, `config validate`,
`gateway run --bind loopback --port <n>`, `gateway install --force --port <n>`, `gateway stop`, `gateway uninstall` et
`doctor --non-interactive`, ainsi que `metier <arguments>` et les anciens noms des commandes du moteur (PLAN T0.7
lot 2, `core/src/cli/opsys-metier-cli.ts`, écrit ici d'après lui). Le service émulé
est celui de macOS (LaunchAgent) : plist, fichier d'environnement 0600 et enveloppe, comme
`core/src/daemon/launchd-service-files.ts` ; `launchctl` est un autre faux, qui lit le fichier de pid.

Le dossier d'état du profil `opsys` (PLAN T0.7 lot 3, `core/src/config/opsys-instance.ts`, écrit ici d'après lui) est
`~/.opsys/core`, avec `opsys.json` (un `openclaw.json` qui existe reste lu) ; tant que seul l'ancien
`~/.openclaw-opsys` porte un état, le core l'utilise en place. `doctor --non-interactive` y joue la seule étape qui
importe ici, celle de `core/src/infra/state-migrations.opsys-instance.ts` : DÉPLACER l'ancien état (un renommage),
laisser un lien à l'ancien chemin, ne jamais fusionner ni supprimer (deux états : il s'arrête). Les autres profils
gardent `~/.openclaw-<profil>` et `openclaw.json`.

`FAUX_PLATEFORME=windows` : le service émulé est la tâche planifiée « OpenClaw Gateway (<profil>) » : le script
`<état du core>/gateway.cmd` (sans secret) et un enregistrement de tâche dans `$FAUX_TACHES` (défaut :
`~/.faux-taches`), comme `core/src/daemon/schtasks-install.ts`. `gateway uninstall` arrête le Gateway, supprime la
tâche et le script.

Fautes injectables (variables d'environnement, pour les contrôles négatifs) :
- FAUX_SECRET_DANS_PLIST=1 : le plist reçoit le jeton du moteur (le core ne doit jamais le faire) ;
- FAUX_SECRET_DANS_JOURNAL=1 : le journal du service reçoit le jeton du moteur ;
- FAUX_ETIQUETTE=<étiquette> : le service prend une autre étiquette que ai.openclaw.<profil> ;
- FAUX_SERVICE_ARRETE=1 : le service est installé mais ne démarre pas ;
- FAUX_PLIST_SANS_RUNATLOAD=1 : le plist n'a pas RunAtLoad ;
- FAUX_ENV_LISIBLE=1 : le fichier d'environnement du service porte le jeton du moteur et est écrit 0644 ;
- FAUX_SANS_PROFIL=1 : le fichier d'environnement du service ne porte pas le profil ;
- FAUX_SANS_JOURNAL=1 : le service n'écrit aucun journal ;
- FAUX_DESINSTALLATION_INCOMPLETE=1 : `gateway uninstall` laisse le plist en place ;
- FAUX_SANTE=1 : le faux Gateway répond aussi 200 sur /sante (pour un essai sans moteur, un seul port) ;
- FAUX_CRACHE_LE_JETON=1 : `gateway install` écrit le jeton du moteur dans sa sortie (l'installateur doit le masquer) ;
- FAUX_SANS_REPLI=1 : le core ne replie pas sur `~/.openclaw-opsys` tant qu'il est seul à porter un état ;
- FAUX_DOCTOR_INACTIF=1 : `doctor` ne déplace rien ;
- FAUX_DOCTOR_COPIE=1 : `doctor` COPIE l'état au lieu de le déplacer (l'ancien reste en place, sans lien) ;
- FAUX_DOCTOR_SANS_LIEN=1 : `doctor` déplace l'état mais ne laisse aucun lien à l'ancien chemin ;
- FAUX_DOCTOR_PERD_UN_FICHIER=1 : `doctor` perd `opsys/tools.json` en chemin ;
- FAUX_DOCTOR_ALTERE_UN_SECRET=1 : `doctor` modifie `.env` en chemin ;
- FAUX_DOCTOR_RENOMME_LA_CONFIG=1 : `doctor` renomme `openclaw.json` en `opsys.json` ;
- FAUX_DOCTOR_FUSIONNE=1 : devant deux états, `doctor` fusionne l'ancien dans le nouveau et retire l'ancien ;
- FAUX_SERVICE_GARDE_L=1 : la définition du service nomme toujours `~/.openclaw-opsys` ;
- FAUX_SERVICE_NOMME_LE_NOUVEAU=1 : la définition du service nomme toujours `~/.opsys/core`, même sous le repli.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION_NODE = "v24.16.0"
# Ce que le superviseur du core laisse passer jusqu'au moteur (core/src/gateway/opsys-metier-env.ts) : l'environnement
# nécessaire à Python, jamais OPENCLAW_* ni les clés de fournisseurs.
PASSAVANT_NOMS = {"HOME", "LANG", "PATH", "TMPDIR", "USER", "LOGNAME", "TZ", "SHELL"}
PASSAVANT_PREFIXES = ("LC_", "OPSYS_", "PYTHON", "UV_", "XDG_", "FAUX_")
# `opsys metier` (core/src/cli/opsys-metier-cli.ts) : les mêmes noms que le superviseur, sans FAUX_ (propre à ce faux).
PASSAVANT_PREFIXES_CLI = ("LC_", "LITELLM_", "OPSYS_", "PYTHON", "UV_", "XDG_")
# Les anciennes commandes du moteur (core/src/cli/opsys-metier-argv.ts : OPSYS_METIER_MOVED_COMMANDS) ;
# tests/test_commande_metier.py confronte cette liste à celle du core et au parseur du moteur.
COMMANDES_DEPLACEES = (
    "departements", "verifier", "profils", "agents-base", "approbations", "personnes", "base", "evenements", "mode",
    "budgets",
    "services", "equipes", "meteo", "paliers", "openclaw", "appareils", "instance", "passerelle",
    "memoire-developpement",
)


def lire_env(chemin: Path) -> dict[str, str]:
    valeurs: dict[str, str] = {}
    if chemin.is_file():
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            correspondance = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", ligne)
            if correspondance and not ligne.lstrip().startswith("#"):
                valeurs[correspondance.group(1)] = correspondance.group(2).strip().strip("'\"")
    return valeurs


def porte_un_etat(dossier: Path) -> bool:
    """Le dossier existe et contient quelque chose (`dirHasEntries` du core, sans le cas des dossiers illisibles)."""
    try:
        return any(dossier.iterdir())
    except OSError:
        return False


class Contexte:
    """Ce que `--profile` projette : le dossier d'état et le fichier de configuration canoniques du profil."""

    def __init__(self, profil: str | None) -> None:
        self.profil = profil
        self.home = Path(os.environ["HOME"])
        suffixe = f"-{profil}" if profil else ""
        if profil == "opsys":
            # core/src/config/opsys-instance.ts : ~/.opsys/core ; l'ancien ~/.openclaw-opsys tant qu'il est seul à
            # porter un état (Doctor le déplace ensuite).
            self.canonique = self.home / ".opsys" / "core"
            sans_repli = bool(os.environ.get("FAUX_SANS_REPLI"))
            if not sans_repli and not porte_un_etat(self.canonique) and porte_un_etat(self.home / ".openclaw-opsys"):
                self.canonique = self.home / ".openclaw-opsys"
        else:
            self.canonique = self.home / f".openclaw{suffixe}"
        self.etat = Path(os.environ.get("OPENCLAW_STATE_DIR") or self.canonique)
        config = self.etat / "openclaw.json"
        if profil == "opsys" and ((self.etat / "opsys.json").exists() or not config.exists()):
            config = self.etat / "opsys.json"  # opsys.json ; seul un openclaw.json qui existe reste lu, jamais renommé
        self.config = Path(os.environ.get("OPENCLAW_CONFIG_PATH") or config)
        self.etiquette = os.environ.get("FAUX_ETIQUETTE") or f"ai.openclaw.{profil or 'gateway'}"
        self.dossier_faux_launchd = Path(os.environ.get("FAUX_LAUNCHD", str(self.home / ".faux-launchd")))

    def etat_nomme_par_le_service(self) -> Path:
        """Le dossier d'état que la définition du service écrit : le dossier actif, sauf faute injectée."""
        if os.environ.get("FAUX_SERVICE_GARDE_L"):
            return self.home / ".openclaw-opsys"
        if os.environ.get("FAUX_SERVICE_NOMME_LE_NOUVEAU"):
            return self.home / ".opsys" / "core"
        return self.etat

    def est_le_dossier_canonique(self) -> bool:
        """`isDefaultInstallIdentity` : chemins réels comparés (un lien laissé par Doctor désigne le même dossier)."""
        return os.path.realpath(self.etat) == os.path.realpath(self.canonique)


# -- commandes simples ------------------------------------------------------------------------------------------------
def config_valider(contexte: Contexte) -> int:
    try:
        texte = contexte.config.read_text(encoding="utf-8")
        json.loads(texte)
    except (OSError, ValueError) as erreur:
        sys.stderr.write(f"Config invalid: {erreur}\n")
        return 1
    dotenv = lire_env(contexte.etat / ".env")
    for nom in set(re.findall(r"\$\{([A-Z0-9_]+)\}", texte)):
        if nom not in dotenv and nom not in os.environ:
            sys.stderr.write(f"Config invalid: MissingEnvVarError: {nom}\n")
            return 1
    print("Config valid")
    return 0


# -- Gateway au premier plan ------------------------------------------------------------------------------------------
class Sondes(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # nom imposé par http.server
        chemins = {"/startupz", "/healthz", "/readyz"} | ({"/sante"} if os.environ.get("FAUX_SANTE") else set())
        self.send_response(200 if self.path.split("?")[0] in chemins else 404)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *_: object) -> None:
        return


def environnement_du_moteur(metier: dict, jeton: str) -> dict[str, str]:
    env = {n: v for n, v in os.environ.items() if n in PASSAVANT_NOMS or n.startswith(PASSAVANT_PREFIXES)}
    env["PYTHONUNBUFFERED"] = "1"
    env.update({str(cle): str(valeur) for cle, valeur in (metier.get("env") or {}).items()})
    env["OPSYS_MCP_JETON"] = jeton  # le jeton de .env : une seule authentification (T0.10)
    return env


def gateway_au_premier_plan(contexte: Contexte, port: int) -> int:
    arret = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: arret.set())
    signal.signal(signal.SIGINT, lambda *_: arret.set())
    serveur = ThreadingHTTPServer(("127.0.0.1", port), Sondes)
    serveur.daemon_threads = True
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    print(f"[faux gateway] 127.0.0.1:{port}, profil {contexte.profil}, état {contexte.etat}", flush=True)
    enfant = None
    chemin_metier = contexte.etat / "opsys" / "metier.json"
    if chemin_metier.is_file():
        metier = json.loads(chemin_metier.read_text(encoding="utf-8"))
        if metier.get("actif"):
            jeton = lire_env(contexte.etat / ".env").get("OPSYS_MCP_JETON") or os.environ.get("OPSYS_MCP_JETON", "")
            enfant = subprocess.Popen(
                metier["commande"], cwd=metier["dossier"], env=environnement_du_moteur(metier, jeton),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

            def relayer() -> None:
                for ligne in enfant.stdout:  # type: ignore[union-attr]
                    print(f"[opsys-metier] {ligne.rstrip()}", flush=True)

            threading.Thread(target=relayer, daemon=True).start()
    while not arret.is_set() and (enfant is None or enfant.poll() is None):
        time.sleep(0.2)
    if enfant is not None and enfant.poll() is None:  # arrêt commun : le Gateway emporte le moteur qu'il supervise
        enfant.terminate()
        try:
            enfant.wait(timeout=15)
        except subprocess.TimeoutExpired:
            enfant.kill()
    serveur.shutdown()
    print("[faux gateway] arrêté", flush=True)
    return 0


# -- service (LaunchAgent) --------------------------------------------------------------------------------------------
def fichier_pid(contexte: Contexte) -> Path:
    return contexte.dossier_faux_launchd / f"{contexte.etiquette}.pid"


def service_vivant(contexte: Contexte) -> int | None:
    try:
        pid = int(fichier_pid(contexte).read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def crache_le_jeton(jeton: str) -> None:
    # Un core qui crache un secret : l'installateur ne doit ni l'afficher ni le journaliser.
    if os.environ.get("FAUX_CRACHE_LE_JETON"):
        print(f"service installe, jeton du moteur : {jeton}")


def service_installer(contexte: Contexte, port: int, noeud: str, entree: str) -> int:
    # core/src/config/paths.ts, isDefaultInstallIdentity : l'état doit être le dossier canonique du profil.
    if os.environ.get("OPENCLAW_HOME") or not contexte.est_le_dossier_canonique():
        sys.stderr.write(
            "Gateway install blocked: Error: service management skipped: non-default state dir or config path.\n")
        return 1
    jeton = lire_env(contexte.etat / ".env").get("OPSYS_MCP_JETON", "")
    dossier_env = contexte.etat / "service-env"
    dossier_env.mkdir(mode=0o700, exist_ok=True)
    fichier_env = dossier_env / f"{contexte.etiquette}.env"
    lignes = ["# Generated by OpenClaw. Do not edit while the gateway service is installed.",
              f"export OPENCLAW_GATEWAY_PORT={shlex.quote(str(port))}"]
    if not os.environ.get("FAUX_SANS_PROFIL"):
        lignes.append(f"export OPENCLAW_PROFILE={shlex.quote(contexte.profil or '')}")
    lignes.append(f"export OPENCLAW_STATE_DIR={shlex.quote(str(contexte.etat_nomme_par_le_service()))}")
    if os.environ.get("FAUX_ENV_LISIBLE"):
        lignes.append(f"export OPSYS_MCP_JETON={shlex.quote(jeton)}")
    fichier_env.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    fichier_env.chmod(0o644 if os.environ.get("FAUX_ENV_LISIBLE") else 0o600)
    enveloppe = dossier_env / f"{contexte.etiquette}-env-wrapper.sh"
    enveloppe.write_text('#!/bin/sh\nset -eu\n. "$1"\nshift\nexec "$@"\n', encoding="utf-8")
    enveloppe.chmod(0o700)
    dossier_journaux = contexte.home / "Library" / "Logs" / "openclaw"
    journal = dossier_journaux / f"gateway-{contexte.profil}.log"
    plist = {
        "Label": contexte.etiquette,
        "ProgramArguments": [
            "/bin/sh", str(enveloppe), str(fichier_env), noeud, entree, "gateway", "--port", str(port)],
        "StandardOutPath": str(journal), "StandardErrorPath": str(journal),
        "KeepAlive": True, "ThrottleInterval": 10, "Umask": 0o077,
    }
    if not os.environ.get("FAUX_PLIST_SANS_RUNATLOAD"):
        plist["RunAtLoad"] = True
    if os.environ.get("FAUX_SECRET_DANS_PLIST"):
        plist["EnvironmentVariables"] = {"OPSYS_MCP_JETON": jeton}
    chemin_plist = contexte.home / "Library" / "LaunchAgents" / f"{contexte.etiquette}.plist"
    chemin_plist.parent.mkdir(parents=True, exist_ok=True)
    chemin_plist.write_bytes(plistlib.dumps(plist))
    chemin_plist.chmod(0o644)
    if not os.environ.get("FAUX_SERVICE_ARRETE"):  # « launchctl bootstrap » : RunAtLoad démarre le Gateway
        contexte.dossier_faux_launchd.mkdir(parents=True, exist_ok=True)
        if not os.environ.get("FAUX_SANS_JOURNAL"):
            dossier_journaux.mkdir(parents=True, exist_ok=True)
            with journal.open("ab") as sortie:
                if os.environ.get("FAUX_SECRET_DANS_JOURNAL"):
                    sortie.write(f"jeton du moteur : {jeton}\n".encode())
        with (journal.open("ab") if journal.exists() else open(os.devnull, "wb")) as sortie:
            processus = subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), entree, "--profile", contexte.profil or "",
                 "gateway", "run", "--bind", "loopback", "--port", str(port)],
                stdout=sortie, stderr=subprocess.STDOUT, start_new_session=True, env={
                    n: v for n, v in os.environ.items() if not n.startswith("OPENCLAW_")})
        fichier_pid(contexte).write_text(str(processus.pid), encoding="utf-8")
    print(f"Installed LaunchAgent: {chemin_plist}\nLogs: {journal}")
    crache_le_jeton(jeton)
    return 0


def service_arreter(contexte: Contexte) -> int:
    """`gateway stop` : le Gateway s'arrête, la définition du service reste installée."""
    pid = service_vivant(contexte)
    if pid is not None:
        os.kill(pid, signal.SIGTERM)
        for _ in range(150):
            if service_vivant(contexte) is None:
                break
            time.sleep(0.2)
    fichier_pid(contexte).unlink(missing_ok=True)
    print("Stopped LaunchAgent")
    return 0


def service_desinstaller(contexte: Contexte) -> int:
    service_arreter(contexte)
    plist = contexte.home / "Library" / "LaunchAgents" / f"{contexte.etiquette}.plist"
    if plist.exists() and not os.environ.get("FAUX_DESINSTALLATION_INCOMPLETE"):
        corbeille = contexte.home / ".Trash"
        corbeille.mkdir(exist_ok=True)
        plist.rename(corbeille / plist.name)
        print(f"Moved LaunchAgent to Trash: {corbeille / plist.name}")
    return 0


# -- service (tâche planifiée Windows) ---------------------------------------------------------------------------------
def nom_de_tache(contexte: Contexte) -> str:
    return f"OpenClaw Gateway ({contexte.profil})" if contexte.profil else "OpenClaw Gateway"


def dossier_des_taches(contexte: Contexte) -> Path:
    return Path(os.environ.get("FAUX_TACHES", str(contexte.home / ".faux-taches")))


def tache_installer(contexte: Contexte, port: int, noeud: str, entree: str) -> int:
    if os.environ.get("OPENCLAW_HOME") or not contexte.est_le_dossier_canonique():
        sys.stderr.write("Gateway install blocked: service management skipped: non-default state dir or config path.\n")
        return 1
    script = contexte.etat / "gateway.cmd"
    script.write_text("\r\n".join([
        "@echo off", f"rem OpenClaw Gateway (profile: {contexte.profil})",
        f'set "OPENCLAW_GATEWAY_PORT={port}"', f'set "OPENCLAW_PROFILE={contexte.profil}"',
        f'set "OPENCLAW_STATE_DIR={contexte.etat_nomme_par_le_service()}"',
        f'"{noeud}" "{entree}" gateway --port {port} < NUL', ""]),
        encoding="utf-8")
    dossier = dossier_des_taches(contexte)
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / f"{nom_de_tache(contexte)}.tache").write_text("LeastPrivilege\n", encoding="utf-8")
    journal = contexte.etat / "logs" / "gateway.log"
    journal.parent.mkdir(exist_ok=True)
    with journal.open("ab") as sortie:
        processus = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), entree, "--profile", contexte.profil or "",
             "gateway", "run", "--bind", "loopback", "--port", str(port)],
            stdout=sortie, stderr=subprocess.STDOUT, start_new_session=True, env={
                n: v for n, v in os.environ.items() if not n.startswith("OPENCLAW_")})
    (dossier / f"{nom_de_tache(contexte)}.pid").write_text(str(processus.pid), encoding="utf-8")
    print(f"Installed Scheduled Task: {nom_de_tache(contexte)}\nTask script: {script}")
    crache_le_jeton(lire_env(contexte.etat / ".env").get("OPSYS_MCP_JETON", ""))
    return 0


def tache_arreter(contexte: Contexte) -> int:
    """`gateway stop` : le Gateway s'arrête, la tâche planifiée reste enregistrée."""
    fichier_pid = dossier_des_taches(contexte) / f"{nom_de_tache(contexte)}.pid"
    try:
        pid = int(fichier_pid.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
        for _ in range(150):
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.2)
    except (OSError, ValueError):
        pass
    fichier_pid.unlink(missing_ok=True)
    print("Stopped Scheduled Task")
    return 0


def tache_desinstaller(contexte: Contexte) -> int:
    tache_arreter(contexte)
    (dossier_des_taches(contexte) / f"{nom_de_tache(contexte)}.tache").unlink(missing_ok=True)
    script = contexte.etat / "gateway.cmd"
    if script.exists():
        script.unlink()
        print(f"Removed task script: {script}")
    return 0


# -- `opsys doctor --non-interactive` : la migration de l'état du profil opsys -----------------------------------------
def doctor(contexte: Contexte) -> int:
    """L'étape `state-dir` de Doctor pour le profil `opsys` (`core/src/infra/state-migrations.opsys-instance.ts`) :
    l'ancien état (`~/.openclaw-opsys`) est DÉPLACÉ vers `~/.opsys/core` par un seul renommage, un lien reste à
    l'ancien chemin (lien de dossier ; jonction sous Windows), rien n'est copié, fusionné ni supprimé. Deux états :
    elle s'arrête."""
    if contexte.profil != "opsys":
        print("Doctor : rien à migrer pour ce profil (faux core : seul le profil opsys a une migration d'état)")
        return 0
    source, cible = contexte.home / ".openclaw-opsys", contexte.home / ".opsys" / "core"
    if os.environ.get("FAUX_DOCTOR_INACTIF"):
        print("Doctor : rien fait (faute injectée)")
        return 0
    if not os.path.lexists(source):
        print("Doctor : état déjà au bon endroit")
        return 0
    if source.is_symlink():
        if os.path.realpath(source) == os.path.realpath(cible):
            print("Doctor : état déjà au bon endroit (ancien chemin lié)")
        else:
            print(f"OPSYS state dir migration skipped: {source} is a symbolic link elsewhere. Nothing was changed.")
        return 0
    if not source.is_dir():
        print(f"OPSYS state dir migration skipped: {source} is not a directory. Nothing was changed.")
        return 0
    source_a_un_etat = porte_un_etat(source)
    remplacer_cible_vide = False
    conflit = False
    if not os.path.lexists(cible):
        if not source_a_un_etat:
            print("Doctor : ancien dossier vide, rien à migrer")
            return 0
    elif not (cible.is_dir() or cible.is_symlink()):
        conflit = True
    elif not source_a_un_etat:  # ancien vide : rien à sauver, il devient le lien
        source.rmdir()
        os.symlink(cible, source, target_is_directory=True)
        print(f"State dir: {source} → {cible} (empty former path now linked)")
        return 0
    elif cible.is_dir() and not cible.is_symlink() and not porte_un_etat(cible):
        remplacer_cible_vide = True
    else:
        conflit = True
    if conflit:
        if os.environ.get("FAUX_DOCTOR_FUSIONNE"):  # ce que Doctor ne doit JAMAIS faire
            for fichier in list(source.iterdir()):
                shutil.move(str(fichier), str(cible / fichier.name))
            source.rmdir()
            print(f"State dir: {source} merged into {cible} (faute injectée)")
            return 0
        print(f"OPSYS state dir migration skipped: both {source} (former location) and {cible} hold state. "
              "Nothing was moved, merged or deleted.")
        return 0
    cible.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.environ.get("FAUX_DOCTOR_COPIE"):  # copier au lieu de déplacer : deux états, la faute que la migration évite
        shutil.copytree(source, cible, symlinks=True)
        print(f"State dir: {source} copied to {cible} (faute injectée)")
        return 0
    if remplacer_cible_vide:
        cible.rmdir()
    os.rename(source, cible)
    if not os.environ.get("FAUX_DOCTOR_SANS_LIEN"):
        os.symlink(cible, source, target_is_directory=True)
    if os.environ.get("FAUX_DOCTOR_PERD_UN_FICHIER"):
        (cible / "opsys" / "tools.json").unlink(missing_ok=True)
    if os.environ.get("FAUX_DOCTOR_ALTERE_UN_SECRET"):
        with (cible / ".env").open("a", encoding="utf-8") as sortie:
            sortie.write("MARQUEUR_ALTERE=1\n")
    if os.environ.get("FAUX_DOCTOR_RENOMME_LA_CONFIG") and (cible / "openclaw.json").exists():
        (cible / "openclaw.json").rename(cible / "opsys.json")
    print(f"State dir: {source} → {cible} (former path now linked)")
    return 0


# -- `opsys metier` : le moteur Python par le core ---------------------------------------------------------------------
def citer(argument: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", argument):
        return argument
    return '"' + re.sub(r'(["\\$`])', r"\\\1", argument) + '"'


def ancienne_forme(nom: str, arguments: list[str]) -> int:
    reste = " ".join(citer(a) for a in [nom, *arguments])
    sys.stderr.write(
        f"opsys : « {nom} » n'est plus une commande de opsys. Depuis que « opsys » est la commande du core,\n"
        f"celles du moteur métier sont sous « opsys metier ».\nUtilisez : opsys metier {reste}\n"
        f"(Avec le moteur seul, sans le core, par exemple dans un conteneur Docker : opsys-metier {reste})\n")
    return 2


def metier(contexte: Contexte, arguments: list[str]) -> int:
    """Ce que fait le core : lit `opsys/metier.json` (`commande_cli`), y ajoute les arguments, hérite du terminal et du
    dossier courant, et rend le code de sortie du moteur ; l'environnement du moteur est celui du superviseur, sans
    OPENCLAW_*, et l'environnement de l'appelant prime sur la clé `env` du fichier."""
    if os.environ.get("OPENCLAW_SHELL") == "exec":
        sys.stderr.write(
            "opsys metier : commande réservée à l'opérateur, refusée depuis le shell d'un agent "
            "(OPENCLAW_SHELL=exec).\n")
        return 1
    chemin = contexte.etat / "opsys" / "metier.json"
    if not chemin.is_file():
        sys.stderr.write(
            f"opsys metier : le moteur métier n'est pas configuré pour ce core ({chemin} est absent).\n")
        return 1
    config = json.loads(chemin.read_text(encoding="utf-8"))
    commande = config.get("commande_cli")
    if not commande:
        sys.stderr.write(
            "opsys metier : metier.json ne dit pas comment lancer la CLI du moteur (clé « commande_cli »).\n")
        return 1
    # le premier gagne : ce que l'appelant a exporté reste
    appelant = {**lire_env(contexte.etat / ".env"), **os.environ}
    env = {str(cle): str(valeur) for cle, valeur in (config.get("env") or {}).items()}
    env.update({n: v for n, v in appelant.items() if n in PASSAVANT_NOMS or n.startswith(PASSAVANT_PREFIXES_CLI)})
    return subprocess.run([*commande, *arguments], env=env, check=False).returncode


# -- point d'entrée ---------------------------------------------------------------------------------------------------
def option(arguments: list[str], nom: str) -> str | None:
    position = arguments.index(nom) + 1 if nom in arguments else len(arguments)
    return arguments[position] if position < len(arguments) else None


def core(entree: str, arguments: list[str]) -> int:
    profil = None
    if arguments[:1] == ["--profile"]:
        profil = arguments[1]
        arguments = arguments[2:]
    contexte = Contexte(profil or None)
    if arguments[:1] == ["metier"]:
        return metier(contexte, arguments[1:])
    if arguments[:1] == ["doctor"]:
        return doctor(contexte)
    if arguments[:1] and arguments[0] in COMMANDES_DEPLACEES:
        return ancienne_forme(arguments[0], arguments[1:])
    if arguments == ["--version"]:
        print("OPSYS 0.0.0 (faux core)")
        return 0
    if arguments[:2] == ["config", "file"]:
        print(contexte.config)
        return 0
    if arguments[:2] == ["config", "validate"]:
        return config_valider(contexte)
    port = int(option(arguments, "--port") or 18789)
    if arguments[:2] == ["gateway", "run"]:
        return gateway_au_premier_plan(contexte, port)
    windows = os.environ.get("FAUX_PLATEFORME") == "windows"
    if arguments[:2] == ["gateway", "install"]:
        installer = tache_installer if windows else service_installer
        return installer(contexte, port, os.environ.get("FAUX_NODE_CHEMIN", "node"), entree)
    if arguments[:2] == ["gateway", "stop"]:
        return (tache_arreter if windows else service_arreter)(contexte)
    if arguments[:2] == ["gateway", "uninstall"]:
        return (tache_desinstaller if windows else service_desinstaller)(contexte)
    sys.stderr.write(f"faux core : commande inattendue : {' '.join(arguments)}\n")
    return 99


def main(arguments: list[str]) -> int:
    if arguments[:1] == ["-v"]:
        print(VERSION_NODE)
        return 0
    if arguments[:1] == ["--input-type=module"]:
        return 0
    if arguments and re.search(r"opsys-node-[0-9a-f]+\.mjs$", arguments[0]):  # le contrôle de version de install.ps1
        return 0
    if arguments and arguments[0].endswith("openclaw.mjs"):
        return core(arguments[0], arguments[1:])
    sys.stderr.write(f"faux node : appel inattendu : {' '.join(arguments)}\n")
    return 99


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
