"""Contexte ambiant d'un appel d'outil : ce que la plateforme fixe, jamais le modèle.

Le serveur MCP fixe le département appelant selon le point d'accès appelé (`/mcp/<département>`) ;
la file d'approbation le fixe au département qui a créé la demande. Les outils qui cloisonnent
(mémoire d'entreprise, budgets) le lisent ici.

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


@contextlib.contextmanager
def appeler_en_tant_que(departement: str | None) -> Iterator[None]:
    """Fixe le département appelant pour les appels faits dans ce contexte (None = aucun)."""
    jeton = DEPARTEMENT_APPELANT.set(departement)
    try:
        yield
    finally:
        DEPARTEMENT_APPELANT.reset(jeton)


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


_IDENTITE_APPELANTE: contextvars.ContextVar[IdentiteAppelante | None] = contextvars.ContextVar(
    "opsys_identite_appelante", default=None
)


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
    if (not isinstance(personne, str) or not personne.strip()
            or not isinstance(role, str) or not role.strip()):
        return None
    return IdentiteAppelante(personne=personne.strip(), role=role.strip())
