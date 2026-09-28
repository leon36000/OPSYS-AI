"""Département appelant d'un appel d'outil : fixé par la plateforme, jamais par le modèle.

Le serveur MCP le fixe selon le point d'accès appelé (`/mcp/<département>`) ; la file
d'approbation le fixe au département qui a créé la demande. Les outils qui cloisonnent
(mémoire d'entreprise, budgets) le lisent ici.
"""

from __future__ import annotations

import contextlib
import contextvars
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
