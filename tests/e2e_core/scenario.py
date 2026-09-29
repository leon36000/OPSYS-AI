#!/usr/bin/env python3
"""E2E « app -> core -> moteur » avec le VRAI core (PLAN T1.5-b) : `python tests/e2e_core/scenario.py`.

`tests/e2e/` prouve le moteur, avec la règle de la porte d'appareil du core refaite en Python. Ce scénario prouve
le trajet réel : un Gateway OPSYS-CORE construit (`pnpm build`), la configuration que `opsys openclaw configurer`
génère, le moteur métier, un appareil qui s'appaire comme l'app, et les appels que l'app fait ensuite.

Étapes (chacune échoue franchement, avec les journaux du Gateway et du moteur) :
 1. configuration : `opsys base migrer`, `opsys paliers definir`, `opsys openclaw configurer` (les vrais fragments
    `roles.json`, `mcp.json`, ...), puis `openclaw.json` complété du bloc `gateway` (le seul réglage que le socle
    n'écrit pas) et, avec `--moteur superviseur`, `opsys/metier.json` ; une personne (`opsys personnes creer`) ;
 2. donnée : un chantier assigné à cette personne, par les vrais outils (`executer_atomique`) ;
 3. démarrage : `openclaw config validate` (le core accepte la configuration générée), puis le Gateway
    (`openclaw gateway run`), qui lance et surveille le moteur (superviseur T0.10) ou, avec `--moteur direct`, un
    moteur lancé ici (`opsys-mcp --http`) ;
 4. appairage : `openclaw qr` (code d'appairage), puis `appairer.mjs` joue la poignée de main de l'app (défi,
    charge v3 signée Ed25519) ; le propriétaire approuve par la CLI du core (`openclaw devices approve`) ; l'appareil
    reçoit son jeton ; avant l'attribution, le core ne lui donne ni identité ni outil ;
 5. attribution : `opsys appareils appairer <deviceId> --personne ... --role employee` ;
 6. trajet : `trajet.jouer` (identité, lecture, écritures avec `idempotencyKey`, `_meta` arrivé au moteur, rejeu,
    refus hors portée), chaque appel chronométré.

Le core n'est pas modifié par ce script. Une seule différence avec un vrai téléphone, voulue : la connexion vient
de 127.0.0.1, que le core approuverait en silence ; `gateway.nodes.pairing.autoApproveLocal=false` impose
l'approbation explicite, celle d'un téléphone distant.

Prérequis : `pip install -e ".[dev]"`, Node 24 et le core construit (`cd core && pnpm install && pnpm build`).
Code de sortie : 0 tout est vrai, 1 un constat est faux ou un processus a échoué.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import json
import os
import queue
import re
import secrets
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[2]
ICI = Path(__file__).resolve().parent
if str(ICI) not in sys.path:
    sys.path.insert(0, str(ICI))

from trajet import (  # noqa: E402
    Appareil,
    EchecE2E,
    EtatDuMoteur,
    LectureDirecte,
    Passerelle,
    exiger,
    jouer,
    resume_latences,
    verifier_avant_attribution,
)

PERSONNE = "sylvie-fictif"
NOM_PERSONNE = "Sylvie Tremblay (fictif)"
ROLE = "employee"
MOT_DE_PASSE = "mot-de-passe-e2e-core-fictif-1234"
DEPARTEMENT_TERRAIN = "m04-field-ops"
ID_CLIENT_APP = "opsys-mobile"
URL_INJOIGNABLE = "http://127.0.0.1:9/v1"  # LiteLLM et embeddings : refus immédiat, jamais un DNS qui traîne
DELAI_COMMANDE_S = 180
SECRETS: list[str] = []


# -- secrets : masqués dans le journal de GitHub Actions et caviardés dans nos propres sorties ------------------
def masquer(valeur: str) -> str:
    SECRETS.append(valeur)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{valeur}", flush=True)
    return valeur


def caviarder(texte: str) -> str:
    for secret in SECRETS:
        texte = texte.replace(secret, "***")
    return texte


def etape(texte: str) -> None:
    print(f"\n== {texte}", flush=True)


# -- l'instance ---------------------------------------------------------------------------------------------
@dataclasses.dataclass
class Instance:
    travail: Path
    core: Path  # racine du fork (`core/`), où est `openclaw.mjs`
    commande_core: list[str]
    superviseur: bool
    port_gateway: int
    port_moteur: int
    jeton_mcp: str
    jeton_gateway: str
    env: dict[str, str]

    @property
    def dossier_core(self) -> Path:
        """Dossier de configuration ET d'état du core (`OPENCLAW_STATE_DIR`) : `openclaw.json`, `opsys/`."""
        return self.travail / "core-etat"

    @property
    def dossier_opsys(self) -> Path:
        return self.dossier_core / "opsys"

    @property
    def url_gateway(self) -> str:
        return f"http://127.0.0.1:{self.port_gateway}"

    @property
    def url_mcp(self) -> str:
        return f"http://127.0.0.1:{self.port_moteur}/mcp"

    @property
    def journaux(self) -> Path:
        return self.travail / "journaux"


def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def environnement_de_base(
    travail: Path, *, port_gateway: int, jeton_mcp: str, jeton_gateway: str, base_sql: str | None = None,
) -> dict[str, str]:
    """Environnement commun des processus enfants (CLI du socle, CLI du core, Gateway, moteur)."""
    from opsys.serveur_mcp import ENV_REPARTITEUR

    env = dict(os.environ)
    chemins_python = [str(RACINE / "src"), *sorted(str(p) for p in RACINE.glob("departments/*/src"))]
    if env.get("PYTHONPATH"):
        chemins_python.append(env["PYTHONPATH"])
    env.update({
        "PYTHONPATH": os.pathsep.join(chemins_python),
        "OPSYS_HOME": str(travail / "opsys-home"),
        "OPSYS_BASE_URL": base_sql or f"sqlite:///{travail / 'opsys.db'}",
        "OPSYS_MCP_JETON": jeton_mcp,
        # Le bus est livré à la main dans `tests/e2e/` ; ici personne ne l'attend, le répartiteur de fond reste éteint.
        ENV_REPARTITEUR: "0",
        "OPSYS_EMBEDDINGS_URL": URL_INJOIGNABLE,
        "OPSYS_EMBEDDINGS_MODELE": "bge-m3",
        "OPSYS_PERSONNE_MOT_DE_PASSE": MOT_DE_PASSE,
        "OPENCLAW_STATE_DIR": str(travail / "core-etat"),
        "OPENCLAW_GATEWAY_TOKEN": jeton_gateway,
        "OPENCLAW_GATEWAY_PORT": str(port_gateway),
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "NO_COLOR": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def creer_instance(
    travail: Path, core: Path, *, commande_core: list[str] | None = None, superviseur: bool = True,
    jeton_mcp: str | None = None, base_sql: str | None = None,
) -> Instance:
    exiger(not travail.exists() or not any(travail.iterdir()),
           "le dossier de travail doit être neuf : une base ou un état de core d'une exécution précédente "
           "fausserait le scénario", dossier=str(travail))
    travail.mkdir(parents=True, exist_ok=True)
    (travail / "journaux").mkdir(exist_ok=True)
    jeton_mcp = masquer(jeton_mcp or secrets.token_hex(24))  # 48 caractères : le moteur en exige 24 au moins
    jeton_gateway = masquer(secrets.token_hex(24))
    port_gateway, port_moteur = port_libre(), port_libre()
    return Instance(
        travail=travail, core=core, commande_core=commande_core or ["node", str(core / "openclaw.mjs")],
        superviseur=superviseur, port_gateway=port_gateway, port_moteur=port_moteur, jeton_mcp=jeton_mcp,
        jeton_gateway=jeton_gateway,
        env=environnement_de_base(travail, port_gateway=port_gateway, jeton_mcp=jeton_mcp,
                                  jeton_gateway=jeton_gateway, base_sql=base_sql))


# -- commandes ------------------------------------------------------------------------------------------------
def lancer(argv: list[str], env: dict[str, str], *, cwd: Path | None = None, delai_s: int = DELAI_COMMANDE_S,
           ) -> subprocess.CompletedProcess[str]:
    """Une commande qui doit réussir. Sinon `EchecE2E` avec sa sortie, secrets caviardés."""
    libelle = " ".join(shlex.quote(a) for a in argv)
    try:
        resultat = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=delai_s, check=False)
    except subprocess.TimeoutExpired as erreur:
        raise EchecE2E(f"commande sans réponse après {delai_s} s : {caviarder(libelle)}") from erreur
    if resultat.returncode != 0:
        raise EchecE2E(f"commande en échec (code {resultat.returncode}) : {caviarder(libelle)}\n"
                       f"--- sortie\n{caviarder(resultat.stdout[-3000:])}\n"
                       f"--- erreurs\n{caviarder(resultat.stderr[-3000:])}")
    return resultat


def opsys(instance: Instance, *args: str) -> subprocess.CompletedProcess[str]:
    return lancer([sys.executable, "-m", "opsys.cli", *args], instance.env, cwd=RACINE)


def openclaw(instance: Instance, *args: str, delai_s: int = DELAI_COMMANDE_S) -> subprocess.CompletedProcess[str]:
    """La CLI du core, lancée depuis le dossier de configuration : les chemins relatifs des fragments (les espaces de
    travail, `./opsys/espaces`) sont relatifs à ce dossier, comme dans le déploiement."""
    return lancer([*instance.commande_core, *args], instance.env, cwd=instance.dossier_core, delai_s=delai_s)


def json_de_sortie(texte: str, quoi: str) -> Any:
    """Le JSON d'une commande qui a pu écrire un bandeau avant lui."""
    debut = texte.find("{")
    if debut < 0:
        raise EchecE2E(f"{quoi} : aucune sortie JSON\n{caviarder(texte[-1500:])}")
    try:
        return json.loads(texte[debut:])
    except ValueError as erreur:
        raise EchecE2E(f"{quoi} : sortie JSON illisible ({erreur})\n{caviarder(texte[-1500:])}") from erreur


# -- 1. configuration et personne --------------------------------------------------------------------------------
def preparer_configuration(instance: Instance) -> None:
    """Les vraies commandes du socle, puis les deux réglages du core que le socle n'écrit pas."""
    opsys(instance, "base", "migrer")
    opsys(instance, "paliers", "definir", "standard", "--provider", "anthropic", "--model", "claude-sonnet-5")
    opsys(instance, "openclaw", "configurer", "--config-dir", str(instance.dossier_core), "--url-mcp", instance.url_mcp,
          "--url-passerelle", URL_INJOIGNABLE)

    racine = instance.dossier_core / "openclaw.json"
    config = json.loads(racine.read_text(encoding="utf-8"))
    exiger({"models", "agents", "mcp", "tools", "memory", "plugins"} <= set(config) and "gateway" not in config,
           "openclaw.json doit venir de `opsys openclaw configurer` : six $include OPSYS, aucun bloc gateway",
           cles=sorted(config))
    config["gateway"] = {
        "mode": "local", "port": instance.port_gateway, "bind": "loopback", "auth": {"mode": "token"},
        # Un téléphone est distant pour le core : approbation explicite (voir l'en-tête du module).
        "nodes": {"pairing": {"autoApproveLocal": False}},
    }
    racine.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    roles = json.loads((instance.dossier_opsys / "roles.json").read_text(encoding="utf-8"))
    exiger("m4_lister_interventions" in roles["roles"][ROLE] and roles["serveurs"].get("m4_pointer") == "opsys_m4",
           "roles.json doit permettre à l'employé les outils du scénario, portés par le serveur opsys_m4",
           employee=roles["roles"][ROLE][:5])
    mcp = json.loads((instance.dossier_opsys / "mcp.json").read_text(encoding="utf-8"))
    exiger(mcp["servers"]["opsys_m4"]["url"] == f"{instance.url_mcp}/{DEPARTEMENT_TERRAIN}",
           "mcp.json doit pointer le moteur de ce scénario", serveur=mcp["servers"]["opsys_m4"])

    # Le core refuse de charger une configuration qui cite une variable absente : les clés virtuelles des
    # départements (LiteLLM, injoignable ici) reçoivent une valeur fictive, le jeton du moteur est le vrai.
    for fichier in sorted(instance.dossier_opsys.glob("*.json")):
        for nom in re.findall(r"\$\{([A-Z_][A-Z0-9_]*)\}", fichier.read_text(encoding="utf-8")):
            instance.env.setdefault(nom, f"fictif-{nom.lower()}-e2e-core")

    if instance.superviseur:
        metier = {
            "actif": True, "dossier": str(RACINE), "hote": "127.0.0.1", "port": instance.port_moteur,
            "commande": [sys.executable, "-m", "opsys.serveur_mcp", "--http", "--hote", "127.0.0.1",
                         "--port", str(instance.port_moteur)],
            "env": {cle: instance.env[cle] for cle in ("OPSYS_HOME", "OPSYS_BASE_URL", "PYTHONPATH")
                    } | {"OPSYS_EVENEMENTS_REPARTITEUR": "0"},
            "delai_pret_ms": 180_000,
        }
        (instance.dossier_opsys / "metier.json").write_text(json.dumps(metier, indent=2) + "\n", encoding="utf-8")

    opsys(instance, "personnes", "creer", PERSONNE, "--nom", NOM_PERSONNE, "--role", ROLE)


# -- 2. la donnée --------------------------------------------------------------------------------------------------
def semer_chantier() -> Any:
    """Un chantier assigné à `PERSONNE`, par les vrais outils de M2, M3 et M4. Dans CE processus : l'environnement
    (`OPSYS_HOME`, `OPSYS_BASE_URL`) doit déjà désigner la base de l'instance."""
    import m2_revenue_crm.outils as m2_outils
    import m5_financecore.outils as m5_outils
    from harnais_e2e import DT_TZ
    from harnais_e2e_chantier import preparer_chantier

    from opsys import stockage
    from opsys.departements import charger_departements

    stockage.migrer()
    m2_outils.utiliser_stockage_durable()
    m5_outils.utiliser_stockage_durable()
    # La journée de travail a commencé il y a une heure : l'heure réelle est dans la fenêtre du chantier.
    debut = dt.datetime.now(DT_TZ).replace(microsecond=0) - dt.timedelta(hours=1)
    return preparer_chantier(charger_departements(), suffixe="E2E-CORE", technicien=PERSONNE, debut=debut)


# -- 3. les processus ------------------------------------------------------------------------------------------------
class Processus:
    """Un processus de fond : journal dans un fichier, groupe de processus à part pour l'arrêter en entier."""

    def __init__(self, nom: str, argv: list[str], env: dict[str, str], cwd: Path, journal: Path) -> None:
        self.nom = nom
        self.journal = journal
        self._sortie = journal.open("wb")
        self.popen = subprocess.Popen(argv, env=env, cwd=cwd, stdout=self._sortie, stderr=subprocess.STDOUT,
                                      start_new_session=True)

    def vivant(self) -> bool:
        return self.popen.poll() is None

    def fin_du_journal(self, lignes: int = 120) -> str:
        texte = self.journal.read_text(encoding="utf-8", errors="replace")
        return caviarder("\n".join(texte.splitlines()[-lignes:]))

    def arreter(self, delai_s: int = 30) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(self.popen.pid, signal.SIGTERM)
        try:
            self.popen.wait(delai_s)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.popen.pid, signal.SIGKILL)
            self.popen.wait(10)
        self._sortie.close()


def attendre_http(url: str, quoi: str, delai_s: float, surveiller: list[Processus]) -> None:
    """Attend un 200 sur `url`, et échoue tout de suite si un processus surveillé s'arrête."""
    ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    limite = time.monotonic() + delai_s
    dernier = "aucune réponse"
    while time.monotonic() < limite:
        for processus in surveiller:
            if not processus.vivant():
                raise EchecE2E(f"{processus.nom} s'est arrêté (code {processus.popen.returncode}) avant : {quoi}\n"
                               f"--- fin du journal de {processus.nom}\n{processus.fin_du_journal()}")
        try:
            with ouvreur.open(url, timeout=5) as reponse:
                if reponse.status == 200:
                    return
                dernier = f"HTTP {reponse.status}"
        except urllib.error.HTTPError as erreur:
            dernier = f"HTTP {erreur.code}"
        except (urllib.error.URLError, OSError) as erreur:
            dernier = str(erreur)
        time.sleep(0.5)
    fins = "\n".join(f"--- fin du journal de {p.nom}\n{p.fin_du_journal(60)}" for p in surveiller)
    raise EchecE2E(f"délai de {delai_s:.0f} s dépassé : {quoi} ({url} : {dernier})\n{fins}")


def demarrer_moteur_direct(instance: Instance, pile: contextlib.ExitStack) -> Processus:
    moteur = Processus(
        "moteur", [sys.executable, "-m", "opsys.serveur_mcp", "--http", "--hote", "127.0.0.1", "--port",
                   str(instance.port_moteur)], instance.env, RACINE, instance.journaux / "moteur.log")
    pile.callback(moteur.arreter)
    attendre_http(f"http://127.0.0.1:{instance.port_moteur}/sante", "le moteur répond à /sante", 120, [moteur])
    return moteur


def demarrer_gateway(instance: Instance, pile: contextlib.ExitStack, delai_s: int) -> Processus:
    gateway = Processus("gateway", [*instance.commande_core, "gateway", "run", "--bind", "loopback", "--port",
                                    str(instance.port_gateway)], instance.env, instance.dossier_core,
                        instance.journaux / "gateway.log")
    pile.callback(gateway.arreter)
    attendre_http(f"{instance.url_gateway}/startupz", "le Gateway a fini de démarrer (/startupz)", delai_s, [gateway])
    if instance.superviseur:
        attendre_http(f"http://127.0.0.1:{instance.port_moteur}/sante", "le superviseur a lancé le moteur (/sante)",
                      180, [gateway])
    return gateway


# -- 4. l'appairage, comme l'app -----------------------------------------------------------------------------------
class SortieDeLignes:
    """Lit la sortie d'un processus ligne par ligne, dans un fil : les évènements JSON de `appairer.mjs`."""

    def __init__(self, flux: Any) -> None:
        self.file: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._fil = threading.Thread(target=self._lire, args=(flux,), daemon=True)
        self._fil.start()

    def _lire(self, flux: Any) -> None:
        for ligne in flux:
            with contextlib.suppress(ValueError):
                evenement = json.loads(ligne)
                if isinstance(evenement, dict):
                    self.file.put(evenement)
        self.file.put(None)

    def attendre(self, noms: set[str], delai_s: float) -> dict[str, Any]:
        """Le prochain évènement dont le nom est dans `noms` ; `echec` lève, un autre nom est un écart."""
        try:
            evenement = self.file.get(timeout=delai_s)
        except queue.Empty as erreur:
            raise EchecE2E(f"aucun évènement de l'appairage parmi {sorted(noms)} en {delai_s:.0f} s") from erreur
        if evenement is None:
            raise EchecE2E(f"appairer.mjs s'est arrêté sans évènement parmi {sorted(noms)}")
        if evenement.get("evenement") == "echec":
            raise EchecE2E(f"l'appairage a échoué : {caviarder(json.dumps(evenement, ensure_ascii=False))}")
        exiger(evenement.get("evenement") in noms, f"évènement d'appairage inattendu (attendu : {sorted(noms)})",
               evenement=evenement.get("evenement"))
        return evenement


def code_d_appairage(instance: Instance) -> str:
    """`openclaw qr` : le code que le propriétaire remet au téléphone (jeton d'amorçage à usage unique)."""
    sortie = openclaw(instance, "qr", "--json", "--url", f"ws://127.0.0.1:{instance.port_gateway}")
    contenu = json_de_sortie(sortie.stdout, "openclaw qr --json")
    exiger(isinstance(contenu.get("setupCode"), str) and contenu.get("gatewayUrl")
           == f"ws://127.0.0.1:{instance.port_gateway}", "openclaw qr doit rendre un code pour ce Gateway",
           cles=sorted(contenu))
    return masquer(contenu["setupCode"])


def demande_en_attente(instance: Instance, device_id: str, delai_s: float = 30) -> dict[str, Any]:
    """La demande d'appairage de cet appareil, telle que le propriétaire la voit (`openclaw devices list`)."""
    limite = time.monotonic() + delai_s
    while True:
        liste = json_de_sortie(openclaw(instance, "devices", "list", "--json").stdout, "openclaw devices list --json")
        pour_lui = [d for d in liste.get("pending", []) if d.get("deviceId") == device_id]
        if pour_lui:
            return pour_lui[-1]
        if time.monotonic() > limite:
            raise EchecE2E(f"aucune demande d'appairage de {device_id[:12]}… chez le propriétaire",
                           liste={k: len(v) for k, v in liste.items() if isinstance(v, list)})
        time.sleep(0.5)


def appairer_comme_l_app(instance: Instance) -> tuple[str, str]:
    """L'appairage de bout en bout ; rend (deviceId, jeton d'appareil). Le jeton est masqué dès qu'il existe."""
    code = code_d_appairage(instance)
    app = subprocess.Popen(
        ["node", str(ICI / "appairer.mjs"), "--code", code, "--attente", "stdin", "--budget-s", "240"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=instance.env)
    evenements = SortieDeLignes(app.stdout)
    try:
        device_id = evenements.attendre({"identite"}, 60)["deviceId"]
        # Premier refus : l'appareil est inconnu du core, le propriétaire doit approuver (autoApproveLocal=false).
        premier = evenements.attendre({"attente_approbation", "reussi"}, 60)
        exiger(premier["evenement"] == "attente_approbation",
               "l'appareil a été appairé sans l'approbation du propriétaire : le core a ignoré "
               "gateway.nodes.pairing.autoApproveLocal=false", evenement=premier["evenement"])
        demande = demande_en_attente(instance, device_id)
        exiger(demande.get("clientId") == ID_CLIENT_APP, "la demande doit venir de l'app OPSYS", demande=demande)
        approbation = json_de_sortie(openclaw(instance, "devices", "approve", demande["requestId"], "--json").stdout,
                                     "openclaw devices approve")
        exiger(approbation.get("device", {}).get("deviceId") == device_id,
               "l'approbation doit viser l'appareil demandeur", approbation=approbation)
        assert app.stdin is not None
        app.stdin.write("approuve\n")
        app.stdin.flush()
        reussi = evenements.attendre({"reussi"}, 90)
        jeton = masquer(reussi["deviceToken"])
        exiger(reussi["deviceId"] == device_id and reussi["role"] == "operator",
               "hello-ok doit rendre le rôle de transport `operator`, jamais un rôle OPSYS", role=reussi["role"])
        exiger(app.wait(timeout=30) == 0, "appairer.mjs doit se terminer avec succès")
        liste = json_de_sortie(openclaw(instance, "devices", "list", "--json").stdout, "openclaw devices list --json")
        exiger(device_id in {d.get("deviceId") for d in liste.get("paired", [])},
               "l'appareil approuvé doit figurer parmi les appareils appairés du core")
        return device_id, jeton
    finally:
        if app.poll() is None:
            app.kill()
        app.wait()


def attribuer(instance: Instance, device_id: str) -> None:
    """Deuxième temps de l'appairage (ADR-0009 §5) : la personne et le rôle OPSYS de l'appareil approuvé."""
    opsys(instance, "appareils", "appairer", device_id, "--personne", PERSONNE, "--role", ROLE,
          "--config-dir", str(instance.dossier_core))
    fragment = json.loads((instance.dossier_opsys / "appareils.json").read_text(encoding="utf-8"))
    exiger(fragment == {"appareils": {device_id: {"personne": PERSONNE, "role": ROLE}}},
           "appareils.json doit attribuer l'appareil à la personne et au rôle", fragment=fragment)


# -- sortie ----------------------------------------------------------------------------------------------------------
def publier_mesures(travail: Path, mesures: list[dict[str, Any]]) -> None:
    tableau = resume_latences(mesures)
    print("\n" + tableau, flush=True)
    (travail / "mesures.json").write_text(json.dumps(mesures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sommaire = os.environ.get("GITHUB_STEP_SUMMARY")
    if sommaire:
        with open(sommaire, "a", encoding="utf-8") as fichier:
            fichier.write("### E2E avec le vrai core : latence de chaque appel de l'app\n\n" + tableau + "\n")


@contextlib.contextmanager
def environnement_du_processus(env: dict[str, str]) -> Iterator[None]:
    """Ce processus lit la base de l'instance (semer le chantier, prouver le `_meta`) : même environnement que ses
    enfants pour les seules variables du socle."""
    cles = ("OPSYS_HOME", "OPSYS_BASE_URL")
    avant = {cle: os.environ.get(cle) for cle in cles}
    os.environ.update({cle: env[cle] for cle in cles})
    try:
        yield
    finally:
        for cle, valeur in avant.items():
            if valeur is None:
                os.environ.pop(cle, None)
            else:
                os.environ[cle] = valeur


def executer(travail: Path, core: Path, *, moteur: str, commande_core: list[str] | None, delai_gateway_s: int) -> int:
    instance = creer_instance(travail, core, commande_core=commande_core, superviseur=moteur == "superviseur")
    print(f"dossier de travail : {travail}\nmoteur : {moteur} (port {instance.port_moteur}), "
          f"Gateway : port {instance.port_gateway}", flush=True)
    try:
        with environnement_du_processus(instance.env), contextlib.ExitStack() as pile:
            etape("1. configuration : commandes du socle, bloc gateway, personne")
            preparer_configuration(instance)
            etape("2. donnée : un chantier assigné à la personne")
            from opsys import stockage

            chantier = semer_chantier()
            pile.callback(stockage.liberer)
            etape("   la configuration générée est valide pour le vrai core : openclaw config validate")
            openclaw(instance, "config", "validate")
            etape("3. démarrage : Gateway" + (" + moteur supervisé (T0.10)" if instance.superviseur else " et moteur"))
            if not instance.superviseur:
                demarrer_moteur_direct(instance, pile)
            demarrer_gateway(instance, pile, delai_gateway_s)
            etape("4. appairage comme l'app, approbation par la CLI du core")
            device_id, jeton = appairer_comme_l_app(instance)
            passerelle = Passerelle(instance.url_gateway, jeton)
            etape("   avant l'attribution : ni identité ni outil")
            verifier_avant_attribution(passerelle)
            etape("5. attribution : opsys appareils appairer")
            attribuer(instance, device_id)
            etape("6. trajet de l'employé par la porte du core")
            mesures = jouer(
                passerelle, Appareil(device_id, jeton, PERSONNE, ROLE), chantier, EtatDuMoteur(),
                LectureDirecte(f"{instance.url_mcp}/{DEPARTEMENT_TERRAIN}", instance.jeton_mcp),
                secret_partage=instance.jeton_gateway)
            publier_mesures(travail, mesures)
    except Exception as erreur:  # toute faute du script est un échec, avec les journaux
        detail = str(erreur) if isinstance(erreur, EchecE2E) else caviarder(traceback.format_exc())
        print(f"\nÉCHEC : {caviarder(detail)}", file=sys.stderr, flush=True)
        for journal in sorted((travail / "journaux").glob("*.log")):
            texte = journal.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
            print(f"\n--- fin de {journal.name}\n" + caviarder("\n".join(texte)), file=sys.stderr, flush=True)
        return 1
    print("\nE2E avec le vrai core : tout est vrai."
          + (" (commande du core remplacée : répétition, pas le vrai core)" if commande_core else ""), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description="E2E app -> core -> moteur avec le vrai core (PLAN T1.5-b)")
    parseur.add_argument("--core", type=Path, default=RACINE / "core", help="racine du fork construit (défaut : core/)")
    parseur.add_argument("--travail", type=Path, help="dossier de travail (défaut : un dossier temporaire)")
    parseur.add_argument("--moteur", choices=["superviseur", "direct"], default="superviseur",
                         help="superviseur : le Gateway lance le moteur (T0.10) ; direct : ce script le lance")
    parseur.add_argument("--commande-core", help="remplace `node <core>/openclaw.mjs` (répétition sans core)")
    parseur.add_argument("--delai-gateway-s", type=int, default=300, help="attente du démarrage du Gateway")
    args = parseur.parse_args(argv)
    travail = (args.travail or Path(tempfile.mkdtemp(prefix="e2e-core-"))).resolve()
    if not (args.core / "openclaw.mjs").is_file() and not args.commande_core:
        print(f"{args.core}/openclaw.mjs introuvable : construire le core (cd core && pnpm install && pnpm build)",
              file=sys.stderr)
        return 1
    if not args.commande_core and not (args.core / "dist").is_dir():
        print(f"{args.core}/dist introuvable : `pnpm build` n'a pas été exécuté", file=sys.stderr)
        return 1
    commande = shlex.split(args.commande_core) if args.commande_core else None
    return executer(travail, args.core.resolve(), moteur=args.moteur, commande_core=commande,
                    delai_gateway_s=args.delai_gateway_s)


if __name__ == "__main__":
    raise SystemExit(main())
