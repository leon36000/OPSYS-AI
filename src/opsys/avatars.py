"""Avatars des départements : nom, rôle, voix et visage, personnalisables par client (chantier « avatars », étape 1).

Chaque département se présente sous un avatar (M1 → Léa, M5 → Sophie, M10 → Mnémo...). Deux couches, même patron que
`opsys.taxonomie` :

- Le DÉFAUT, dans le manifeste : `department.yaml`, bloc `avatar` (`nom`, `role`, `voix`, `visage`, `canaux`). Il est
  validé à la lecture du manifeste (`normaliser_avatar`, appelée par `departements.lire_manifeste`) ; la présence d'un
  avatar dans CHAQUE département et l'unicité des noms entre départements sont contrôlées par `opsys-metier verifier`
  (`verifier_declarations`).
- Les SURCHARGES DU CLIENT, dans le profil d'entreprise : `$OPSYS_HOME/entreprise.yaml`, clé `avatars`, par identifiant
  de département (`m01-front-office: {nom: Julie, voix: voix.julie.chaleureuse}`). Le client peut renommer un
  avatar et changer sa voix et son visage logiques ; il ne change ni son rôle ni ses canaux (ce que le département
  sait faire est dans le code, pas dans un fichier client).

`resoudre_identites` est une fonction PURE : défauts des manifestes + surcharges validées -> identité effective de
chaque département, avec la provenance de chaque champ. Fail-closed : une surcharge invalide (nom trop long, caractère
refusé, doublon de nom avec un autre avatar, département inconnu, identifiant mal formé) lève `AvatarInvalide` ; elle
n'est jamais ignorée en silence au profit du défaut, qui afficherait un nom que le client a remplacé.

`voix` et `visage` sont des IDENTIFIANTS LOGIQUES (`voix.lea.defaut`, `visage.lea.defaut`), jamais un fournisseur ni un
modèle : le registre de fournisseurs les résoudra (étapes suivantes, `docs/architecture/AVATARS.md`). Ce module ne
vérifie que leur forme.

Canaux d'un avatar : `messagerie` (chat), `voix` (temps réel), `audiovisuel` (visage animé). Chacun est `disponible` ou
`prevu`. Seule la messagerie peut être `disponible` aujourd'hui (`CANAUX_REALISES`) : aucun worker vocal ni rendu de
visage n'existe encore, et un manifeste qui prétendrait le contraire est refusé. Ces canaux ne sont pas les `canaux` du
public d'un manifeste (`opsys.canaux`, p. ex. `sms`), qui décrivent par où le public écrit au département.

Ce module ne dépend pas de `opsys.departements` à l'import (le manifeste l'appelle pour valider son bloc).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .taxonomie import ProfilInvalide, _valeur_du_profil, fichier_profil

if TYPE_CHECKING:
    from .departements import Departement

CLE_AVATARS = "avatars"
CLES_MANIFESTE = ("nom", "role", "voix", "visage", "canaux")
CLES_OBLIGATOIRES = CLES_MANIFESTE
CLES_SURCHARGE = ("nom", "voix", "visage")

CANAL_MESSAGERIE = "messagerie"
CANAL_VOIX = "voix"
CANAL_AUDIOVISUEL = "audiovisuel"
CANAUX_AVATAR = (CANAL_MESSAGERIE, CANAL_VOIX, CANAL_AUDIOVISUEL)
ETAT_DISPONIBLE = "disponible"
ETAT_PREVU = "prevu"
ETATS_CANAL = (ETAT_DISPONIBLE, ETAT_PREVU)
# Canaux qui existent réellement aujourd'hui : la messagerie avec l'agent du département dans l'interface du core.
# La voix temps réel et l'audiovisuel s'y ajouteront quand leur runtime sera livré (AVATARS.md, étapes suivantes).
CANAUX_REALISES = frozenset({CANAL_MESSAGERIE})

# L'interface du core tronque le nom affiché d'un agent à 50 unités UTF-16 (`core/src/gateway/assistant-identity.ts`,
# `ASSISTANT_IDENTITY_LIMITS.name`) : 40 caractères laissent une marge, sans troncature silencieuse.
NOM_MAX = 40
ROLE_MAX = 80
IDENTIFIANT_MAX = 64
# Un nom : des mots de lettres (accents compris), séparés par une espace, un trait d'union ou une apostrophe.
# Ni chiffre, ni ponctuation, ni balise, ni émoji, ni caractère de contrôle.
_NOM = re.compile(r"^[^\W\d_]+(?:[ '’-][^\W\d_]+)*$")
_CARACTERE_INTERDIT_ROLE = re.compile(r"[\x00-\x1f\x7f<>]")
_SEGMENT = r"[a-z0-9][a-z0-9_-]{0,31}"
_IDENTIFIANTS = {
    "voix": re.compile(rf"^voix(?:\.{_SEGMENT}){{2,3}}$"),
    "visage": re.compile(rf"^visage(?:\.{_SEGMENT}){{2,3}}$"),
}

SOURCE_MANIFESTE = "manifeste"
SOURCE_ENTREPRISE = "entreprise"


class AvatarInvalide(ValueError):
    """Un avatar (manifeste) ou une surcharge (profil d'entreprise) ne respecte pas le contrat ; le message dit quoi
    corriger."""


@dataclass(frozen=True)
class Avatar:
    """L'avatar déclaré par un manifeste (le défaut)."""

    nom: str
    role: str
    voix: str
    visage: str
    canaux: Mapping[str, str]


@dataclass(frozen=True)
class Surcharge:
    """Ce que le client change à un avatar ; un champ `None` garde le défaut du manifeste."""

    nom: str | None = None
    voix: str | None = None
    visage: str | None = None


@dataclass(frozen=True)
class IdentiteEffective:
    """L'identité sous laquelle un département se présente pour CE client, et d'où vient chaque champ."""

    departement: str
    code: str
    nom: str
    role: str
    voix: str
    visage: str
    canaux: Mapping[str, str]
    sources: Mapping[str, str]

    def en_dict(self) -> dict[str, Any]:
        return {
            "departement": self.departement, "code": self.code, "nom": self.nom, "role": self.role,
            "voix": self.voix, "visage": self.visage, "canaux": dict(self.canaux), "sources": dict(self.sources),
        }


def cle_de_nom(nom: str) -> str:
    """Forme de comparaison d'un nom : sans casse ni accent (« Lea » et « Léa » se confondent à l'oral)."""
    decompose = unicodedata.normalize("NFKD", nom.casefold())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def valider_nom(valeur: Any, contexte: str) -> str:
    if not isinstance(valeur, str) or not valeur.strip():
        raise AvatarInvalide(f"{contexte} : nom requis (texte non vide)")
    nom = unicodedata.normalize("NFC", valeur.strip())
    if len(nom) > NOM_MAX:
        raise AvatarInvalide(f"{contexte} : nom de {len(nom)} caractères (au plus {NOM_MAX})")
    if not _NOM.match(nom):
        raise AvatarInvalide(
            f"{contexte} : nom {nom!r} refusé : des lettres seulement (accents permis), en mots séparés par une "
            "espace, un trait d'union ou une apostrophe ; ni chiffre, ni ponctuation, ni symbole"
        )
    return nom


def _valider_role(valeur: Any, contexte: str) -> str:
    if not isinstance(valeur, str) or not valeur.strip():
        raise AvatarInvalide(f"{contexte} : role requis (texte court non vide)")
    role = valeur.strip()
    if len(role) > ROLE_MAX:
        raise AvatarInvalide(f"{contexte} : role de {len(role)} caractères (au plus {ROLE_MAX})")
    if _CARACTERE_INTERDIT_ROLE.search(role):
        raise AvatarInvalide(f"{contexte} : role : caractère de contrôle ou chevron refusé")
    return role


def valider_identifiant(espace: str, valeur: Any, contexte: str) -> str:
    """`voix.<nom>.<variante>` ou `visage.<nom>.<variante>` (une sous-variante permise) : identifiant logique, jamais
    un fournisseur, une URL ou un chemin."""
    if not isinstance(valeur, str) or not valeur:
        raise AvatarInvalide(f"{contexte} : {espace} requis (identifiant logique, p. ex. {espace}.lea.defaut)")
    if len(valeur) > IDENTIFIANT_MAX or not _IDENTIFIANTS[espace].match(valeur):
        raise AvatarInvalide(
            f"{contexte} : {espace} {valeur!r} mal formé : attendu « {espace}.<nom>.<variante> » en minuscules ASCII "
            f"(chiffres, '_' et '-' permis), au plus {IDENTIFIANT_MAX} caractères"
        )
    return valeur


def _valider_canaux(valeur: Any, contexte: str) -> dict[str, str]:
    if not isinstance(valeur, Mapping) or not valeur:
        raise AvatarInvalide(
            f"{contexte} : canaux doit être un objet non vide ({{canal: état}}, canaux : {', '.join(CANAUX_AVATAR)})"
        )
    canaux: dict[str, str] = {}
    for canal, etat in valeur.items():
        if canal not in CANAUX_AVATAR:
            raise AvatarInvalide(f"{contexte} : canal inconnu {canal!r} (canaux connus : {', '.join(CANAUX_AVATAR)})")
        if etat not in ETATS_CANAL:
            raise AvatarInvalide(f"{contexte} : canaux.{canal} : état {etat!r} (attendu : {', '.join(ETATS_CANAL)})")
        if etat == ETAT_DISPONIBLE and canal not in CANAUX_REALISES:
            raise AvatarInvalide(
                f"{contexte} : canaux.{canal} déclaré disponible, mais aucun runtime ne le réalise encore "
                f"(disponibles aujourd'hui : {', '.join(sorted(CANAUX_REALISES))}) ; déclare-le « {ETAT_PREVU} »"
            )
        canaux[canal] = etat
    # Ordre stable, celui de CANAUX_AVATAR, quel que soit l'ordre du YAML.
    return {canal: canaux[canal] for canal in CANAUX_AVATAR if canal in canaux}


def normaliser_avatar(brut: Any, contexte: str) -> Avatar:
    """Valide le bloc `avatar` d'un manifeste ; lève `AvatarInvalide` (un `ValueError`) avec la consigne."""
    ctx = f"{contexte} : avatar"
    if not isinstance(brut, Mapping):
        raise AvatarInvalide(f"{ctx} doit être un objet ({', '.join(CLES_MANIFESTE)})")
    inconnues = sorted(set(brut) - set(CLES_MANIFESTE))
    if inconnues:
        raise AvatarInvalide(f"{ctx} : clé(s) inconnue(s) {inconnues} (attendu : {', '.join(CLES_MANIFESTE)})")
    manquantes = [cle for cle in CLES_OBLIGATOIRES if cle not in brut]
    if manquantes:
        raise AvatarInvalide(f"{ctx} : champ(s) obligatoire(s) manquant(s) {manquantes}")
    return Avatar(
        nom=valider_nom(brut["nom"], ctx),
        role=_valider_role(brut["role"], ctx),
        voix=valider_identifiant("voix", brut["voix"], ctx),
        visage=valider_identifiant("visage", brut["visage"], ctx),
        canaux=_valider_canaux(brut["canaux"], ctx),
    )


def _doublons_de_noms(noms: Mapping[str, str]) -> list[str]:
    """`noms` : département -> nom ; un message par groupe de départements qui partagent un nom."""
    par_cle: dict[str, list[str]] = {}
    for dep_id, nom in noms.items():
        par_cle.setdefault(cle_de_nom(nom), []).append(dep_id)
    return [
        f"nom d'avatar {noms[ids[0]]!r} partagé par {', '.join(sorted(ids))} (casse et accents ignorés)"
        for ids in par_cle.values() if len(ids) > 1
    ]


def verifier_declarations(departements: Mapping[str, Departement]) -> list[str]:
    """`opsys-metier verifier` : chaque département déclare un avatar, et deux avatars n'ont jamais le même nom."""
    problemes = [
        f"{dep.id} : department.yaml ne déclare pas de bloc avatar ({', '.join(CLES_OBLIGATOIRES)})"
        for dep in departements.values() if dep.avatar is None
    ]
    noms = {dep.id: dep.avatar.nom for dep in departements.values() if dep.avatar is not None}
    return problemes + [f"manifestes : {probleme}" for probleme in _doublons_de_noms(noms)]


def normaliser_surcharges(brut: Any) -> dict[str, Surcharge]:
    """Valide la clé `avatars` du profil d'entreprise (forme seulement : les départements connus et l'unicité des noms
    se vérifient à la résolution, qui connaît les manifestes)."""
    if brut is None:
        return {}
    if not isinstance(brut, Mapping):
        raise AvatarInvalide(f"'{CLE_AVATARS}' doit être un objet {{identifiant de département: surcharge}}")
    surcharges: dict[str, Surcharge] = {}
    for dep_id, entree in brut.items():
        ctx = f"'{CLE_AVATARS}.{dep_id}'"
        if not isinstance(dep_id, str) or not dep_id:
            raise AvatarInvalide(f"'{CLE_AVATARS}' : clé {dep_id!r} : identifiant de département attendu")
        if not isinstance(entree, Mapping) or not entree:
            raise AvatarInvalide(f"{ctx} doit être un objet non vide ({', '.join(CLES_SURCHARGE)})")
        inconnues = sorted(set(entree) - set(CLES_SURCHARGE))
        if inconnues:
            raise AvatarInvalide(
                f"{ctx} : clé(s) non personnalisable(s) {inconnues} (le client change seulement : "
                f"{', '.join(CLES_SURCHARGE)})"
            )
        surcharges[dep_id] = Surcharge(
            nom=valider_nom(entree["nom"], ctx) if "nom" in entree else None,
            voix=valider_identifiant("voix", entree["voix"], ctx) if "voix" in entree else None,
            visage=valider_identifiant("visage", entree["visage"], ctx) if "visage" in entree else None,
        )
    return surcharges


def resoudre_identites(
    departements: Mapping[str, Departement], surcharges: Mapping[str, Surcharge] | None = None
) -> dict[str, IdentiteEffective]:
    """Identité effective de chaque département : défaut du manifeste + surcharges validées du client.

    Pure (aucun fichier lu). Lève `AvatarInvalide` si un département n'a pas d'avatar, si une surcharge vise un
    département absent, ou si deux identités effectives portent le même nom (casse et accents ignorés).
    """
    surcharges = dict(surcharges or {})
    inconnus = sorted(set(surcharges) - set(departements))
    if inconnus:
        raise AvatarInvalide(
            f"'{CLE_AVATARS}' : département(s) inconnu(s) {inconnus} (départements : {', '.join(departements)})"
        )
    sans_avatar = [dep.id for dep in departements.values() if dep.avatar is None]
    if sans_avatar:
        raise AvatarInvalide(f"département(s) sans avatar déclaré dans leur manifeste : {sans_avatar}")
    identites: dict[str, IdentiteEffective] = {}
    for dep in sorted(departements.values(), key=lambda d: d.numero):
        defaut = dep.avatar
        assert defaut is not None  # vérifié ci-dessus ; garde pour le typage
        surcharge = surcharges.get(dep.id, Surcharge())
        sources = {
            champ: SOURCE_ENTREPRISE if getattr(surcharge, champ) is not None else SOURCE_MANIFESTE
            for champ in CLES_SURCHARGE
        }
        identites[dep.id] = IdentiteEffective(
            departement=dep.id,
            code=dep.code,
            nom=surcharge.nom or defaut.nom,
            role=defaut.role,
            voix=surcharge.voix or defaut.voix,
            visage=surcharge.visage or defaut.visage,
            canaux=dict(defaut.canaux),
            sources=sources,
        )
    doublons = _doublons_de_noms({ident: identite.nom for ident, identite in identites.items()})
    if doublons:
        raise AvatarInvalide(f"'{CLE_AVATARS}' : {' ; '.join(doublons)} : chaque avatar garde un nom distinct")
    return identites


def lire_surcharges(chemin: Path | None = None) -> dict[str, Surcharge]:
    """Surcharges déclarées par le profil de l'instance ; `{}` si le fichier ou la clé est absent.

    Lève `ProfilInvalide` si le fichier est illisible ou si la clé ne respecte pas le contrat : une surcharge cassée
    n'est jamais lue comme une absence de surcharge.
    """
    fichier = chemin or fichier_profil()
    brut = _valeur_du_profil(CLE_AVATARS, fichier)
    try:
        return normaliser_surcharges(brut)
    except AvatarInvalide as exc:
        raise ProfilInvalide(f"{fichier} : {exc}") from exc


def identites_effectives(
    departements: Mapping[str, Departement], chemin: Path | None = None
) -> dict[str, IdentiteEffective]:
    """Identités effectives de l'instance (manifestes + `$OPSYS_HOME/entreprise.yaml`). Lève `ProfilInvalide` si le
    profil est illisible, si une surcharge est mal formée ou si elle ne se résout pas contre les manifestes."""
    fichier = chemin or fichier_profil()
    surcharges = lire_surcharges(fichier)
    try:
        return resoudre_identites(departements, surcharges)
    except AvatarInvalide as exc:
        raise ProfilInvalide(f"{fichier} : {exc}") from exc


def verifier_profil(departements: Mapping[str, Departement]) -> list[str]:
    """`opsys-metier verifier` : des surcharges présentes doivent être valides et se résoudre contre les manifestes.
    Un profil sans clé `avatars` n'est pas une erreur : les avatars gardent leur défaut."""
    if any(dep.avatar is None for dep in departements.values()):
        return []  # déjà signalé par `verifier_declarations`
    try:
        identites_effectives(departements)
    except ProfilInvalide as exc:
        return [str(exc)]
    return []
