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
"""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import datetime as dt
from collections.abc import Iterator

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
