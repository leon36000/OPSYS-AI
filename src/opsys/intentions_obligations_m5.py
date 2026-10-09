"""Corrélation M5 transportée par le socle, sans autorité ni effet métier."""
from __future__ import annotations

import contextlib
import contextvars
import json
from dataclasses import dataclass
from typing import Any

from . import idempotence


@dataclass(frozen=True)
class _Intention:
    meta: idempotence.Meta
    arguments: dict[str, Any]


_INTENTION: contextvars.ContextVar[_Intention | None] = contextvars.ContextVar(
    "intention_obligations_preparees_m5", default=None,
)


def _copie(arguments: dict[str, Any]) -> dict[str, Any]:
    if type(arguments) is not dict:
        raise ValueError("la corrélation M5 exige un objet JSON")
    texte = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
    texte.encode("utf-8", errors="strict")
    return json.loads(texte)


@contextlib.contextmanager
def contexte_intention(meta: idempotence.Meta, arguments: dict[str, Any]):
    """Expose une copie du corps reçu après les gardes du répartiteur.

    Le département doit encore vérifier l'identité SQL, la forme métier et
    l'association persistée. Ce contexte seul ne valide aucune déclaration.
    """
    if not isinstance(meta, idempotence.Meta):
        raise ValueError("la corrélation M5 exige une Meta de transport")
    token = _INTENTION.set(_Intention(meta, _copie(arguments)))
    try:
        yield
    finally:
        _INTENTION.reset(token)


def intention_courante() -> tuple[idempotence.Meta, dict[str, Any]] | None:
    intention = _INTENTION.get()
    if intention is None:
        return None
    return intention.meta, _copie(intention.arguments)
