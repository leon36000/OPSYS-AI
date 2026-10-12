"""Préparation de l'instance locale par l'installateur (PLAN T0.11, `install/install.sh` et `install.ps1`).

L'installateur s'occupe du logiciel : Node, pnpm, uv, construction du core, service. Tout ce qui touche à la
donnée de l'instance est ici, en Python testé, pour que Linux, macOS et Windows partagent UNE implémentation.
`opsys-metier instance initialiser` est idempotent : on le relance à chaque mise à jour, et à la main après un
changement de paliers ou de départements.

Deux dossiers, deux rôles (PLAN T0.11-b, puis T0.7 lot 3) :
- `$OPSYS_HOME` (`~/.opsys`) : les DONNÉES métier (`opsys.db`, `paliers.yaml`, `entreprise.yaml`) ;
- l'ÉTAT DU CORE : `core/` dans le dossier d'instance, `~/.opsys/core` (`dossier_core`), configuration `opsys.json`
  (`fichier_config`). C'est le dossier canonique du profil `opsys` du core : le core n'installe un service natif que
  pour lui (`isDefaultInstallIdentity`, `core/src/config/paths.ts`) et donne à chaque profil son propre nom de service
  (`core/src/daemon/constants.ts`) : celui du core d'origine n'est donc jamais touché. Il vit sous le dossier
  personnel du COMPTE, pas sous `$OPSYS_HOME` : le core ne lit pas cette variable et la définition du service ne la
  porte pas. Avec l'`OPSYS_HOME` par défaut, les deux dossiers sont le même dossier d'instance.

Avant T0.7 lot 3, l'état du core était dans `~/.openclaw-opsys`. Ce module ne le déplace JAMAIS : le déplacement est
celui de Doctor, dans le core (`opsys doctor --non-interactive`, `core/src/infra/state-migrations.opsys-instance.ts`),
un seul mécanisme à tenir d'accord. `initialiser` REFUSE d'écrire tant que cet état est à l'ancien emplacement
(`disposition_du_profil_d_avant`) et dit quoi faire.

Ce que la commande fait, dans l'ordre :
1. refuse l'ancienne disposition (`$OPSYS_HOME/core`, d'avant T0.11-b) et l'ancien dossier du profil
   (`~/.openclaw-opsys`, d'avant T0.7 lot 3) avec la marche à suivre : rien n'est migré en silence ;
2. crée `$OPSYS_HOME` et le dossier d'état du core, accessibles à leur propriétaire seul (0700 ; sous Windows,
   ACL réduite à l'utilisateur et héritée par ce que le service y écrit, `restreindre_dossier`) ;
3. migre la base de l'instance (SQLite, `$OPSYS_HOME/opsys.db`) ;
4. pose `<état du core>/.env`, 0600 : les secrets qui manquent (jetons `OPSYS_MCP_JETON` et
   `OPSYS_CONTEXT_MCP_JETON` réservé au moteur de contexte, jeton du
   Gateway, une clé virtuelle par département) et les réglages fournis (`OPSYS_EMBEDDINGS_*`,
   `OPSYS_PASSERELLE_URL`). Les fournisseurs de modèles OpenClaw sont natifs par défaut ; LiteLLM n'est utilisé
   qu'avec le mode explicite `litellm` et une URL. Une URL historique seule ne change pas le mode. Une mise à jour
   d'instance existante ajoute le jeton de contexte s'il manque et conserve le `OPSYS_MCP_JETON` déjà configuré.
   Un secret présent n'est JAMAIS régénéré ; aucune valeur n'est
   rendue ni écrite dans une sortie ;
5. vérifie que le core peut être configuré. Sinon (paliers de modèles, service d'embeddings) : verdict
   `en_attente` qui dit quoi fournir, et RIEN d'autre n'est écrit. Fail-closed : aucune valeur inventée ;
6. génère la configuration du core (`opsys-metier openclaw configurer`), le bloc `gateway` du fichier racine
   (`opsys.json` ; l'`openclaw.json` d'une installation antérieure reste lu et n'est jamais renommé) s'il manque, et
   `opsys/metier.json` (le superviseur du core lance alors le moteur, PLAN T0.10).

`<état du core>/.env` est le fichier que le core lit lui-même au démarrage du Gateway, du service et de ses
commandes (`core/src/config/state-dir-dotenv.ts`) : `${OPSYS_MCP_JETON}` des fragments de configuration y est
résolu sans autre mécanisme.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from . import modeles, openclaw, stockage
from .departements import Departement, charger_departements
from .memoire.embeddings import ENV_CLE, ENV_LOCAL, ENV_MODELE, ENV_URL, ClientEmbeddings, ErreurEmbeddings

# Le profil du core et ses dossiers : recopiés de `core/src/config/opsys-instance.ts` (le module que lisent
# `resolveProfileStateDir`, `isDefaultInstallIdentity` et Doctor) ; `tests/test_instance.py` les relit dans le fork.
PROFIL_CORE = "opsys"
DOSSIER_INSTANCE = ".opsys"  # le dossier d'instance, sous le dossier personnel du compte
SOUS_DOSSIER_CORE = "core"  # l'état du core y loge : `~/.opsys/core`
# d'avant T0.7 lot 3 (installations faites depuis T0.11-b) : Doctor le déplace vers `~/.opsys/core`
ANCIEN_DOSSIER_PROFIL = ".openclaw-opsys"
NOM_CONFIG = openclaw.NOM_RACINE_INSTANCE  # `opsys.json` ; un `openclaw.json` qui existe reste lu (`fichier_config`)
NOM_CONFIG_ANCIEN = openclaw.NOM_RACINE
ANCIEN_SOUS_DOSSIER_CORE = "core"  # disposition d'avant T0.11-b : `$OPSYS_HOME/core` (jamais migrée en silence)
# Variables du core qui sortiraient l'état du dossier canonique ou changeraient l'identité du service
# (`isDefaultInstallIdentity`, `resolveGatewayNativeServiceIdentityConflict`) : les commandes installées les écartent.
VARIABLES_ECARTEES = (
    "OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH", "OPENCLAW_HOME", "OPENCLAW_PROFILE",
    "OPENCLAW_LAUNCHD_LABEL", "OPENCLAW_SYSTEMD_UNIT", "OPENCLAW_WINDOWS_TASK_NAME",
)
NOM_ENV = ".env"
ENV_JETON_MCP = "OPSYS_MCP_JETON"  # core/src/gateway/opsys-metier-config.ts::OPSYS_MCP_TOKEN_ENV
ENV_JETON_CONTEXTE = "OPSYS_CONTEXT_MCP_JETON"
ENV_JETON_GATEWAY = "OPENCLAW_GATEWAY_TOKEN"
ENV_PASSERELLE = "OPSYS_PASSERELLE_URL"
ENV_MODE_FOURNISSEUR = "OPSYS_MODE_FOURNISSEUR"
ENV_BASE_URL = stockage.ENV_URL
PORT_GATEWAY_DEFAUT = 18789  # core/src/config/paths.ts::DEFAULT_GATEWAY_PORT
PORT_MOTEUR_DEFAUT = 8765  # core/src/gateway/opsys-metier-config.ts::DEFAULT_PORT
CLE_COMMANDE_CLI = "commande_cli"  # core/src/cli/opsys-metier-cli.ts::OPSYS_METIER_CLI_COMMAND_KEY
HOTE_LOCAL = "127.0.0.1"
CODE_EN_ATTENTE = 3  # code de sortie de `opsys-metier instance initialiser` : installé, mais il manque une décision

# Les seuls réglages que l'installateur accepte de l'environnement et écrit dans `.env`.
REGLAGES_ACCEPTES = (ENV_URL, ENV_MODELE, ENV_CLE, ENV_LOCAL, ENV_PASSERELLE, ENV_MODE_FOURNISSEUR)

# Alphabet d'une valeur de `.env` : sans espace, guillemet, `$`, `#`, barre oblique inverse ni saut de ligne.
# Écrite ainsi, une ligne est lue de la même façon par le core (dotenv), par les enveloppes `opsys-metier` (bash, cmd)
# et par `lire_env`, sans aucune règle de guillemets.
_VALEUR_PERMISE = re.compile(r"^[A-Za-z0-9._:/@%+=,~-]{1,512}$")
_AFFECTATION = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
_ENTETE_ENV = (
    "# Réglages et secrets de l'instance OPSYS. Géré par `opsys-metier instance initialiser`.",
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
    dossier_core: Path
    mode_fournisseur: str

    def en_json(self) -> dict[str, Any]:
        return {
            "etat": self.etat,
            "revision": self.revision,
            "manque": list(self.manque),
            "avertissements": list(self.avertissements),
            "port_gateway": self.port_gateway,
            "port_moteur": self.port_moteur,
            "dossier_core": str(self.dossier_core),
            "mode_fournisseur": self.mode_fournisseur,
            "env": {
                "chemin": str(self.env.chemin),
                "secrets_generes": list(self.env.generees),
                "secrets_conserves": list(self.env.conservees),
                "reglages_ecrits": list(self.env.reglees),
            },
            "fichiers": dict(self.fichiers),
        }


# -- dossiers ----------------------------------------------------------------------------------------------------
def _dossier_personnel(environ: Mapping[str, str] | None) -> Path:
    """Le dossier personnel du COMPTE, lu comme le fait le core (`resolveEffectiveHomeDir`,
    `core/packages/normalization-core/src/home-dir.ts`) : HOME, puis USERPROFILE, puis le dossier de l'utilisateur du
    système. OPENCLAW_HOME est écarté : les commandes installées l'écartent aussi, et avec lui le core refuserait
    tout service.

    `environ=None` : l'environnement du processus, avec le repli sur le dossier de l'utilisateur du système. Un
    `environ` fourni est pris tel quel ; sans HOME ni USERPROFILE, c'est un refus, jamais un dossier deviné.
    """
    if environ is None:
        environ = os.environ
        repli = str(Path.home())
    else:
        repli = ""
    base = ""
    for nom in ("HOME", "USERPROFILE"):
        valeur = environ.get(nom, "").strip()
        if valeur and valeur not in ("undefined", "null"):  # `normalizeHomeDirValue` du core
            base = valeur
            break
    base = base or repli
    if not base:
        raise ErreurInstance(
            "HOME et USERPROFILE sont absents : le dossier d'état du core (dossier personnel + "
            f"{DOSSIER_INSTANCE}/{SOUS_DOSSIER_CORE}) ne peut pas être déterminé. Définissez HOME, puis relancez."
        )
    return Path(os.path.abspath(base))


def dossier_core(environ: Mapping[str, str] | None = None) -> Path:
    """Le dossier d'état du profil `opsys` du core : `<dossier personnel>/.opsys/core`.

    Le core n'installe un service que si son état est à cet endroit (`isDefaultInstallIdentity`,
    `core/src/config/paths.ts`) ; la règle est `resolveOpsysProfileStateDir` (`core/src/config/opsys-instance.ts`),
    que lit `resolveProfileStateDir` (`core/src/cli/profile-utils.ts`). Le core garde l'ancien dossier
    (`ancien_dossier_profil`) tant qu'il est seul à porter un état ; ce module n'a pas ce repli : `initialiser`
    refuse plutôt que d'écrire à côté (`disposition_du_profil_d_avant`).

    `environ=None` : l'environnement du processus (voir `_dossier_personnel`).
    """
    return _dossier_personnel(environ) / DOSSIER_INSTANCE / SOUS_DOSSIER_CORE


def ancien_dossier_profil(environ: Mapping[str, str] | None = None) -> Path:
    """`<dossier personnel>/.openclaw-opsys` : où le core rangeait l'état du profil `opsys` avant T0.7 lot 3."""
    return _dossier_personnel(environ) / ANCIEN_DOSSIER_PROFIL


def chemin_env(etat_core: Path) -> Path:
    return etat_core / NOM_ENV


def fichier_config(etat_core: Path) -> Path:
    """Le fichier de configuration du core dans `etat_core` : `opsys.json` s'il existe, sinon l'`openclaw.json` d'une
    installation antérieure, sinon `opsys.json`. Jamais renommé ici : le service installé peut le nommer. C'est la règle
    du core (`resolveOpsysConfigPath`, `core/src/config/opsys-instance.ts`)."""
    return openclaw.fichier_racine(etat_core, nom_creation=NOM_CONFIG)


def ancienne_disposition(home: Path, etat_core: Path) -> Path | None:
    """`$OPSYS_HOME/core` s'il porte encore l'état du core posé avant T0.11-b, sinon `None`.

    Un dossier vide (créé par une installation interrompue) ou qui EST le dossier d'état du core n'est pas l'ancienne
    disposition : avec l'`OPSYS_HOME` par défaut, `~/.opsys/core` est aujourd'hui le dossier canonique lui-même.
    """
    ancien = home / ANCIEN_SOUS_DOSSIER_CORE
    if not ancien.is_dir():
        return None
    if ancien.resolve() == etat_core.resolve() or not any(ancien.iterdir()):
        return None
    return ancien


def _refuser_ancienne_disposition(ancien: Path, etat_core: Path) -> ErreurInstance:
    return ErreurInstance(
        f"ancienne disposition détectée : {ancien} porte l'état du core posé par une version antérieure de "
        f"l'installateur. Le core lit maintenant son état dans {etat_core} (profil « {PROFIL_CORE} » : le seul dossier "
        "pour lequel il installe un service). Rien n'est migré en silence et rien n'a été modifié. Deux issues, "
        "le service arrêté d'abord (`opsys gateway stop`, s'il tourne). "
        f"(1) Garder les secrets et les appareils appairés : déplacez {ancien} vers {etat_core} (`mv` ; "
        "`Move-Item` sous Windows), à condition que ce dernier n'existe pas encore, puis relancez. "
        f"(2) Repartir à neuf (nouveaux secrets, appareils à réappairer) : renommez {ancien} en {ancien}.ancien, puis "
        "relancez. Le dossier mis de côté contient des secrets en clair : le détruire est une décision humaine."
    )


def _porte_un_etat(dossier: Path) -> bool:
    """Le dossier contient quelque chose. Illisible : il compte comme un état, on ne décide pas à la place du core."""
    try:
        return any(dossier.iterdir())
    except OSError:
        return True


def disposition_du_profil_d_avant(etat_core: Path, ancien: Path) -> str | None:
    """Ce que l'ancien dossier du profil (`~/.openclaw-opsys`, installations d'avant T0.7 lot 3) demande, ou `None`.

    Même classement que Doctor (`core/src/infra/state-migrations.opsys-instance.ts`), pour que le refus d'ici et la
    migration de là-bas parlent de la même situation :
    - `None` : rien à faire. Il n'existe pas, il est vide (Doctor le retirera), ou c'est le lien (jonction sous Windows)
      que Doctor a laissé vers `etat_core` ;
    - `"a_migrer"` : il porte un état et `etat_core` n'en porte pas : Doctor le déplace ;
    - `"conflit"` : les deux portent un état : aucune décision automatique, jamais de fusion ;
    - `"autre"` : c'est un fichier, ou un lien vers un autre dossier : ni le core ni ce module n'y touchent.

    Un lien se reconnaît à ce que son chemin résolu diffère du chemin résolu de son dossier parent suivi de son nom :
    vrai pour un lien symbolique comme pour une jonction, et sans effet d'un préfixe qui serait lui-même un lien
    (`/tmp`, macOS).
    """
    if not os.path.lexists(ancien):
        return None
    cible = ancien.resolve()
    if cible != ancien.parent.resolve() / ancien.name:
        return None if cible == etat_core.resolve() else "autre"
    if not ancien.is_dir():
        return "autre"
    if not _porte_un_etat(ancien):
        return None
    if etat_core.exists() and (not etat_core.is_dir() or _porte_un_etat(etat_core)):
        return "conflit"
    return "a_migrer"


def _refuser_profil_d_avant(disposition: str, ancien: Path, etat_core: Path) -> ErreurInstance:
    if disposition == "a_migrer":
        return ErreurInstance(
            f"ancien emplacement détecté : {ancien} porte l'état du core posé par une installation d'avant "
            f"T0.7 lot 3 ; le core le lit maintenant dans {etat_core}. Rien n'a été modifié, et cette commande ne le "
            "déplace pas : "
            "le déplacement est celui de Doctor, dans le core. Dans l'ordre : "
            "(1) arrêtez le service (`opsys gateway stop` ; sous Windows c'est indispensable, des fichiers ouverts "
            "empêchent le déplacement) ; "
            f"(2) `opsys doctor --non-interactive` déplace {ancien} vers {etat_core} (un seul renommage : rien n'est "
            "copié ni supprimé) et laisse un lien à l'ancien chemin ; "
            "(3) relancez cette commande, ou l'installateur, qui réinstalle aussi le service vers le nouvel "
            "emplacement. "
            "Si `opsys` est encore le moteur (installation d'avant T0.7 lot 2), lancez `openclaw` à sa place."
        )
    if disposition == "conflit":
        return ErreurInstance(
            f"ancien emplacement en conflit : {ancien} (état du core d'une installation d'avant T0.7 lot 3) et "
            f"{etat_core} portent chacun un état. Rien n'a été modifié, fusionné ni supprimé : choisir lequel garder "
            "est une décision humaine. Le service arrêté d'abord (`opsys gateway stop`) : "
            f"pour garder l'état neuf, renommez {ancien} en {ancien}.old ; "
            f"pour garder l'ancien (secrets, appareils appairés), renommez {etat_core} en {etat_core}.old, puis "
            "`opsys doctor --non-interactive` déplace l'ancien. Relancez ensuite. "
            "Le dossier mis de côté contient des secrets en clair : le détruire est une décision humaine."
        )
    return ErreurInstance(
        f"ancien emplacement inattendu : {ancien} est un fichier, ou un lien vers un autre dossier que {etat_core}. "
        "Le core n'y touche pas, et cette commande non plus : rien n'a été modifié. Regardez ce que c'est ; "
        f"s'il ne sert plus, renommez-le en {ancien}.old, puis relancez."
    )


def _preparer_dossiers(dossiers: Sequence[Path]) -> list[str]:
    """Crée chacun de `dossiers`, dans l'ordre, pour son propriétaire seul. Un dossier existant n'est jamais
    modifié : s'il est ouvert à d'autres comptes, on le signale (renseignements personnels, Loi 25)."""
    avertissements: list[str] = []
    for dossier in dossiers:
        if dossier.exists():
            if os.name != "nt" and stat.S_IMODE(dossier.stat().st_mode) & 0o077:
                avertissements.append(
                    f"{dossier} est accessible à d'autres comptes du poste : `chmod 700 {dossier}`."
                )
            continue
        dossier.mkdir(mode=0o700, parents=True)
        restreindre_dossier(dossier)  # le umask a pu retirer des droits, jamais en ajouter ; ceci fixe le résultat
    return avertissements


def _sous_windows() -> bool:
    return os.name == "nt"


_SCRIPT_ACL_WINDOWS = r"""
$ErrorActionPreference = 'Stop'
try {
    # ACL commands must come from this runtime, never a module path inherited from another shell.
    $env:PSModulePath = [System.IO.Path]::Combine($PSHOME, 'Modules')
    $securityModule = [System.IO.Path]::Combine(
        $PSHOME, 'Modules', 'Microsoft.PowerShell.Security', 'Microsoft.PowerShell.Security.psd1'
    )
    Import-Module -Name $securityModule -ErrorAction Stop
    $path = $env:OPSYS_INSTANCE_ACL_PATH
    if ([string]::IsNullOrWhiteSpace($path)) { throw 'chemin ACL absent' }
    $isDirectory = $env:OPSYS_INSTANCE_ACL_DIRECTORY -eq '1'
    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    if ($null -eq $currentSid) { throw 'SID du compte Windows courant absent' }

    $acl = Get-Acl -LiteralPath $path
    $ownerBefore = $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
    $explicitRules = @($acl.GetAccessRules($true, $false, [System.Security.Principal.SecurityIdentifier]))
    # Build a complete private DACL in memory, then apply it with one Set-Acl operation.
    # No /reset or intermediate broad ACL is ever written to the file or directory.
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in $explicitRules) { [void]$acl.RemoveAccessRuleSpecific($rule) }

    $rights = [System.Security.AccessControl.FileSystemRights]::FullControl
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    if ($isDirectory) {
        $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
            [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $currentSid, $rights, $inheritance,
            [System.Security.AccessControl.PropagationFlags]::None, $allow
        )
    } else {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new($currentSid, $rights, $allow)
    }
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $path -AclObject $acl

    $verified = Get-Acl -LiteralPath $path
    $verifiedRules = @($verified.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
    if (-not $verified.AreAccessRulesProtected -or $verifiedRules.Count -ne 1) {
        throw 'DACL appliquée différente de la règle privée attendue'
    }
    $applied = $verifiedRules[0]
    $full = [long][System.Security.AccessControl.FileSystemRights]::FullControl
    if ($applied.IdentityReference.Value -ne $currentSid.Value -or
        $applied.AccessControlType -ne $allow -or $applied.IsInherited -or
        (([long]$applied.FileSystemRights -band $full) -ne $full)) {
        throw 'ACE Allow FullControl du SID courant absente ou incorrecte'
    }
    if ($isDirectory -and ([int]$applied.InheritanceFlags -ne 3)) {
        throw 'ACE du dossier sans héritage OI/CI'
    }
    if ($verified.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $ownerBefore) {
        throw 'le propriétaire du chemin a changé'
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
exit 0
"""


def _restreindre_acl_windows(chemin: Path, *, dossier: bool) -> None:
    """Remplace la DACL en une opération par une règle FullControl au SID courant."""
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        raise ErreurInstance(f"PowerShell est absent : impossible de restreindre l'accès à {chemin}.")
    # A child shell must load its own built-in modules. A PS7 parent's PSModulePath
    # can otherwise make Windows PowerShell 5 import incompatible PS7 assemblies.
    environnement = {nom: valeur for nom, valeur in os.environ.items() if nom.casefold() != "psmodulepath"}
    environnement["OPSYS_INSTANCE_ACL_PATH"] = str(chemin)
    environnement["OPSYS_INSTANCE_ACL_DIRECTORY"] = "1" if dossier else "0"
    try:
        resultat = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", _SCRIPT_ACL_WINDOWS],
            env=environnement,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as erreur:
        raise ErreurInstance(f"PowerShell n'a pas pu restreindre l'accès à {chemin} : {erreur}") from erreur
    if resultat.returncode != 0:
        raise ErreurInstance(
            f"PowerShell a refusé de restreindre l'accès à {chemin} : {resultat.stderr.strip()}"
        )


def restreindre_acces(chemin: Path) -> None:
    """Le fichier n'est lisible que par son propriétaire (0600 ; ACL réduite à l'utilisateur sous Windows).

    Sous Windows, `os.chmod` ne touche pas les droits : la DACL peut contenir des ACE explicites en plus des droits
    hérités. PowerShell construit puis applique en une opération une DACL protégée qui n'accorde FullControl qu'au SID
    courant. Sert à `.env` (secrets) et aux archives d'export (renseignements personnels).
    """
    if _sous_windows():
        _restreindre_acl_windows(chemin, dossier=False)
        return
    os.chmod(chemin, 0o600)


def restreindre_dossier(chemin: Path) -> None:
    """Le dossier n'est accessible qu'à son propriétaire (0700 ; ACL réduite à l'utilisateur sous Windows, héritée par
    tout ce que le dossier contiendra ensuite). Sert à l'état du core, où le service écrit ses propres fichiers : le
    script de la tâche planifiée (`gateway.cmd`) porte les valeurs de `.env` (l'environnement durable du service,
    `core/src/commands/daemon-install-helpers.ts`), et n'a donc pas d'ACL propre."""
    if _sous_windows():
        _restreindre_acl_windows(chemin, dossier=True)
        return
    os.chmod(chemin, 0o700)


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
        restreindre_acces(fichier_temporaire)
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
        restreindre_acces(chemin)  # un fichier posé à la main avec des droits trop larges est resserré
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
    """Ajoute au fichier de configuration du core (`fichier_config` : `opsys.json`, ou l'`openclaw.json` d'une
    installation antérieure) le bloc `gateway` que `opsys-metier openclaw configurer` n'écrit pas, s'il manque.

    Rend (bloc ajouté, port effectif). Un bloc existant n'est jamais modifié : c'est celui de l'opérateur.
    Le bloc : mode local, boucle locale seulement, authentification par jeton (`OPENCLAW_GATEWAY_TOKEN`, lu dans
    `.env`) et approbation explicite des appareils, même venus de 127.0.0.1 (le trajet que `tests/e2e_core`
    exerce).
    """
    racine = fichier_config(dossier)
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


def ecrire_metier(etat_core: Path, *, home: Path, source: Path, python: Path, port: int) -> Path:
    """`<état du core>/opsys/metier.json` : active le superviseur du moteur (`core/src/gateway/opsys-metier-config.ts`).

    La commande est l'interpréteur de l'environnement de l'installation, en chemin absolu : aucune résolution de
    dépendances ni accès réseau au démarrage, et `uv` n'a pas à être dans le PATH du service. Le fichier est celui
    de l'installateur : ses clés sont réécrites à chaque exécution, les autres clés sont conservées.

    `commande_cli` (T0.7 lot 2) est la ligne de commande de la CLI du moteur, celle que `opsys metier <commande>` lance
    en lui ajoutant les arguments (`core/src/cli/opsys-metier-cli.ts`) : le même interpréteur, `-m opsys.cli`. C'est
    le seul endroit où le core apprend où est le moteur ; il n'en devine aucun autre.
    """
    chemin = etat_core / "opsys" / "metier.json"
    metier = _lire_objet_json(chemin) if chemin.is_file() else {}
    env = metier.get("env") if isinstance(metier.get("env"), dict) else {}
    metier.update({
        "actif": True,
        "dossier": str(source),
        "hote": HOTE_LOCAL,
        "port": port,
        "commande": [str(python), "-m", "opsys.serveur_mcp", "--http", "--hote", HOTE_LOCAL, "--port", str(port)],
        CLE_COMMANDE_CLI: [str(python), "-m", "opsys.cli"],
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
    """Ce que `opsys-metier openclaw configurer` exige et que l'opérateur n'a pas encore décidé. Rien n'est inventé."""
    manque: list[str] = []
    try:
        paliers = modeles.charger_paliers()
    except ValueError as erreur:
        raise ErreurInstance(f"paliers.yaml est invalide : {erreur}") from erreur
    absents = sorted({dep.modeles["defaut"] for dep in departements.values()} - set(paliers))
    if absents:
        manque.append(
            f"paliers de modèles à choisir ({', '.join(absents)}) : "
            "`opsys-metier paliers definir <palier> --provider <fournisseur> --model <modèle>`, "
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
    mode_fournisseur: str | None = None,
    url_passerelle: str | None = None,
    environ: Mapping[str, str] | None = None,
    departements: Mapping[str, Departement] | None = None,
    etat_core: Path | None = None,
    ancien_profil: Path | None = None,
) -> ResultatInitialisation:
    """Prépare l'instance de `home`. Voir l'en-tête du module. Lève `ErreurInstance` quand rien ne peut continuer.

    `etat_core` : dossier d'état du core, par défaut celui du profil `opsys` (`dossier_core`). Les tests le fixent.
    `ancien_profil` : l'ancien dossier du profil (`ancien_dossier_profil`), dont l'état doit avoir été déplacé par
    Doctor avant que cette commande écrive quoi que ce soit. Par défaut, celui du même dossier personnel que
    `etat_core` quand ce dernier est le défaut ; un `etat_core` fourni ne cherche rien hors de lui, sauf si l'appelant
    donne `ancien_profil`.
    """
    environnement_du_processus = environ is None
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

    dossiers = [home, etat_core]
    etat_core_par_defaut = etat_core is None
    if etat_core is None:
        base = None if environnement_du_processus else environ
        etat_core = dossier_core(base)
        if ancien_profil is None:
            ancien_profil = ancien_dossier_profil(base)
        # `mkdir(parents=True)` ne donne le mode demandé qu'au dernier dossier : le dossier d'instance, qui n'est pas
        # `home` quand OPSYS_HOME est ailleurs, est créé lui aussi pour son propriétaire seul.
        dossiers = [home, etat_core.parent, etat_core]
    ancien = ancienne_disposition(home, etat_core)
    if ancien is not None:
        raise _refuser_ancienne_disposition(ancien, etat_core)
    if ancien_profil is not None:
        etat_d_avant = disposition_du_profil_d_avant(etat_core, ancien_profil)
        if etat_d_avant is not None:
            raise _refuser_profil_d_avant(etat_d_avant, ancien_profil, etat_core)

    chemin = chemin_env(etat_core)
    env_existant = lire_env(chemin)
    mode_explicitement_fourni = mode_fournisseur is not None or ENV_MODE_FOURNISSEUR in environ
    mode_effectif = (
        mode_fournisseur
        or environ.get(ENV_MODE_FOURNISSEUR)
        or env_existant.get(ENV_MODE_FOURNISSEUR)
        or "natif"
    ).strip().lower()
    if mode_effectif not in {"natif", "litellm"}:
        raise ErreurInstance(f"{ENV_MODE_FOURNISSEUR} doit valoir 'natif' ou 'litellm'.")
    passerelle_existante = env_existant.get(ENV_PASSERELLE, "").strip()
    passerelle_fournie = (url_passerelle or environ.get(ENV_PASSERELLE, "")).strip()
    url_explicite_sans_mode = bool(url_passerelle or environ.get(ENV_PASSERELLE, "").strip())
    if url_explicite_sans_mode and mode_effectif != "litellm":
        raise ErreurInstance(f"{ENV_PASSERELLE} est réservée à --mode-fournisseur litellm.")
    if mode_effectif == "litellm" and not (passerelle_fournie or passerelle_existante):
        raise ErreurInstance(f"le mode litellm exige une URL explicite avec --url-passerelle ou {ENV_PASSERELLE}.")
    if mode_effectif == "litellm":
        valeur_passerelle = passerelle_fournie or passerelle_existante
        _valider_reglage(ENV_PASSERELLE, valeur_passerelle)
        if not valeur_passerelle.startswith(("http://", "https://")):
            raise ErreurInstance(f"{ENV_PASSERELLE} doit être une URL http(s) valide.")
    # Un OPSYS_PASSERELLE_URL seul dans l'ancien .env n'active jamais LiteLLM : il reste lisible pour un choix
    # explicite ultérieur, tandis que le générateur natif reçoit uniquement les fournisseurs de paliers.
    if mode_effectif == "litellm":
        reglages_modele = {ENV_MODE_FOURNISSEUR: "litellm", ENV_PASSERELLE: passerelle_fournie or passerelle_existante}
    else:
        reglages_modele = ({ENV_MODE_FOURNISSEUR: "natif"} if mode_explicitement_fourni else {})
    avertissements = _preparer_dossiers(list(dict.fromkeys(dossiers)))
    if etat_core_par_defaut and home.resolve() != etat_core.parent.resolve():
        avertissements.append(
            f"OPSYS_HOME est {home} : les données métier (base, paliers) y sont, mais l'état du core (secrets, "
            f"configuration, service) reste dans {etat_core}, où le core le lit : il ne lit pas OPSYS_HOME."
        )
    ecartees = [nom for nom in VARIABLES_ECARTEES if environ.get(nom, "").strip()]
    if ecartees:
        avertissements.append(
            f"{', '.join(ecartees)} : défini dans l'environnement, ignoré. Le core lit son état dans {etat_core} "
            "(profil « opsys ») ; les commandes installées écartent ces variables."
        )
    revision = stockage.migrer()
    deps = dict(departements) if departements is not None else charger_departements()

    reglages = {nom: environ[nom].strip() for nom in REGLAGES_ACCEPTES if environ.get(nom, "").strip()}
    reglages.update(reglages_modele)
    secrets_attendus = [
        ENV_JETON_MCP, ENV_JETON_CONTEXTE, ENV_JETON_GATEWAY,
        *(openclaw._variable_cle(dep) for dep in deps.values()),
    ]
    rapport = assurer_env(chemin, secrets_attendus, reglages)
    env = lire_env(chemin)

    manque, paliers = _ce_qui_manque(deps, env)
    port_effectif_moteur = port_moteur or PORT_MOTEUR_DEFAUT
    fichiers = {"env": str(chemin)}
    if manque:
        return ResultatInitialisation(
            "en_attente", revision, tuple(manque), tuple(avertissements), rapport, fichiers,
            port_gateway or PORT_GATEWAY_DEFAUT, port_effectif_moteur, etat_core, mode_effectif,
        )

    openclaw.generer(
        deps, etat_core, paliers, url_mcp=f"http://{HOTE_LOCAL}:{port_effectif_moteur}/mcp",
        # Accord limité au serveur lancé par ce superviseur, jamais à une URL HTTP fournie par un tiers.
        origine_http_mcp_autorisee=(
            f"http://{HOTE_LOCAL}" + (f":{port_effectif_moteur}" if port_effectif_moteur != 80 else "")
        ),
        url_passerelle=(passerelle_fournie or passerelle_existante) if mode_effectif == "litellm" else None,
        mode_fournisseur=mode_effectif, environ=env,
    )
    openclaw.racine_si_absente(etat_core, nom_creation=NOM_CONFIG)
    _, port_effectif_gateway = completer_racine(etat_core, port_gateway)
    config = fichier_config(etat_core)
    if port_gateway and port_gateway != port_effectif_gateway:
        avertissements.append(
            f"gateway.port vaut {port_effectif_gateway} dans {config.name} : le port {port_gateway} demandé est ignoré "
            f"(`opsys config set gateway.port {port_gateway}` pour le changer)."
        )
    metier = ecrire_metier(etat_core, home=home, source=source, python=python, port=port_effectif_moteur)
    fichiers.update({"openclaw": str(config), "metier": str(metier)})
    return ResultatInitialisation(
        "pret", revision, (), tuple(avertissements), rapport, fichiers, port_effectif_gateway, port_effectif_moteur,
        etat_core, mode_effectif,
    )
