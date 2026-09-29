"""Préparation de l'instance locale par l'installateur (PLAN T0.11, `install/install.sh` et `install.ps1`).

L'installateur s'occupe du logiciel : Node, pnpm, uv, construction du core, service. Tout ce qui touche à la
donnée de l'instance est ici, en Python testé, pour que Linux, macOS et Windows partagent UNE implémentation.
`opsys instance initialiser` est idempotent : on le relance à chaque mise à jour, et à la main après un
changement de paliers ou de départements.

Ce que la commande fait, dans l'ordre :
1. crée `$OPSYS_HOME` et `$OPSYS_HOME/core` (`OPENCLAW_STATE_DIR`, R14 décision 4), accessibles à leur
   propriétaire seul ;
2. migre la base de l'instance (SQLite, `$OPSYS_HOME/opsys.db`) ;
3. pose `$OPSYS_HOME/core/.env`, 0600 : les secrets qui manquent (jeton du moteur `OPSYS_MCP_JETON`, jeton du
   Gateway, une clé virtuelle par département) et les réglages fournis (`OPSYS_EMBEDDINGS_*`,
   `OPSYS_PASSERELLE_URL`). Un secret présent n'est JAMAIS régénéré ; aucune valeur n'est rendue ni écrite dans
   une sortie ;
4. vérifie que le core peut être configuré. Sinon (paliers de modèles, service d'embeddings) : verdict
   `en_attente` qui dit quoi fournir, et RIEN d'autre n'est écrit. Fail-closed : aucune valeur inventée ;
5. génère la configuration du core (`opsys openclaw configurer`), le bloc `gateway` de `openclaw.json` s'il
   manque, et `opsys/metier.json` (le superviseur du core lance alors le moteur, PLAN T0.10).

`$OPSYS_HOME/core/.env` est le fichier que le core lit lui-même au démarrage du Gateway, du service et de ses
commandes (`core/src/config/state-dir-dotenv.ts`) : `${OPSYS_MCP_JETON}` des fragments de configuration y est
résolu sans autre mécanisme.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from . import modeles, openclaw, stockage
from .departements import Departement, charger_departements
from .memoire.embeddings import ENV_CLE, ENV_LOCAL, ENV_MODELE, ENV_URL, ClientEmbeddings, ErreurEmbeddings

SOUS_DOSSIER_CORE = "core"
NOM_ENV = ".env"
ENV_JETON_MCP = "OPSYS_MCP_JETON"  # core/src/gateway/opsys-metier-config.ts::OPSYS_MCP_TOKEN_ENV
ENV_JETON_GATEWAY = "OPENCLAW_GATEWAY_TOKEN"
ENV_PASSERELLE = "OPSYS_PASSERELLE_URL"
ENV_BASE_URL = stockage.ENV_URL
URL_PASSERELLE_DEFAUT = "http://127.0.0.1:4000/v1"  # port usuel de LiteLLM en local ; l'installateur ne l'installe pas
PORT_GATEWAY_DEFAUT = 18789  # core/src/config/paths.ts::DEFAULT_GATEWAY_PORT
PORT_MOTEUR_DEFAUT = 8765  # core/src/gateway/opsys-metier-config.ts::DEFAULT_PORT
HOTE_LOCAL = "127.0.0.1"
CODE_EN_ATTENTE = 3  # code de sortie de `opsys instance initialiser` : installé, mais il manque une décision

# Les seuls réglages que l'installateur accepte de l'environnement et écrit dans `.env`.
REGLAGES_ACCEPTES = (ENV_URL, ENV_MODELE, ENV_CLE, ENV_LOCAL, ENV_PASSERELLE)

# Alphabet d'une valeur de `.env` : sans espace, guillemet, `$`, `#`, barre oblique inverse ni saut de ligne.
# Écrite ainsi, une ligne est lue de la même façon par le core (dotenv), par les enveloppes `opsys` (bash, cmd)
# et par `lire_env`, sans aucune règle de guillemets.
_VALEUR_PERMISE = re.compile(r"^[A-Za-z0-9._:/@%+=,~-]{1,512}$")
_AFFECTATION = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
_ENTETE_ENV = (
    "# Réglages et secrets de l'instance OPSYS. Géré par `opsys instance initialiser`.",
    "# Ne jamais partager ni versionner ce fichier. Il n'est pas inclus dans l'export de l'instance.",
)


class ErreurInstance(Exception):
    """Une préparation refusée ; le message dit quoi faire. Ne contient jamais la valeur d'un secret."""


@dataclasses.dataclass(frozen=True)
class RapportEnv:
    """Ce que `assurer_env` a fait, par NOM de variable : jamais une valeur."""

    chemin: Path
    generees: tuple[str, ...]
    conservees: tuple[str, ...]
    reglees: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class ResultatInitialisation:
    etat: str  # "pret" | "en_attente"
    revision: str
    manque: tuple[str, ...]
    avertissements: tuple[str, ...]
    env: RapportEnv
    fichiers: Mapping[str, str]
    port_gateway: int
    port_moteur: int

    def en_json(self) -> dict[str, Any]:
        return {
            "etat": self.etat,
            "revision": self.revision,
            "manque": list(self.manque),
            "avertissements": list(self.avertissements),
            "port_gateway": self.port_gateway,
            "port_moteur": self.port_moteur,
            "env": {
                "chemin": str(self.env.chemin),
                "secrets_generes": list(self.env.generees),
                "secrets_conserves": list(self.env.conservees),
                "reglages_ecrits": list(self.env.reglees),
            },
            "fichiers": dict(self.fichiers),
        }


# -- dossiers ----------------------------------------------------------------------------------------------------
def dossier_core(home: Path) -> Path:
    return home / SOUS_DOSSIER_CORE


def chemin_env(home: Path) -> Path:
    return dossier_core(home) / NOM_ENV


def _preparer_dossiers(home: Path) -> list[str]:
    """Crée `home` et `home/core` pour leur propriétaire seul. Un dossier existant n'est jamais modifié : s'il est
    ouvert à d'autres comptes, on le signale (renseignements personnels, Loi 25)."""
    avertissements: list[str] = []
    for dossier in (home, dossier_core(home)):
        if dossier.exists():
            if os.name != "nt" and stat.S_IMODE(dossier.stat().st_mode) & 0o077:
                avertissements.append(
                    f"{dossier} est accessible à d'autres comptes du poste : `chmod 700 {dossier}`."
                )
            continue
        dossier.mkdir(mode=0o700, parents=True)
        if os.name != "nt":
            os.chmod(dossier, 0o700)  # le umask a pu retirer des droits, jamais en ajouter ; ceci fixe le résultat
    return avertissements


def _restreindre(chemin: Path) -> None:
    """Le fichier n'est lisible que par son propriétaire (0600 ; ACL réduite à l'utilisateur sous Windows)."""
    if os.name == "nt":
        utilisateur = os.environ.get("USERNAME", "")
        if not utilisateur:
            raise ErreurInstance("USERNAME est absent : impossible de restreindre l'accès à .env (icacls).")
        resultat = subprocess.run(
            ["icacls", str(chemin), "/inheritance:r", "/grant:r", f"{utilisateur}:(F)"],
            capture_output=True, text=True, check=False,
        )
        if resultat.returncode != 0:
            raise ErreurInstance(f"icacls a refusé de restreindre l'accès à {chemin} : {resultat.stderr.strip()}")
        return
    os.chmod(chemin, 0o600)


# -- .env ----------------------------------------------------------------------------------------------------------
def _nette(valeur: str) -> str:
    valeur = valeur.strip()
    if len(valeur) >= 2 and valeur[0] == valeur[-1] and valeur[0] in "\"'":
        return valeur[1:-1]
    return valeur


def _affectations(lignes: Sequence[str]) -> dict[str, tuple[int, str]]:
    """Nom -> (index de la dernière ligne qui l'affecte, valeur sans guillemets). Le dernier gagne, comme dotenv."""
    trouvees: dict[str, tuple[int, str]] = {}
    for index, ligne in enumerate(lignes):
        if ligne.lstrip().startswith("#"):
            continue
        correspondance = _AFFECTATION.match(ligne)
        if correspondance:
            trouvees[correspondance.group(1)] = (index, _nette(correspondance.group(2)))
    return trouvees


def lire_env(chemin: Path) -> dict[str, str]:
    """Les affectations du fichier (`{}` s'il n'existe pas). Les valeurs vides sont conservées."""
    if not chemin.is_file():
        return {}
    lignes = chemin.read_text(encoding="utf-8").splitlines()
    return {nom: valeur for nom, (_, valeur) in _affectations(lignes).items()}


def _valider_reglage(nom: str, valeur: str) -> None:
    if not _VALEUR_PERMISE.match(valeur):
        raise ErreurInstance(
            f"la valeur de {nom} est refusée : 1 à 512 caractères parmi lettres, chiffres et . _ : / @ % + = , ~ - "
            "(ni espace, ni guillemet, ni $, ni #). Ni la valeur ni ses caractères ne sont répétés ici."
        )


def _secret_pour(nom: str) -> str:
    if nom.startswith("OPSYS_CLE_"):
        return f"sk-opsys-{nom.removeprefix('OPSYS_CLE_').lower()}-{secrets.token_hex(16)}"
    return secrets.token_hex(32)  # 256 bits ; le moteur en exige 24 caractères au moins


def _ecrire_prive(chemin: Path, lignes: Sequence[str]) -> None:
    """Écriture atomique d'un fichier 0600 : jamais, même un instant, lisible par un autre compte."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    descripteur, temporaire = tempfile.mkstemp(prefix=f"{chemin.name}.", dir=chemin.parent)
    fichier_temporaire = Path(temporaire)
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8", newline="\n") as sortie:
            sortie.write("\n".join(lignes) + "\n")
        _restreindre(fichier_temporaire)
        os.replace(fichier_temporaire, chemin)
    except BaseException:
        fichier_temporaire.unlink(missing_ok=True)
        raise


def assurer_env(
    chemin: Path,
    secrets_attendus: Sequence[str],
    reglages: Mapping[str, str] | None = None,
    *,
    fabrique: Callable[[str], str] = _secret_pour,
) -> RapportEnv:
    """Pose dans `chemin` (0600) les secrets qui manquent et les réglages fournis. Idempotent.

    - un secret déjà présent et non vide est conservé tel quel : jamais régénéré ;
    - un réglage fourni remplace la valeur en place si elle diffère (l'opérateur l'a demandé) ;
    - le reste du fichier (commentaires, variables ajoutées à la main) est conservé ligne pour ligne ;
    - le rapport porte des noms, jamais des valeurs.
    """
    reglages = dict(reglages or {})
    for nom, valeur in reglages.items():
        _valider_reglage(nom, valeur)
    existait = chemin.is_file()
    lignes = chemin.read_text(encoding="utf-8").splitlines() if existait else list(_ENTETE_ENV)
    presentes = _affectations(lignes)

    def poser(nom: str, valeur: str) -> None:
        if nom in presentes:
            lignes[presentes[nom][0]] = f"{nom}={valeur}"
        else:
            lignes.append(f"{nom}={valeur}")
            presentes[nom] = (len(lignes) - 1, valeur)

    generees: list[str] = []
    conservees: list[str] = []
    reglees: list[str] = []
    for nom in secrets_attendus:
        if nom in presentes and presentes[nom][1]:
            conservees.append(nom)
            continue
        poser(nom, fabrique(nom))
        generees.append(nom)
    for nom, valeur in reglages.items():
        if nom in presentes and presentes[nom][1] == valeur:
            continue
        poser(nom, valeur)
        reglees.append(nom)

    if generees or reglees or not existait:
        _ecrire_prive(chemin, lignes)
    else:
        _restreindre(chemin)  # un fichier posé à la main avec des droits trop larges est resserré
    return RapportEnv(chemin, tuple(generees), tuple(conservees), tuple(reglees))


# -- configuration du core -------------------------------------------------------------------------------------------
def _ecrire_json(chemin: Path, donnees: Any) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_name(f".{chemin.name}.tmp")
    temporaire.write_text(json.dumps(donnees, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporaire, chemin)


def _lire_objet_json(chemin: Path) -> dict[str, Any]:
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erreur:
        raise ErreurInstance(
            f"{chemin} est illisible ({erreur}) : corrigez-le ou déplacez-le, puis relancez.") from erreur
    if not isinstance(donnees, dict):
        raise ErreurInstance(f"{chemin} doit contenir un objet JSON.")
    return donnees


def completer_racine(dossier: Path, port_gateway: int | None) -> tuple[bool, int]:
    """Ajoute à `openclaw.json` le bloc `gateway` que `opsys openclaw configurer` n'écrit pas, s'il manque.

    Rend (bloc ajouté, port effectif). Un bloc existant n'est jamais modifié : c'est celui de l'opérateur.
    Le bloc : mode local, boucle locale seulement, authentification par jeton (`OPENCLAW_GATEWAY_TOKEN`, lu dans
    `.env`) et approbation explicite des appareils, même venus de 127.0.0.1 (le trajet que `tests/e2e_core`
    exerce).
    """
    racine = dossier / "openclaw.json"
    config = _lire_objet_json(racine)
    bloc = config.get("gateway")
    if bloc is not None:
        port = bloc.get("port") if isinstance(bloc, dict) else None
        return False, port if isinstance(port, int) else PORT_GATEWAY_DEFAUT
    port = port_gateway or PORT_GATEWAY_DEFAUT
    config["gateway"] = {
        "mode": "local", "port": port, "bind": "loopback", "auth": {"mode": "token"},
        "nodes": {"pairing": {"autoApproveLocal": False}},
    }
    _ecrire_json(racine, config)
    return True, port


def ecrire_metier(home: Path, *, source: Path, python: Path, port: int) -> Path:
    """`core/opsys/metier.json` : active le superviseur du moteur (`core/src/gateway/opsys-metier-config.ts`).

    La commande est l'interpréteur de l'environnement de l'installation, en chemin absolu : aucune résolution de
    dépendances ni accès réseau au démarrage, et `uv` n'a pas à être dans le PATH du service. Le fichier est celui
    de l'installateur : ses clés sont réécrites à chaque exécution, les autres clés sont conservées.
    """
    chemin = dossier_core(home) / "opsys" / "metier.json"
    metier = _lire_objet_json(chemin) if chemin.is_file() else {}
    env = metier.get("env") if isinstance(metier.get("env"), dict) else {}
    metier.update({
        "actif": True,
        "dossier": str(source),
        "hote": HOTE_LOCAL,
        "port": port,
        "commande": [str(python), "-m", "opsys.serveur_mcp", "--http", "--hote", HOTE_LOCAL, "--port", str(port)],
        "env": {**env, "OPSYS_HOME": str(home)},
    })
    metier.setdefault("delai_pret_ms", 120_000)
    _ecrire_json(chemin, metier)
    return chemin


# -- initialisation --------------------------------------------------------------------------------------------------
def _verifier_port(nom: str, port: int) -> int:
    if not 1 <= port <= 65535:
        raise ErreurInstance(f"{nom} : {port} n'est pas un port (1 à 65535).")
    return port


def _ce_qui_manque(departements: Mapping[str, Departement], env: Mapping[str, str]) -> tuple[list[str], dict[str, Any]]:
    """Ce que `opsys openclaw configurer` exige et que l'opérateur n'a pas encore décidé. Rien n'est inventé."""
    manque: list[str] = []
    try:
        paliers = modeles.charger_paliers()
    except ValueError as erreur:
        raise ErreurInstance(f"paliers.yaml est invalide : {erreur}") from erreur
    absents = sorted({dep.modeles["defaut"] for dep in departements.values()} - set(paliers))
    if absents:
        manque.append(
            f"paliers de modèles à choisir ({', '.join(absents)}) : "
            "`opsys paliers definir <palier> --provider <fournisseur> --model <modèle>`, "
            f"ou déposez {modeles.fichier_paliers()}"
        )
    try:
        if ClientEmbeddings.depuis_env(env) is None:
            manque.append(
                f"service d'embeddings compatible OpenAI (ex. bge-m3 par Ollama) : définissez {ENV_URL} et "
                f"{ENV_MODELE} dans l'environnement de la commande (elles sont ensuite gardées dans .env)"
            )
    except ErreurEmbeddings as erreur:
        manque.append(f"réglage des embeddings invalide : {erreur}")
    return manque, paliers


def initialiser(
    home: Path,
    *,
    source: Path,
    python: Path,
    port_gateway: int | None = None,
    port_moteur: int | None = None,
    environ: Mapping[str, str] | None = None,
    departements: Mapping[str, Departement] | None = None,
) -> ResultatInitialisation:
    """Prépare l'instance de `home`. Voir l'en-tête du module. Lève `ErreurInstance` quand rien ne peut continuer."""
    environ = os.environ if environ is None else environ
    if environ.get(ENV_BASE_URL, "").strip():
        raise ErreurInstance(
            f"{ENV_BASE_URL} est défini : l'installateur local gère la base SQLite de l'instance "
            "($OPSYS_HOME/opsys.db). Pour PostgreSQL, utilisez Docker Compose (deploy/). "
            "Retirez la variable pour continuer."
        )
    if port_gateway is not None:
        _verifier_port("port du Gateway", port_gateway)
    if port_moteur is not None:
        _verifier_port("port du moteur", port_moteur)
    if not (source / "pyproject.toml").is_file() or not (source / "departments").is_dir():
        raise ErreurInstance(f"{source} n'est pas un dépôt OPSYS (pyproject.toml et departments/ attendus) : --source.")
    if not python.is_file():
        raise ErreurInstance(f"interpréteur introuvable : {python}")

    avertissements = _preparer_dossiers(home)
    revision = stockage.migrer()
    deps = dict(departements) if departements is not None else charger_departements()

    chemin = chemin_env(home)
    reglages = {nom: environ[nom].strip() for nom in REGLAGES_ACCEPTES if environ.get(nom, "").strip()}
    if ENV_PASSERELLE not in reglages and not lire_env(chemin).get(ENV_PASSERELLE):
        reglages[ENV_PASSERELLE] = URL_PASSERELLE_DEFAUT
    secrets_attendus = [ENV_JETON_MCP, ENV_JETON_GATEWAY, *(openclaw._variable_cle(dep) for dep in deps.values())]
    rapport = assurer_env(chemin, secrets_attendus, reglages)
    env = lire_env(chemin)

    manque, paliers = _ce_qui_manque(deps, env)
    port_effectif_moteur = port_moteur or PORT_MOTEUR_DEFAUT
    fichiers = {"env": str(chemin)}
    if manque:
        return ResultatInitialisation(
            "en_attente", revision, tuple(manque), tuple(avertissements), rapport, fichiers,
            port_gateway or PORT_GATEWAY_DEFAUT, port_effectif_moteur,
        )

    dossier = dossier_core(home)
    openclaw.generer(
        deps, dossier, paliers, url_mcp=f"http://{HOTE_LOCAL}:{port_effectif_moteur}/mcp",
        url_passerelle=env[ENV_PASSERELLE], environ=env,
    )
    openclaw.racine_si_absente(dossier)
    _, port_effectif_gateway = completer_racine(dossier, port_gateway)
    if port_gateway and port_gateway != port_effectif_gateway:
        avertissements.append(
            f"gateway.port vaut {port_effectif_gateway} dans openclaw.json : le port {port_gateway} demandé est ignoré "
            f"(`openclaw config set gateway.port {port_gateway}` pour le changer)."
        )
    metier = ecrire_metier(home, source=source, python=python, port=port_effectif_moteur)
    fichiers.update({"openclaw": str(dossier / "openclaw.json"), "metier": str(metier)})
    return ResultatInitialisation(
        "pret", revision, (), tuple(avertissements), rapport, fichiers, port_effectif_gateway, port_effectif_moteur,
    )
