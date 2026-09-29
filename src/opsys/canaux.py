"""Canaux du core qu'un département reçoit du public (PLAN T2.1-a).

Un département déclare `canaux: [sms]` dans son manifeste. Le socle en tire la configuration d'OPSYS-CORE
(`openclaw.generer`) : le canal de l'extension du fork, sa liaison à l'agent du département, la portée des
sessions, l'interdiction d'une réponse automatique au client et une boîte à outils fermée pour l'agent.
Conception et chemin d'un message : `docs/departements/M1-canaux.md`.

Règles, toutes pour un canal où n'importe quel correspondant peut écrire :

- **Désactivé par défaut.** Un canal n'est actif que si TOUTES ses variables d'environnement sont fournies :
  les identifiants du fournisseur (secrets de production, T3, jamais dans git) et l'attestation écrite que le
  propriétaire a validé les politiques applicables. La configuration ne porte que des références `${...}`.
- **Aucune réponse automatique.** Le core envoie par défaut le texte final de l'agent au correspondant. Deux
  verrous l'en empêchent : `session.sendPolicy` (refus du canal) et le retrait de l'outil `message` de l'agent.
  Tout message vers un client passe par un outil du département, donc par la file d'approbation (T3).
- **Une session par correspondant** (`per-channel-peer`) : deux clients ne partagent jamais une session, et la
  session d'un client peut être liée à son affaire (M10, `m10_lier_session_affaire`).
- **Un agent aux outils fermés.** Il n'appelle que les outils de son propre serveur MCP.

Ce module est pur : il lit l'environnement qu'on lui passe et ne connaît ni la base ni le réseau. Il ne dépend
pas de `opsys.departements` à l'import (un manifeste le consulte pour valider ses `canaux`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .departements import Departement

# Outils du core qui envoient un message au correspondant : jamais donnés à un agent qui reçoit le public.
OUTILS_MESSAGERIE_REFUSES = ("message", "group:messaging")
CLE_SESSION_PAR_CORRESPONDANT = "per-channel-peer"
# Clés de `openclaw.json` que les fragments d'un canal alimentent : `channels` (le canal), `bindings` (l'agent),
# `session` (la portée des sessions ET le refus de réponse automatique). Un canal n'est jamais actif si l'une manque.
CLES_RACINE = ("channels", "bindings", "session")

_VARIABLE = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class Canal:
    """Un canal du core que le socle sait configurer pour un département.

    `identifiants` : clé de configuration du canal -> variable d'environnement qui porte sa valeur.
    `validation` : variable qui atteste la validation écrite des politiques applicables (SMS, photos) ;
    sa valeur, la référence de cette validation, n'est jamais écrite dans la configuration.
    `outil_accueil` : l'outil du département que l'agent appelle pour chaque message reçu.
    `session_par_correspondant` : la clé de session d'un client se compose (agent, canal, correspondant).
    """

    id: str
    extension: str
    identifiants: Mapping[str, str]
    validation: str
    outil_accueil: str
    session_par_correspondant: bool

    def __post_init__(self) -> None:
        for variable in (*self.identifiants.values(), self.validation):
            if not _VARIABLE.match(variable):
                raise ValueError(f"canal {self.id} : nom de variable d'environnement invalide {variable!r}")

    @property
    def variables(self) -> tuple[str, ...]:
        """Toutes les variables exigées pour activer le canal, dans l'ordre de la configuration."""
        return (*self.identifiants.values(), self.validation)


CANAL_SMS = Canal(
    id="sms",
    extension="sms",
    identifiants={
        "accountSid": "OPSYS_SMS_COMPTE_SID",
        "authToken": "OPSYS_SMS_JETON",
        "fromNumber": "OPSYS_SMS_NUMERO",
        "publicWebhookUrl": "OPSYS_SMS_URL_PUBLIQUE",
    },
    validation="OPSYS_SMS_POLITIQUES_VALIDEES",
    outil_accueil="m1_recevoir_message_canal",
    session_par_correspondant=True,
)

CANAUX: Mapping[str, Canal] = {CANAL_SMS.id: CANAL_SMS}


def ids_canaux() -> tuple[str, ...]:
    return tuple(sorted(CANAUX))


def canal(ident: str) -> Canal:
    try:
        return CANAUX[ident]
    except KeyError:
        raise ValueError(f"canal inconnu {ident!r} (canaux connus : {', '.join(ids_canaux())})") from None


def manquantes(un_canal: Canal, environ: Mapping[str, str]) -> tuple[str, ...]:
    """Variables exigées que l'environnement ne fournit pas (absente, vide ou faite d'espaces)."""
    return tuple(v for v in un_canal.variables if not str(environ.get(v, "")).strip())


def est_actif(un_canal: Canal, environ: Mapping[str, str]) -> bool:
    return not manquantes(un_canal, environ)


def cle_session(agent_id: str, ident_canal: str, correspondant: str) -> str:
    """Clé de session qu'OPSYS-CORE compose pour un correspondant en `per-channel-peer`.

    Même forme que `buildAgentPeerSessionKey` (`core/src/routing/session-key.ts`, cas `per-channel-peer`) :
    `agent:<agent>:<canal>:direct:<correspondant>`, correspondant en minuscules. C'est la clé que M10 lie à une
    affaire. Un canal dont la session n'est pas composée par correspondant (courriel : une session par message)
    n'en a pas.
    """
    un_canal = canal(ident_canal)
    if not un_canal.session_par_correspondant:
        raise ValueError(f"le canal {ident_canal} n'a pas de session par correspondant")
    pair = correspondant.strip().lower()
    if not pair or re.search(r"[\s\x00-\x1f\x7f]", pair):
        raise ValueError("correspondant invalide : non vide, sans espace ni caractère de contrôle")
    return f"agent:{agent_id.strip().lower()}:{un_canal.id}:direct:{pair}"


def reference(variable: str) -> str:
    """Référence `${VARIABLE}` : la seule forme sous laquelle un identifiant entre dans la configuration."""
    return "${" + variable + "}"


def fragment_canal(un_canal: Canal, actif: bool) -> dict[str, Any]:
    """Valeur de `channels.<id>` (schéma : `core/extensions/sms/src/config-schema.ts`).

    `dmPolicy: "open"` avec `allowFrom: ["*"]` : un client inconnu doit pouvoir écrire, et l'appairage
    (`pairing`, le défaut de l'extension) enverrait un message automatique à un inconnu. `configWrites: false`
    : le canal ne modifie jamais la configuration.
    """
    if un_canal.id != CANAL_SMS.id:
        raise ValueError(f"canal {un_canal.id} : aucune configuration connue")
    return {
        "enabled": actif,
        "dmPolicy": "open",
        "allowFrom": ["*"],
        "configWrites": False,
        **{cle: reference(variable) for cle, variable in un_canal.identifiants.items()},
    }


def liaison(agent_id: str, un_canal: Canal) -> dict[str, Any]:
    """Entrée de `bindings[]` : ce canal parle à cet agent, une session par correspondant.

    `match.accountId` absent : seul le compte par défaut du canal. Un autre compte n'a pas de liaison, et le
    core refuse alors de choisir un agent (l'agent par défaut n'existe pas : `agents.ownership = "explicit"`).
    """
    return {
        "type": "route",
        "agentId": agent_id,
        "comment": f"OPSYS : le canal {un_canal.id} entre par {agent_id} (T2.1-a) ; une session par correspondant",
        "match": {"channel": un_canal.id},
        "session": {"dmScope": CLE_SESSION_PAR_CORRESPONDANT},
    }


def regles_d_envoi(agent_id: str, un_canal: Canal) -> list[dict[str, Any]]:
    """Refus d'envoi automatique pour ce canal : deux règles, la seconde ne dépend pas de la lecture du canal."""
    return [
        {"action": "deny", "match": {"channel": un_canal.id}},
        {"action": "deny", "match": {"rawKeyPrefix": f"agent:{agent_id}:{un_canal.id}:"}},
    ]


@dataclass(frozen=True)
class ConfigurationCanaux:
    """Ce que les départements à canaux ajoutent à la configuration du core."""

    canaux: dict[str, Any]  # channels
    liaisons: list[dict[str, Any]]  # bindings
    session: dict[str, Any]  # session
    plugins: dict[str, Any]  # plugins.entries (activation des extensions de canal)
    agents_exposes: tuple[str, ...]  # agents dont la boîte à outils est fermée
    etat: list[dict[str, Any]]  # ce que `opsys-metier verifier` et `opsys-metier openclaw configurer` affichent


def configuration(
    departements: Mapping[str, Departement],
    environ: Mapping[str, str],
    includes_manquants: Sequence[str] = (),
) -> ConfigurationCanaux:
    """Configuration des canaux de tous les départements qui en déclarent ; vide si aucun n'en déclare.

    `includes_manquants` : les clés de `CLES_RACINE` qu'un `openclaw.json` existant n'inclut pas. Tant qu'il en
    manque une, aucun canal n'est actif, même avec toutes ses variables : un canal dont le refus de réponse
    automatique (`session.sendPolicy`) ne serait pas lu par le core répondrait aux clients sans approbation.
    """
    channels: dict[str, Any] = {}
    liaisons: list[dict[str, Any]] = []
    regles: list[dict[str, Any]] = []
    plugins: dict[str, Any] = {}
    exposes: list[str] = []
    etat: list[dict[str, Any]] = []
    proprietaire: dict[str, str] = {}
    for dep in departements.values():
        for ident in dep.canaux:
            un_canal = canal(ident)
            if ident in proprietaire:
                raise ValueError(
                    f"le canal {ident} est déclaré par {proprietaire[ident]} et par {dep.id} : "
                    "un canal entre par un seul agent"
                )
            proprietaire[ident] = dep.id
            absentes = manquantes(un_canal, environ)
            actif = not absentes and not includes_manquants
            channels[ident] = fragment_canal(un_canal, actif)
            liaisons.append(liaison(dep.id, un_canal))
            regles.extend(regles_d_envoi(dep.id, un_canal))
            plugins[un_canal.extension] = {"enabled": actif}
            if dep.id not in exposes:
                exposes.append(dep.id)
            etat.append({
                "departement": dep.id,
                "canal": ident,
                "actif": actif,
                "variables_manquantes": list(absentes),
                "includes_manquants": list(includes_manquants),
            })
    session: dict[str, Any] = {}
    if regles:
        session = {
            "dmScope": CLE_SESSION_PAR_CORRESPONDANT,
            "sendPolicy": {"default": "allow", "rules": regles},
        }
    return ConfigurationCanaux(channels, liaisons, session, plugins, tuple(exposes), etat)


def mode_refuse(dep: Departement, mode: str) -> str | None:
    """Raison pour laquelle `mode` est refusé à ce département, ou `None`.

    Un département qui reçoit le public ne passe pas en `autonome` : dans ce mode, un message à un client
    (action externe, T2) partirait sans approbation, et un engagement externe est une frontière humaine (T3).
    """
    if mode == "autonome" and dep.canaux:
        return (
            f"{dep.id} reçoit le public par {', '.join(dep.canaux)} : le mode autonome enverrait un message à "
            "un client sans approbation humaine (frontière T3) ; choisis « ombre » ou « supervise »"
        )
    return None


def verifier_declarations(departements: Mapping[str, Departement]) -> list[str]:
    """`opsys-metier verifier` : chaque canal déclaré est connu, son département a l'outil d'accueil, et cet outil
    s'exécute sans approbation de niveau N3 (la session d'un client qui écrit pour la première fois n'a pas
    encore d'affaire liée : le garde du core refuserait un outil de niveau N3 ou plus, ADR-0010).
    """
    problemes: list[str] = []
    pour_canal: dict[str, list[str]] = {}
    for dep in departements.values():
        if not dep.canaux:
            continue
        if dep.mode == "autonome":
            problemes.append(str(mode_refuse(dep, "autonome")))
        try:
            outils = {o.nom: o for o in dep.charger_outils()}
        except Exception as exc:  # noqa: BLE001 — signalé, jamais une panne de `opsys-metier verifier`
            problemes.append(f"{dep.id} : outils illisibles ({type(exc).__name__}: {exc})")
            continue
        for ident in dep.canaux:
            pour_canal.setdefault(ident, []).append(dep.id)
            if ident not in CANAUX:
                problemes.append(f"{dep.id} : canal inconnu {ident!r} (canaux connus : {', '.join(ids_canaux())})")
                continue
            nom = CANAUX[ident].outil_accueil
            outil = outils.get(nom)
            if outil is None:
                problemes.append(f"{dep.id} : le canal {ident} exige l'outil d'accueil {nom}, absent du département")
            elif outil.niveau_effectif.value not in ("N0", "N1", "N2"):
                problemes.append(
                    f"{dep.id} : l'outil d'accueil {nom} est de niveau {outil.niveau_effectif.value} ; "
                    "il doit être N2 au plus (le premier message d'un client arrive sans affaire liée)"
                )
    for ident, deps in sorted(pour_canal.items()):
        if len(deps) > 1:
            problemes.append(f"le canal {ident} est déclaré par plusieurs départements ({', '.join(deps)})")
    return problemes


def _raisons(entree: Mapping[str, Any]) -> list[str]:
    """Pourquoi un canal est inactif : variables à fournir, `$include` du squelette qui manquent."""
    raisons = []
    if entree["variables_manquantes"]:
        raisons.append(f"variables à fournir : {', '.join(entree['variables_manquantes'])}")
    if entree["includes_manquants"]:
        raisons.append(f"openclaw.json n'inclut pas {', '.join(entree['includes_manquants'])}")
    return raisons


def lignes_d_etat(etat: Sequence[Mapping[str, Any]]) -> list[str]:
    """Une ligne lisible par canal : actif, ou inactif avec ce qui manque."""
    lignes = []
    for entree in etat:
        base = f"canal {entree['departement']} / {entree['canal']}"
        lignes.append(f"{base} : ACTIF" if entree["actif"] else f"{base} : INACTIF, {' ; '.join(_raisons(entree))}")
    return lignes


def verifier_configuration(
    departements: Mapping[str, Departement],
    environ: Mapping[str, str],
    config_ecrite: Mapping[str, Any] | None,
    includes_manquants: Sequence[str] = (),
) -> list[str]:
    """`opsys-metier verifier --config-dir` : la configuration écrite dit la même chose que l'environnement.

    `config_ecrite` : `{"channels": ..., "plugins": ...}` relus des fragments. Un canal écrit actif alors que
    l'environnement n'a plus ses variables, ou écrit inactif alors que tout est fourni, est un écart : il
    faut relancer `opsys-metier openclaw configurer`. Un fragment absent est un écart, jamais un canal inactif.
    """
    attendu = configuration(departements, environ, includes_manquants)
    problemes: list[str] = []
    if config_ecrite is None:
        return ["configuration OpenClaw absente : lance `opsys-metier openclaw configurer --config-dir ...`"]
    channels = config_ecrite.get("channels", {})
    for entree in attendu.etat:
        ident = entree["canal"]
        ecrit = channels.get(ident)
        if not isinstance(ecrit, Mapping):
            problemes.append(f"canal {ident} : absent de channels.json, relance `opsys-metier openclaw configurer`")
        elif ecrit.get("enabled") is not entree["actif"]:
            etat_ecrit = "actif" if ecrit.get("enabled") else "inactif"
            etat_reel = "actif" if entree["actif"] else "inactif"
            detail = "" if entree["actif"] else f" ({' ; '.join(_raisons(entree))})"
            problemes.append(
                f"canal {ident} : écrit {etat_ecrit} mais l'environnement le rend {etat_reel}{detail} ; "
                "relance `opsys-metier openclaw configurer`"
            )
    return problemes
