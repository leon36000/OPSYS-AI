"""Contexte ambiant d'un appel d'outil : ce que la plateforme fixe, jamais le modèle.

Le répartiteur pose le département propriétaire de l'outil en cours et, séparément, son origine fiable
depuis le point d'accès MCP lié (`/mcp/contexte/<département>`). L'origine sert aux vues cloisonnées :
un outil appelé au nom d'un département ne peut pas choisir le destinataire par ses arguments. La file
d'approbation fixe les deux au département qui a créé la demande.

Une mutation d'appareil idempotente (`opsys.idempotence`, T1.4-b) fixe en plus les deux horloges de
l'appel (contrat : `docs/architecture/IDEMPOTENCE.md`, modèle de synchro : R12 §4) : celle de
l'appareil (affichée à l'employé, jamais fiable pour un calcul — une horloge d'appareil peut
dériver) et celle de réception du serveur (fait foi, ex. la paie brouillon de M4, T1.4-d). Un outil
qui en a besoin les lit ici, jamais dans ses propres arguments : ni l'une ni l'autre ne vient du
modèle.

L'identité portée par un jeton d'appareil (personne, rôle — T1.4-c2, `docs/architecture/
IDEMPOTENCE.md` §7 bis) suit le même principe : OPSYS-CORE la résout (fragment de configuration
généré par `opsys.openclaw.ecrire_appareils`/`roles_outils`, jamais écrit à la main dans le core)
et la transmet en `_meta` MCP (`opsys/personne`, `opsys/role`) ; le socle ne fait que l'exposer ici,
pendant l'appel, pour qu'un outil ou une projection par rôle (ex. `m3_lire_devis`, pas encore
adapté) la lise par cet accesseur plutôt que par un paramètre fourni par l'appelant.
"""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import datetime as dt
from collections.abc import Iterator, Mapping
from typing import Any

DEPARTEMENT_APPELANT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "opsys_departement_appelant", default=None
)
DEPARTEMENT_ORIGINE_APPELANT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "opsys_departement_origine_appelant", default=None
)


@contextlib.contextmanager
def appeler_en_tant_que(departement: str | None, *, origine: str | None = None) -> Iterator[None]:
    """Fixe le département qui exécute l'outil et son origine fiable (None = aucun).

    `origine` est fixé par le répartiteur depuis son point d'accès MCP, jamais depuis les arguments.
    Sans valeur explicite, il suit `departement` pour les appels internes et les approbations.
    """
    jeton = DEPARTEMENT_APPELANT.set(departement)
    jeton_origine = DEPARTEMENT_ORIGINE_APPELANT.set(origine if origine is not None else departement)
    try:
        yield
    finally:
        DEPARTEMENT_ORIGINE_APPELANT.reset(jeton_origine)
        DEPARTEMENT_APPELANT.reset(jeton)


def departement_origine_appelante() -> str | None:
    """Département d'origine fiable du répartiteur en cours, ou None hors d'un appel."""
    return DEPARTEMENT_ORIGINE_APPELANT.get()


@dataclasses.dataclass(frozen=True)
class HorodatageAppareil:
    """Les deux horloges d'une mutation d'appareil idempotente (R12 §4)."""

    appareil: str
    horodatage_appareil: dt.datetime  # heure de l'appareil : affichage seulement, jamais un calcul
    recu_le: dt.datetime  # heure de réception du serveur : fait foi (ex. paie, M4/T1.4-d)


_HORODATAGE_APPAREIL: contextvars.ContextVar[HorodatageAppareil | None] = contextvars.ContextVar(
    "opsys_horodatage_appareil", default=None
)


@contextlib.contextmanager
def receptionne_de(horodatage: HorodatageAppareil | None) -> Iterator[None]:
    """Fixe les horloges de la mutation d'appareil en cours (None = aucune, hors idempotence)."""
    jeton = _HORODATAGE_APPAREIL.set(horodatage)
    try:
        yield
    finally:
        _HORODATAGE_APPAREIL.reset(jeton)


def horodatage_reception() -> HorodatageAppareil | None:
    """Horloges de la mutation d'appareil en cours d'exécution, ou None hors de ce contexte."""
    return _HORODATAGE_APPAREIL.get()


# -- identité portée par un jeton d'appareil (T1.4-c2) -------------------------------------------

PERSONNE_META = "opsys/personne"
ROLE_META = "opsys/role"


@dataclasses.dataclass(frozen=True)
class IdentiteAppelante:
    """Personne et rôle OPSYS portés par le jeton d'appareil ayant fait l'appel en cours (`_meta`
    MCP `opsys/personne`/`opsys/role`, docs/architecture/IDEMPOTENCE.md §7 bis).

    Un rôle de jeton d'appareil est toujours un des quatre noms de `opsys.appareils.ROLES_APPAREIL`
    au moment où OPSYS-CORE le résout — mais cette structure ne fait que rendre ce que le core a
    transmis ; elle ne revérifie ni que la personne existe encore, ni qu'elle porte encore ce rôle
    (un outil qui en a besoin le revérifie via `opsys.identite.personne_active`, comme toute autre
    lecture d'identité)."""

    personne: str
    role: str
    # Établie par l'adaptateur serveur; le parseur MCP ne lit jamais une source depuis `_meta`.
    source: str = "appareil"


_IDENTITE_APPELANTE: contextvars.ContextVar[IdentiteAppelante | None] = contextvars.ContextVar(
    "opsys_identite_appelante", default=None
)

_TICKET_AGENT_CFO: contextvars.ContextVar[tuple[str, dict[str, Any]] | None] = contextvars.ContextVar(
    "opsys_ticket_agent_cfo", default=None
)


@contextlib.contextmanager
def appele_avec_ticket_agent_cfo(ticket: str | None, tool_arguments: Mapping[str, Any] | None = None) -> Iterator[None]:
    """Fixe un ticket opaque émis par la route runtime privée; aucun champ d'argument n'est lu."""
    jeton = _TICKET_AGENT_CFO.set((ticket, dict(tool_arguments or {})) if ticket is not None else None)
    try:
        yield
    finally:
        _TICKET_AGENT_CFO.reset(jeton)


def ticket_agent_cfo() -> str | None:
    value = _TICKET_AGENT_CFO.get()
    return value[0] if value else None


def arguments_ticket_agent_cfo() -> dict[str, Any] | None:
    value = _TICKET_AGENT_CFO.get()
    return dict(value[1]) if value else None


@contextlib.contextmanager
def appele_par_appareil(identite: IdentiteAppelante | None) -> Iterator[None]:
    """Fixe l'identité (personne, rôle) du jeton d'appareil pour les appels faits dans ce contexte
    (None = aucune, appel sans jeton d'appareil : Hermes, Claude Code, un outil interne)."""
    jeton = _IDENTITE_APPELANTE.set(identite)
    try:
        yield
    finally:
        _IDENTITE_APPELANTE.reset(jeton)


def identite_appelante() -> IdentiteAppelante | None:
    """Personne et rôle transmis par OPSYS-CORE pour l'appel MCP en cours, ou None hors contexte.

    AUTHENTIFIÉS depuis PLAN T1.4-c4 (`docs/architecture/IDEMPOTENCE.md` §7 bis) : OPSYS-CORE
    (`/tools/invoke`) n'attribue `opsys/personne`/`opsys/role` que lorsque l'appelant s'est
    authentifié par son propre jeton d'appareil vérifié (jamais par le corps de la requête, jamais
    par le secret partagé — un appelant par secret partagé ne porte jamais ces deux clés `_meta`).
    Le `deviceId` qui a produit cette identité vient du même jeton vérifié, avec refus fermé si le
    corps en déclare un différent ; côté socle, `depuis_meta_mcp_identite` (juste en dessous) ne
    lit que `_meta`, jamais les arguments de l'outil (que le modèle produit et pourrait halluciner,
    omettre ou falsifier) — voir `tests/test_contexte.py`,
    `test_identite_appelante_ignore_les_arguments_de_loutil`. Un outil peut donc s'en servir pour
    signer une décision ou choisir une projection par rôle ; il doit tout de même revérifier que la
    personne existe encore et porte encore ce rôle (`opsys.identite.personne_active`), comme le
    signale déjà `IdentiteAppelante` ci-dessus. Réserve (PLAN T1.4-c1) : les tests vitest de cette
    chaîne côté core ne tournent que depuis le job CI `tests-opsys` ; tant qu'il n'est pas vert, la
    garantie repose sur la lecture du code, pas sur une preuve exécutée.
    """
    return _IDENTITE_APPELANTE.get()


# -- demande approuvée en cours d'exécution (T4.15-c) --------------------------------------------

_DEMANDE_APPROUVEE: contextvars.ContextVar[str | None] = contextvars.ContextVar("opsys_demande_approuvee", default=None)


@contextlib.contextmanager
def executer_demande_approuvee(demande_id: str | None) -> Iterator[None]:
    """Fixe l'identifiant de la demande d'approbation dont l'outil s'exécute dans ce contexte (None = aucune). Seul
    `approbations.decider` l'appelle, après avoir réservé la demande (`en_cours`, avec son approbateur) : un agent ne
    peut que créer une demande `en_attente` et n'entre jamais dans `decider`."""
    jeton = _DEMANDE_APPROUVEE.set(demande_id)
    try:
        yield
    finally:
        _DEMANDE_APPROUVEE.reset(jeton)


def demande_approuvee_en_cours() -> str | None:
    """L'identifiant de la demande approuvée que l'outil en cours d'exécution accomplit, ou None hors de
    `approbations.decider` (appel d'agent, d'appareil, de la ligne de commande). Ce n'est qu'un pointeur : la personne
    et le rôle qui l'ont approuvée se lisent EN BASE, par `approbations.approbateur_en_cours`, que l'outil appelle."""
    return _DEMANDE_APPROUVEE.get()


def depuis_meta_mcp_identite(meta: Mapping[str, Any] | None) -> IdentiteAppelante | None:
    """Lit `opsys/personne`/`opsys/role` du `_meta` MCP (T1.4-c2, transmis par OPSYS-CORE) ; None si
    l'un des deux manque ou n'est pas une chaîne non vide.

    Fail-closed *silencieux* ici, à la différence d'`opsys.idempotence.depuis_meta_mcp` : un appel
    MCP sans identité de jeton d'appareil reste un appel valide (Hermes, Claude Code, un outil
    interne n'envoient jamais ces clés) — c'est OPSYS-CORE (`/tools/invoke`) qui applique le refus
    fermé sur la portée du rôle, avant même d'émettre `tools/call` ; ce module ne fait que
    transporter ce que le core a déjà décidé de laisser passer.
    """
    if not meta:
        return None
    personne, role = meta.get(PERSONNE_META), meta.get(ROLE_META)
    if not isinstance(personne, str) or not personne.strip() or not isinstance(role, str) or not role.strip():
        return None
    return IdentiteAppelante(personne=personne.strip(), role=role.strip())


_LIMITE_SORTIE: contextvars.ContextVar[int | None] = contextvars.ContextVar("opsys_limite_sortie", default=None)


@contextlib.contextmanager
def sortie_bornee(limite: int) -> Iterator[None]:
    """Quota fiable du répartiteur, jamais lu des arguments ou du _meta client."""
    if type(limite) is not int or limite < 1:
        raise ValueError("quota de sortie invalide")
    token = _LIMITE_SORTIE.set(limite)
    try:
        yield
    finally:
        _LIMITE_SORTIE.reset(token)


def limite_sortie() -> int | None:
    return _LIMITE_SORTIE.get()
